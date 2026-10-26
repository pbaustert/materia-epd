import copy
import json
import logging
import uuid as uuid_lib
import structlog
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from materia_epd.core.constants import ATTR, NS, XP
from materia_epd.epd.generators import gen_epds, gen_epds_from_url, gen_xml_objects
from materia_epd.epd.generic import generic_process_from_json
from materia_epd.epd.generic import generic_uuid as get_generic_uuid
from materia_epd.epd.models import IlcdProcess, reference_flow_uuid
from materia_epd.io.files import read_json_file
from materia_epd.io.remote import UrlSource, resolve_base_url
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
    requested = len(ctx.process.matches.get("uuids", []))
    if not requested:
        requested = len(ctx.process.matches.get("components", []))

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
    table.add_row("Requested", str(requested))
    table.add_row("Missing", str(len(ctx.missing_epds)))
    table.add_row("Rejected", str(len(ctx.rejected_epds)))
    table.add_row("Unmatched", str(len(ctx.unmatched_epds)))
    table.add_row("Filtered", str(len(ctx.filtered_epds)))
    table.add_row("Fallback used", str(ctx.used_mass_fallback))
    table.add_row("Final declared unit", str(ctx.active_dec_unit))

    # Keep panel border green/red based on overall success
    border_style = "green" if ctx.success else "red"
    console.print(Panel(table, title=title, border_style=border_style))


def expand_process_uuids(
    all_generic: dict[str, IlcdProcess], process_uuids: set[str] | None = None
) -> set[str]:
    """Requested processes (default: all with matches) plus assembled components."""
    processes_to_run: set[str] = set()
    to_visit = set(process_uuids or [p.uuid for p in all_generic.values() if p.matches])

    while to_visit:
        uuid = to_visit.pop()
        processes_to_run.add(uuid)
        if (
            (p := all_generic.get(uuid))
            and p.matches
            and p.matches.get("type") == "assembled"
        ):
            for c in p.matches.get("components", []):
                to_visit.add(c["uuid"] if isinstance(c, dict) else c)
    return processes_to_run


def required_epd_uuids_for(matches: dict | None) -> list[str]:
    """Source EPD UUIDs referenced by a matches object, in order."""
    mtype = (matches or {}).get("type")
    if mtype in ("average", "market-average"):
        return list(matches.get("uuids", []))
    if mtype == "regression":
        return [e["uuid"] for e in matches.get("data", []) if "uuid" in e]
    return []


def collect_required_epd_uuids(
    all_generic: dict[str, IlcdProcess], processes_to_run: set[str]
) -> set[str]:
    required: set[str] = set()
    for uuid in processes_to_run:
        if (p := all_generic.get(uuid)) and p.matches:
            required.update(required_epd_uuids_for(p.matches))
    return required


def _write_outputs(
    ctx: EpdPipelineContext, process: IlcdProcess, output_path: Path
) -> None:
    """Write process/flow XML and the JSON/PDF report; failures become diagnostics."""
    steps = (
        (
            "process",
            f"processes/{process.uuid}.xml",
            process.write_process,
            (ctx.avg_gwps, output_path),
        ),
        ("flow", None, process.write_flow, (ctx.avg_properties, output_path)),
        (
            "report_json",
            f"reports/{process.uuid}.json",
            write_report,
            (ctx.report, output_path, process.uuid),
        ),
        (
            "report_pdf",
            f"reports/{process.uuid}.pdf",
            draw_report,
            (ctx.report, output_path, process.uuid),
        ),
    )
    for kind, rel_path, fn, args in steps:
        try:
            fn(*args)
        except Exception as e:
            logger.exception("Writing output failed", kind=kind, uuid=process.uuid)
            ctx.add_diagnostic(
                kind="error",
                message=f"Writing the {kind} output failed: {e}",
                stage="write-outputs",
                process_uuid=process.uuid,
            )
            continue
        ctx.outputs[kind] = rel_path or f"flows/{process.ref_flow.uuid}.xml"


