from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from materia_epd.core.constants import (
    ATTR,
    FLOW_PROPERTY_MAPPING,
    ILCD_QUANTITY_LABELS,
    NS,
    UNIT_PROPERTY_MAPPING,
    UNIT_QUANTITY_MAPPING,
    XP,
)
from materia_epd.core.physics import Material, check_properties_ranges
from materia_epd.core.utils import qn_uri, to_float
from materia_epd.geo.locations import ilcd_to_iso_location
from materia_epd.io.files import latest_flow_file, read_json_file, write_xml_root
from materia_epd.metrics.normalize import normalize_module_values
from materia_epd.resources import get_indicator_synonyms, get_market_shares


@dataclass
class IlcdFlow:
    root: ET.Element
    uuid: Union[str, None] = None
    units: Union[list, None] = None
    props: Union[list, None] = None

    def __post_init__(self):
        self._get_uuid()
        self._get_units()
        self._get_props()

    def _get_uuid(self) -> str | None:
        node = self.root.find(XP.UUID, NS)
        self.uuid = node.text.strip() if (node is not None and node.text) else None

    def _get_units(self):
        self.units = []
        for prop in self.root.findall(XP.FLOW_PROPERTY, NS):
            mean_value = prop.findtext(XP.MEAN_VALUE, namespaces=NS)
            ref = prop.find(XP.REF_TO_FLOW_PROP, NS)

            if mean_value and ref is not None:
                amount = mean_value
                uuid = ref.attrib.get(ATTR.REF_OBJECT_ID)
                name = next(
                    (
                        desc.text
                        for desc in ref.findall(XP.SHORT_DESC, NS)
                        if desc.attrib.get(ATTR.LANG) == "en"
                    ),
                    None,
                )
                unit = next(
                    (
                        symbol
                        for symbol, mapped_uuid in FLOW_PROPERTY_MAPPING.items()
                        if mapped_uuid == uuid
                    ),
                    None,
                )

                self.units.append(
                    {
                        "Name": name,
                        "Unit": unit,
                        "Amount": to_float(amount, positive=True),
                    }
                )

    def _get_props(self):
        self.props = []
        matml = self.root.find(XP.MATML_DOC, NS)

        if matml is None:
            return

        amounts = {
            pd.attrib.get(ATTR.PROPERTY): pd.findtext(XP.PROP_DATA, namespaces=NS)
            for pd in matml.findall(XP.PROPERTY_DATA, NS)
            if pd.attrib.get(ATTR.PROPERTY) and pd.find(XP.PROP_DATA, NS) is not None
        }

        for detail in matml.findall(XP.PROPERTY_DETAILS, NS):
            prop_id = detail.attrib.get(ATTR.ID)
            name = detail.findtext(XP.PROP_NAME, namespaces=NS)
            unit = detail.find(XP.PROP_UNITS, NS)
            unit_name = unit.attrib.get(ATTR.NAME) if unit is not None else None
            amount = amounts.get(prop_id)

            if name and unit_name and amount is not None:
                self.props.append(
                    {
                        "Name": name,
                        "Unit": unit_name,
                        "Amount": to_float(amount, positive=True),
                    }
                )


