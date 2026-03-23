from __future__ import annotations

import logging
import structlog

from materia_epd.epd.models import IlcdProcess
from materia_epd.core.errors import NoMatchingEPDError
from materia_epd.geo.locations import escalate_location_set

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
)
logger = structlog.wrap_logger(logging.getLogger(__name__))


class EPDFilter:
    def matches(self, epd: IlcdProcess) -> bool:
        return True

    def __repr__(self):
        return self.__class__.__name__


class UUIDFilter(EPDFilter):
    def __init__(self, matches: dict):
        self.uuids = matches.get("uuids", matches)

    def matches(self, epd: IlcdProcess) -> bool:
        return epd.uuid in self.uuids

    def __repr__(self):
        return f"{self.__class__.__name__}(uuids={self.uuids})"


class UnitConformityFilter(EPDFilter):
    def __init__(self, target_kwargs):
        self.target_kwargs = target_kwargs

    def matches(self, epd: IlcdProcess) -> bool:
        try:
            epd.get_ref_flow()
            logger.debug(
                "Ref. flow identified and parsed \n",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
            )
        except Exception as e:
            logger.debug(
                "Flow XML could not be processsed \n",
                epd_uuid=epd.uuid,
                exec_info=e,
            )
            return False

        try:
            epd.material.rescale(self.target_kwargs)
            logger.debug(
                "Flow rescaled correctly \n",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
            )
        except Exception as e:
            logger.debug(
                "Flow XML could not be rescaled \n",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
                exec_info=e,
            )
            return False
        return True

    def __repr__(self):
        return f"{self.__class__.__name__}(target={self.target_kwargs})"


class LocationFilter(EPDFilter):
    def __init__(self, locations):
        self.locations = locations

    def matches(self, epd: IlcdProcess) -> bool:
        return epd.loc in self.locations

    def __repr__(self):
        return f"{self.__class__.__name__}(code={self.locations})"


def filter_failure(epd, filter):
    """Returns explanation for why a filter rejected an EPD."""
    try:
        ok = filter.matches(epd)
    except Exception as e:
        return f"{filter.__class__.__name__} raised exception: {e}"

    if ok:
        return None

    if isinstance(filter, UUIDFilter):
        return f"UUID does not match {filter.uuids}."

    if isinstance(filter, UnitConformityFilter):
        return f"Unit conformity failed for {filter.target_kwargs}."

    if isinstance(filter, LocationFilter):
        return f"Location does not match {filter.locations}."

    return f"Failed filter {filter.__class__.__name__}"


def get_filtered_epds(epds: list[IlcdProcess], filter: EPDFilter):
    """Filters out EPD objects that do not match and collects reason."""
    accepted = []
    rejected = []

    for epd in epds:
        if not filter.matches(epd):
            rejected.append((epd.uuid, filter_failure(epd, filter)))
        else:
            accepted.append(epd)

    return accepted, rejected


def get_locfiltered_epds(
    epd_roots: list[IlcdProcess], filter: LocationFilter, max_attempts=4
):
    """Filters EPDS by location"""
    wanted_locations = set(filter.locations)
    for _ in range(max_attempts):
        epds, _ = get_filtered_epds(epd_roots, filter)
        if epds:
            return epds
        else:
            wanted_locations = escalate_location_set(wanted_locations)
            filter = LocationFilter(wanted_locations)
    raise NoMatchingEPDError(filter)
