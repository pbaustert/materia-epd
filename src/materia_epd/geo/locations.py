import pycountry

from materia_epd.resources import get_location_data
from materia_epd.resources import get_regions_mapping


def ilcd_to_iso_location(ilcd_code):
    """Convert an ILCD location code to an ISO-compliant location code."""
    return (
        {"GLO": "GLO", "UK": "GBR"}.get(ilcd_code)
        or (get_regions_mapping().get(ilcd_code) or {}).get("Regions")
        or getattr(pycountry.countries.get(alpha_2=ilcd_code), "alpha_3", None)
        or getattr(pycountry.historic_countries.get(alpha_2=ilcd_code), "alpha_3", None)
    )


def get_location_attribute(location_code: str, attribute: str):
    """Returns a specific attribute from a location JSON file."""
    location_data = get_location_data(location_code)  # .get(attribute)
    return (location_data or {}).get(attribute)


def escalate_location_set(location_set):
    """Return all children of the parent locations of a given location set."""
    return {
        child
        for parent in {get_location_attribute(loc, "Parent") for loc in location_set}
        for child in (get_location_attribute(parent, "Children") or [])
    }


def get_location_color(location_code: str):
    """Return color metadata (hex + rgba) for a location, if available."""
    location_data = get_location_data(location_code) or {}
    return {
        "hex": location_data.get("ColorHex"),
        "rgba": location_data.get("ColorRGBA"),
    }
