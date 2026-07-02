"""Feather-backed EPD corpus cache: build, validate, and load."""

from __future__ import annotations

import json
import logging
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import structlog
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    track,
)

from materia_epd.core.constants import PROPERTIES, QUANTITIES
from materia_epd.epd.extract import extract_epd_record
from materia_epd.epd.extraction_errors import EpdExtractionError
from materia_epd.epd.models import IlcdProcess

logger = structlog.wrap_logger(logging.getLogger(__name__))

DEFAULT_CACHE_DIR_NAME = ".materia_epd_cache"
CACHE_FORMAT_VERSION = 1
PROCESSES_FEATHER = "processes.feather"
LCIA_FEATHER = "lcia.feather"
MANIFEST_JSON = "manifest.json"

MATERIAL_COLUMNS = list(QUANTITIES) + list(PROPERTIES)


class CacheError(Exception):
    """Base error for EPD cache operations."""


class CacheMissingError(CacheError):
    """Raised when a required cache is absent and auto-build is disabled."""


def resolve_cache_dir(epd_cache: Path | None) -> Path:
    if epd_cache is not None:
        return epd_cache
    return Path.cwd() / DEFAULT_CACHE_DIR_NAME


def cache_exists(cache_dir: Path) -> bool:
    return all((cache_dir / name).exists() for name in (PROCESSES_FEATHER, LCIA_FEATHER, MANIFEST_JSON))


def _fingerprint_file(path: Path) -> dict:
    stat = path.stat()
    return {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size}


def _collect_source_fingerprints(epd_folder: Path) -> dict[str, dict]:
    fingerprints: dict[str, dict] = {}
    for sub in ("processes", "flows"):
        folder = epd_folder / sub
        if not folder.is_dir():
            continue
        for xml_file in sorted(folder.glob("*.xml")):
            rel = str(xml_file.relative_to(epd_folder))
            fingerprints[rel] = _fingerprint_file(xml_file)
    return fingerprints


def _read_manifest(cache_dir: Path) -> dict | None:
    path = cache_dir / MANIFEST_JSON
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def is_cache_valid(cache_dir: Path, epd_folder: Path) -> bool:
    manifest = _read_manifest(cache_dir)
    if manifest is None:
        return False
    if manifest.get("format_version") != CACHE_FORMAT_VERSION:
        return False
    if Path(manifest.get("source_dir", "")).resolve() != epd_folder.resolve():
        return False
    current = _collect_source_fingerprints(epd_folder)
    return manifest.get("files") == current


def _should_use_parallel(num_files: int, workers: int) -> bool:
    return workers > 1 and num_files >= 2 and num_files >= workers * 2


def _record_extraction_failure(
    failures: list[dict],
    process_path: Path,
    exc: Exception,
) -> None:
    if isinstance(exc, EpdExtractionError):
        failures.append(exc.to_log_dict())
        return

    failures.append(
        {
            "file": process_path.name,
            "process_path": str(process_path),
            "stage": "extract_epd_record",
            "error": str(exc),
            "cause_type": type(exc).__name__,
            "detail": f"{process_path.name} [extract_epd_record] {exc}",
        }
    )


def _log_extraction_failures(failures: list[dict]) -> None:
    for failure in failures:
        logger.warning("Failed to extract EPD", **failure)


def _retry_paths_sequential(
    process_paths: list[str],
    flows_folder: str,
    records: list[dict],
    failures: list[dict],
    *,
    reason: str,
    progress: Progress | None = None,
    task_id: int | None = None,
    verbose: bool = False,
) -> None:
    if not process_paths:
        return
    logger.warning(
        "Retrying EPD extraction sequentially after parallel worker failure",
        reason=reason,
        file_count=len(process_paths),
    )
    for path_str in process_paths:
        path = Path(path_str)
        try:
            records.append(extract_epd_record(path_str, flows_folder))
        except Exception as exc:
            _record_extraction_failure(failures, path, exc)
        if progress is not None and task_id is not None:
            if verbose:
                progress.update(
                    task_id,
                    description=f"Extracting EPDs — {path.name}",
                )
            progress.advance(task_id)


