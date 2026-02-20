from __future__ import annotations

import logging

import structlog

from materia_epd.epd.models import IlcdProcess

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
    def __init__(self, matches: list):
        self.uuids = (
            matches.get("uuids", matches) if isinstance(matches, dict) else matches
        )

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
                "Ref. flow identified and parsed",
                epd_uuid=epd.uuid,
                flow_uuid=epd.ref_flow.uuid,
            )
        except Exception as e:
            logger.debug(
                "Flow XML could not be processsed \n", epd_uuid=epd.uuid, exec_info=e
            )
            return False

        try:
            epd.material.rescale(self.target_kwargs)
            logger.debug(
                "Flow rescaled correctly",
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
