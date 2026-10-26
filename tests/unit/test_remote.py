import functools
import http.server
import threading
import xml.etree.ElementTree as ET

import pytest
from click.testing import CliRunner

from materia_epd import cli
from materia_epd.core.constants import NS, XP
from materia_epd.epd.models import IlcdProcess, reference_flow_uuid
from materia_epd.io.remote import RemoteFetchError, UrlSource, resolve_base_url
from materia_epd.pipeline import run

PROCESS_XML = """<?xml version="1.0" encoding="utf-8"?>
<processDataSet xmlns="http://lca.jrc.it/ILCD/Process"
    xmlns:common="http://lca.jrc.it/ILCD/Common">
  <processInformation>
    <dataSetInformation>
      <common:UUID>{uuid}</common:UUID>
      <name><baseName xml:lang="de">Beton</baseName></name>
    </dataSetInformation>
    <quantitativeReference>
      <referenceToReferenceFlow>1</referenceToReferenceFlow>
    </quantitativeReference>
    <geography>
      <locationOfOperationSupplyOrProduction location="DE"/>
    </geography>
  </processInformation>
  <exchanges>
    <exchange dataSetInternalID="1">
      <referenceToFlowDataSet refObjectId="{flow_uuid}" uri="../flows/{flow_uuid}.xml"/>
      <meanAmount>1000</meanAmount>
      <resultingAmount>1000</resultingAmount>
    </exchange>
  </exchanges>
</processDataSet>
"""

FLOW_XML = """<?xml version="1.0" encoding="utf-8"?>
<flowDataSet xmlns="http://lca.jrc.it/ILCD/Flow"
    xmlns:common="http://lca.jrc.it/ILCD/Common">
  <flowInformation>
    <dataSetInformation><common:UUID>{uuid}</common:UUID></dataSetInformation>
  </flowInformation>
</flowDataSet>
"""


