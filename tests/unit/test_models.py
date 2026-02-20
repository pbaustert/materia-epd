# test_models_full_coverage.py
import xml.etree.ElementTree as ET
from pathlib import Path

from materia_epd.core import constants as real_constants
from materia_epd.epd import models


def _restore_module_constants():
    """Restore original constants after tests that patch them."""
    models.NS = real_constants.NS
    models.XP = real_constants.XP
    models.ATTR = real_constants.ATTR
    models.FLOW_PROPERTY_MAPPING = real_constants.FLOW_PROPERTY_MAPPING
    models.UNIT_QUANTITY_MAPPING = real_constants.UNIT_QUANTITY_MAPPING
    models.UNIT_PROPERTY_MAPPING = real_constants.UNIT_PROPERTY_MAPPING


def test_models_full_coverage(tmp_path):
    # -------- Patch minimal constants & helpers (no namespaces) --------
    models.FLOW_PROPERTY_MAPPING = {"kg": "UUID-MASS"}
    models.UNIT_QUANTITY_MAPPING = {"kg": "mass"}
    models.UNIT_PROPERTY_MAPPING = {"g/cm3": "gross_density"}
    models.NS = {}

    class XP:
        FLOW_PROPERTY = "flowProperty"
        MEAN_VALUE = "meanValue"
        REF_TO_FLOW_PROP = "refToFlowProp"
        SHORT_DESC = "shortDescription"
        MATML_DOC = "matML_Doc"
        PROPERTY_DATA = "propertyData"
        PROP_DATA = "propData"
        PROPERTY_DETAILS = "propertyDetails"
        PROP_NAME = "propName"
        PROP_UNITS = "propUnits"

        UUID = "UUID"
        LOCATION = "location"
        QUANT_REF = "quantitativeReference"
        REF_TO_FLOW = "refToFlow"
        MEAN_AMOUNT = "meanAmount"
        LCIA_RESULT = ".//lciaResult"
        REF_TO_LCIA_METHOD = "refToLCIAMethod"
        AMOUNT = "amount"
        HS_CLASSIFICATION = ".//hsClassification"
        CLASS_LEVEL_2 = "classLevel2"

        @staticmethod
        def exchange_by_id(_id: str) -> str:
            return f".//exchange[@id='{_id}']"

    class ATTR:
        REF_OBJECT_ID = "refObjectId"
        LANG = "lang"
        LOCATION = "location"
        PROPERTY = "property"
        ID = "id"
        NAME = "name"
        CLASS_ID = "classId"

    models.XP = XP
    models.ATTR = ATTR

    models.to_float = lambda v, positive=False: float(v)
    models.ilcd_to_iso_location = lambda code: code

    class Material:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.scaling_factor = 2.0

    models.Material = Material
    models.normalize_module_values = lambda elems, scaling_factor=1.0: [10, 20, 30]
    models.get_indicator_synonyms = lambda: {"GWP": ["Global Warming Potential"]}
    models.get_market_shares = lambda _loc, _hs: {"EU": 0.7}
    models.read_json_file = lambda _p: {"match": True}
    models.MATCHES_FOLDER = str(tmp_path)

    def _ilcdflow_init(self, root):
        self.root = root
        self._get_units()
        self._get_props()

    models.IlcdFlow.__init__ = _ilcdflow_init

    # -------- Tiny on-disk dataset --------
    base = tmp_path / "dataset"
    flows_dir = base / "flows"
    processes_dir = base / "processes"
    flows_dir.mkdir(parents=True, exist_ok=True)
    processes_dir.mkdir(parents=True, exist_ok=True)

    flow_xml = """<flow>
      <flowProperty>
        <meanValue>2.0</meanValue>
        <refToFlowProp refObjectId="UUID-MASS">
          <shortDescription lang="en">Mass</shortDescription>
        </refToFlowProp>
      </flowProperty>
      <matML_Doc>
        <propertyDetails id="PD1">
          <propName>Density</propName>
          <propUnits name="g/cm3" />
        </propertyDetails>
        <propertyData property="PD1">
          <propData>7.8</propData>
        </propertyData>
      </matML_Doc>
    </flow>"""
    (flows_dir / "FLOW-UUID-1.xml").write_text(flow_xml, encoding="utf-8")

    process_xml = """<process>
      <UUID>abc-123</UUID>
      <location location="FR" />
      <quantitativeReference>ex1</quantitativeReference>
      <exchanges>
        <exchange id="ex1">
          <meanAmount>3</meanAmount>
          <refToFlow refObjectId="FLOW-UUID-1" />
        </exchange>
      </exchanges>
      <lciaResults>
        <lciaResult>
          <refToLCIAMethod>
            <shortDescription lang="en">Global Warming Potential</shortDescription>
          </refToLCIAMethod>
          <amount>1</amount><amount>2</amount><amount>3</amount>
        </lciaResult>
      </lciaResults>
      <hsClassification>
        <classLevel2 classId="72"/>
      </hsClassification>
    </process>"""
    process_path = processes_dir / "proc.xml"
    process_path.write_text(process_xml, encoding="utf-8")

    # -------- Drive all code paths --------
    proc = models.IlcdProcess(root=ET.fromstring(process_xml), path=process_path)

    assert proc.uuid == "abc-123"
    assert proc.loc == "FR"

    proc.get_ref_flow()
    assert proc.material_kwargs["mass"] == 6.0
    assert proc.material_kwargs["gross_density"] == 7.8

    proc.get_lcia_results()
    assert proc.lcia_results == [{"name": "GWP", "values": [10, 20, 30]}]

    proc.get_hs_class()
    assert proc.hs_class == "72"
    assert proc.get_market() == {"EU": 0.7}

    proc.get_matches()
    assert proc.matches == {"match": True}

    f_no_matml = models.IlcdFlow.__new__(models.IlcdFlow)
    f_no_matml.root = ET.fromstring("<flow/>")
    f_no_matml._get_props()

    f_with_matml = models.IlcdFlow.__new__(models.IlcdFlow)
    f_with_matml.root = ET.fromstring(flow_xml)
    f_with_matml.__post_init__()
    assert f_with_matml.units and f_with_matml.props

    # Restore original constants for subsequent tests
    _restore_module_constants()


