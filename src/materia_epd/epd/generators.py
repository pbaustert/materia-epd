from rich.progress import track
import xml.etree.ElementTree as ET
from pathlib import Path

from materia_epd.epd.models import IlcdProcess


def gen_xml_objects(folder_path, logger, uuids=None):
    """Creates a generator that returns parsed XML files."""
    for xml_file in Path(folder_path).glob("*.xml"):
        if uuids is not None:
            # Extract UUID from filename (handles version suffixes like _00.03.000)
            file_uuid = xml_file.stem.split("_")[0]
            if file_uuid not in uuids:
                continue
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            yield xml_file, root
        except Exception as e:
            print(f"❌ Error reading {xml_file.name}: {e}")


def gen_epds(folder_path, logger, uuids=None):
    """Creates a generator of `IlcdProcess` instances."""
    for path, root in track(
        gen_xml_objects(folder_path, logger, uuids),
        description="Parsing XMLs into IlcdProcess objects",
        transient=True,
    ):
        yield IlcdProcess(root=root, path=path)
    logger.info("XML processes files parsed")
