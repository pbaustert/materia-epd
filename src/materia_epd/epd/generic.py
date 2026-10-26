"""Generic EPD skeletons built from a generic-EPD JSON object and the XML templates.

A generic-EPD JSON object (one file per product in ``<gen>/jsons/<ID>.json``, or one
entry of the website export ``{"project_name": ..., "data": [...]}``) looks like::

    {
      "ID": "<generic uuid>",
      "Product Reference (French)": "...", "Product Reference": "...",
      "Cat. 1 (French)": "...", "Cat. 2 (French)": "...", "Cat. 3 (French)": "...",
      "Cat. 1": ..., "Cat. 2": ..., "Cat. 3": ...,
      "Declared Unit": "m3",
      "Market Shares": {"DEU": 0.65, "BEL": 0.13, "RoW": 0.08, ...},
      "HS Code": "4418",
      ...
    }

``build_generic_datasets`` fills ``GenPro_template.xml`` / ``GenRef_template.xml``
(bundled in ``materia_epd/data/templates``, or from ``<gen>/templates``) with it.
Unused keys (e.g. "cptax_classification", "Comment", "GWP") are ignored.
"""

from __future__ import annotations

import copy
import logging
import re
import uuid as uuid_lib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

from materia_epd.core.constants import (
    FLOW_PROPERTY_MAPPING,
    ILCD_QUANTITY_LABELS,
    NS,
    UNIT_QUANTITY_MAPPING,
    XP,
)
from materia_epd.core.utils import qn_uri
from materia_epd.epd.models import IlcdProcess
from materia_epd.resources import list_locations, templates_dir

logger = structlog.wrap_logger(logging.getLogger(__name__))

PROCESS_TEMPLATE = "GenPro_template.xml"
FLOW_TEMPLATE = "GenRef_template.xml"

# "Declared Unit" spellings -> unit symbol of FLOW_PROPERTY_MAPPING
DECLARED_UNIT_ALIASES = {
    "kg": "kg",
    "m": "m",
    "m2": "m^2",
    "m²": "m^2",
    "m^2": "m^2",
    "m3": "m^3",
    "m³": "m^3",
    "m^3": "m^3",
    "unit": "unit",
    "units": "unit",
    "u": "unit",
    "pc": "unit",
    "pcs": "unit",
    "piece": "unit",
    "pieces": "unit",
    "stk": "unit",
}

FRENCH = " (French)"


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _text(generic: dict, key: str) -> str | None:
    """English value of a field, else its French variant ("<key> (French)")."""
    return _clean(generic.get(key)) or _clean(generic.get(key + FRENCH))


def generic_uuid(generic: dict) -> str | None:
    return _clean(generic.get("ID"))


def declared_unit_symbol(generic: dict) -> str:
    raw = (_clean(generic.get("Declared Unit")) or "").lower().replace(" ", "")
    symbol = DECLARED_UNIT_ALIASES.get(raw)
    if symbol is None:
        raise ValueError(
            f"Unsupported 'Declared Unit' {generic.get('Declared Unit')!r} for generic "
            f"EPD {generic_uuid(generic)}; use one of kg, m, m2, m3, unit."
        )
    return symbol


def market_shares_from_generic(generic: dict) -> dict[str, float]:
    """Positive numeric "Market Shares" of a generic EPD (location code -> share)."""
    shares = generic.get("Market Shares") or {}
    if not isinstance(shares, dict):
        return {}
    out = {}
    for loc, share in shares.items():
        try:
            value = float(share)
        except (TypeError, ValueError):
            continue
        if _clean(loc) and value > 0:
            out[str(loc).strip()] = value
    return out


@lru_cache(maxsize=8)
def _load_templates(folder: str | None) -> tuple[ET.Element, ET.Element]:
    if folder:
        base = Path(folder)
        return (
            ET.parse(base / PROCESS_TEMPLATE).getroot(),
            ET.parse(base / FLOW_TEMPLATE).getroot(),
        )
    with templates_dir() as base:
        return (
            ET.parse(Path(base) / PROCESS_TEMPLATE).getroot(),
            ET.parse(Path(base) / FLOW_TEMPLATE).getroot(),
        )


def _set_names(name_node: ET.Element, ns: str, names: dict[str, str]) -> None:
    for child in list(name_node):
        if child.tag in (
            qn_uri(ns, "baseName"),
            qn_uri(ns, "functionalUnitFlowProperties"),
        ):
            name_node.remove(child)
    for i, (lang, text) in enumerate(names.items()):
        node = ET.Element(qn_uri(ns, "baseName"), {qn_uri(NS["xml"], "lang"): lang})
        node.text = text
        name_node.insert(i, node)


def _set_classes(
    root: ET.Element, name: str, classes: list[tuple[int, str, str]]
) -> None:
    """Replace the ``(level, classId, text)`` classes of a classification.

    The classification is removed when there are no classes.
    """
    info = root.find(".//proc:classificationInformation", NS)
    node = root.find(f".//common:classification[@name='{name}']", NS)
    if info is None or node is None:
        return
    if not classes:
        info.remove(node)
        return
    for child in list(node):
        node.remove(child)
    for level, class_id, text in classes:
        cls = ET.SubElement(
            node,
            qn_uri(NS["common"], "class"),
            {"level": str(level), "classId": class_id},
        )
        cls.text = text


