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
        self.last_failure = None

    def matches(self, epd: IlcdProcess) -> bool:
        self.last_failure = None

        try:
            epd.get_ref_flow()
            logger.debug(
                "Ref. flow identified and parsed",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
                target_kwargs=self.target_kwargs,
            )
        except Exception as e:
            self.last_failure = f"Flow XML could not be processed: {e}"
            logger.debug(
                "Flow XML could not be processed",
                epd_uuid=epd.uuid,
                target_kwargs=self.target_kwargs,
                exec_info=repr(e),
            )
            return False

        logger.debug(
            "Material before rescale",
            epd_uuid=epd.uuid,
            flow_uuid=epd.ref_flow.uuid,
            target_kwargs=self.target_kwargs,
            material=epd.material.to_dict(),
        )

        try:
            logger.debug(
                "Flow rescale attempt",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
                target_kwargs=self.target_kwargs,
            )
            epd.material.rescale(self.target_kwargs)

            logger.debug(
                "Material after rescale",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
                target_kwargs=self.target_kwargs,
                material=epd.material.to_dict(),
            )

            logger.debug(
                "Flow rescaled correctly",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
                target_kwargs=self.target_kwargs,
            )

        except Exception as e:
            self.last_failure = f"Flow XML could not be rescaled: {e}"

            logger.debug(
                "Material after failed rescale",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
                target_kwargs=self.target_kwargs,
                material=epd.material.to_dict(),
                exec_info=repr(e),
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
    if isinstance(filter, UnitConformityFilter) and filter.last_failure:
        return filter.last_failure

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