@pytest.fixture
def file_server(tmp_path):
    """Serve tmp_path/{xml,flows}/<uuid>.xml over HTTP, like the EPD file server."""
    (tmp_path / "xml").mkdir()
    (tmp_path / "flows").mkdir()
    for epd, flow in (("epd-1", "flow-1"), ("epd-2", "flow-2")):
        (tmp_path / "xml" / f"{epd}.xml").write_text(
            PROCESS_XML.format(uuid=epd, flow_uuid=flow), encoding="utf-8"
        )
        (tmp_path / "flows" / f"{flow}.xml").write_text(
            FLOW_XML.format(uuid=flow), encoding="utf-8"
        )
    (tmp_path / "xml" / "broken.xml").write_text("<not-xml", encoding="utf-8")

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(QuietHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_resolve_base_url(monkeypatch):
    monkeypatch.delenv("MATERIA_EPD_BASE_URL", raising=False)
    assert resolve_base_url(None, "http://a/raw/") == "http://a/raw"
    assert resolve_base_url("http://b", "http://a") == "http://b"
    with pytest.raises(ValueError):
        resolve_base_url(None, "")
    monkeypatch.setenv("MATERIA_EPD_BASE_URL", "http://env/raw")
    assert resolve_base_url(None) == "http://env/raw"


def test_url_source_fetch_and_cache(file_server):
    source = UrlSource(file_server + "/")
    assert source.process_url("x") == f"{file_server}/xml/x.xml"
    assert source.flow_url("y") == f"{file_server}/flows/y.xml"

    root = source.process_root("epd-1")
    assert root.find(XP.UUID, NS).text == "epd-1"
    assert source.process_root("epd-1") is root  # cached

    with pytest.raises(RemoteFetchError, match="HTTP 404"):
        source.process_root("missing")
    with pytest.raises(RemoteFetchError, match="Invalid XML"):
        source.process_root("broken")


def test_gen_processes_prefetches_flows_and_records_errors(file_server):
    source = UrlSource(file_server, max_workers=2)
    errors = {}
    fetched = list(source.gen_processes(["epd-1", "missing", "epd-2"], errors=errors))

    assert [url for url, _ in fetched] == [
        source.process_url("epd-1"),
        source.process_url("epd-2"),
    ]
    assert list(errors) == ["missing"]
    assert source.flow_url("flow-1") in source._cache
    assert source.flow_url("flow-2") in source._cache


def test_reference_flow_uuid():
    root = ET.fromstring(PROCESS_XML.format(uuid="p", flow_uuid="f"))
    assert reference_flow_uuid(root) == "f"
    assert reference_flow_uuid(ET.fromstring("<processDataSet/>")) is None


def test_get_ref_flow_uses_flow_loader():
    root = ET.fromstring(PROCESS_XML.format(uuid="p", flow_uuid="f"))
    calls = []

    def loader(uuid):
        calls.append(uuid)
        raise RuntimeError("boom")

    process = IlcdProcess(root=root, path="http://server/xml/p.xml", flow_loader=loader)
    with pytest.raises(RuntimeError, match="boom"):
        process.get_ref_flow()
    assert calls == ["f"]


def test_hs_class_and_market_tolerate_missing_classification():
    root = ET.fromstring(PROCESS_XML.format(uuid="p", flow_uuid="f"))
    process = IlcdProcess(root=root, path="x")
    assert process.get_hs_class() is None
    assert process.get_market() == {}


def test_normalize_url_spec_forms():
    spec = run.normalize_url_spec(["a", "b", "a", ""])
    (item,) = spec["processes"]
    assert item["matches"] == {"type": "average", "uuids": ["a", "b"]}
    assert item["uuid"]

    spec = run.normalize_url_spec(
        {"base_url": "http://x", "uuid": "g", "type": "market-average", "uuids": ["a"]}
    )
    assert spec["base_url"] == "http://x"
    assert spec["processes"][0]["uuid"] == "g"
    assert spec["processes"][0]["matches"]["type"] == "market-average"

    spec = run.normalize_url_spec(
        {"processes": [{"matches": {"type": "average", "uuids": ["a"]}}]}
    )
    assert spec["processes"][0]["matches"]["uuids"] == ["a"]

    for bad in ("nope", {"processes": []}, {"processes": [{"name": "x"}]}):
        with pytest.raises(ValueError):
            run.normalize_url_spec(bad)


def test_skeleton_from_epd_renames_process_and_flow(file_server):
    source = UrlSource(file_server)
    root, flow_loader = run._skeleton_from_epd(source, "epd-1", "generic-1")

    assert root.find(XP.UUID, NS).text == "generic-1"
    new_flow_uuid = reference_flow_uuid(root)
    assert new_flow_uuid not in ("flow-1", None)
    exchange = root.find(XP.exchange_by_id("1"), NS)
    assert exchange.findtext("proc:meanAmount", namespaces=NS) == "1"
    assert exchange.findtext("proc:resultingAmount", namespaces=NS) == "1"

    flow_root = flow_loader(new_flow_uuid)
    assert flow_root.find(XP.UUID, NS).text == new_flow_uuid
    # the cached source EPD and its flow are left untouched
    assert source.process_root("epd-1").find(XP.UUID, NS).text == "epd-1"
    assert source.flow_root("flow-1").find(XP.UUID, NS).text == "flow-1"

    run._set_name(root, "Generic concrete")
    names = root.findall(".//proc:dataSetInformation/proc:name/proc:baseName", NS)
    assert [n.text for n in names] == ["Generic concrete"]


def test_run_materia_from_url_reports_skeleton_failure(file_server):
    result = run.run_materia_from_url({"uuids": ["missing"]}, base_url=file_server)
    (process,) = result["processes"]
    assert process["success"] is False
    assert "skeleton" in process["error"]
    assert process["missing_epds"][0]["uuid"] == "missing"
    assert "HTTP 404" in result["fetch_errors"]["missing"]


def test_cli_modes(monkeypatch, tmp_path):
    calls = {}
    monkeypatch.setattr(cli, "setup_logging", lambda **kw: None)
    monkeypatch.setattr(
        cli, "run_materia_from_url", lambda *a, **kw: calls.update(url=(a, kw))
    )
    monkeypatch.setattr(cli, "run_materia", lambda *a: calls.update(local=a))
    spec = tmp_path / "spec.json"
    spec.write_text('["a"]', encoding="utf-8")
    runner = CliRunner()

    res = runner.invoke(cli.main, ["--from-url", str(spec), "--base-url", "http://x"])
    assert res.exit_code == 0, res.output
    assert calls["url"] == ((["a"], None), {"base_url": "http://x"})

    res = runner.invoke(cli.main, [str(tmp_path), str(tmp_path)])
    assert res.exit_code == 0, res.output
    assert calls["local"] == (tmp_path, tmp_path, None, None)

    assert runner.invoke(cli.main, []).exit_code == 2
    assert (
        runner.invoke(cli.main, ["--from-url", str(spec), str(tmp_path)]).exit_code == 2
    )
    assert (
        runner.invoke(
            cli.main, [str(tmp_path), str(tmp_path), "--base-url", "http://x"]
        ).exit_code
        == 2
    )
