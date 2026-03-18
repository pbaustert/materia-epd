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