def _extract_sequential(
    process_paths: list[Path],
    flows_folder: str,
    *,
    disable_progress: bool,
    verbose: bool,
) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    failures: list[dict] = []
    iterator = process_paths
    if not disable_progress:
        iterator = track(
            process_paths,
            description="Extracting EPDs",
            transient=True,
        )
    for path in iterator:
        try:
            records.append(extract_epd_record(str(path.resolve()), flows_folder))
        except Exception as exc:
            _record_extraction_failure(failures, path, exc)
    return records, failures


def _extract_parallel(
    process_paths: list[Path],
    flows_folder: str,
    workers: int,
    *,
    disable_progress: bool,
    verbose: bool,
) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    failures: list[dict] = []
    mp_context = multiprocessing.get_context()
    path_strs = [str(p.resolve()) for p in process_paths]
    completed: set[str] = set()

    progress_columns = [
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        TimeElapsedColumn(),
    ]

    def _run_pool(progress: Progress | None, task_id: int | None) -> None:
        with ProcessPoolExecutor(
            max_workers=workers, mp_context=mp_context
        ) as executor:
            futures = {
                executor.submit(extract_epd_record, p, flows_folder): p
                for p in path_strs
            }
            try:
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        records.append(future.result())
                        completed.add(source)
                    except BrokenProcessPool:
                        raise
                    except Exception as exc:
                        _record_extraction_failure(failures, Path(source), exc)
                        completed.add(source)
                    if progress is not None and task_id is not None:
                        if verbose:
                            progress.update(
                                task_id,
                                description=f"Extracting EPDs — {Path(source).name}",
                            )
                        progress.advance(task_id)
            except BrokenProcessPool:
                pending = [p for p in path_strs if p not in completed]
                _retry_paths_sequential(
                    pending,
                    flows_folder,
                    records,
                    failures,
                    reason=(
                        "A worker process was terminated abruptly "
                        "(often caused by memory pressure)."
                    ),
                    progress=progress,
                    task_id=task_id,
                    verbose=verbose,
                )
                completed.update(pending)

    if disable_progress:
        _run_pool(None, None)
    else:
        with Progress(*progress_columns, transient=True) as progress:
            task_id = progress.add_task("Extracting EPDs", total=len(path_strs))
            _run_pool(progress, task_id)

    return records, failures


