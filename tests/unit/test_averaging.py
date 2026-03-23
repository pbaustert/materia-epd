# tests/unit/test_averaging.py
from materia_epd.metrics import averaging as avg


# ----------------------------- average_material_properties ------------------


class DummyMat:
    def __init__(self, d):
        self._d = d

    def to_dict(self):
        return self._d


class DummyEpd:
    def __init__(self, d):
        self.material = DummyMat(d)


def test_average_material_properties_handles_empty():
    epds = [DummyEpd({"non_numeric": "x"}), DummyEpd({})]
    assert avg.average_material_properties(epds) == {}
