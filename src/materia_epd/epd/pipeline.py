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
    filter_failure,
)
from materia_epd.epd.models import IlcdProcess
from materia_epd.epd.report import build_report, write_report, draw_report
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


def get_filtered_epds(epds: list[IlcdProcess], filters: list[EPDFilter]):
    """Filters out EPD objects that do not match filters AND collects reasons."""
    accepted = []
    rejected = []

    for epd in epds:
        reasons = []
        for filt in filters:
            if not filt.matches(epd):
                reason = filter_failure(epd, filt)
                if reason:
                    reasons.append(reason)
        if reasons:
            rejected.append((epd.uuid, reasons))
        else:
            accepted.append(epd)

    return accepted, rejected


def get_locfiltered_epds(
    epd_roots: list[IlcdProcess], filters: list[EPDFilter], max_attempts=4
):
    """Filters EPDS by location"""
    filters = [f for f in filters if isinstance(f, LocationFilter)]
    wanted_locations = set()
    for filt in filters:
        wanted_locations.update(filt.locations)
    for _ in range(max_attempts):
        epds, _ = get_filtered_epds(epd_roots, filters)
        if epds:
            return epds
        else:
            wanted_locations = escalate_location_set(wanted_locations)
            filters = [LocationFilter(wanted_locations)]
    raise NoMatchingEPDError(filters)


def epd_pipeline(process: IlcdProcess, epds: list[IlcdProcess]):
    """Aggregates the data of different EPDs into a new generic EPD.
    For a new EPD detailed in `process`, it looks
    the source EPDs that should be included in `epds`.
    This pipeline applies different filtering criteria
    to exclude not-matching or inconsisting source EPDs.
    """

    # Pre-filter stage: get matched epds
    pre_filtered_epds, _ = get_filtered_epds(epds, [UUIDFilter(process.matches)])

    # If an EPD is not found in provided folder we catch it here
    missing_epds = []
    for uuid in process.matches["uuids"]:
        if uuid not in [epd.uuid for epd in pre_filtered_epds]:
            missing_epds.append((uuid, "EPD was not found in provided folder."))

    # Filter stage: get viable epds
    filtered_epds, rejected_epds = get_filtered_epds(
        pre_filtered_epds, [UnitConformityFilter(process.material_kwargs)]
    )

    # If no viable epds: try for mass based declared unit
    if len(filtered_epds) == 0:
        logger.warning(
            f"Switched from {process.dec_unit}-based to "
            f"mass-based functional unit {ICONS.WARNING}",
            uuid=process.uuid,
        )
        logger.info(f"Processing {ICONS.HOURGLASS}", uuid=process.uuid)
        process.material_kwargs = MASS_KWARGS
        process.dec_unit = "mass"
        filtered_epds, rejected_epds = get_filtered_epds(
            pre_filtered_epds, [UnitConformityFilter(process.material_kwargs)]
        )

    # If no viable epds: return None
    if len(filtered_epds) == 0:
        return None, None, None

    for epd in filtered_epds:
        epd.get_lcia_results()

    avg_properties = average_material_properties(filtered_epds)
    mat = Material(**avg_properties)
    mat.rescale(process.material_kwargs)
    avg_properties = mat.to_dict()

    # Market stage:
    market_epds = {
        country: list(get_locfiltered_epds(filtered_epds, [LocationFilter({country})]))
        for country in process.market
    }

    # If an EPD is not matched to a market country (or RoW) we catch it here
    unmatched_epds = []
    for uuid in [epd.uuid for epd in filtered_epds]:
        if uuid not in set([epd.uuid for epds in market_epds.values() for epd in epds]):
            unmatched_epds.append((uuid, "EPD has no appropriate location in market."))

    market_impacts = {
        country: average_impacts([epd.lcia_results for epd in country_epds])
        for country, country_epds in market_epds.items()
    }

    avg_gwps = weighted_averages(process.market, market_impacts)

    logger.info(
        f"Generic EPD {process.uuid} generated",
        initial_epds=len(process.matches["uuids"]),
        selected_epds=len(filtered_epds),
    )

    report = build_report(
        report_uuid=process.uuid,
        epd_entries=filtered_epds,
        avg_impacts=avg_gwps,
        avg_physical=avg_properties,
        initial_epds=len(process.matches["uuids"]),
        selected_epds=len(filtered_epds),
        rejected_epds=rejected_epds + missing_epds + unmatched_epds,
    )

    return avg_properties, avg_gwps, report


def run_materia(path_to_gen_folder: Path, path_to_epd_folder: Path, output_path: Path):
    exclude = ["processes", "processes_old", "flows"]
    copy_except_folders(path_to_gen_folder, output_path, exclude)

    # First parse all XML processes to keep it in memory
    epds = list(gen_epds(path_to_epd_folder / "processes"))

    logger.info(f"Parsed XML EPDs, {len(epds)}")

    for path, root in gen_xml_objects(path_to_gen_folder / "processes"):
        process = IlcdProcess(root=root, path=path)
        process.get_ref_flow()
        process.get_declared_unit()
        process.get_hs_class()
        process.get_market()
        process.get_matches()
        if process.matches:
            logger.info(f"Processing {ICONS.HOURGLASS}", uuid=process.uuid)

            avg_properties, avg_gwps, report = epd_pipeline(process, epds)
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
                write_report(report, output_path, process.uuid)
                draw_report(report, output_path, process.uuid)
                logger.info(
                    f"Completed {ICONS.SUCCESS}",
                    uuid=process.uuid,
                )
