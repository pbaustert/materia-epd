from typing import List, Tuple

# ----------------------------- ICONS ----------------------------------------


class ICONS:
    HOURGLASS = "⏳"
    SUCCESS = "✅"
    WARNING = "⚠️"
    ERROR = "❌"


# ----------------------------- TRADE ----------------------------------------

TRADE_YEARS = [str(y) for y in range(2020, 2025)]
TRADE_TARGET = "442"  # Luxembourg
TRADE_FLOW = "M"  # Imports
TRADE_ROW_REGIONS = {"E19", "S19", "E27", "OED", "EUU", "EEC", "ROW", "_X "}

# ----------------------------- ILCD -----------------------------------------


NS = {
    "common": "http://lca.jrc.it/ILCD/Common",
    "proc": "http://lca.jrc.it/ILCD/Process",
    "flow": "http://lca.jrc.it/ILCD/Flow",
    "epd": "http://www.iai.kit.edu/EPD/2013",
    "epd2": "http://www.indata.network/EPD/2019",
    "xml": "http://www.w3.org/XML/1998/namespace",
    "mat": "http://www.matml.org/",
}


class XP:
    # Process-related
    QUANT_REF = ".//proc:quantitativeReference/proc:referenceToReferenceFlow"
    UUID = ".//common:UUID"
    LOCATION = ".//proc:locationOfOperationSupplyOrProduction"
    HS_CLASSIFICATION = ".//common:classification[@name='HS Classification']"
    CLASS_LEVEL_2 = "common:class[@level='2']"
    MEAN_AMOUNT = "proc:meanAmount"
    REF_TO_FLOW = "proc:referenceToFlowDataSet"

    @staticmethod
    def exchange_by_id(internal_id: str) -> str:
        return f".//proc:exchange[@dataSetInternalID='{internal_id}']"

    # LCIA-related
    LCIA_RESULT = ".//proc:LCIAResult"
    REF_TO_LCIA_METHOD = "proc:referenceToLCIAMethodDataSet"
    SHORT_DESC = "common:shortDescription"
    AMOUNT = ".//epd:amount"

    # Flow-related
    FLOW_PROPERTIES = ".//flow:flowProperties"
    FLOW_PROPERTY = ".//flow:flowProperty"
    MEAN_VALUE = "flow:meanValue"
    REF_TO_FLOW_PROP = "flow:referenceToFlowPropertyDataSet"
    REF_TO_REF_FLOW_PROP = ".//flow:referenceToReferenceFlowProperty"

    # MatML-related
    MATML_DOC = ".//mat:MatML_Doc"
    PROPERTY_DATA = ".//mat:PropertyData"
    PROPERTY_DETAILS = ".//mat:PropertyDetails"
    PROP_NAME = "mat:Name"
    PROP_UNITS = "mat:Units"
    PROP_DATA = "mat:Data"


class ATTR:
    REF_OBJECT_ID = "refObjectId"
    CLASS_ID = "classId"
    LANG = "{http://www.w3.org/XML/1998/namespace}lang"
    NAME = "name"
    PROPERTY = "property"
    ID = "id"
    LOCATION = "location"
    UNIT = "Unit"
    AMOUNT = "Amount"
    INTERNAL_ID = "dataSetInternalID"


MODULES = ["A1-A3", "C1", "C2", "C3", "C4", "D"]

FLOW_PROPERTY_MAPPING = {
    "kg": "93a60a56-a3c8-11da-a746-0800200b9a66",
    "m": "838aaa23-0117-11db-92e3-0800200c9a66",
    "m^2": "93a60a56-a3c8-19da-a746-0800200c9a66",
    "m^3": "93a60a56-a3c8-22da-a746-0800200c9a66",
    "unit": "01846770-4cfe-4a25-8ad9-919d8d378345",
}

UNIT_QUANTITY_MAPPING = {
    "kg": "mass",
    "m": "length",
    "m^2": "surface",
    "m^3": "volume",
    "unit": "unit_count",
}

UNIT_PROPERTY_MAPPING = {
    "kg/m^3": "gross_density",
    "kg/m^2": "grammage",
    "kg/m": "linear_density",
    "m": "layer_thickness",
    "m^2": "cross_sectional_area",
    "kg": "weight_per_piece",
}

ILCD_QUANTITY_LABELS = {
    "mass": "Mass",
    "volume": "Volume",
    "surface": "Area",
    "unit_count": "Unit",
    "length": "Length",
}

UNIT_GROUP_MAPPING = {
    "93a60a56-a3c8-11da-a746-0800200b9a66": "ad38d542-3fe9-439d-9b95-2f5f7752acaf",
    "838aaa23-0117-11db-92e3-0800200c9a66": "838aaa22-0117-11db-92e3-0800200c9a66",
    "93a60a56-a3c8-19da-a746-0800200c9a66": "c20a03d7-bd90-4569-bc94-66cfd364dfc8",
    "93a60a56-a3c8-22da-a746-0800200c9a66": "cd950537-0a98-4044-9ba7-9f9a68d0a504",
    "01846770-4cfe-4a25-8ad9-919d8d378345": "934110e3-baf4-49e9-992c-3d8109a6aafb",
}

LCIA_OUTPUT_MODULES = ["A1-A3", "C1", "C2", "C3", "C4", "D"]

LCIA_AGGREGATE_MAP = {"A1-A3": ["A1", "A2", "A3"]}

# ----------------------------- Physics --------------------------------------

_TOL_ABS = 1e-7
_TOL_REL = 1e-5
_REL_DEC = 8

QUANTITIES = ("mass", "volume", "surface", "length", "unit_count")

PROPERTIES = (
    "gross_density",
    "grammage",
    "linear_density",
    "layer_thickness",
    "cross_sectional_area",
    "weight_per_piece",
)

MASS_KWARGS = {
    "surface": None,
    "mass": 1.0,
    "unit_count": None,
    "weight_per_piece": None,
    "length": None,
    "layer_thickness": None,
    "linear_density": None,
    "cross_sectional_area": None,
    "gross_density": None,
    "grammage": None,
    "volume": None,
}

REASONABLE_RANGES = {
    "surface": (0.001, 1000.0),
    "mass": (0.001, 10000.0),
    "unit_count": (1, 1),
    "weight_per_piece": (0.001, 1000.0),
    "length": (0.001, 1000.0),
    "layer_thickness": (0.000001, 0.1),
    "linear_density": (0.001, 100.0),
    "cross_sectional_area": (0.000001, 10.0),
    "gross_density": (1.0, 20000.0),
    "grammage": (0.05, 30.0),
    "volume": (0.000001, 100.0),
}

POTENTIAL_CORRECTIONS = {
    "grammage": {"from": "g/m^2", "to": "kg/m^2", "factor": 0.001},
}

ACCEPTED_RESCALINGS = [
    {"mass"},
    {"volume"},
    {"surface", "layer_thickness"},
]

VARS = QUANTITIES + PROPERTIES

NAME_TO_IDX = {name: i for i, name in enumerate(VARS)}
IDX_TO_NAME = {v: k for k, v in NAME_TO_IDX.items()}

REL: List[Tuple[str, List[str]]] = [
    ("mass", ["volume", "gross_density"]),
    ("mass", ["surface", "grammage"]),
    ("mass", ["length", "linear_density"]),
    ("mass", ["unit_count", "weight_per_piece"]),
    ("volume", ["surface", "layer_thickness"]),
    ("volume", ["length", "cross_sectional_area"]),
    ("grammage", ["layer_thickness", "gross_density"]),
    ("linear_density", ["cross_sectional_area", "gross_density"]),
]
