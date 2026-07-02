"""Tests for EPD Feather cache build, load, and integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from materia_epd.core.constants import FLOW_PROPERTY_MAPPING
from materia_epd.epd import cache, extract
from materia_epd.epd.extraction_errors import EpdExtractionError
from materia_epd.epd.generators import load_epd_corpus

KG_UUID = FLOW_PROPERTY_MAPPING["kg"]


def _flow_xml(flow_uuid: str, mean_kg: float = 1.0) -> str:
    return f"""<flow xmlns:flow="http://lca.jrc.it/ILCD/Flow"
                 xmlns:common="http://lca.jrc.it/ILCD/Common"
                 xmlns:mat="http://www.matml.org/">
  <common:UUID>{flow_uuid}</common:UUID>
  <flow:flowProperties>
    <flow:flowProperty dataSetInternalID="0">
      <flow:referenceToFlowPropertyDataSet refObjectId="{KG_UUID}">
        <common:shortDescription xml:lang="en">Mass</common:shortDescription>
      </flow:referenceToFlowPropertyDataSet>
      <flow:meanValue>{mean_kg}</flow:meanValue>
    </flow:flowProperty>
  </flow:flowProperties>
  <flow:referenceToReferenceFlowProperty>0</flow:referenceToReferenceFlowProperty>
</flow>"""


def _process_xml(
    process_uuid: str,
    flow_uuid: str,
    *,
    gwp_a1a3: float = 10.0,
    loc: str = "FR",
) -> str:
    return f"""<process xmlns:common="http://lca.jrc.it/ILCD/Common"
                        xmlns:proc="http://lca.jrc.it/ILCD/Process"
                        xmlns:epd="http://www.iai.kit.edu/EPD/2013">
  <common:UUID>{process_uuid}</common:UUID>
  <proc:locationOfOperationSupplyOrProduction location="{loc}" />
  <proc:quantitativeReference>
    <proc:referenceToReferenceFlow>0</proc:referenceToReferenceFlow>
  </proc:quantitativeReference>
  <proc:exchanges>
    <proc:exchange dataSetInternalID="0">
      <proc:meanAmount>1</proc:meanAmount>
      <proc:referenceToFlowDataSet refObjectId="{flow_uuid}" />
    </proc:exchange>
  </proc:exchanges>
  <proc:LCIAResults>
    <proc:LCIAResult>
      <proc:referenceToLCIAMethodDataSet>
        <common:shortDescription xml:lang="en">Global Warming Potential total (GWP-total)</common:shortDescription>
      </proc:referenceToLCIAMethodDataSet>
      <epd:amount epd:module="A1-A3">{gwp_a1a3}</epd:amount>
      <epd:amount epd:module="C1">1.0</epd:amount>
      <epd:amount epd:module="C2">2.0</epd:amount>
      <epd:amount epd:module="C3">3.0</epd:amount>
      <epd:amount epd:module="C4">4.0</epd:amount>
      <epd:amount epd:module="D">5.0</epd:amount>
    </proc:LCIAResult>
  </proc:LCIAResults>