def execute_processes(
    processes: list[IlcdProcess],
    epds: list[IlcdProcess],
    output_path: Path | None,
) -> dict[str, EpdPipelineContext]:
    """Run the recipe of each generic process; write outputs when `output_path` is set.

    Base processes run first, then assembled ones (which need their components'
    results). Returns the final pipeline context per process UUID.
    """
    results_registry: dict[str, dict] = {}
    contexts: dict[str, EpdPipelineContext] = {}

    def _run_process(process: IlcdProcess) -> EpdPipelineContext:
        ctx = EpdPipelineContext(
            process=process,
            matches=process.matches,
            all_epds=epds,
            active_material_kwargs=process.material_kwargs,
            active_dec_unit=process.dec_unit,
            recipe_type=process.matches.get("type"),
            results_registry=results_registry,
        )

        # A failing process must not stop the others.
        try:
            pipeline = Pipeline(RecipeFactory().build(ctx))
            ctx = pipeline.run(ctx)
        except Exception as e:
            logger.exception("Pipeline failed", process_uuid=process.uuid)
            ctx.add_diagnostic(
                kind="error",
                message=f"Pipeline failed: {e}",
                stage="pipeline",
                process_uuid=process.uuid,
            )
            ctx.stop(success=False)
        print_pipeline_summary(ctx)
        # log_pipeline_diagnostics(logger, ctx)

        if pipeline_has_outputs(ctx):
            results_registry[process.uuid] = {
                "avg_gwps": ctx.avg_gwps,
                "avg_properties": ctx.avg_properties,
                "report": ctx.report,
            }
            process.material = Material(**ctx.avg_properties)
            if output_path is not None:
                _write_outputs(ctx, process, output_path)
        contexts[process.uuid] = ctx
        return ctx

    base_processes = [p for p in processes if p.matches.get("type") != "assembled"]
    assembled_queue = [p for p in processes if p.matches.get("type") == "assembled"]

    for process in base_processes:
        _run_process(process)

    while assembled_queue:
        progressed = False
        deferred = []
        for process in assembled_queue:
            ctx = _run_process(process)
            if pipeline_has_outputs(ctx):
                progressed = True
                continue

            missing_dependency_error = any(
                d.get("stage") == "resolve-component-results"
                and d.get("kind") == "error"
                for d in ctx.diagnostics
            )
            if missing_dependency_error:
                deferred.append(process)
                continue

            progressed = True

        if not deferred:
            break

        if not progressed:
            unresolved = [p.uuid for p in deferred]
            logger.warning(
                "Assembled processes unresolved due to missing component outputs.",
                processes=unresolved,
            )
            break

        assembled_queue = deferred

    return contexts


def load_generic_jsons(
    path_to_gen_folder: Path,
    process_uuids: set[str] | None = None,
    skip: set[str] | None = None,
) -> dict[str, IlcdProcess]:
    """Generic processes from ``<gen>/matches/<ID>.json`` + ``<gen>/jsons/<ID>.json``.

    Only the JSON objects that have a matches file (or are listed in `process_uuids`)
    are read; their skeletons are built from ``<gen>/templates`` or the bundled ones.
    """
    gen = Path(path_to_gen_folder)
    if not (gen / "jsons").is_dir():
        return {}
    templates = gen / "templates"
    templates = templates if (templates / "GenPro_template.xml").is_file() else None
    wanted = {p.stem for p in (gen / "matches").glob("*.json")} | set(
        process_uuids or []
    )

    out: dict[str, IlcdProcess] = {}
    for gid in sorted(wanted - set(skip or [])):
        data = read_json_file(gen / "jsons" / f"{gid}.json")
        matches = read_json_file(gen / "matches" / f"{gid}.json")
        if not isinstance(data, dict) or not matches:
            continue
        try:
            process = generic_process_from_json({**data, "ID": gid}, templates)
        except Exception as e:
            logger.warning("Generic EPD JSON skipped", uuid=gid, error=str(e))
            continue
        process.matches = matches
        out[gid] = process
    return out


def run_materia(
    path_to_gen_folder: Path,
    path_to_epd_folder: Path,
    output_path: Path,
    process_uuids: set[str] | None = None,
) -> dict[str, EpdPipelineContext]:
    # Load all generic processes
    all_generic = {}
    for path, root in gen_xml_objects(path_to_gen_folder / "processes", logger):
        process = IlcdProcess(root=root, path=path)
        process.get_ref_flow()
        process.get_declared_unit()
        process.get_hs_class()
        process.get_market()
        process.get_matches()
        all_generic[process.uuid] = process

    # Generic EPD JSON objects (jsons/<ID>.json) without an XML skeleton are built from
    # the templates (<gen>/templates, else the bundled ones) when they have matches.
    all_generic.update(
        load_generic_jsons(path_to_gen_folder, process_uuids, skip=set(all_generic))
    )

    # Expand process list with dependencies
    processes_to_run = expand_process_uuids(all_generic, process_uuids)

    # Collect required EPD UUIDs
    required_epd_uuids = collect_required_epd_uuids(all_generic, processes_to_run)

    # Load only required EPDs
    epds = list(gen_epds(path_to_epd_folder / "processes", logger, required_epd_uuids))

    # Build process list
    processes = [all_generic[uuid] for uuid in processes_to_run if uuid in all_generic]
    return execute_processes(processes, epds, output_path)


