from rich.progress import track
import xml.etree.ElementTree as ET
from pathlib import Path

from rich.console import Console

from materia_epd.epd.cache import (
    build_epd_cache,
    cache_exists,
    is_cache_valid,
    load_epds_from_cache,
    resolve_cache_dir,
)
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


def load_epd_corpus(
    epd_folder: Path,
    cache_dir: Path | None,
    logger,
    *,
    use_cache: bool = True,
    auto_build: bool = True,
    console: Console | None = None,
    verbose: bool = False,
    disable_progress: bool = False,
) -> list[IlcdProcess]:
    """Load source EPDs from cache (building if needed) or directly from XML."""
    if not use_cache:
        return list(gen_epds(epd_folder / "processes", logger))

    resolved_cache = resolve_cache_dir(cache_dir)
    out = console or Console()

    if cache_exists(resolved_cache) and is_cache_valid(resolved_cache, epd_folder):
        logger.info("Loading EPD corpus from cache", cache_dir=str(resolved_cache))
        return load_epds_from_cache(resolved_cache, epd_folder)

    if not auto_build:
        from materia_epd.epd.cache import CacheMissingError

        raise CacheMissingError(
            f"EPD cache not found or stale at {resolved_cache}; "
            "run build-cache or omit --no-epd-cache"
        )

    if cache_exists(resolved_cache):
        out.print(
            f"[yellow]EPD cache at {resolved_cache} is out of date; "
            f"rebuilding from {epd_folder}...[/yellow]"
        )
        logger.warning(
            "EPD cache is stale; rebuilding",
            cache_dir=str(resolved_cache),
            epd_folder=str(epd_folder),
        )
    else:
        out.print(
            f"[yellow]EPD cache not found at {resolved_cache}; "
            f"building cache from {epd_folder} (this may take a while)...[/yellow]"
        )
        logger.info(
            "EPD cache not found; building",
            cache_dir=str(resolved_cache),
            epd_folder=str(epd_folder),
        )

    build_epd_cache(
        epd_folder,
        resolved_cache,
        force=True,
        console=out,
        verbose=verbose,
        disable_progress=disable_progress,
    )
    return load_epds_from_cache(resolved_cache, epd_folder)
