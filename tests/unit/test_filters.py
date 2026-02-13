# tests/unit/test_filters.py

from typing import Union

from materia_epd.epd.filters import (
    EPDFilter,
    LocationFilter,
    UnitConformityFilter,
    UUIDFilter,
)

# --- helpers -----------------------------------------------------------------


class FakeMaterial:
    def __init__(self, raise_error: bool = False):
        self.raise_error = raise_error
        self.calls = []

    def rescale(self, target_kwargs):
        self.calls.append(target_kwargs)
        if self.raise_error:
            raise ValueError("cannot rescale")


class FakeFlow:
    def __init__(self, uuid="f-1", units="dummy-units", props="dummy-props"):
        self.uuid = uuid
        self.units = units
        self.props = props


class FakeProcess:
    def __init__(self, uuid="u-1", loc="FR", material=None):
        self.uuid = uuid
        self.loc = loc
        self.material = material or FakeMaterial()
        self.ref_flow_called = 0
        self.ref_flow: Union[FakeFlow, None] = None

    def get_ref_flow(self):
        self.ref_flow_called += 1
        self.ref_flow = FakeFlow()
        return {"dummy": True}


# --- tests -------------------------------------------------------------------


def test_base_epdfilter_matches_always_true_and_repr():
    f = EPDFilter()
    epd = FakeProcess()
    assert f.matches(epd) is True
    assert repr(f) == "EPDFilter"


def test_uuidfilter_matches_and_repr():
    f = UUIDFilter({"uuids": ["u-1", "u-2"]})
    assert f.matches(FakeProcess(uuid="u-1")) is True
    assert f.matches(FakeProcess(uuid="u-3")) is False
    assert "uuids=['u-1', 'u-2']" in repr(f)


def test_locationfilter_matches_and_repr():
    f = LocationFilter({"FR", "DE"})
    assert f.matches(FakeProcess(loc="FR")) is True
    assert f.matches(FakeProcess(loc="IT")) is False
    assert "code=" in repr(f)


def test_unitconformityfilter_matches_when_rescale_ok():
    mat = FakeMaterial(raise_error=False)
    epd = FakeProcess(material=mat)
    filt = UnitConformityFilter({"mass": 2.0})
    assert filt.matches(epd) is True
    # get_ref_flow called and rescale received kwargs
    assert epd.ref_flow_called == 1
    assert mat.calls == [{"mass": 2.0}]
    assert "target={'mass': 2.0}" in repr(filt)


def test_unitconformityfilter_returns_false_on_valueerror():
    mat = FakeMaterial(raise_error=True)
    epd = FakeProcess(material=mat)
    filt = UnitConformityFilter({"volume": 3.0})
    assert filt.matches(epd) is False
    # Still calls get_ref_flow even if rescale fails
    assert epd.ref_flow_called == 1
