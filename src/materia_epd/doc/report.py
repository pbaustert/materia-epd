import json
from typing import Any, Dict, List, Tuple
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from pathlib import Path

from materia_epd.epd.models import IlcdProcess
from materia_epd.core.constants import QUANTITIES, PROPERTIES, PHYS_TITLES, METHOD_UUIDS
from materia_epd.doc.plots import physical_boxplots, gwp_boxplots
from materia_epd.doc.pages import (
    modular_summary_page,
    table_page,
    img_page,
    regression_model_page,
)
from materia_epd.doc.utils import get_report_data, build_impact_comparison_table


def build_report_json(
    report_uuid: str,
    process: IlcdProcess,
    epd_entries: List[IlcdProcess],
    avg_impacts: Dict[str, Dict[str, Any]],
    avg_physical: Dict[str, Any],
    initial_epds: int,
    selected_epds: int,
    rejected_epds: List[Tuple[str, List[str]]],
    mass_composition: dict[str, Any],
    regression_models: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    process.get_names()
    process.get_lcia_results()
    return {
        "meta": {
            "report_uuid": report_uuid,
            "generated_at": datetime.now(timezone.utc).date().isoformat(),
            "version": process.version,
            "pipeline": {
                "initial_epds": initial_epds,
                "selected_epds": selected_epds,
                "rejected_count": len(rejected_epds),
                "recipe_type": process.matches.get("type"),
            },
            "indicators": list(avg_impacts.keys()),
            "product": {
                "names_by_language": process.names,
                "hs_classification": process.hs_classes,
                "target_location": process.loc,
            },
            "market": process.market,
        },
        "epds": [
            {
                "epd_uuid": e.uuid,
                "physical": e.material.to_dict(),
                "impacts": e.lcia_results,
                "location": e.loc,
            }
            for e in epd_entries
        ],
        "components": process.matches.get("components", []),
        "average": {"physical": avg_physical, "impacts": avg_impacts},
        "mass_composition": mass_composition,
        "prior": {"impacts": {x["name"]: x["values"] for x in process.lcia_results}},
        "rejected": [{"epd_uuid": u, "reasons": r} for u, r in rejected_epds],
        "regression_models": regression_models,
    }


def draw_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    c, page_w, page_h = (
        canvas.Canvas(str(reports_dir / f"{report_uuid}.pdf"), pagesize=A4),
        *A4,
    )
    _, _, _, _, rt = get_report_data(report)
    modular_summary_page(c, page_w, page_h, report)
    if rt == "assembled":
        table_page(
            c,
            page_w,
            page_h,
            report["components"],
            [(40, "material"), (180, "function"), (420, "quantity"), (480, "unit")],
            "List of Components",
        )
    else:
        table_page(
            c,
            page_w,
            page_h,
            report["epds"],
            [
                (40, "uuid"),
                (240, "mass"),
                (300, "volume"),
                (360, "surface"),
                (420, "length"),
                (480, "unit_count"),
            ],
            "Overview of Input EPDs",
            get_row=lambda e: {**e["physical"], "uuid": e["epd_uuid"]},
        )
    img_page(
        c,
        page_h,
        "Physical Properties",
        physical_boxplots(QUANTITIES + PROPERTIES, PHYS_TITLES, report),
    )
    img_page(
        c,
        page_h,
        "Indicator Comparison",
        gwp_boxplots(list(METHOD_UUIDS.keys()), report),
    )
    table_page(
        c,
        page_w,
        page_h,
        build_impact_comparison_table(report).to_dict("records"),
        [(40, "indicator"), (240, "module"), (360, "prior"), (480, "posterior")],
        "Results Table",
    )
    if rt == "regression":
        regression_model_page(c, page_w, page_h, report)
    c.save()


def write_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    with (reports_dir / f"{report_uuid}.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