def _records_to_frames(records: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    process_rows = []
    lcia_rows = []

    for rec in records:
        if not rec.get("uuid"):
            continue
        row = {
            "uuid": rec["uuid"],
            "loc": rec.get("loc"),
            "ref_flow_uuid": rec.get("ref_flow_uuid"),
            "source_path": rec.get("source_path"),
        }
        for col in MATERIAL_COLUMNS:
            row[col] = rec.get("material_kwargs", {}).get(col)
        process_rows.append(row)

        for indicator, modules in rec.get("raw_lcia", {}).items():
            for module, value in modules.items():
                if value is not None:
                    lcia_rows.append(
                        {
                            "uuid": rec["uuid"],
                            "indicator": indicator,
                            "module": module,
                            "value": float(value),
                        }
                    )

    processes_df = pd.DataFrame(process_rows)
    lcia_df = pd.DataFrame(lcia_rows)
    return processes_df, lcia_df


def _write_cache_artifacts(
    cache_dir: Path,
    epd_folder: Path,
    processes_df: pd.DataFrame,
    lcia_df: pd.DataFrame,
    *,
    console: Console | None,
    disable_progress: bool,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = console or Console()

    if not disable_progress:
        out.print("[dim]Writing processes.feather…[/dim]")
    processes_df.to_feather(cache_dir / PROCESSES_FEATHER)

    if not disable_progress:
        out.print("[dim]Writing lcia.feather…[/dim]")
    lcia_df.to_feather(cache_dir / LCIA_FEATHER)

    manifest = {
        "format_version": CACHE_FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(epd_folder.resolve()),
        "files": _collect_source_fingerprints(epd_folder),
        "counts": {
            "processes": len(processes_df),
            "lcia_rows": len(lcia_df),
        },
    }
    if not disable_progress:
        out.print("[dim]Writing manifest.json…[/dim]")
    with open(cache_dir / MANIFEST_JSON, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def build_epd_cache(
    epd_folder: Path,
    cache_dir: Path,
    *,
    force: bool = False,
    workers: int | None = None,
    console: Console | None = None,
    disable_progress: bool = False,
    verbose: bool = False,
) -> Path:
    """Build or rebuild the Feather cache for an EPD folder."""
    processes_dir = epd_folder / "processes"
    flows_dir = epd_folder / "flows"
    if not processes_dir.is_dir():
        raise CacheError(f"EPD processes folder not found: {processes_dir}")
    if not flows_dir.is_dir():
        raise CacheError(f"EPD flows folder not found: {flows_dir}")

    if cache_exists(cache_dir) and not force and is_cache_valid(cache_dir, epd_folder):
        logger.info("EPD cache is already up to date", cache_dir=str(cache_dir))
        return cache_dir

    process_paths = sorted(processes_dir.glob("*.xml"))
    if not process_paths:
        raise CacheError(f"No process XML files found in {processes_dir}")

    worker_count = workers if workers is not None else (os.cpu_count() or 1)
    flows_folder = str(flows_dir.resolve())

    if _should_use_parallel(len(process_paths), worker_count):
        records, failures = _extract_parallel(
            process_paths,
            flows_folder,
            worker_count,
            disable_progress=disable_progress,
            verbose=verbose,
        )
    else:
        records, failures = _extract_sequential(
            process_paths,
            flows_folder,
            disable_progress=disable_progress,
            verbose=verbose,
        )

    _log_extraction_failures(failures)

    if not records:
        raise CacheError("No EPD records could be extracted from source folder.")

    processes_df, lcia_df = _records_to_frames(records)
    _write_cache_artifacts(
        cache_dir,
        epd_folder,
        processes_df,
        lcia_df,
        console=console,
        disable_progress=disable_progress,
    )

    logger.info(
        "EPD cache built",
        cache_dir=str(cache_dir),
        processes=len(processes_df),
        failures=len(failures),
    )
    return cache_dir


def load_epds_from_cache(cache_dir: Path, epd_folder: Path) -> list[IlcdProcess]:
    """Load IlcdProcess instances from a validated Feather cache."""
    if not is_cache_valid(cache_dir, epd_folder):
        raise CacheError(
            f"EPD cache at {cache_dir} is missing or stale for {epd_folder}"
        )

    processes_df = pd.read_feather(cache_dir / PROCESSES_FEATHER)
    lcia_df = pd.read_feather(cache_dir / LCIA_FEATHER)

    raw_lcia_by_uuid: dict[str, dict[str, dict[str, float | None]]] = {}
    if not lcia_df.empty:
        for row in lcia_df.itertuples(index=False):
            by_indicator = raw_lcia_by_uuid.setdefault(row.uuid, {})
            by_indicator.setdefault(row.indicator, {})[row.module] = row.value

    epds: list[IlcdProcess] = []
    for row in processes_df.itertuples(index=False):
        material_kwargs = {col: getattr(row, col, None) for col in MATERIAL_COLUMNS}
        epds.append(
            IlcdProcess.from_cache_record(
                uuid=row.uuid,
                loc=row.loc,
                ref_flow_uuid=row.ref_flow_uuid,
                source_path=row.source_path,
                material_kwargs=material_kwargs,
                raw_lcia=raw_lcia_by_uuid.get(row.uuid, {}),
                epd_folder=epd_folder,
            )
        )

    return epds
