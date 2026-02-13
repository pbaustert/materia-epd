# tests/unit/test_pipeline.py
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from materia_epd.epd import pipeline as pl

# ------------------------------ gen_xml_objects ------------------------------


def test_gen_xml_objects_with_folder_reads_xml_only(tmp_path: Path):
    (tmp_path / "a.xml").write_text("<a/>", encoding="utf-8")
    (tmp_path / "b.xml").write_text("<b/>", encoding="utf-8")
    (tmp_path / "skip.txt").write_text("x", encoding="utf-8")

    out = list(pl.gen_xml_objects(tmp_path))
    names = {p.name for p, _ in out}
    assert names == {"a.xml", "b.xml"}
    assert all(isinstance(root, ET.Element) for _, root in out)


def test_gen_xml_objects_with_file_uses_parent(tmp_path: Path):
    (tmp_path / "x1.xml").write_text("<r/>", encoding="utf-8")
    (tmp_path / "x2.xml").write_text("<r/>", encoding="utf-8")
    file_inside = tmp_path / "x1.xml"

    out = list(pl.gen_xml_objects(file_inside))
    names = {p.name for p, _ in out}
    assert names == {"x1.xml", "x2.xml"}


def test_gen_xml_objects_invalid_path_raises(tmp_path: Path):
    bogus = tmp_path / "does_not_exist.anything"
    with pytest.raises(ValueError):
        list(pl.gen_xml_objects(bogus))


def test_gen_xml_objects_skips_bad_xml(tmp_path: Path, capsys):
    (tmp_path / "ok.xml").write_text("<r/>", encoding="utf-8")
    (tmp_path / "bad.xml").write_text("<r>", encoding="utf-8")

    out = list(pl.gen_xml_objects(tmp_path))
    assert [p.name for p, _ in out] == ["ok.xml"]
    msg = capsys.readouterr().out
    assert "Error reading bad.xml" in msg


# -------------------------------- gen_epds -----------------------------------


def test_gen_epds_wraps_xmls_in_IlcdProcess(tmp_path: Path, monkeypatch):
    (tmp_path / "p1.xml").write_text("<root id='1'/>", encoding="utf-8")
    (tmp_path / "p2.xml").write_text("<root id='2'/>", encoding="utf-8")

    calls = []

    class FakeIlcd:
        def __init__(self, root, path):
            calls.append((path.name, root.tag))

    monkeypatch.setattr(pl, "IlcdProcess", FakeIlcd, raising=True)
    out = list(pl.gen_epds(tmp_path))
    assert len(out) == 2
    assert {n for n, _ in calls} == {"p1.xml", "p2.xml"}


# ----------------------------- gen_filtered_epds -----------------------------


def test_gen_filtered_epds_applies_all_filters():
    class E:
        def __init__(self, v):
            self.v = v

    class F:
        def __init__(self, ok):
            self.ok = ok

        def matches(self, epd):
            return self.ok(epd)

    epds = [E(1), E(2), E(3), E(4)]
    f1 = F(lambda e: e.v >= 2)
    f2 = F(lambda e: e.v % 2 == 0)
    out = list(pl.gen_filtered_epds(epds, [f1, f2]))
    assert [e.v for e in out] == [2, 4]


# ---------------------------- gen_locfiltered_epds ---------------------------


def test_gen_locfiltered_epds_escalates_until_found(monkeypatch):
    class LF:
        def __init__(self, locs):
            self.locations = set(locs)

    attempts = {"n": 0}

    def fake_gen_filtered(epds, filters):
        attempts["n"] += 1
        return [] if attempts["n"] == 1 else ["FOUND"]

    monkeypatch.setattr(pl, "LocationFilter", LF, raising=True)
    monkeypatch.setattr(pl, "gen_filtered_epds", fake_gen_filtered, raising=True)
    monkeypatch.setattr(pl, "escalate_location_set", lambda s: s | {"EU"}, raising=True)

    out = list(pl.gen_locfiltered_epds(epd_roots=[1, 2], filters=[LF({"FR"})]))
    assert out == ["FOUND"]
    assert attempts["n"] >= 2


def test_gen_locfiltered_epds_raises_when_not_found(monkeypatch):
    class LF:
        def __init__(self, locs):
            self.locations = set(locs)

    monkeypatch.setattr(pl, "LocationFilter", LF, raising=True)
    monkeypatch.setattr(pl, "gen_filtered_epds", lambda *_: [], raising=True)
    monkeypatch.setattr(pl, "escalate_location_set", lambda s: s, raising=True)

    with pytest.raises(pl.NoMatchingEPDError):
        list(pl.gen_locfiltered_epds([1], [LF({"XX"})], max_attempts=2))


# ------------------------------ epd_pipeline ------------------------------ #


