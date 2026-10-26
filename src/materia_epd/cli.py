# materia/cli.py
from pathlib import Path

import click
import json

from materia_epd.pipeline.run import run_materia, run_materia_from_url
from materia_epd.logging_utils import setup_logging


@click.command()
@click.argument(
    "input_path", type=click.Path(exists=True, path_type=Path), required=False
)
@click.argument(
    "epd_folder_path", type=click.Path(exists=True, path_type=Path), required=False
)
@click.option("--output_path", "-o", type=click.Path(path_type=Path), required=False)
@click.option(
    "--process-list", "-p", type=click.Path(exists=True, path_type=Path), required=False
)
@click.option(
    "--from-url",
    "from_url",
    type=click.Path(exists=True, path_type=Path),
    required=False,
    help="JSON spec of generic processes whose source EPDs are fetched from a file "
    "server instead of local folders (replaces INPUT_PATH and EPD_FOLDER_PATH).",
)
@click.option(
    "--base-url",
    "base_url",
    required=False,
    help="File server URL for --from-url, e.g. http://host:44003/raw "
    "(default: `base_url` in the spec, then $MATERIA_EPD_BASE_URL).",
)
@click.option(
    "--verbose", "-v", "verbose", is_flag=True, flag_value=True, default=False
)
def main(
    input_path: Path | None,
    epd_folder_path: Path | None,
    output_path: Path | None,
    process_list: Path | None,
    from_url: Path | None,
    base_url: str | None,
    verbose: bool,
):
    """Process the given file or folder path.

    Local mode:     materia-epd INPUT_PATH EPD_FOLDER_PATH -o OUTPUT

    From-url mode:  materia-epd --from-url SPEC.json [--base-url URL] -o OUTPUT
    """
    if from_url:
        if input_path or epd_folder_path or process_list:
            raise click.UsageError(
                "--from-url cannot be combined with INPUT_PATH, EPD_FOLDER_PATH "
                "or --process-list."
            )
    elif not (input_path and epd_folder_path):
        raise click.UsageError(
            "INPUT_PATH and EPD_FOLDER_PATH are required (or use --from-url)."
        )
    elif base_url:
        raise click.UsageError("--base-url is only used with --from-url.")

    # Setup logging immediately after CLI options are parsed
    setup_logging(verbose=verbose, output_folder=output_path)

    if from_url:
        with open(from_url, "r") as f:
            spec = json.load(f)
        try:
            run_materia_from_url(spec, output_path, base_url=base_url)
        except ValueError as e:
            raise click.UsageError(str(e))
        return

    process_uuids: set[str] | None = None
    if process_list:
        with open(process_list, "r") as f:
            uuids = json.load(f)
            process_uuids = set(uuids)

    run_materia(input_path, epd_folder_path, output_path, process_uuids)


if __name__ == "__main__":
    main()