# ----------------------------- from-url mode ---------------------------------


def normalize_url_spec(spec: Any) -> dict[str, Any]:
    """Normalize a from-url request into ``{..options.., "processes": [...]}``.

    Accepted forms:

    * a list of EPD UUIDs -> one "average" generic process;
    * a single process object (``{"matches": {...}}`` or ``{"uuids": [...]}``);
    * ``{"base_url": ..., "processes": [<process>, ...]}``;
    * the website export ``{"project_name": ..., "data": [<generic EPD>, ...]}``.

    A generic EPD object (``"ID"`` + the fields of ``jsons/<ID>.json`` + ``"matches"``,
    as exported by the website) is turned into ``{"generic": ..., "matches": ...}``;
    its skeleton is then built from the templates (see `materia_epd.epd.generic`).
    Fields that are not used, e.g. ``cptax_classification``, are ignored.

    A process object accepts ``uuid`` (generic UUID, random if omitted), ``name``,
    ``matches`` (same format as the local ``matches/<uuid>.json`` files) or the
    shorthand ``uuids`` + ``type`` (default "average"), and the skeleton options
    ``template`` (UUID of the source EPD used as skeleton, default: first matched
    EPD), ``template_url`` / ``template_flow_url`` (a ready generic process XML and
    its reference flow), ``location`` (ILCD code, e.g. "LU"), ``hs_class`` and
    ``declared_unit`` (mass, volume, surface, length or unit_count; default: the
    declared unit of the template EPD).
    """
    if isinstance(spec, list):
        spec = {"processes": [{"uuids": spec}]}
    elif not isinstance(spec, dict):
        raise ValueError("from-url spec must be a JSON object or a list of UUIDs.")
    elif "processes" not in spec and isinstance(spec.get("data"), list):
        spec = {**spec, "processes": spec["data"]}
    elif "processes" not in spec:
        options = {
            k: spec[k]
            for k in ("base_url", "processes_dir", "flows_dir", "timeout")
            if k in spec
        }
        process = {k: v for k, v in spec.items() if k not in options}
        spec = {**options, "processes": [process]}

    processes = []
    for i, item in enumerate(spec.get("processes") or []):
        if not isinstance(item, dict):
            raise ValueError(f"processes[{i}] must be an object.")
        item = dict(item)
        if "ID" in item and "generic" not in item:  # website / jsons/ object
            generic = {k: v for k, v in item.items() if k != "matches"}
            item = {"generic": generic, "matches": item.get("matches")}
        if "generic" in item:
            if not isinstance(item["generic"], dict):
                raise ValueError(f"processes[{i}].generic must be an object.")
            item["generic"] = dict(item["generic"])
            gid = (
                get_generic_uuid(item["generic"])
                or item.get("uuid")
                or uuid_lib.uuid4()
            )
            item["generic"]["ID"] = item["uuid"] = str(gid)
            if item.get("matches") is None and "uuids" not in item:
                item["matches"] = {"type": "average", "uuids": []}
        matches = item.get("matches")
        if matches is None:
            if "uuids" not in item:
                raise ValueError(f"processes[{i}] needs `matches` or `uuids`.")
            matches = {"type": item.pop("type", "average"), "uuids": item.pop("uuids")}
        if not isinstance(matches, dict) or not matches.get("type"):
            raise ValueError(f"processes[{i}].matches must be an object with `type`.")
        if "uuids" in matches:
            matches["uuids"] = list(
                dict.fromkeys(str(u).strip() for u in matches["uuids"] if u)
            )
        item["matches"] = matches
        item["uuid"] = str(item.get("uuid") or uuid_lib.uuid4())
        processes.append(item)

    if not processes:
        raise ValueError("from-url spec contains no processes.")
    return {**spec, "processes": processes}


# Declared quantities a generic process can be expressed in (`declared_unit`)
DECLARED_UNITS = ("mass", "volume", "surface", "length", "unit_count")


def _set_name(root: ET.Element, name: str) -> None:
    name_node = root.find(".//proc:dataSetInformation/proc:name", NS)
    if name_node is None:
        return
    for base_name in name_node.findall("proc:baseName", NS):
        name_node.remove(base_name)
    node = ET.Element(f"{{{NS['proc']}}}baseName", {f"{{{NS['xml']}}}lang": "en"})
    node.text = name
    name_node.insert(0, node)


