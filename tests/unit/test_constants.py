# tests/unit/test_constants.py
from materia_epd.core import constants as c


# ----------------------------- Namespaces -----------------------------------


def test_ns_and_epd_ns_contain_expected_keys():
    assert "proc" in c.NS
    assert "common" in c.NS
    assert "epd" in c.NS
    assert c.NS["epd"].startswith("http")
    assert "flow" in c.NS


# ----------------------------- XP class -------------------------------------


def test_xp_exchange_by_id_returns_expected_xpath():
    result = c.XP.exchange_by_id("123")
    assert isinstance(result, str)
    assert "@dataSetInternalID='123'" in result


def test_xp_has_expected_members():
    # Pick a few representative XPath attributes
    for attr in ["UUID", "LOCATION", "LCIA_RESULT", "MATML_DOC"]:
        assert hasattr(c.XP, attr)


# ----------------------------- ATTR class -----------------------------------


def test_attr_contains_expected_fields():
    expected = {"REF_OBJECT_ID", "CLASS_ID", "LANG", "NAME", "LOCATION", "UNIT"}
    for field in expected:
        assert hasattr(c.ATTR, field)
    assert c.ATTR.LANG.startswith("{http")


# ----------------------------- Mappings and Lists ---------------------------


def test_unit_mappings_consistent_with_properties():
    # All keys in quantity map correspond to property map units
    for unit, quantity in c.UNIT_QUANTITY_MAPPING.items():
        assert isinstance(unit, str)
        assert isinstance(quantity, str)

    for unit, prop in c.UNIT_PROPERTY_MAPPING.items():
        assert isinstance(prop, str)
        assert unit  # non-empty key


def test_flow_property_mapping_is_unique():
    vals = list(c.FLOW_PROPERTY_MAPPING.values())
    assert len(vals) == len(set(vals))


def test_unit_group_mapping_keys_match_flow_property_mapping():
    # Each key in UNIT_GROUP_MAPPING appears as a value in FLOW_PROPERTY_MAPPING
    for key in c.UNIT_GROUP_MAPPING:
        assert key in c.FLOW_PROPERTY_MAPPING.values()


# ----------------------------- LCIA & Indicators ----------------------------


def test_lcia_output_modules_and_map_consistency():
    for mod in c.LCIA_AGGREGATE_MAP:
        for sub in c.LCIA_AGGREGATE_MAP[mod]:
            assert isinstance(sub, str)
    assert set(c.LCIA_OUTPUT_MODULES).issuperset(c.LCIA_AGGREGATE_MAP.keys())
