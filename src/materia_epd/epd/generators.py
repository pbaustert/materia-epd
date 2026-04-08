from rich.progress import track
import xml.etree.ElementTree as ET
from pathlib import Path

from materia_epd.epd.models import IlcdProcess


def gen_xml_objects(folder_path, logger):
    """Creates a generator that returns parsed XML EPD files"""
    if folder_path.is_file():
        folder = Path(folder_path).parent
    elif folder_path.is_dir():
        folder = Path(folder_path)
    else:
        e = ValueError("Not a file/folder path")
        logger.error("Error", exec_info=e)
        raise e

    for xml_file in folder.glob("*.xml"):
        try:
            tree = ET.parse(xml_file)
            root = tree.getroot()
            yield xml_file, root
        except Exception as e:
            print(f"❌ Error reading {xml_file.name}: {e}")


def gen_epds(folder_path, logger):
    """Creates a generator of `IlcdProcess` instances from parsed XML EPD files."""
    for path, root in track(
        gen_xml_objects(folder_path, logger),
        description="Parsing XMLs into IlcdProcess objects",
        transient=True,
    ):
        yield IlcdProcess(root=root, path=path)
    logger.info("XML processes files parsed")