def test_write_process_updates_amounts_and_uses_output_path(monkeypatch, tmp_path):
    process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common"
                              xmlns:proc="http://lca.jrc.it/ILCD/Process"
                              xmlns:epd="http://www.iai.kit.edu/EPD/2013">
      <common:UUID>abc-123</common:UUID>
      <proc:LCIAResults>
        <proc:LCIAResult>
        <proc:referenceToLCIAMethodDataSet>
          <common:shortDescription xml:lang="en">
            Global Warming Potential
          </common:shortDescription>
        </proc:referenceToLCIAMethodDataSet>

          <epd:amount module="A1-A3">0</epd:amount>
          <epd:amount module="A4">0</epd:amount>
          <epd:amount module="C1">0</epd:amount>
          <epd:amount module="C2">0</epd:amount>
          <epd:amount module="C3">0</epd:amount>
          <epd:amount module="C4">0</epd:amount>
          <epd:amount module="D">0</epd:amount>
        </proc:LCIAResult>
      </proc:LCIAResults>
    </process>"""
    root = ET.fromstring(process_xml)
    proc_path = tmp_path / "dataset" / "processes" / "proc.xml"
    proc_path.parent.mkdir(parents=True, exist_ok=True)
    proc_path.write_text(process_xml, encoding="utf-8")

    proc = models.IlcdProcess(root=root, path=proc_path)

    captured = {}

    def fake_write_xml_root(r, p):
        captured["root"] = r
        captured["path"] = Path(p)
        return True

    monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

    results = {
        "Global Warming Potential": {
            "A1-A3": 1108.0370876767083,
            "C1": 8.826807938835385,
            "C2": 8.825722954263789,
            "C3": 62.08764988382313,
            "C4": 56.859680185480855,
            "D": -98.9221132329585,
        }
    }

    out_dir = tmp_path / "out"
    ok = proc.write_process(results, out_dir)
    assert ok is True

    assert captured["path"] == out_dir / "processes" / "abc-123.xml"

    updated = {}
    for amt in captured["root"].findall(".//{http://www.iai.kit.edu/EPD/2013}amount"):
        mod = amt.attrib.get("module")
        if mod:
            updated[mod] = amt.text

    assert updated["A1-A3"] == str(float(results["Global Warming Potential"]["A1-A3"]))
    assert updated["C1"] == str(float(results["Global Warming Potential"]["C1"]))
    assert updated["C2"] == str(float(results["Global Warming Potential"]["C2"]))
    assert updated["C3"] == str(float(results["Global Warming Potential"]["C3"]))
    assert updated["C4"] == str(float(results["Global Warming Potential"]["C4"]))
    assert updated["D"] == str(float(results["Global Warming Potential"]["D"]))
    assert updated["A4"] == "0"


def test_write_process_skips_missing_indicator_and_still_writes(monkeypatch, tmp_path):
    process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common"
                              xmlns:proc="http://lca.jrc.it/ILCD/Process"
                              xmlns:epd="http://www.iai.kit.edu/EPD/2013">
      <common:UUID>abc-123</common:UUID>
      <proc:LCIAResults>
        <proc:LCIAResult>
          <proc:referenceToLCIAMethodDataSet>
            <common:shortDescription xml:lang="en">
            Some Other Indicator
            </common:shortDescription>
          </proc:referenceToLCIAMethodDataSet>
          <epd:amount module="A1-A3">0</epd:amount>
        </proc:LCIAResult>
      </proc:LCIAResults>
    </process>"""
    root = ET.fromstring(process_xml)
    proc = models.IlcdProcess(root=root, path=tmp_path / "dataset/processes/proc.xml")

    called = {}

    def fake_write_xml_root(r, p):
        called["path"] = Path(p)
        return True

    monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

    results = {"Global Warming Potential": {"A1-A3": 123.0}}

    ok = proc.write_process(results, tmp_path / "out")
    assert ok is True

    amt = root.find(".//{http://www.iai.kit.edu/EPD/2013}amount[@module='A1-A3']")
    assert amt is not None and amt.text == "0"

    assert called["path"] == tmp_path / "out" / "processes" / "abc-123.xml"


