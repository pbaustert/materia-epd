from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

import structlog
from rich.progress import track

from materia_epd.core.constants import ICONS, MASS_KWARGS
from materia_epd.core.errors import NoMatchingEPDError
from materia_epd.core.physics import Material
from materia_epd.core.utils import copy_except_folders
from materia_epd.epd.filters import (
    EPDFilter,
    LocationFilter,
    UnitConformityFilter,
    UUIDFilter,
)
from materia_epd.epd.models import IlcdProcess
from materia_epd.geo.locations import escalate_location_set
from materia_epd.metrics.averaging import (
    average_impacts,
    average_material_properties,
    weighted_averages,
)

logger = structlog.wrap_logger(logging.getLogger(__name__))


def gen_xml_objects(folder_path):
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


def gen_epds(folder_path):
    """Creates a generator of `IlcdProcess` instances from parsed XML EPD files."""
    for path, root in track(
        gen_xml_objects(folder_path),
        description="Parsing XMLs into IlcdProcess objects",
        transient=True,
    ):
        yield IlcdProcess(root=root, path=path)
    logger.info("XML processes files parsed")


def gen_filtered_epds(epds: list[IlcdProcess], filters: list[EPDFilter]):
    """Filters out EPD objects that do not match filters"""
    for epd in track(epds, description="Processing...", transient=True):
        # logger.debug(f"Filtering EPD {epd.uuid}")
        if all(filt.matches(epd) for filt in filters):
            yield epd


def gen_locfiltered_epds(
    epd_roots: list[IlcdProcess], filters: list[EPDFilter], max_attempts=4
):
    """Filters EPDS by location"""
    filters = [f for f in filters if isinstance(f, LocationFilter)]
    wanted_locations = set()
    for filt in filters:
        wanted_locations.update(filt.locations)
    for _ in range(max_attempts):
        epds = list(gen_filtered_epds(epd_roots, filters))
        if epds:
            yield from epds
            return
        wanted_locations = escalate_location_set(wanted_locations)
        filters = [LocationFilter(wanted_locations)]
    raise NoMatchingEPDError(filters)


def epd_pipeline(process: IlcdProcess, epds: dict[str, IlcdProcess]):
    """Aggregates the data of different EPDs into a new generic EPD.
    For a new EPD detailed in `process`, it looks
    the source EPDs that should be included in `epds`.
    This pipeline applies different filtering criteria
    to exclude not-matching or inconsisting source EPDs.
    """
    pre_filtered_edps = []
    for uuid in process.matches["uuids"]:
        try:
            pre_filtered_edps.append(epds[uuid])
            logger.debug("Files check", source_uuid=uuid, exists=True)
        except Exception as e:
            logger.debug("Files check", source_uuid=uuid, exists=False, exec_info=e)
    filters = []
    if process.matches:
        filters.append(UUIDFilter(process.matches))
    if process.material_kwargs:
        filters.append(UnitConformityFilter(process.material_kwargs))

    filtered_epds = list(gen_filtered_epds(pre_filtered_edps, filters))

    if len(filtered_epds) == 0:
        logger.warning(
            f"Switched from {process.dec_unit}-based to "
            f"mass-based functional unit {ICONS.WARNING}",
            uuid=process.uuid,
        )
        logger.info(f"Processing {ICONS.HOURGLASS}", uuid=process.uuid)
        process.material_kwargs = MASS_KWARGS
        process.dec_unit = "mass"
        filters = [f for f in filters if not isinstance(f, UnitConformityFilter)]
        filters.append(UnitConformityFilter(process.material_kwargs))
        filtered_epds = list(gen_filtered_epds(pre_filtered_edps, filters))

    if len(filtered_epds) == 0:
        return None, None

    for epd in filtered_epds:
        # print(epd.uuid)
        # print(epd.material.to_dict())
        epd.get_lcia_results()

    avg_properties = average_material_properties(filtered_epds)
    mat = Material(**avg_properties)
    mat.rescale(process.material_kwargs)
    avg_properties = mat.to_dict()

    market_epds = {
        country: list(gen_locfiltered_epds(filtered_epds, [LocationFilter({country})]))
        for country in process.market
    }

    # TODO: is this supposed to loop and `epds` generator?????
    market_impacts = {
        country: average_impacts([epd.lcia_results for epd in epds])
        for country, epds in market_epds.items()
    }

    avg_gwps = weighted_averages(process.market, market_impacts)

    logger.info(
        f"Generic EPD {process.uuid} generated",
        initial_epds=len(process.matches["uuids"]),
        selected_epds=len(filtered_epds),
    )

    return avg_properties, avg_gwps


def run_materia(path_to_gen_folder: Path, path_to_epd_folder: Path, output_path: Path):
    exclude = ["processes", "processes_old", "flows"]
    copy_except_folders(path_to_gen_folder, output_path, exclude)

    # First parse all XML processes to keep it in memory
    epds_generator = gen_epds(path_to_epd_folder / "processes")
    epds: dict[str, IlcdProcess] = {
        str(parsed.uuid): parsed for parsed in epds_generator
    }

    logger.info(f"Parsed XML EPDs, {len(epds)}")
    # assert 0
    # breakpoint()
    for path, root in gen_xml_objects(path_to_gen_folder / "processes"):
        process = IlcdProcess(root=root, path=path)
        process.get_ref_flow()
        process.get_declared_unit()
        process.get_hs_class()
        process.get_market()
        process.get_matches()
        if process.matches:
            logger.info(f"Processing {ICONS.HOURGLASS}", uuid=process.uuid)

            avg_properties, avg_gwps = epd_pipeline(process, epds)
            if avg_properties is None and avg_gwps is None:
                logger.warning(
                    f"Failed {ICONS.ERROR}",
                    uuid=process.uuid,
                    message="Cannot be complete, properties and impacts are None",
                )
            else:
                process.material = Material(**avg_properties)
                process.write_process(avg_gwps, output_path)
                process.write_flow(avg_properties, output_path)
                logger.info(
                    f"Completed {ICONS.SUCCESS}",
                    uuid=process.uuid,
                )
