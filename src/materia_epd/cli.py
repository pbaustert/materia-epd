# materia/cli.py
from pathlib import Path

import click

from materia_epd.epd.pipeline import run_materia
from materia_epd.logging_utils import setup_logging


@click.command()
@click.argument("input_path", type=click.Path(exists=True, path_type=Path))
@click.argument("epd_folder_path", type=click.Path(exists=True, path_type=Path))
@click.option("--output_path", "-o", type=click.Path(path_type=Path), required=False)
@click.option(
    "--verbose", "-v", "verbose", is_flag=True, flag_value=True, default=False
)
def main(
    input_path: Path, epd_folder_path: Path, output_path: Path | None, verbose: bool
):
    """Process the given file or folder path."""
    # Setup logging immediately after CLI options are parsed
    setup_logging(verbose=verbose, output_folder=output_path)

    run_materia(input_path, epd_folder_path, output_path)