def test_write_process_attr_lookup_returns_none_when_no_known_attr(
    monkeypatch, tmp_path
):
    process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common"
                              xmlns:proc="http://lca.jrc.it/ILCD/Process"
                              xmlns:epd="http://www.iai.kit.edu/EPD/2013">
      <common:UUID>abc-123</common:UUID>
      <proc:LCIAResults>
        <proc:LCIAResult>
          <proc:referenceToLCIAMethodDataSet>
            <common:shortDescription xml:lang="en">
            Global Warming Potential
            </common:shortDescription>
          </proc:referenceToLCIAMethodDataSet>
          <epd:amount someOtherAttr="X">0</epd:amount>
          <epd:amount anotherAttr="Y">0</epd:amount>
        </proc:LCIAResult>
      </proc:LCIAResults>
    </process>"""
    root = ET.fromstring(process_xml)
    proc = models.IlcdProcess(root=root, path=tmp_path / "dataset/processes/proc.xml")

    monkeypatch.setattr(models, "write_xml_root", lambda r, p: True, raising=True)

    results = {"Global Warming Potential": {"A1-A3": 10.0, "C1": 20.0}}

    ok = proc.write_process(results, tmp_path / "out")
    assert ok is True

    amounts = root.findall(".//{http://www.iai.kit.edu/EPD/2013}amount")
    assert [a.text for a in amounts] == ["0", "0"]


# #
# # -------------------- write_flow tests --------------------
# # These tests were generated with Opus4.5. The logic has not been reviewed.
# # TODO:verify these tests


# def _create_namespaced_flow_xml(uuid="flow-uuid-123", ref_prop_value="0"):
#     """Helper to create properly namespaced flow XML for write_flow tests."""
#     return f"""<flow xmlns:flow="http://lca.jrc.it/ILCD/Flow"
#                      xmlns:common="http://lca.jrc.it/ILCD/Common"
#                      xmlns:mat="http://www.matml.org/">
#       <common:UUID>{uuid}</common:UUID>
#       <flow:flowProperties></flow:flowProperties>
#       <mat:MatML_Doc></mat:MatML_Doc>
#       <flow:referenceToReferenceFlowProperty>
# {ref_prop_value}
# </flow:referenceToReferenceFlowProperty>
#     </flow>"""


