from typing import Any, Dict
from materia_epd.core.constants import QUANTITIES, PHYS_TITLES, LCIA_OUTPUT_MODULES
from materia_epd.core.utils import to_float
import pandas as pd
import numpy as np


def _flatten_impacts(impacts: list[dict]) -> dict:
    row = {}
    for i in impacts:
        n, v = i["name"], i["values"]
        row.update(
            {
                f"{n}_A1-A3": v.get("A1-A3") or 0,
                f"{n}_A4": v.get("A4") or 0,
                f"{n}_C1-C4": sum(v.get(k) or 0 for k in ("C1", "C2", "C3", "C4")),
                f"{n}_D": v.get("D") or 0,
            }
        )
    return row


def get_report_data(report: Dict[str, Any]):
    df = pd.DataFrame(
        [
            {"epd_uuid": e["epd_uuid"], **_flatten_impacts(e["impacts"])}
            for e in report["epds"]
        ]
    )
    df_avg = pd.DataFrame(
        [
            _flatten_impacts(
                [
                    {"name": n, "values": v}
                    for n, v in report["average"]["impacts"].items()
                ]
            )
        ]
    )
    df_phys = pd.DataFrame(
        [{"epd_uuid": e["epd_uuid"], **e["physical"]} for e in report["epds"]]
    )
    df_phys_avg = pd.DataFrame([report["average"]["physical"]])
    rt = report["meta"]["pipeline"]["recipe_type"]
    return df, df_avg, df_phys, df_phys_avg, rt


def detect_declared_unit(avg_physical: dict) -> str | None:
    for key in QUANTITIES:
        value = avg_physical.get(key)
        if value is not None and abs(value - 1.0) < 1e-9:
            return PHYS_TITLES[key]
    return None


def format_value(value):
    if value is None:
        return "-"
    else:
        try:
            return "-" if np.isnan(value) else f"{float(value):.2e}"
        except (TypeError, ValueError):
            return str(value)


def draw_header(c, y, cols, page_w, line_y_offset=8):
    c.setFont("Helvetica", 9)
    for x, h in cols:
        c.drawString(x, y, h)
    c.line(40, y - line_y_offset, page_w - 40, y - line_y_offset)
    return y - 22


def build_impact_comparison_table(report: Dict[str, Any]) -> pd.DataFrame:
    prior, posterior = report.get("prior", {}).get("impacts", {}), report.get(
        "average", {}
    ).get("impacts", {})
    rows, modules = [], LCIA_OUTPUT_MODULES.copy()
    modules.insert(1, "A4")
    for ind in sorted(set(prior) | set(posterior)):
        pv, nv = prior.get(ind, {}), posterior.get(ind, {})
        for mod in sorted(
            set(pv) | set(nv) | {"A4", "C1", "C2"}, key=lambda m: (modules.index(m), m)
        ):
            rows.append(
                {
                    "indicator": ind,
                    "module": mod,
                    "prior": to_float(pv.get(mod), default=0.0),
                    "posterior": to_float(nv.get(mod), default=0.0),
                }
            )
    return pd.DataFrame(rows)


def increment_version(version: str, part: str = "patch") -> str:
    major, minor, patch = version.split(".")
    if part == "major":
        return f"{str(int(major)+1).zfill(2)}.00.000"
    elif part == "minor":
        return f"{major}.{str(int(minor)+1).zfill(2)}.000"
    else:
        return f"{major}.{minor}.{str(int(patch)+1).zfill(3)}"
