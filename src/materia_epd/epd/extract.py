"""Pure extraction helpers for EPD cache building (multiprocessing-safe)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from materia_epd.core.constants import (
    ATTR,
    FLOW_PROPERTY_MAPPING,
    NS,
    UNIT_PROPERTY_MAPPING,
    UNIT_QUANTITY_MAPPING,
    XP,
)
from materia_epd.core.physics import check_properties_ranges
from materia_epd.core.utils import to_float
from materia_epd.epd.extraction_errors import (
    EpdExtractionError,
    describe_element,
    element_attributes,
    find_element_line,
    wrap_extraction_error,
)
from materia_epd.geo.locations import ilcd_to_iso_location
from materia_epd.io.files import latest_flow_file
from materia_epd.metrics.normalize import normalize_module_values
from materia_epd.resources import get_indicator_synonyms


def _raise_extraction_error(
    process_path: Path,
    stage: str,
    message: str,
    *,
    process_uuid: str | None = None,
    element: ET.Element | None = None,
    flow_path: Path | None = None,
) -> None:
    raise EpdExtractionError(
        process_path=str(process_path),
        stage=stage,
        message=message,
        process_uuid=process_uuid,
        xml_tag=describe_element(element),
        xml_attributes=element_attributes(element),
        xml_line=find_element_line(process_path, element),
        xml_text=(element.text or "").strip() if element is not None else None,
        flow_path=str(flow_path) if flow_path is not None else None,
    )


def _parse_uuid(root: ET.Element) -> str | None:
    node = root.find(XP.UUID, NS)
    return node.text.strip() if (node is not None and node.text) else None


def _parse_loc(root: ET.Element) -> str | None:
    loc_node = root.find(XP.LOCATION, NS)
    loc_code = loc_node.attrib.get(ATTR.LOCATION) if loc_node is not None else None
    return ilcd_to_iso_location(loc_code) if loc_code else None


def _parse_material_kwargs(
    process_root: ET.Element,
    process_path: Path,
    flows_folder: Path,
    uuid: str | None,
) -> tuple[dict, str]:
    quant_ref_node = process_root.find(XP.QUANT_REF, NS)
    ref_flow_id = (
        quant_ref_node.text.strip()
        if quant_ref_node is not None and quant_ref_node.text
        else ""
    )
    if not ref_flow_id:
        _raise_extraction_error(
            process_path,
            "parse_reference_flow",
            "missing proc:quantitativeReference/proc:referenceToReferenceFlow",
            process_uuid=uuid,
            element=quant_ref_node,
        )

    ref_flow_exchange = process_root.find(XP.exchange_by_id(ref_flow_id), NS)
    if ref_flow_exchange is None:
        _raise_extraction_error(
            process_path,
            "parse_reference_flow",
            f"reference exchange not found for dataSetInternalID={ref_flow_id!r}",
            process_uuid=uuid,
        )

    ref_to_flow = ref_flow_exchange.find(XP.REF_TO_FLOW, NS)
    if ref_to_flow is None:
        _raise_extraction_error(
            process_path,
            "parse_reference_flow",
            "missing proc:referenceToFlowDataSet on reference exchange",
            process_uuid=uuid,
            element=ref_flow_exchange,
        )

    ref_flow_uuid = ref_to_flow.attrib.get(ATTR.REF_OBJECT_ID)
    if not ref_flow_uuid:
        _raise_extraction_error(
            process_path,
            "parse_reference_flow",
            "reference exchange is missing refObjectId for flow",
            process_uuid=uuid,
            element=ref_to_flow,
        )

    try:
        flow_file = latest_flow_file(flows_folder, ref_flow_uuid)
    except FileNotFoundError as exc:
        raise EpdExtractionError(
            process_path=str(process_path),
            stage="parse_reference_flow",
            message=str(exc),
            process_uuid=uuid,
            xml_tag=describe_element(ref_to_flow),
            xml_attributes=element_attributes(ref_to_flow),
            xml_line=find_element_line(process_path, ref_to_flow),
        ) from exc

    flow_root = ET.parse(flow_file).getroot()

    mean_amount_node = ref_flow_exchange.find(XP.MEAN_AMOUNT, NS)
    exchange_amount = to_float(
        mean_amount_node.text if mean_amount_node is not None else None,
        positive=True,
    )
    if exchange_amount is None:
        _raise_extraction_error(
            process_path,
            "parse_reference_flow",
            "proc:meanAmount is missing, empty, or not a positive number on reference exchange",
            process_uuid=uuid,
            element=mean_amount_node or ref_flow_exchange,
            flow_path=flow_file,
        )

    kwargs = {
        v: None
        for v in set(UNIT_QUANTITY_MAPPING.values()) | set(UNIT_PROPERTY_MAPPING.values())
    }

    for prop in flow_root.findall(XP.FLOW_PROPERTY, NS):
        mean_value = prop.findtext(XP.MEAN_VALUE, namespaces=NS)
        ref = prop.find(XP.REF_TO_FLOW_PROP, NS)
        if mean_value and ref is not None:
            unit_uuid = ref.attrib.get(ATTR.REF_OBJECT_ID)
            unit = next(
                (
                    symbol
                    for symbol, mapped_uuid in FLOW_PROPERTY_MAPPING.items()
                    if mapped_uuid == unit_uuid
                ),
                None,
            )
            field = UNIT_QUANTITY_MAPPING.get(unit)
            amount = to_float(mean_value, positive=True)
            if field and amount is not None:
                kwargs[field] = amount * exchange_amount
            elif field and mean_value:
                _raise_extraction_error(
                    process_path,
                    "parse_flow_quantities",
                    f"flow:meanValue is missing or invalid for unit {unit!r}",
                    process_uuid=uuid,
                    element=prop,
                    flow_path=flow_file,
                )

    matml = flow_root.find(XP.MATML_DOC, NS)
    if matml is not None:
        amounts = {
            pd.attrib.get(ATTR.PROPERTY): pd.findtext(XP.PROP_DATA, namespaces=NS)
            for pd in matml.findall(XP.PROP_DATA, NS)
            if pd.attrib.get(ATTR.PROPERTY) and pd.find(XP.PROP_DATA, NS) is not None
        }
        for detail in matml.findall(XP.PROPERTY_DETAILS, NS):
            prop_id = detail.attrib.get(ATTR.ID)
            unit = detail.find(XP.PROP_UNITS, NS)
            unit_name = unit.attrib.get(ATTR.NAME) if unit is not None else None
            amount_text = amounts.get(prop_id)
            if unit_name and amount_text is not None:
                field = UNIT_PROPERTY_MAPPING.get(unit_name)
                amount = to_float(amount_text, positive=True)
                if field and amount is not None:
                    kwargs[field] = amount
                elif field:
                    _raise_extraction_error(
                        process_path,
                        "parse_flow_properties",
                        f"mat:Data is missing or invalid for property {prop_id!r} ({unit_name})",
                        process_uuid=uuid,
                        element=detail,
                        flow_path=flow_file,
                    )

    kwargs = check_properties_ranges(uuid, kwargs)
    return kwargs, ref_flow_uuid


def _parse_raw_lcia(
    process_root: ET.Element, process_path: Path, uuid: str | None
) -> dict[str, dict[str, float | None]]:
    synonyms = get_indicator_synonyms()
    raw_lcia: dict[str, dict[str, float | None]] = {}

    for lcia_result in process_root.findall(XP.LCIA_RESULT, NS):
        ref_method = lcia_result.find(XP.REF_TO_LCIA_METHOD, NS)
        name = "Unknown"
        if ref_method is not None:
            for sd in ref_method.findall(XP.SHORT_DESC, NS):
                if sd.attrib.get(ATTR.LANG) == "en":
                    name = sd.text.strip() if sd.text else "Unknown"
                    break

        amount_elems = lcia_result.findall(XP.AMOUNT, NS)
        try:
            values = normalize_module_values(amount_elems, scaling_factor=1.0)
        except Exception as exc:
            element = amount_elems[0] if amount_elems else lcia_result
            raise wrap_extraction_error(
                exc,
                process_path=process_path,
                stage="parse_lcia",
                process_uuid=uuid,
                element=element,
            ) from exc

        canon = next(
            (c for c, aliases in synonyms.items() if name in aliases),
            None,
        )
        if canon:
            raw_lcia[canon] = values

    return raw_lcia


def extract_epd_record(process_path: str, flows_folder: str) -> dict:
    """
    Extract cacheable fields from one EPD process XML.

    Module-level worker for ProcessPoolExecutor (str paths for Windows spawn).
    """
    process_file = Path(process_path)
    flows_dir = Path(flows_folder)
    uuid: str | None = None

    try:
        root = ET.parse(process_file).getroot()
        uuid = _parse_uuid(root)
        loc = _parse_loc(root)
        material_kwargs, ref_flow_uuid = _parse_material_kwargs(
            root, process_file, flows_dir, uuid
        )
        raw_lcia = _parse_raw_lcia(root, process_file, uuid)
    except EpdExtractionError:
        raise
    except ET.ParseError as exc:
        raise EpdExtractionError(
            process_path=str(process_file),
            stage="parse_xml",
            message=str(exc),
            process_uuid=uuid,
            cause_type=type(exc).__name__,
        ) from exc
    except Exception as exc:
        raise wrap_extraction_error(
            exc,
            process_path=process_file,
            stage="extract_epd_record",
            process_uuid=uuid,
        ) from exc

    return {
        "uuid": uuid,
        "loc": loc,
        "ref_flow_uuid": ref_flow_uuid,
        "source_path": process_file.name,
        "material_kwargs": material_kwargs,
        "raw_lcia": raw_lcia,
    }