# def test_write_flow_creates_output_file_at_correct_path(monkeypatch, tmp_path):
#     """Test that write_flow writes to the correct output path."""
#     flow_xml = _create_namespaced_flow_xml()
#     flow_root = ET.fromstring(flow_xml)
#     process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common">
#         <common:UUID>proc-123</common:UUID>
#     </process>"""
#     proc_root = ET.fromstring(process_xml)

#     mock_flow = models.IlcdFlow.__new__(models.IlcdFlow)
#     mock_flow.root = flow_root
#     mock_flow.uuid = "flow-uuid-123"

#     proc = models.IlcdProcess(root=proc_root, path=tmp_path / "processes/proc.xml")
#     proc.ref_flow = mock_flow
#     proc.dec_unit = "mass"

#     captured = {}

#     def fake_write_xml_root(r, p):
#         captured["root"] = r
#         captured["path"] = Path(p)
#         return True

#     monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

#     out_dir = tmp_path / "output"
#     proc.write_flow({}, out_dir)

#     assert captured["path"] == out_dir / "flows" / "flow-uuid-123.xml"


# def test_write_flow_skips_properties_with_none_values(monkeypatch, tmp_path):
#     """Test that write_flow skips properties where value is None."""
#     flow_xml = _create_namespaced_flow_xml()
#     flow_root = ET.fromstring(flow_xml)
#     process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common">
#         <common:UUID>proc-123</common:UUID>
#     </process>"""
#     proc_root = ET.fromstring(process_xml)

#     mock_flow = models.IlcdFlow.__new__(models.IlcdFlow)
#     mock_flow.root = flow_root
#     mock_flow.uuid = "flow-uuid-123"

#     proc = models.IlcdProcess(root=proc_root, path=tmp_path / "processes/proc.xml")
#     proc.ref_flow = mock_flow
#     proc.dec_unit = "mass"

#     captured = {}

#     def fake_write_xml_root(r, p):
#         captured["root"] = r
#         return True

#     monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

#     # Pass kwargs with None values - these should be skipped
#     kwargs = {"gross_density": None, "grammage": None}
#     proc.write_flow(kwargs, tmp_path / "output")

#     # Check that no PropertyData elements were created in BulkDetails
#     matml = captured["root"].find(XP.MATML_DOC, NS)
#     property_data_elements = matml.findall(".//{http://www.matml.org/}PropertyData")
#     assert len(property_data_elements) == 0


# def test_write_flow_creates_property_data_for_valid_properties(monkeypatch, tmp_path):
#     """Test that write_flow creates PropertyData elements for valid properties."""
#     flow_xml = _create_namespaced_flow_xml()
#     flow_root = ET.fromstring(flow_xml)
#     process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common">
#         <common:UUID>proc-123</common:UUID>
#     </process>"""
#     proc_root = ET.fromstring(process_xml)

#     mock_flow = models.IlcdFlow.__new__(models.IlcdFlow)
#     mock_flow.root = flow_root
#     mock_flow.uuid = "flow-uuid-123"

#     proc = models.IlcdProcess(root=proc_root, path=tmp_path / "processes/proc.xml")
#     proc.ref_flow = mock_flow
#     proc.dec_unit = "mass"

#     captured = {}

#     def fake_write_xml_root(r, p):
#         captured["root"] = r
#         return True

#     monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

#     # Pass kwargs with valid property that maps to a unit (kg/m^3 -> gross_density)
#     kwargs = {"gross_density": 2500.0}
#     proc.write_flow(kwargs, tmp_path / "output")

#     # Check that PropertyData was created
#     matml = captured["root"].find(XP.MATML_DOC, NS)
#     property_data_elements = matml.findall(".//{http://www.matml.org/}PropertyData")
#     assert len(property_data_elements) == 1