@dataclass
class IlcdProcess:
    root: ET.Element
    path: Path
    uuid: Union[str, None] = None
    loc: Union[None, str] = None
    ref_flow: Union[IlcdFlow, None] = None

    def __post_init__(self):
        self._get_uuid()
        self._get_loc()

    def _get_uuid(self) -> str | None:
        node = self.root.find(XP.UUID, NS)
        self.uuid = node.text.strip() if (node is not None and node.text) else None

    def _get_loc(self) -> str | None:
        loc_node = self.root.find(XP.LOCATION, NS)
        loc_code = loc_node.attrib.get(ATTR.LOCATION) if loc_node is not None else None
        self.loc = ilcd_to_iso_location(loc_code) if loc_code else None

    def get_ref_flow(self) -> IlcdFlow:
        ref_flow_id = self.root.findtext(XP.QUANT_REF, namespaces=NS).strip()
        ref_flow_exchange = self.root.find(XP.exchange_by_id(ref_flow_id), NS)
        ref_flow_uuid = ref_flow_exchange.find(XP.REF_TO_FLOW, NS).attrib.get(
            ATTR.REF_OBJECT_ID
        )
        flows_folder = self.path.parent.parent / "flows"
        flow_file = latest_flow_file(flows_folder, ref_flow_uuid)

        try:
            self.ref_flow = IlcdFlow(root=ET.parse(flow_file).getroot())
        except Exception as e:
            e.add_note(f"Error parsing {flow_file.name}")
            raise e

        exchange_amount = to_float(
            ref_flow_exchange.findtext(XP.MEAN_AMOUNT, namespaces=NS), positive=True
        )
        kwargs = {
            v: None
            for v in set(UNIT_QUANTITY_MAPPING.values())
            | set(UNIT_PROPERTY_MAPPING.values())
        }

        for u in self.ref_flow.units:
            field = UNIT_QUANTITY_MAPPING.get(u.get("Unit"))
            if field and isinstance(u.get("Amount"), (int, float)):
                kwargs[field] = u["Amount"] * exchange_amount

        for p in self.ref_flow.props:
            field = UNIT_PROPERTY_MAPPING.get(p.get("Unit"))
            if field and isinstance(p.get("Amount"), (int, float)):
                kwargs[field] = p["Amount"]

        kwargs = check_properties_ranges(self.uuid, kwargs)

        self.material_kwargs = kwargs
        self.material = Material(**kwargs)

    def get_declared_unit(self) -> str | None:
        ref_id = self.ref_flow.root.find(XP.REF_TO_REF_FLOW_PROP, NS).text

        flow_props = self.ref_flow.root.find(XP.FLOW_PROPERTIES, NS)
        for fp in flow_props.findall(XP.FLOW_PROPERTY, NS):
            if fp.get(ATTR.INTERNAL_ID) == ref_id:
                ref_fp = fp
                break

        ref = ref_fp.find(XP.REF_TO_FLOW_PROP, NS)
        uuid = ref.get(ATTR.REF_OBJECT_ID)

        uuid_to_unit = {v: k for k, v in FLOW_PROPERTY_MAPPING.items()}
        unit_symbol = uuid_to_unit.get(uuid)

        self.dec_unit = UNIT_QUANTITY_MAPPING.get(unit_symbol)

    def get_lcia_results(self) -> list[dict]:
        results = []

        for lcia_result in self.root.findall(XP.LCIA_RESULT, NS):
            ref_method = lcia_result.find(XP.REF_TO_LCIA_METHOD, NS)
            name = "Unknown"

            if ref_method is not None:
                for sd in ref_method.findall(XP.SHORT_DESC, NS):
                    if sd.attrib.get(ATTR.LANG) == "en":
                        name = sd.text.strip() if sd.text else "Unknown"
                        break

            amount_elems = lcia_result.findall(XP.AMOUNT, NS)
            values = normalize_module_values(
                amount_elems, scaling_factor=self.material.scaling_factor
            )

            canon = next(
                (
                    c
                    for c, aliases in get_indicator_synonyms().items()
                    if name in aliases
                ),
                None,
            )
            if canon:
                results.append({"name": canon, "values": values})

        self.lcia_results = results

    def get_hs_class(self) -> str:
        hs_node = self.root.find(XP.HS_CLASSIFICATION, NS)
        top_class = hs_node.find(XP.CLASS_LEVEL_2, NS)
        self.hs_class = top_class.attrib.get(ATTR.CLASS_ID)

    def get_market(self) -> dict:
        self.market = get_market_shares(self.loc, self.hs_class)
        return self.market

    def get_matches(self) -> dict:
        MATCHES_FOLDER = self.path.parent.parent / "matches"
        matches_path = os.path.join(MATCHES_FOLDER, f"{self.uuid}.json")
        self.matches = read_json_file(matches_path)

    def write_process(
        self, results: dict[str, dict[str, float]], out_path: Path
    ) -> bool:
        def _get_attr_local(el: ET.Element, local: str):
            for k, v in el.attrib.items():
                if k.rsplit("}", 1)[-1] == local:
                    return v
            return None

        lcia_map = {
            next(
                (
                    sd.text.strip()
                    for sd in r.findall(f"{XP.REF_TO_LCIA_METHOD}/{XP.SHORT_DESC}", NS)
                    if sd.attrib.get(ATTR.LANG) == "en"
                ),
                "Unknown",
            ): r
            for r in self.root.findall(XP.LCIA_RESULT, NS)
        }

        for ind, stages in results.items():
            r = lcia_map.get(ind)
            if r is None:
                continue

            by_module = {}
            for el in r.findall(XP.AMOUNT, NS):
                mod = (
                    _get_attr_local(el, "module")
                    or _get_attr_local(el, "phase")
                    or _get_attr_local(el, "stageId")
                    or _get_attr_local(el, "lifecycleModule")
                )
                if mod:
                    by_module[mod] = el

            for stage, val in stages.items():
                el = by_module.get(stage)
                if el is not None:
                    el.text = str(float(val))

        file_path = out_path / "processes" / f"{self.uuid}.xml"
        return write_xml_root(self.root, file_path)

    def write_flow(self, kwargs: dict, out_path: Path) -> None:
        def fmt(v):
            return f"{float(v):.6f}".rstrip("0").rstrip(".")

        matml = self.ref_flow.root.find(XP.MATML_DOC, NS)
        for ch in list(matml):
            matml.remove(ch)

        flow_props = self.ref_flow.root.find(XP.FLOW_PROPERTIES, NS)
        for ch in list(flow_props):
            flow_props.remove(ch)

        material = ET.SubElement(matml, qn_uri(NS.get("mat"), "Material"))
        bulk = ET.SubElement(material, qn_uri(NS.get("mat"), "BulkDetails"))
        meta = ET.SubElement(matml, qn_uri(NS.get("mat"), "Metadata"))

        for prop, value in kwargs.items():
            unit = {v: k for k, v in UNIT_PROPERTY_MAPPING.items()}.get(prop)
            if unit is None or value is None:
                continue

            pd = ET.SubElement(
                bulk,
                qn_uri(NS.get("mat"), "PropertyData"),
                {ATTR.PROPERTY: f"pr_{prop}"},
            )
            ET.SubElement(
                pd, qn_uri(NS.get("mat"), "Data"), {"format": "float"}
            ).text = fmt(value)

            det = ET.SubElement(
                meta, qn_uri(NS.get("mat"), "PropertyDetails"), {ATTR.ID: f"pr_{prop}"}
            )
            ET.SubElement(det, qn_uri(NS.get("mat"), "Name")).text = prop.replace(
                "_", " "
            )
            units = ET.SubElement(
                det,
                qn_uri(NS.get("mat"), "Units"),
                {ATTR.NAME: unit, "description": unit},
            )
            if "/" in unit:
                num, den = unit.split("/", 1)
                u1 = ET.SubElement(units, qn_uri(NS.get("mat"), "Unit"))
                ET.SubElement(u1, qn_uri(NS.get("mat"), "Name")).text = num.strip()
                base = den.strip().split("^")[0]
                power = -int(den.strip().split("^")[1]) if "^" in den else -1
                u2 = ET.SubElement(
                    units, qn_uri(NS.get("mat"), "Unit"), {"power": str(power)}
                )
                ET.SubElement(u2, qn_uri(NS.get("mat"), "Name")).text = base
            else:
                u = ET.SubElement(units, qn_uri(NS.get("mat"), "Unit"))
                ET.SubElement(u, qn_uri(NS.get("mat"), "Name")).text = unit

        quantity_list = [
            {
                "property": k,
                "unit": u,
                "value": v,
                "uuid": FLOW_PROPERTY_MAPPING.get(u),
            }
            for k, v in kwargs.items()
            if (u := {v: k for k, v in UNIT_QUANTITY_MAPPING.items()}.get(k))
            is not None
            and v is not None
        ]

        quantity_list = [
            item for item in quantity_list if item["property"] == self.dec_unit
        ] + [item for item in quantity_list if item["property"] != self.dec_unit]

        self.ref_flow.root.find(XP.REF_TO_REF_FLOW_PROP, NS).text = "0"

        for idx, item in enumerate(quantity_list):
            fp = ET.SubElement(
                flow_props,
                qn_uri(NS.get("flow"), "flowProperty"),
                {"dataSetInternalID": str(idx)},
            )
            ref = ET.SubElement(
                fp,
                qn_uri(NS.get("flow"), "referenceToFlowPropertyDataSet"),
                {
                    ATTR.REF_OBJECT_ID: item["uuid"],
                    "version": "00.00.000",  # TODO: make dynamic
                    "type": "flow property data set",
                    "uri": f"../flowproperties/{item['uuid']}.xml",
                },
            )
            sd = ET.SubElement(
                ref, qn_uri(NS.get("common"), "shortDescription"), {ATTR.LANG: "en"}
            )
            sd.text = ILCD_QUANTITY_LABELS.get(
                item["property"], item["property"].title()
            )
            ET.SubElement(fp, qn_uri(NS.get("flow"), "meanValue")).text = fmt(
                item["value"]
            )

        file_path = out_path / "flows" / f"{self.ref_flow.uuid}.xml"
        return write_xml_root(self.ref_flow.root, file_path)