</process>"""


def _make_epd_folder(tmp_path: Path, specs: list[dict]) -> Path:
    epd_root = tmp_path / "epds"
    flows = epd_root / "flows"
    processes = epd_root / "processes"
    flows.mkdir(parents=True)
    processes.mkdir(parents=True)

    for spec in specs:
        flow_uuid = spec["flow_uuid"]
        process_uuid = spec["process_uuid"]
        (flows / f"{flow_uuid}.xml").write_text(
            _flow_xml(flow_uuid, spec.get("mean_kg", 1.0)),
            encoding="utf-8",
        )
        (processes / f"{process_uuid}.xml").write_text(
            _process_xml(
                process_uuid,
                flow_uuid,
                gwp_a1a3=spec.get("gwp_a1a3", 10.0),
                loc=spec.get("loc", "FR"),
            ),
            encoding="utf-8",
        )
    return epd_root


@pytest.fixture
def epd_folder(tmp_path):
    return _make_epd_folder(
        tmp_path,
        [
            {"process_uuid": "epd-1", "flow_uuid": "flow-1", "gwp_a1a3": 100.0},
            {"process_uuid": "epd-2", "flow_uuid": "flow-2", "gwp_a1a3": 200.0},
        ],
    )


def test_extract_epd_record(epd_folder):
    process_path = epd_folder / "processes" / "epd-1.xml"
    record = extract.extract_epd_record(
        str(process_path.resolve()),
        str((epd_folder / "flows").resolve()),
    )
    assert record["uuid"] == "epd-1"
    assert record["ref_flow_uuid"] == "flow-1"
    assert record["material_kwargs"]["mass"] == 1.0
    assert "Climate change-Total" in record["raw_lcia"]
    assert record["raw_lcia"]["Climate change-Total"]["A1-A3"] == 100.0


def test_build_and_load_roundtrip(epd_folder, tmp_path):
    cache_dir = tmp_path / "cache"
    cache.build_epd_cache(
        epd_folder,
        cache_dir,
        force=True,
        workers=1,
        disable_progress=True,
    )

    assert cache.cache_exists(cache_dir)
    assert cache.is_cache_valid(cache_dir, epd_folder)

    epds = cache.load_epds_from_cache(cache_dir, epd_folder)
    assert len(epds) == 2
    uuids = {e.uuid for e in epds}
    assert uuids == {"epd-1", "epd-2"}

    epd = next(e for e in epds if e.uuid == "epd-1")
    assert epd.root is None
    assert epd.material.mass == 1.0
    epd.get_lcia_results()
    assert epd.lcia_results[0]["values"]["A1-A3"] == 100.0


def test_cached_lcia_scales_with_rescale(epd_folder, tmp_path):
    cache_dir = tmp_path / "cache"
    cache.build_epd_cache(
        epd_folder, cache_dir, force=True, workers=1, disable_progress=True
    )
    epd = cache.load_epds_from_cache(cache_dir, epd_folder)[0]
    epd.get_ref_flow()
    epd.material.rescale({"mass": 2.0})
    epd.get_lcia_results()
    values = epd.lcia_results[0]["values"]
    assert values["A1-A3"] == pytest.approx(200.0)


def test_stale_cache_detected(epd_folder, tmp_path):
    cache_dir = tmp_path / "cache"
    cache.build_epd_cache(
        epd_folder, cache_dir, force=True, workers=1, disable_progress=True
    )
    process_file = epd_folder / "processes" / "epd-1.xml"
    process_file.write_text(process_file.read_text() + "\n", encoding="utf-8")
    assert not cache.is_cache_valid(cache_dir, epd_folder)


def test_load_epd_corpus_auto_builds(epd_folder, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"

    class FakeLogger:
        def info(self, *args, **kwargs):
            pass

        def warning(self, *args, **kwargs):
            pass

    epds = load_epd_corpus(
        epd_folder,
        cache_dir,
        FakeLogger(),
        disable_progress=True,
    )
    assert len(epds) == 2
    assert cache.cache_exists(cache_dir)


def test_load_epd_corpus_no_cache_uses_xml(epd_folder):
    class FakeLogger:
        def info(self, *args, **kwargs):
            pass

        def error(self, *args, **kwargs):
            pass

    epds = load_epd_corpus(
        epd_folder,
        None,
        FakeLogger(),
        use_cache=False,
    )
    assert len(epds) == 2
    assert all(e.root is not None for e in epds)


def test_parallel_build_workers_two(epd_folder, tmp_path):
    cache_dir = tmp_path / "cache"
    cache.build_epd_cache(
        epd_folder,
        cache_dir,
        force=True,
        workers=2,
        disable_progress=True,
    )
    epds = cache.load_epds_from_cache(cache_dir, epd_folder)
    assert len(epds) == 2


def test_retry_paths_sequential_after_pool_failure(epd_folder, monkeypatch):
    process_path = epd_folder / "processes" / "epd-1.xml"
    path_str = str(process_path.resolve())
    flows_folder = str((epd_folder / "flows").resolve())
    records: list[dict] = []
    failures: list[dict] = []

    cache._retry_paths_sequential(
        [path_str],
        flows_folder,
        records,
        failures,
        reason="test pool crash",
    )

    assert len(records) == 1
    assert records[0]["uuid"] == "epd-1"
    assert failures == []


def test_from_cache_record_get_ref_flow_is_noop(epd_folder, tmp_path):
    cache_dir = tmp_path / "cache"
    cache.build_epd_cache(
        epd_folder, cache_dir, force=True, workers=1, disable_progress=True
    )
    epd = cache.load_epds_from_cache(cache_dir, epd_folder)[0]
    flow = epd.get_ref_flow()
    assert flow.uuid == "flow-1"
    assert epd.material.mass == 1.0


def test_extract_missing_mean_amount_reports_xml_context(epd_folder):
    process_path = epd_folder / "processes" / "epd-1.xml"
    xml = process_path.read_text(encoding="utf-8").replace(
        "<proc:meanAmount>1</proc:meanAmount>\n", ""
    )
    process_path.write_text(xml, encoding="utf-8")

    with pytest.raises(EpdExtractionError) as exc_info:
        extract.extract_epd_record(
            str(process_path.resolve()),
            str((epd_folder / "flows").resolve()),
        )

    err = exc_info.value
    assert err.stage == "parse_reference_flow"
    assert "meanAmount" in err.message
    assert err.xml_tag in {"meanAmount", "exchange"}
    assert err.xml_line is not None
    assert err.process_uuid == "epd-1"
    log_payload = err.to_log_dict()
    assert log_payload["xml_line"] == err.xml_line
    assert "meanAmount" in log_payload["detail"]


def test_build_logs_detailed_extraction_failure(epd_folder, tmp_path, monkeypatch):
    process_path = epd_folder / "processes" / "epd-1.xml"
    xml = process_path.read_text(encoding="utf-8").replace(
        "<proc:meanAmount>1</proc:meanAmount>\n", ""
    )
    process_path.write_text(xml, encoding="utf-8")

    logged: list[dict] = []

    def fake_warning(_event, **kwargs):
        logged.append(kwargs)

    monkeypatch.setattr(cache.logger, "warning", fake_warning)

    cache_dir = tmp_path / "cache"
    cache.build_epd_cache(
        epd_folder,
        cache_dir,
        force=True,
        workers=1,
        disable_progress=True,
    )

    assert len(logged) == 1
    assert logged[0]["file"] == "epd-1.xml"
    assert logged[0]["stage"] == "parse_reference_flow"
    assert "meanAmount" in logged[0]["error"]
    assert logged[0]["xml_line"] is not None
    assert "meanAmount" in logged[0]["detail"]
