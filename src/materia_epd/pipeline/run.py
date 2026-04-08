import logging
import structlog
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from materia_epd.epd.generators import gen_epds, gen_xml_objects
from materia_epd.epd.models import IlcdProcess
from materia_epd.core.physics import Material
from materia_epd.pipeline.report import write_report, draw_report
from materia_epd.pipeline.pipeline import Pipeline
from materia_epd.pipeline.recipes import RecipeFactory
from materia_epd.pipeline.context import EpdPipelineContext

logger = structlog.wrap_logger(logging.getLogger(__name__))
console = Console()


def log_pipeline_diagnostics(logger, ctx):
    for diag in ctx.diagnostics:
        payload = {k: v for k, v in diag.items() if k not in {"kind", "message"}}

        if diag["kind"] == "error":
            logger.error(diag["message"], **payload)
        elif diag["kind"] == "warning":
            logger.warning(diag["message"], **payload)
        else:
            logger.info(diag["message"], **payload)


def pipeline_has_outputs(ctx: EpdPipelineContext) -> bool:
    return (
        ctx.success
        and ctx.avg_properties is not None
        and ctx.avg_gwps is not None
        and ctx.report is not None
    )


def print_pipeline_summary(ctx: EpdPipelineContext) -> None:
    # Decide base status color by success, override to yellow if fallback used
    status_color = "green" if ctx.success else "red"
    if ctx.used_mass_fallback:
        status_color = "yellow"

    # Status label (optionally clarify that fallback was used)
    status_label = "SUCCESS" if ctx.success else "FAILED"
    if ctx.used_mass_fallback:
        status_label += " (MASS-FALLBACK)"

    status_text = f"[{status_color}]{status_label}[/{status_color}]"
    title = f"Pipeline result for {ctx.process.uuid}"

    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")

    table.add_row("Status", status_text)
    table.add_row("Recipe type", ctx.recipe_type)
    table.add_row("Requested", str(len(ctx.process.matches["uuids"])))
    table.add_row("Missing", str(len(ctx.missing_epds)))
    table.add_row("Rejected", str(len(ctx.rejected_epds)))
    table.add_row("Unmatched", str(len(ctx.unmatched_epds)))
    table.add_row("Filtered", str(len(ctx.filtered_epds)))
    table.add_row("Fallback used", str(ctx.used_mass_fallback))
    table.add_row("Final declared unit", str(ctx.active_dec_unit))

    # Keep panel border green/red based on overall success
    border_style = "green" if ctx.success else "red"
    console.print(Panel(table, title=title, border_style=border_style))


def run_materia(
    path_to_gen_folder: Path, path_to_epd_folder: Path, output_path: Path
) -> None:
    epds = list(gen_epds(path_to_epd_folder / "processes", logger))
    logger.info("Parsed XML EPDs", count=len(epds))

    for path, root in gen_xml_objects(path_to_gen_folder / "processes", logger):
        process = IlcdProcess(root=root, path=path)
        process.get_ref_flow()
        process.get_declared_unit()
        process.get_hs_class()
        process.get_market()
        process.get_matches()

        if not process.matches:
            continue

        ctx = EpdPipelineContext(
            process=process,
            matches=process.matches,
            all_epds=epds,
            active_material_kwargs=process.material_kwargs,
            active_dec_unit=process.dec_unit,
            recipe_type=process.matches.get("type"),
        )

        pipeline = Pipeline(RecipeFactory().build(ctx))
        ctx = pipeline.run(ctx)
        print_pipeline_summary(ctx)
        # log_pipeline_diagnostics(logger, ctx)

        if pipeline_has_outputs(ctx):
            process.material = Material(**ctx.avg_properties)
            process.write_process(ctx.avg_gwps, output_path)
            process.write_flow(ctx.avg_properties, output_path)
            write_report(ctx.report, output_path, process.uuid)
            draw_report(ctx.report, output_path, process.uuid)