def _skeleton_from_epd(
    source: UrlSource, epd_uuid: str, generic_uuid: str
) -> tuple[ET.Element, Any]:
    """Copy a source EPD into a generic process skeleton with new process/flow UUIDs.

    Returns the process root and a flow loader resolving the renamed reference flow.
    """
    root = copy.deepcopy(source.process_root(epd_uuid))
    root.find(XP.UUID, NS).text = generic_uuid

    flow_uuid = reference_flow_uuid(root)
    new_flow_uuid = str(uuid_lib.uuid5(uuid_lib.NAMESPACE_URL, f"{generic_uuid}/flow"))
    ref_flow_id = root.findtext(XP.QUANT_REF, namespaces=NS).strip()
    exchange = root.find(XP.exchange_by_id(ref_flow_id), NS)
    ref = exchange.find(XP.REF_TO_FLOW, NS)
    ref.set(ATTR.REF_OBJECT_ID, new_flow_uuid)
    if ref.get("uri"):
        ref.set("uri", f"../flows/{new_flow_uuid}.xml")
    # Like the generic skeletons, the generic process declares 1 unit of product
    for tag in ("meanAmount", "resultingAmount"):
        amount = exchange.find(f"proc:{tag}", NS)
        if amount is not None:
            amount.text = "1"

    def flow_loader(uuid: str) -> ET.Element:
        if uuid != new_flow_uuid:
            return source.flow_root(uuid)
        flow_root = copy.deepcopy(source.flow_root(flow_uuid))
        flow_root.find(XP.UUID, NS).text = new_flow_uuid
        return flow_root

    return root, flow_loader


def _build_generic_process(
    source: UrlSource, item: dict[str, Any], available: list[str]
) -> IlcdProcess:
    """Build the generic `IlcdProcess` for one from-url process spec."""
    generic_uuid = item["uuid"]
    if item.get("generic"):
        process = generic_process_from_json(
            item["generic"], location=item.get("location")
        )
        if item.get("hs_class"):
            process.hs_class = str(item["hs_class"])
        process.matches = item["matches"]
        return process
    if item.get("template_url"):
        root = copy.deepcopy(source.fetch_xml_root(item["template_url"]))
        flow_url = item.get("template_flow_url")
        flow_loader = (
            (lambda _uuid: source.fetch_xml_root(flow_url))
            if flow_url
            else source.flow_root
        )
        root.find(XP.UUID, NS).text = generic_uuid
        path = item["template_url"]
    else:
        template = item.get("template") or next(iter(available), None)
        if not template:
            raise ValueError(
                "No skeleton available: none of the matched EPDs could be fetched and "
                "no `template` / `template_url` was given."
            )
        root, flow_loader = _skeleton_from_epd(source, template, generic_uuid)
        path = source.process_url(template)
        item["template"] = template

    if item.get("name"):
        _set_name(root, item["name"])
    if item.get("location"):
        loc_node = root.find(XP.LOCATION, NS)
        if loc_node is not None:
            loc_node.set(ATTR.LOCATION, item["location"])

    process = IlcdProcess(root=root, path=path, flow_loader=flow_loader)
    process.get_ref_flow()
    process.get_declared_unit()
    if not item.get("template_url"):
        # An EPD flow also carries material properties (density, grammage, ...); the
        # target of a generic process is only its declared quantity, set to 1 unit.
        if item.get("declared_unit"):
            process.dec_unit = item["declared_unit"]
        if process.dec_unit not in DECLARED_UNITS:
            raise ValueError(
                f"Declared unit {process.dec_unit!r} is not supported "
                f"(template EPD {item['template']}); use one of {DECLARED_UNITS}."
            )
        process.material_kwargs = {
            k: (1.0 if k == process.dec_unit else None) for k in process.material_kwargs
        }
        process.material = Material(**process.material_kwargs)
    process.get_hs_class()
    if item.get("hs_class"):
        process.hs_class = str(item["hs_class"])
    process.get_market()
    process.matches = item["matches"]
    return process


def to_jsonable(obj: Any) -> Any:
    """Convert numpy scalars, tuples, sets and paths into JSON-compatible values."""
    return json.loads(json.dumps(obj, default=_json_default))


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "item"):  # numpy scalar
        return obj.item()
    if hasattr(obj, "tolist"):  # numpy array
        return obj.tolist()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    return str(obj)