# def test_write_flow_creates_flow_properties_for_quantities(monkeypatch, tmp_path):
#     """Test that write_flow creates flowProperty elements for quantity mappings."""
#     flow_xml = _create_namespaced_flow_xml()
#     flow_root = ET.fromstring(flow_xml)
#     process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common">
#         <common:UUID>proc-123</common:UUID>
#     </process>"""
#     proc_root = ET.fromstring(process_xml)

#     mock_flow = models.IlcdFlow.__new__(models.IlcdFlow)
#     mock_flow.root = flow_root
#     mock_flow.uuid = "flow-uuid-123"

#     proc = models.IlcdProcess(root=proc_root, path=tmp_path / "processes/proc.xml")
#     proc.ref_flow = mock_flow
#     proc.dec_unit = "mass"

#     captured = {}

#     def fake_write_xml_root(r, p):
#         captured["root"] = r
#         return True

#     monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

#     # Pass kwargs with quantities that map via UNIT_QUANTITY_MAPPING
#     kwargs = {"mass": 1.0, "volume": 0.5}
#     proc.write_flow(kwargs, tmp_path / "output")

#     # Check that flowProperty elements were created
#     flow_props = captured["root"].find(XP.FLOW_PROPERTIES, NS)
#     fp_elements = flow_props.findall("{http://lca.jrc.it/ILCD/Flow}flowProperty")
#     assert len(fp_elements) == 2


# def test_write_flow_puts_declared_unit_first(monkeypatch, tmp_path):
#     """Test that write_flow orders quantity list with declared unit first."""
#     flow_xml = _create_namespaced_flow_xml()
#     flow_root = ET.fromstring(flow_xml)
#     process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common">
#         <common:UUID>proc-123</common:UUID>
#     </process>"""
#     proc_root = ET.fromstring(process_xml)

#     mock_flow = models.IlcdFlow.__new__(models.IlcdFlow)
#     mock_flow.root = flow_root
#     mock_flow.uuid = "flow-uuid-123"

#     proc = models.IlcdProcess(root=proc_root, path=tmp_path / "processes/proc.xml")
#     proc.ref_flow = mock_flow
#     proc.dec_unit = "volume"  # Set volume as declared unit

#     captured = {}

#     def fake_write_xml_root(r, p):
#         captured["root"] = r
#         return True

#     monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

#     # Pass mass first, but volume is declared unit
#     kwargs = {"mass": 1.0, "volume": 0.5}
#     proc.write_flow(kwargs, tmp_path / "output")

#     # First flowProperty should have dataSetInternalID="0" and be volume
#     flow_props = captured["root"].find(XP.FLOW_PROPERTIES, NS)
#     fp_elements = flow_props.findall("{http://lca.jrc.it/ILCD/Flow}flowProperty")

#     first_fp = fp_elements[0]
#     assert first_fp.get("dataSetInternalID") == "0"

#     # Check the shortDescription contains "Volume"
#     short_desc = first_fp.find(".//{http://lca.jrc.it/ILCD/Common}shortDescription")
#     assert short_desc is not None
#     assert short_desc.text == "Volume"


# def test_write_flow_sets_reference_to_zero(monkeypatch, tmp_path):
#     """Test that write_flow sets referenceToReferenceFlowProperty to '0'."""
#     flow_xml = _create_namespaced_flow_xml(ref_prop_value="5")
#     flow_root = ET.fromstring(flow_xml)
#     process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common">
#         <common:UUID>proc-123</common:UUID>
#     </process>"""
#     proc_root = ET.fromstring(process_xml)

#     mock_flow = models.IlcdFlow.__new__(models.IlcdFlow)
#     mock_flow.root = flow_root
#     mock_flow.uuid = "flow-uuid-123"

#     proc = models.IlcdProcess(root=proc_root, path=tmp_path / "processes/proc.xml")
#     proc.ref_flow = mock_flow
#     proc.dec_unit = "mass"

#     captured = {}

#     def fake_write_xml_root(r, p):
#         captured["root"] = r
#         return True

