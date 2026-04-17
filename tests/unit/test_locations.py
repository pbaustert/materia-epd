# tests/unit/test_locations.py
import types
import materia_epd.geo.locations as loc


def test_locations_full_coverage(monkeypatch):
    # ---------- stubs for ilcd_to_iso_location ----------
    loc.get_regions_mapping = lambda: {"R1": {"Regions": "REG-VAL"}}

    class _C:
        def __init__(self, a3):
            self.alpha_3 = a3

    class _Countries:
        def get(self, *, alpha_2=None):
            return _C("FRA") if alpha_2 == "FR" else None

    class _Historic:
        def get(self, *, alpha_2=None):
            return _C("HST") if alpha_2 == "HX" else None

    loc.pycountry = types.SimpleNamespace(
        countries=_Countries(), historic_countries=_Historic()
    )

    # direct map, regions map, countries, historic, and miss
    assert loc.ilcd_to_iso_location("UK") == "GBR"
    assert loc.ilcd_to_iso_location("R1") == "REG-VAL"
    assert loc.ilcd_to_iso_location("FR") == "FRA"
    assert loc.ilcd_to_iso_location("HX") == "HST"
    assert loc.ilcd_to_iso_location("ZZ") is None

    # ---------- get_location_attribute ----------
    data = {
        "X": {"Foo": None},
        "Y": {"Bar": {"Bar": 123}},
    }
    loc.get_location_data = lambda code: data[code]
    assert loc.get_location_attribute("X", "Foo") is None
    # expect the first-level value (a dict), matching the implementation
    assert loc.get_location_attribute("Y", "Bar") == {"Bar": 123}

    # ---------- escalate_location_set ----------
    parents = {"A": "P1", "B": "P1", "C": None}
    children = {"P1": ["Achild", "Bchild"]}

    loc.get_location_attribute = lambda code, attr: (
        parents if attr == "Parent" else children
    ).get(code)

    assert loc.escalate_location_set({"A", "B", "C"}) == {"Achild", "Bchild"}


def test_get_location_color(monkeypatch):
    loc.get_location_data = lambda code: {
        "ColorHex": "#112233",
        "ColorRGBA": [0.07, 0.13, 0.2, 0.2],
    }

    assert loc.get_location_color("XXX") == {
        "hex": "#112233",
        "rgba": [0.07, 0.13, 0.2, 0.2],
    }