def build_generic_datasets(
    generic: dict,
    templates_folder: str | Path | None = None,
    location: str | None = None,
) -> tuple[ET.Element, ET.Element]:
    """Return ``(process_root, flow_root)`` of the generic EPD described by ``generic``.

    The process gets the generic "ID", names, HS / EE classifications and a reference
    flow (UUID derived from the ID) declaring 1 "Declared Unit" of product.
    """
    gid = generic_uuid(generic)
    if not gid:
        raise ValueError("Generic EPD object has no 'ID'.")
    unit_symbol = declared_unit_symbol(generic)
    quantity = UNIT_QUANTITY_MAPPING[unit_symbol]

    process_tpl, flow_tpl = _load_templates(
        str(templates_folder) if templates_folder else None
    )
    proc, flow = copy.deepcopy(process_tpl), copy.deepcopy(flow_tpl)
    flow_uuid = str(uuid_lib.uuid5(uuid_lib.NAMESPACE_URL, f"{gid}/flow"))
    timestamp = datetime.now(timezone.utc).isoformat()

    names = {
        lang: text
        for lang, text in (
            ("en", _clean(generic.get("Product Reference"))),
            ("fr", _clean(generic.get("Product Reference" + FRENCH))),
        )
        if text
    } or {"en": f"Generic product {gid}"}
    label = next(iter(names.values()))

    # ── process ──────────────────────────────────────────────────────────
    proc.find(XP.UUID, NS).text = gid
    _set_names(proc.find(".//proc:dataSetInformation/proc:name", NS), NS["proc"], names)

    # HS levels as in the template: 1 chapter, 2 heading (read by get_hs_class), 3 sub.
    hs = re.sub(r"\D", "", str(generic.get("HS Code") or ""))
    _set_classes(
        proc,
        "HS Classification",
        [(level, hs[:n], "") for level, n in ((1, 2), (2, 4), (3, 6)) if len(hs) >= n],
    )
    cats = [_text(generic, f"Cat. {i}") for i in (1, 2, 3)]
    _set_classes(
        proc, "EE Classification", [(i, c, c) for i, c in enumerate(cats) if c]
    )

    if location:
        loc = proc.find(XP.LOCATION, NS)
        if loc is not None:
            loc.set("location", location)

    for node in proc.iter(qn_uri(NS["common"], "timeStamp")):
        node.text = timestamp

    exchange = proc.find(XP.exchange_by_id("1"), NS)
    ref = exchange.find(XP.REF_TO_FLOW, NS)
    ref.set("refObjectId", flow_uuid)
    ref.set("uri", f"../flows/{flow_uuid}.xml")
    ref.find(XP.SHORT_DESC, NS).text = label

    # ── reference flow ───────────────────────────────────────────────────
    flow.find(XP.UUID, NS).text = flow_uuid
    _set_names(flow.find(".//flow:dataSetInformation/flow:name", NS), NS["flow"], names)
    for node in flow.iter(qn_uri(NS["common"], "timeStamp")):
        node.text = timestamp

    # Empty MatML document: filled with the averaged properties by write_flow
    info = flow.find(".//flow:dataSetInformation", NS)
    other = ET.SubElement(info, qn_uri(NS["common"], "other"))
    ET.SubElement(other, qn_uri(NS["mat"], "MatML_Doc"))

    flow_props = flow.find(XP.FLOW_PROPERTIES, NS)
    props = flow_props.findall("flow:flowProperty", NS)
    for extra in props[1:]:
        flow_props.remove(extra)
    prop = props[0]
    prop.set("dataSetInternalID", "0")
    prop_ref = prop.find("flow:referenceToFlowPropertyDataSet", NS)
    prop_uuid = FLOW_PROPERTY_MAPPING[unit_symbol]
    prop_ref.set("refObjectId", prop_uuid)
    prop_ref.set("uri", f"../flowproperties/{prop_uuid}.xml")
    prop_ref.find(XP.SHORT_DESC, NS).text = ILCD_QUANTITY_LABELS[quantity]
    prop.find("flow:meanValue", NS).text = "1"
    flow.find(XP.REF_TO_REF_FLOW_PROP, NS).text = "0"

    return proc, flow


def generic_process_from_json(
    generic: dict,
    templates_folder: str | Path | None = None,
    location: str | None = None,
) -> IlcdProcess:
    """`IlcdProcess` of a generic EPD JSON object, ready for the pipeline but matches.

    Its market comes from "Market Shares" when given; otherwise from the market data of
    its location and HS code, as for XML skeletons.
    """
    proc_root, flow_root = build_generic_datasets(generic, templates_folder, location)
    gid = generic_uuid(generic)
    process = IlcdProcess(
        root=proc_root, path=f"generic:{gid}", flow_loader=lambda _uuid: flow_root
    )
    process.get_ref_flow()
    process.get_declared_unit()
    process.get_hs_class()
    process.warnings = []
    shares = market_shares_from_generic(generic)
    known = {loc["code"] for loc in list_locations()}
    unknown = sorted(set(shares) - known)
    if unknown:
        # No location data (transport, report colors) for these codes: leave them out
        message = (
            f"Market Shares ignored for unknown location codes: {', '.join(unknown)}"
        )
        logger.warning(message, uuid=gid)
        process.warnings.append(message)
        shares = {loc: v for loc, v in shares.items() if loc in known}
    if shares:
        process.market = shares
    else:
        try:
            process.get_market()
        except Exception as e:  # e.g. Comtrade unreachable for an unknown HS code
            logger.warning("No market shares available", uuid=gid, error=str(e))
            process.market = {}
    process.generic = generic
    return process
