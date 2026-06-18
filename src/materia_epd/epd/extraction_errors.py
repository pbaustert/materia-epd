"""Structured errors and XML context for EPD cache extraction."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class EpdExtractionError(Exception):
    """Raised when a single EPD XML file cannot be extracted for the cache."""

    process_path: str
    stage: str
    message: str
    process_uuid: str | None = None
    xml_tag: str | None = None
    xml_attributes: dict[str, str] = field(default_factory=dict)
    xml_line: int | None = None
    xml_text: str | None = None
    flow_path: str | None = None
    cause_type: str | None = None

    def __str__(self) -> str:
        return self.summary()

    def summary(self) -> str:
        parts = [f"{Path(self.process_path).name} [{self.stage}] {self.message}"]
        if self.process_uuid:
            parts.append(f"uuid={self.process_uuid}")
        if self.xml_tag:
            parts.append(f"element={self.xml_tag}")
        if self.xml_attributes:
            attrs = " ".join(f'{k}="{v}"' for k, v in self.xml_attributes.items())
            parts.append(f"attributes={attrs}")
        if self.xml_line is not None:
            parts.append(f"line={self.xml_line}")
        if self.xml_text is not None:
            parts.append(f"text={self.xml_text!r}")
        if self.flow_path:
            parts.append(f"flow={Path(self.flow_path).name}")
        if self.cause_type:
            parts.append(f"cause={self.cause_type}")
        return "; ".join(parts)

    def to_log_dict(self) -> dict:
        payload = {
            "file": Path(self.process_path).name,
            "process_path": self.process_path,
            "stage": self.stage,
            "error": self.message,
        }
        if self.process_uuid:
            payload["uuid"] = self.process_uuid
        if self.xml_tag:
            payload["xml_tag"] = self.xml_tag
        if self.xml_attributes:
            payload["xml_attributes"] = self.xml_attributes
        if self.xml_line is not None:
            payload["xml_line"] = self.xml_line
        if self.xml_text is not None:
            payload["xml_text"] = self.xml_text
        if self.flow_path:
            payload["flow_path"] = self.flow_path
        if self.cause_type:
            payload["cause_type"] = self.cause_type
        payload["detail"] = self.summary()
        return payload


def local_tag(elem: ET.Element) -> str:
    """Return the local XML tag name without namespace URI."""
    if "}" in elem.tag:
        return elem.tag.rsplit("}", 1)[-1]
    return elem.tag


def describe_element(elem: ET.Element | None) -> str | None:
    if elem is None:
        return None
    return local_tag(elem)


def element_attributes(elem: ET.Element | None) -> dict[str, str]:
    if elem is None:
        return {}
    return {
        key.rsplit("}", 1)[-1]: value
        for key, value in elem.attrib.items()
        if value is not None
    }


def find_element_line(xml_path: Path, elem: ET.Element | None) -> int | None:
    """
    Best-effort line number lookup by scanning the source file for the element.

    ElementTree does not expose sourceline; we match tag name and salient text/attributes.
    """
    if elem is None:
        return None

    tag = local_tag(elem)
    text = (elem.text or "").strip()
    attrib_values = [v for v in elem.attrib.values() if v]

    try:
        lines = xml_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None

    candidates: list[int] = []
    for lineno, line in enumerate(lines, 1):
        if tag not in line:
            continue
        if text and text not in line:
            continue
        if attrib_values and not any(value in line for value in attrib_values):
            continue
        candidates.append(lineno)

    if candidates:
        return candidates[0]

    for lineno, line in enumerate(lines, 1):
        if tag in line and ("<" in line or ":" + tag in line):
            return lineno

    return None


def wrap_extraction_error(
    exc: Exception,
    *,
    process_path: Path,
    stage: str,
    process_uuid: str | None = None,
    element: ET.Element | None = None,
    flow_path: Path | None = None,
) -> EpdExtractionError:
    """Convert an unexpected exception into a structured extraction error."""
    if isinstance(exc, EpdExtractionError):
        return exc

    xml_line = find_element_line(process_path, element)
    return EpdExtractionError(
        process_path=str(process_path),
        stage=stage,
        message=str(exc),
        process_uuid=process_uuid,
        xml_tag=describe_element(element),
        xml_attributes=element_attributes(element),
        xml_line=xml_line,
        xml_text=(element.text or "").strip() if element is not None else None,
        flow_path=str(flow_path) if flow_path is not None else None,
        cause_type=type(exc).__name__,
    )
