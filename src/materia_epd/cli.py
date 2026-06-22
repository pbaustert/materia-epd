# materia/cli.py
import sys
from pathlib import Path

import click
from rich.console import Console

from materia_epd.epd.cache import build_epd_cache, resolve_cache_dir
from materia_epd.logging_utils import setup_logging
from materia_epd.pipeline.run import run_materia

console = Console()


@click.command()
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.argument("epd_folder_path", type=click.Path(exists=True, path_type=Path))
@click.option("--output_path", "-o", type=click.Path(path_type=Path), required=False)
@click.option(
    "--epd-cache",
    type=click.Path(path_type=Path),
    default=None,
    help="Directory for the EPD Feather cache (default: ./.materia_epd_cache).",
)
@click.option(
    "--no-epd-cache",
    is_flag=True,
    default=False,
    help="Skip the EPD cache and parse source XML files directly.",
)
@click.option(
    "--verbose", "-v", "verbose", is_flag=True, flag_value=True, default=False
)
def aggregate(
    input_path: Path,
    epd_folder_path: Path,
    output_path: Path | None,
    epd_cache: Path | None,
    no_epd_cache: bool,
    verbose: bool,
):
    """Run the EPD aggregation pipeline."""
    setup_logging(verbose=verbose, output_folder=output_path)
    run_materia(
        input_path,
        epd_folder_path,
        output_path,
        epd_cache_dir=epd_cache,
        use_epd_cache=not no_epd_cache,
        verbose=verbose,
    )


@click.command("build-cache")
@click.argument("epd_folder_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    "cache_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Cache output directory (default: ./.materia_epd_cache).",
)
@click.option("--force", is_flag=True, default=False, help="Rebuild even if cache is valid.")
@click.option(
    "--workers",
    type=int,
    default=None,
    help="Parallel worker count (default: CPU count).",
)
@click.option(
    "--verbose", "-v", "verbose", is_flag=True, flag_value=True, default=False
)
def build_cache_cmd(
    epd_folder_path: Path,
    cache_dir: Path | None,
    force: bool,
    workers: int | None,
    verbose: bool,
):
    """Pre-build the EPD Feather cache without running the aggregation pipeline."""
    setup_logging(verbose=verbose, output_folder=None)
    resolved = resolve_cache_dir(cache_dir)
    build_epd_cache(
        epd_folder_path,
        resolved,
        force=force,
        workers=workers,
        console=console,
        verbose=verbose,
    )
    console.print(f"[green]EPD cache written to {resolved}[/green]")


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "build-cache":
        build_cache_cmd.main(
            args=argv[1:],
            prog_name="materia_epd build-cache",
            standalone_mode=True,
        )
    else:
        aggregate.main(args=argv, prog_name="materia_epd", standalone_mode=True)


if __name__ == "__main__":
    main()
