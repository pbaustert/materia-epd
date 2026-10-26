"""Read ILCD datasets from an HTTP file server instead of local folders.

The file server is expected to expose one file per dataset, named after its UUID::

    {base_url}/{processes_dir}/{uuid}.xml   # EPD process datasets (default: "xml")
    {base_url}/{flows_dir}/{uuid}.xml       # flow datasets (default: "flows")

e.g. ``http://erp-canaria.private.list.lu:44003/raw/xml/<uuid>.xml``.
"""

from __future__ import annotations

import logging
import os
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable, Iterator

import structlog

logger = structlog.wrap_logger(logging.getLogger(__name__))

BASE_URL_ENV = "MATERIA_EPD_BASE_URL"
DEFAULT_TIMEOUT = 60
DEFAULT_MAX_WORKERS = 8


class RemoteFetchError(RuntimeError):
    """Raised when a dataset cannot be downloaded or parsed."""


def resolve_base_url(*candidates: str | None) -> str:
    """Return the first non-empty candidate, else ``$MATERIA_EPD_BASE_URL``."""
    for candidate in (*candidates, os.environ.get(BASE_URL_ENV)):
        if candidate and str(candidate).strip():
            return str(candidate).strip().rstrip("/")
    raise ValueError(
        "No file server URL given: pass `base_url` (CLI: --base-url) "
        f"or set the {BASE_URL_ENV} environment variable."
    )


class UrlSource:
    """Fetch (and cache) ILCD process and flow XMLs from a file server."""

    def __init__(
        self,
        base_url: str,
        processes_dir: str = "xml",
        flows_dir: str = "flows",
        timeout: float = DEFAULT_TIMEOUT,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ):
        self.base_url = base_url.rstrip("/")
        self.processes_dir = processes_dir.strip("/")
        self.flows_dir = flows_dir.strip("/")
        self.timeout = timeout
        self.max_workers = max(1, int(max_workers))
        self._cache: dict[str, ET.Element] = {}
        self._lock = threading.Lock()

    def process_url(self, uuid: str) -> str:
        return f"{self.base_url}/{self.processes_dir}/{uuid}.xml"

    def flow_url(self, uuid: str) -> str:
        return f"{self.base_url}/{self.flows_dir}/{uuid}.xml"

    def fetch_xml_root(self, url: str) -> ET.Element:
        """Download and parse an XML document (cached per URL)."""
        with self._lock:
            if url in self._cache:
                return self._cache[url]
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            raise RemoteFetchError(f"HTTP {e.code} for {url}") from e
        except (urllib.error.URLError, OSError) as e:
            raise RemoteFetchError(f"Could not reach {url}: {e}") from e
        try:
            root = ET.fromstring(data)
        except ET.ParseError as e:
            raise RemoteFetchError(f"Invalid XML at {url}: {e}") from e
        with self._lock:
            self._cache[url] = root
        return root

    def process_root(self, uuid: str) -> ET.Element:
        return self.fetch_xml_root(self.process_url(uuid))

    def flow_root(self, uuid: str) -> ET.Element:
        """Flow loader for `IlcdProcess(flow_loader=...)`."""
        return self.fetch_xml_root(self.flow_url(uuid))

    def gen_processes(
        self, uuids: Iterable[str], errors: dict[str, str] | None = None
    ) -> Iterator[tuple[str, ET.Element]]:
        """Yield ``(url, root)`` for each process UUID, downloaded concurrently.

        The reference flow of every process is prefetched in the same worker, so the
        unit-conformity filter later reads it from the cache. UUIDs that cannot be
        fetched are skipped and recorded in ``errors`` (uuid -> message).
        """
        from materia_epd.epd.models import reference_flow_uuid

        def fetch(uuid: str) -> tuple[str, ET.Element]:
            root = self.process_root(uuid)
            try:
                flow_uuid = reference_flow_uuid(root)
                if flow_uuid:
                    self.flow_root(flow_uuid)
            except Exception as e:  # reported again (per EPD) by the unit filter
                logger.debug("Reference flow prefetch failed", uuid=uuid, error=str(e))
            return self.process_url(uuid), root

        ordered = list(dict.fromkeys(u for u in uuids if u))
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {uuid: pool.submit(fetch, uuid) for uuid in ordered}
            for uuid, future in futures.items():
                try:
                    yield future.result()
                except Exception as e:
                    logger.warning("EPD could not be fetched", uuid=uuid, error=str(e))
                    if errors is not None:
                        errors[uuid] = str(e)