def test_epd_pipeline_happy_path(monkeypatch, tmp_path: Path):
    process = types.SimpleNamespace(
        uuid="u0",
        dec_unit="dummy-unit",
        matches={"uuids": ["a", "b"]},
        material_kwargs={"mass": 1.0},
        market={"FR": 0.7, "DE": 0.3},
    )

    class EPD:
        def __init__(self, uuid):
            self.uuid = uuid
            self.lcia_results = {"GWP": 1}

        def get_lcia_results(self):
            self.lcia_results = {"GWP": 2}

    epds = {"a": EPD("a"), "b": EPD("b")}
    # epds = [EPD("a"), EPD("b")]
    # monkeypatch.setattr(
    # 	pl, "pre_filtered_epds", lambda epds: [v for k, v in epds], raising=True
    # )
    monkeypatch.setattr(pl, "UUIDFilter", lambda m: ("UUIDFilter", m), raising=True)
    monkeypatch.setattr(
        pl, "UnitConformityFilter", lambda kw: ("UnitFilter", kw), raising=True
    )
    monkeypatch.setattr(pl, "LocationFilter", lambda s: ("LocFilter", s), raising=True)

    monkeypatch.setattr(
        pl, "gen_filtered_epds", lambda epds, f: list(epds), raising=True
    )

    monkeypatch.setattr(
        pl, "average_material_properties", lambda epds: {"mass": 2.0}, raising=True
    )

    class FakeMat:
        def __init__(self, **kw):
            self.kw = dict(kw)

        def rescale(self, *_):
            pass

        def to_dict(self):
            return dict(self.kw)

    monkeypatch.setattr(pl, "Material", FakeMat, raising=True)

    monkeypatch.setattr(
        pl, "gen_locfiltered_epds", lambda epds, filters: list(epds), raising=True
    )

    monkeypatch.setattr(
        pl,
        "average_impacts",
        lambda lcia_list: {"GWP": sum(d["GWP"] for d in lcia_list) / len(lcia_list)},
        raising=True,
    )

    monkeypatch.setattr(
        pl,
        "weighted_averages",
        lambda market, imp: {"GWP": sum(imp[c]["GWP"] * w for c, w in market.items())},
        raising=True,
    )

    avg_props, avg_gwps = pl.epd_pipeline(process, epds)

    assert avg_props == {"mass": 2.0}
    assert avg_gwps == {"GWP": 2.0}


# ------------------------------ run_materia ------------------------------- #


def test_run_materia_executes_pipeline_and_writes(monkeypatch, tmp_path: Path):
    prod_dir = tmp_path / "products"
    epd_dir = tmp_path / "epds"
    out_dir = tmp_path / "out"
    prod_dir.mkdir()
    epd_dir.mkdir()
    out_dir.mkdir()

    def fake_gen_xml_objects(folder):
        assert Path(folder) == prod_dir / "processes"
        yield (prod_dir / "prod.xml", ET.Element("root"))

    monkeypatch.setattr(pl, "gen_xml_objects", fake_gen_xml_objects, raising=True)

    class FakeIlcd:
        def __init__(self, root, path):
            self.root = root
            self.path = path
            self.uuid = "uuid-123"
            self.matches = True
            self.material_kwargs = {"mass": 1.0}
            self.market = {"FR": 1.0}
            self.material = None
            self._write_called = False
            self._write_args = None

        def get_ref_flow(self):
            pass

        def get_declared_unit(self):
            pass

        def get_hs_class(self):
            pass

        def get_market(self):
            pass

        def get_matches(self):
            pass

        def write_flow(self, avg_properties, output_path):
            pass

        def write_process(self, gwps, output_path):
            self._write_called = True
            self._write_args = (gwps, output_path)

    monkeypatch.setattr(pl, "IlcdProcess", FakeIlcd, raising=True)

    epd_return_avg_props = {"mass": 42.0}
    epd_return_avg_gwps = {"GWP": 3.5}

    def fake_epd_pipeline(process, epds):
        # assert path_to_epd_folder == epd_dir / "processes"
        return epd_return_avg_props, epd_return_avg_gwps

    monkeypatch.setattr(pl, "epd_pipeline", fake_epd_pipeline, raising=True)

    def fake_gen_epd(path_to_epd_folder):
        assert path_to_epd_folder == epd_dir / "processes"
        for root, path in [("dummy-root", "dummy-path")]:
            yield FakeIlcd(root, path)

    monkeypatch.setattr(pl, "gen_epds", fake_gen_epd, raising=True)

    class FakeMaterial:
        def __init__(self, **kw):
            self.kw = kw

    monkeypatch.setattr(pl, "Material", FakeMaterial, raising=True)
    pl.run_materia(prod_dir, epd_dir, out_dir)
