# tests/unit/test_pipeline.py
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