#     monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

#     proc.write_flow({"mass": 1.0}, tmp_path / "output")

#     ref_elem = captured["root"].find(XP.REF_TO_REF_FLOW_PROP, NS)
#     assert ref_elem.text == "0"


# def test_write_flow_clears_existing_children(monkeypatch, tmp_path):
#     """Test that write_flow clears existing children from matML and flowProperties."""
#     flow_xml = """<flow xmlns:flow="http://lca.jrc.it/ILCD/Flow"
#                         xmlns:common="http://lca.jrc.it/ILCD/Common"
#                         xmlns:mat="http://www.matml.org/">
#       <common:UUID>flow-uuid-123</common:UUID>
#       <flow:flowProperties>
#         <flow:existingChild>should be removed</flow:existingChild>
#       </flow:flowProperties>
#       <mat:MatML_Doc>
#         <mat:existingMatML>should be removed</mat:existingMatML>
#       </mat:MatML_Doc>
#       <flow:referenceToReferenceFlowProperty>0</flow:referenceToReferenceFlowProperty>
#     </flow>"""

#     flow_root = ET.fromstring(flow_xml)
#     process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common">
#         <common:UUID>proc-123</common:UUID>
#     </process>"""
#     proc_root = ET.fromstring(process_xml)

#     mock_flow = models.IlcdFlow.__new__(models.IlcdFlow)
#     mock_flow.root = flow_root
#     mock_flow.uuid = "flow-uuid-123"

#     proc = models.IlcdProcess(root=proc_root, path=tmp_path / "processes/proc.xml")
#     proc.ref_flow = mock_flow
#     proc.dec_unit = "mass"

#     captured = {}

#     def fake_write_xml_root(r, p):
#         captured["root"] = r
#         return True

#     monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

#     proc.write_flow({}, tmp_path / "output")

#     # Check that old children are gone
#     assert (
#         captured["root"].find(".//{http://lca.jrc.it/ILCD/Flow}existingChild") is None
#     )
#     assert captured["root"].find(".//{http://www.matml.org/}existingMatML") is None


# def test_write_flow_handles_simple_unit_without_slash(monkeypatch, tmp_path):
#     """Test that write_flow handles simple units without '/'"""
#     flow_xml = _create_namespaced_flow_xml()
#     flow_root = ET.fromstring(flow_xml)
#     process_xml = """<process xmlns:common="http://lca.jrc.it/ILCD/Common">
#         <common:UUID>proc-123</common:UUID>
#     </process>"""
#     proc_root = ET.fromstring(process_xml)

#     mock_flow = models.IlcdFlow.__new__(models.IlcdFlow)
#     mock_flow.root = flow_root
#     mock_flow.uuid = "flow-uuid-123"

#     proc = models.IlcdProcess(root=proc_root, path=tmp_path / "processes/proc.xml")
#     proc.ref_flow = mock_flow
#     proc.dec_unit = "mass"

#     captured = {}

#     def fake_write_xml_root(r, p):
#         captured["root"] = r
#         return True

#     monkeypatch.setattr(models, "write_xml_root", fake_write_xml_root, raising=True)

#     # layer_thickness maps to unit "m" which has no "/" - tests the else branch
#     kwargs = {"layer_thickness": 0.05}
#     proc.write_flow(kwargs, tmp_path / "output")

#     # Check that PropertyDetails was created with simple unit structure
#     matml = captured["root"].find(XP.MATML_DOC, NS)
#     property_details = matml.findall(".//{http://www.matml.org/}PropertyDetails")
#     assert len(property_details) == 1

#     # Check that Units element has a single Unit child
#     units_elem = property_details[0].find(".//{http://www.matml.org/}Units")
#     assert units_elem is not None
#     unit_children = units_elem.findall("{http://www.matml.org/}Unit")
#     # Simple unit should have exactly 1 Unit element (not 2 like compound units)
#     assert len(unit_children) == 1

#     # The unit name should be "m"
#     unit_name = unit_children[0].find("{http://www.matml.org/}Name")
#     assert unit_name is not None
#     assert unit_name.text == "m"
