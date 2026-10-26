import json

import pytest

from materia_epd.core.constants import NS, XP
from materia_epd.epd import generic as gen
from materia_epd.epd.models import reference_flow_uuid
from materia_epd.pipeline import run
from materia_epd import resources
from materia_epd.resources import list_locations

GENERIC = {
    "ID": "0047306e-bbc8-404c-bd9c-5163e42e68c3",
    "Product Reference (French)": "Parquet contre-colle  ",
    "Cat. 1 (French)": "Produits de construction",
    "Cat. 2 (French)": "Revetements des sols et murs",
    "Cat. 3 (French)": None,
    "Product Reference": None,
    "Cat. 1": "Construction products",
    "Declared Unit": "m3",
    "Market Shares": {"DEU": 0.65, "BEL": "0.13", "RoW": 0.08, "XXX": None, "": 1},
    "HS Code": "4418",
    "GWP": {"GWP-total": {"A1-A3": []}},
    "cptax_classification": "Wood>Flooring",
}


@pytest.fixture(autouse=True)
def _clear_resource_caches():
    # Other tests patch these loaders and expect an empty cache.
    yield
    for fn in (
        resources.load_json_from_package,
        resources.get_regions_mapping,
        resources.get_indicator_synonyms,
        resources.list_locations,
    ):
        fn.cache_clear()


def test_declared_unit_symbol():
    assert gen.declared_unit_symbol({"Declared Unit": " M3 "}) == "m^3"
    assert gen.declared_unit_symbol({"Declared Unit": "m²"}) == "m^2"
    assert gen.declared_unit_symbol({"Declared Unit": "pcs"}) == "unit"
    with pytest.raises(ValueError, match="Declared Unit"):
        gen.declared_unit_symbol({"ID": "x", "Declared Unit": "ton"})


def test_market_shares_from_generic():
    assert gen.market_shares_from_generic(GENERIC) == {
        "DEU": 0.65,
        "BEL": 0.13,
        "RoW": 0.08,
    }
    assert gen.market_shares_from_generic({"Market Shares": []}) == {}


def test_build_generic_datasets():
    proc, flow = gen.build_generic_datasets(GENERIC, location="DE")

    assert proc.find(XP.UUID, NS).text == GENERIC["ID"]
    names = proc.findall(".//proc:dataSetInformation/proc:name/proc:baseName", NS)
    assert [(n.get(f"{{{NS['xml']}}}lang"), n.text) for n in names] == [
        ("fr", "Parquet contre-colle")
    ]
    hs = proc.find(XP.HS_CLASSIFICATION, NS).findall("common:class", NS)
    assert [(c.get("level"), c.get("classId")) for c in hs] == [
        ("1", "44"),
        ("2", "4418"),
    ]
    ee = proc.find(".//common:classification[@name='EE Classification']", NS)
    assert [c.text for c in ee] == [
        "Construction products",
        "Revetements des sols et murs",
    ]
    assert proc.find(XP.LOCATION, NS).get("location") == "DE"

    flow_uuid = reference_flow_uuid(proc)
    assert flow.find(XP.UUID, NS).text == flow_uuid
    props = flow.findall(XP.FLOW_PROPERTY, NS)
    assert len(props) == 1
    assert props[0].findtext("flow:meanValue", namespaces=NS) == "1"
    assert flow.find(XP.MATML_DOC, NS) is not None


def test_build_generic_datasets_without_hs_and_names():
    proc, _ = gen.build_generic_datasets({"ID": "g", "Declared Unit": "kg"})
    assert proc.find(XP.HS_CLASSIFICATION, NS) is None
    names = proc.findall(".//proc:dataSetInformation/proc:name/proc:baseName", NS)
    assert [n.text for n in names] == ["Generic product g"]
    with pytest.raises(ValueError, match="ID"):
        gen.build_generic_datasets({"Declared Unit": "kg"})


def test_generic_process_from_json():
    process = gen.generic_process_from_json(GENERIC)
    assert process.uuid == GENERIC["ID"]
    assert process.loc == "LUX"
    assert process.dec_unit == "volume"
    assert process.hs_class == "4418"
    assert {k: v for k, v in process.material_kwargs.items() if v} == {"volume": 1.0}
    assert process.market == {"DEU": 0.65, "BEL": 0.13, "RoW": 0.08}
    assert process.generic["cptax_classification"] == "Wood>Flooring"


def test_normalize_url_spec_website_export():
    export = {
        "project_name": "P",
        "data": [
            {**GENERIC, "matches": {"type": "average", "uuids": ["a", "a", "b"]}},
            {"ID": "g2", "Declared Unit": "kg"},
        ],
    }
    spec = run.normalize_url_spec(export)
    first, second = spec["processes"]
    assert first["uuid"] == GENERIC["ID"]
    assert first["matches"] == {"type": "average", "uuids": ["a", "b"]}
    assert "matches" not in first["generic"]
    assert first["generic"]["cptax_classification"] == "Wood>Flooring"
    assert second["uuid"] == "g2"
    assert second["matches"] == {"type": "average", "uuids": []}


def test_load_generic_jsons(tmp_path):
    (tmp_path / "jsons").mkdir()
    (tmp_path / "matches").mkdir()
    (tmp_path / "jsons" / f"{GENERIC['ID']}.json").write_text(json.dumps(GENERIC))
    (tmp_path / "jsons" / "other.json").write_text(json.dumps({"ID": "other"}))
    (tmp_path / "matches" / f"{GENERIC['ID']}.json").write_text(
        json.dumps({"type": "average", "uuids": ["e1"]})
    )

    loaded = run.load_generic_jsons(tmp_path)
    assert list(loaded) == [GENERIC["ID"]]
    assert loaded[GENERIC["ID"]].matches == {"type": "average", "uuids": ["e1"]}
    assert run.load_generic_jsons(tmp_path, skip={GENERIC["ID"]}) == {}
    assert run.load_generic_jsons(tmp_path / "missing") == {}


def test_list_locations():
    locations = list_locations()
    codes = {loc["code"] for loc in locations}
    assert {"LUX", "DEU", "RoW"} <= codes
    assert locations[0]["class"] == "Country"


def test_unknown_market_share_codes_are_ignored():
    process = gen.generic_process_from_json(
        {**GENERIC, "Market Shares": {"DEU": 0.9, "XYZ": 0.1}}
    )
    assert process.market == {"DEU": 0.9}
    assert process.warnings == ["Market Shares ignored for unknown location codes: XYZ"]
