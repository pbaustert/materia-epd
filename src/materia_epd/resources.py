# src/materia/resources.py
from __future__ import annotations

from functools import lru_cache
from importlib.resources import as_file, files

from materia_epd.io import files as io_files
from materia_epd.io.paths import USER_DATA_DIR


@lru_cache(maxsize=None)
def load_json_from_package(*path_parts):
    """Load and cache a JSON file from the package data folder."""
    resource = files(__package__).joinpath("data", *path_parts)
    with as_file(resource) as path:
        data = io_files.read_json_file(path)
    if data is None:
        raise ValueError(f"Invalid or missing JSON file: {'/'.join(path_parts)}")
    return data


def iter_json_from_package_folder(*folder_parts: str):
    """Yield (filename, data) from all JSON files in a package folder."""
    folder = files(__package__).joinpath("data", *folder_parts)
    with as_file(folder) as folder_path:
        yield from io_files.gen_json_objects(folder_path)


@lru_cache(maxsize=1)
def get_regions_mapping():
    return load_json_from_package("regions_mapping.json")


@lru_cache(maxsize=1)
def get_indicator_synonyms():
    return load_json_from_package("indicator_synonyms.json")


@lru_cache(maxsize=1)
def get_market_shares(loc_code: str, hs_code: str):
    filename = f"{hs_code}.json"
    subfolder = f"market_shares/{loc_code}"

    resource = files(__package__).joinpath("data", subfolder, filename)
    if resource.is_file():
        with as_file(resource) as path:
            data = io_files.read_json_file(path)
            if data is not None:
                return data

    user_file = USER_DATA_DIR / subfolder / filename
    if user_file.exists():
        data = io_files.read_json_file(user_file)
        if data is not None:
            return data

    from materia_epd.market.market import generate_market

    data = generate_market(loc_code, hs_code)
    user_file.parent.mkdir(parents=True, exist_ok=True)
    io_files.write_json_file(user_file, data)
    print(f"Market share for imports of {hs_code} to {loc_code} stored in {user_file}.")
    return data


def get_comtrade_api_key():
    api_file = USER_DATA_DIR / "comtrade_api_key.json"
    if api_file.exists():
        data = io_files.read_json_file(api_file)
        if data and "apikey" in data:
            return data["apikey"]

    api_key = input("Enter your Comtrade API key: ").strip()
    if not api_key:
        raise ValueError("API key cannot be empty.")

    api_file.parent.mkdir(parents=True, exist_ok=True)
    io_files.write_json_file(api_file, {"apikey": api_key})
    print(f"API key stored in {api_file}.")

    return api_key


@lru_cache(maxsize=1)
def get_location_data(loc_code: str):
    return load_json_from_package("locations", f"{loc_code}.json")


@lru_cache(maxsize=1)
def get_national_production(loc_code: str, hs_code: str):
    filename = f"{hs_code}.json"
    subfolder = f"national_production/{loc_code}"

    resource = files(__package__).joinpath("data", subfolder, filename)
    if resource.is_file():
        with as_file(resource) as path:
            data = io_files.read_json_file(path)
            if data is not None:
                return data
    else:
        return {"production": 0}