def summarize_context(
    ctx: EpdPipelineContext, fetch_errors: dict[str, str] | None = None
) -> dict[str, Any]:
    """JSON-serializable summary of a pipeline context."""
    fetch_errors = fetch_errors or {}

    def pairs(items):
        return [
            {"uuid": u, "reason": fetch_errors.get(u, r) if isinstance(r, str) else r}
            for u, r in items
        ]

    matches = ctx.matches or {}
    requested = len(matches.get("uuids", [])) or len(matches.get("components", []))
    product = ((ctx.report or {}).get("meta") or {}).get("product") or {}
    return to_jsonable(
        {
            "uuid": ctx.process.uuid,
            "name": product.get("name"),
            "recipe_type": ctx.recipe_type,
            "success": pipeline_has_outputs(ctx),
            "declared_unit": ctx.active_dec_unit,
            "used_mass_fallback": ctx.used_mass_fallback,
            "location": ctx.process.loc,
            "hs_class": getattr(ctx.process, "hs_class", None),
            "requested": requested,
            "selected_epds": [e.uuid for e in ctx.filtered_epds],
            "missing_epds": pairs(ctx.missing_epds),
            "rejected_epds": pairs(ctx.rejected_epds),
            "unmatched_epds": pairs(ctx.unmatched_epds),
            "avg_properties": ctx.avg_properties,
            "avg_impacts": ctx.avg_gwps,
            "report": ctx.report,
            "outputs": ctx.outputs,
            "diagnostics": [
                *(
                    {"kind": "warning", "message": w, "stage": "generic-epd"}
                    for w in getattr(ctx.process, "warnings", [])
                ),
                *ctx.diagnostics,
            ],
        }
    )


def run_materia_from_url(
    spec: Any,
    output_path: Path | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Run the pipeline on EPDs fetched from a file server instead of local folders.

    `spec` is described in `normalize_url_spec`. The file server URL is taken from
    `base_url`, else `spec["base_url"]`, else `$MATERIA_EPD_BASE_URL`. Outputs
    (process/flow XML, JSON/PDF report) are written only when `output_path` is set.
    Returns ``{"base_url", "processes": [summary, ...], "fetch_errors"}``.
    """
    spec = normalize_url_spec(spec)
    source = UrlSource(
        resolve_base_url(base_url, spec.get("base_url")),
        processes_dir=spec.get("processes_dir", "xml"),
        flows_dir=spec.get("flows_dir", "flows"),
        timeout=float(spec.get("timeout", 60)),
    )
    items = spec["processes"]

    # Fetch every referenced EPD once (concurrently, with its reference flow)
    fetch_errors: dict[str, str] = {}
    required = list(
        dict.fromkeys(
            u for item in items for u in required_epd_uuids_for(item["matches"])
        )
    )
    epds = list(gen_epds_from_url(source, logger, required, errors=fetch_errors))
    fetched = {e.uuid for e in epds}

    # Build the generic skeletons (from a reference EPD unless a template URL is given)
    processes: list[IlcdProcess] = []
    failures: list[dict[str, Any]] = []
    for item in items:
        available = [u for u in required_epd_uuids_for(item["matches"]) if u in fetched]
        try:
            processes.append(_build_generic_process(source, item, available))
        except Exception as e:
            logger.warning("Generic skeleton failed", uuid=item["uuid"], error=str(e))
            failures.append(
                {
                    "uuid": item["uuid"],
                    "name": item.get("name"),
                    "recipe_type": item["matches"].get("type"),
                    "success": False,
                    "requested": len(required_epd_uuids_for(item["matches"])),
                    "error": f"Could not build the generic process skeleton: {e}",
                    "missing_epds": [
                        {"uuid": u, "reason": fetch_errors[u]}
                        for u in required_epd_uuids_for(item["matches"])
                        if u in fetch_errors
                    ],
                }
            )

    contexts = execute_processes(processes, epds, output_path)

    by_uuid = {f["uuid"]: f for f in failures}
    for uuid, ctx in contexts.items():
        summary = summarize_context(ctx, fetch_errors)
        item = next(i for i in items if i["uuid"] == uuid)
        summary["template"] = (
            "generic EPD JSON + templates"
            if item.get("generic")
            else item.get("template") or item.get("template_url")
        )
        summary["name"] = item.get("name") or summary["name"]
        by_uuid[uuid] = summary

    result = {
        "base_url": source.base_url,
        "processes": [by_uuid[i["uuid"]] for i in items if i["uuid"] in by_uuid],
        "fetch_errors": fetch_errors,
    }
    if output_path is not None:
        Path(output_path).mkdir(parents=True, exist_ok=True)
        with (Path(output_path) / "from_url_summary.json").open(
            "w", encoding="utf-8"
        ) as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    return result
