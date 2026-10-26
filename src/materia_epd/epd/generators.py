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


def gen_epds_from_url(source, logger, uuids, errors=None):
    """Creates a generator of `IlcdProcess` instances fetched from a `UrlSource`.

    The EPDs resolve their reference flows through the same source. UUIDs that cannot
    be fetched are skipped and recorded in `errors` (uuid -> message), if given.
    """
    for url, root in track(
        source.gen_processes(uuids, errors=errors),
        description="Fetching EPD XMLs from file server",
        transient=True,
    ):
        yield IlcdProcess(root=root, path=url, flow_loader=source.flow_root)
    logger.info("XML processes fetched from file server", base_url=source.base_url)
