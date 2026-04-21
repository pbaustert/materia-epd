from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MplPath
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from materia_epd.core.constants import NS
from materia_epd.epd.models import IlcdProcess
from materia_epd.geo.locations import get_location_attribute, get_location_color


def fit_image_in_box(reader, x0, y0, box_w, box_h):
    iw, ih = reader.getSize()
    aspect = iw / ih
    w, h = box_w, box_w / aspect
    if h > box_h:
        h = box_h
        w = h * aspect
    x = x0 + (box_w - w) / 2
    y = y0 + (box_h - h) / 2
    return x, y, w, h


def extract_product_metadata(
    process: IlcdProcess,
) -> tuple[str, dict[str, str], list[dict[str, str]]]:
    root = process.root

    XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

    # all base names by language
    base_names: dict[str, str] = {}
    for node in root.findall(".//ns0:name/ns0:baseName", NS):
        if node is None or not node.text or not node.text.strip():
            continue
        lang = node.attrib.get(XML_LANG, "").strip().lower() or "und"
        base_names[lang] = node.text.strip()

    # preferred single name
    name = next(
        (text for lang, text in base_names.items() if lang.startswith("fr")),
        None,
    ) or next(iter(base_names.values()), "Unknown product")

    # HS classification only
    hs_classes: list[dict[str, str]] = []
    for classification in root.findall(".//common:classification", NS):
        cname = (classification.attrib.get("name") or "").strip().lower()
        if cname != "hs classification":
            continue

        for cls in classification.findall("common:class", NS):
            hs_classes.append(
                {
                    "level": (cls.attrib.get("level") or "").strip(),
                    "class_id": (cls.attrib.get("classId") or "").strip(),
                    "text": (cls.text or "").strip(),
                }
            )

    return name, dict(base_names), hs_classes


def flatten_impacts(impacts: list[dict]) -> dict:
    row = {}
    for imp in impacts:
        n, v = imp["name"], imp["values"]
        row[f"{n}_A1-A3"] = v.get("A1-A3") or 0
        row[f"{n}_A4"] = v.get("A4") or 0
        row[f"{n}_C1234"] = sum(v.get(k) or 0 for k in ("C1", "C2", "C3", "C4"))
        row[f"{n}_D"] = v.get("D") or 0
    return row


def detect_declared_unit(avg_physical: dict) -> str | None:
    labels = {
        "mass": "mass",
        "volume": "volume",
        "surface": "surface",
        "length": "length",
        "unit_count": "unit count",
    }
    return next(
        (
            labels[k]
            for k in labels
            if avg_physical.get(k) is not None and abs(avg_physical[k] - 1.0) < 1e-9
        ),
        None,
    )


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_impact_comparison_table(report: Dict[str, Any]) -> pd.DataFrame:
    prev, cur = report.get("previous", {}).get("impacts", {}), report.get(
        "average", {}
    ).get("impacts", {})
    rows = []
    indicators = sorted(set(prev) | set(cur))
    module_order = ["A1-A3", "A4", "C1", "C2", "C3", "C4", "D"]
    for ind in indicators:
        pv = prev.get(ind, {})
        cv = cur.get(ind, {})
        modules = set(pv) | set(cv) | {"A4"}
        sorted_modules = sorted(
            modules,
            key=lambda m: (
                (module_order.index(m), m) if m in module_order else (999, m)
            ),
        )
        for mod in sorted_modules:
            p = as_float(prev.get(ind, {}).get(mod), default=0.0)
            c = as_float(cv.get(mod), default=0.0)
            rows.append(
                {
                    "Indicator": ind,
                    "Module": mod,
                    "Previous": p,
                    "Current": c,
                    "RelativeChange": 0.0
                    if abs(p) <= 1e-12
                    else ((c - p) / abs(p)),
                    "Direction": "no-change"
                    if abs(c - p) <= 1e-12
                    else ("increase" if c > p else "decrease"),
                }
            )
    return pd.DataFrame(rows)


def draw_market_structure_sankey(report: Dict[str, Any], output_png: str) -> str | None:
    market = report.get("meta", {}).get("market", {})
    if not market:
        return None

    items = sorted(market.items(), key=lambda kv: kv[1], reverse=True)
    vals = [v for _, v in items]
    top, bottom, gap = 0.90, 0.10, 0.020
    scale = (top - bottom - gap * (len(vals) - 1)) / sum(vals)
    heights, tops, y = [v * scale for v in vals], [], top
    for h in heights:
        tops.append(y)
        y -= h + gap

    fig, ax = plt.subplots(figsize=(11, 6), dpi=240)
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    lx, rx, w = 0.16, 0.82, 0.026
    sink, cursor = sum(heights), 0.5 + sum(heights) / 2

    def ribbon(x0, x1, y0t, y0b, y1t, y1b, color):
        c1, c2 = x0 + 0.37 * (x1 - x0), x1 - 0.37 * (x1 - x0)
        v = [
            (x0, y0t),
            (c1, y0t),
            (c2, y1t),
            (x1, y1t),
            (x1, y1b),
            (c2, y1b),
            (c1, y0b),
            (x0, y0b),
            (x0, y0t),
        ]
        ax.add_patch(
            PathPatch(
                MplPath(v, [1, 4, 4, 4, 2, 4, 4, 4, 79]),
                facecolor=color,
                edgecolor="none",
            )
        )

    def box(x, y0, bw, bh, color):
        ax.add_patch(
            FancyBboxPatch(
                (x, y0),
                bw,
                bh,
                boxstyle="round,pad=0,rounding_size=0.004",
                facecolor=color,
                edgecolor="none",
            )
        )

    for (loc, _), h, t in zip(items, heights, tops):
        b, t2 = t - h, cursor
        cursor -= h
        ribbon(
            lx + w,
            rx,
            t,
            b,
            t2,
            cursor,
            get_location_color(loc).get("rgba") or [0.5, 0.5, 0.5, 0.25],
        )

    for (loc, share), h, t in zip(items, heights, tops):
        box(lx, t - h, w, h, get_location_color(loc).get("hex") or "#6B7280")
        ax.text(
            lx - 0.02,
            t - h / 2,
            f"{get_location_attribute(loc, 'ISO3') or loc}  {share:.1%}",
            ha="right",
            va="center",
            fontsize=10.5,
            color="#222222",
        )

    p = report.get("meta", {}).get("product", {})
    target = p.get("target_location")
    box(rx, 0.5 - sink / 2, w, sink, "#A9A9A9")
    ax.text(
        rx + 0.03,
        0.5,
        f"{get_location_attribute(target, 'ISO3')} market",
        va="center",
        fontsize=12.5,
        color="#1f2937",
    )
    plt.savefig(output_png, bbox_inches="tight", dpi=240, facecolor="white")
    plt.close(fig)
    return output_png


def build_report(
    report_uuid: str,
    process: IlcdProcess,
    epd_entries: List[IlcdProcess],
    avg_impacts: Dict[str, Dict[str, Any]],
    avg_physical: Dict[str, Any],
    initial_epds: int,
    selected_epds: int,
    rejected_epds: Optional[List[Tuple[str, List[str]]]] = None,
) -> Dict[str, Any]:
    rejected_epds = rejected_epds or []
    name, base_names, hs_classes = extract_product_metadata(process)
    process.get_lcia_results()
    report = {
        "meta": {
            "report_uuid": report_uuid,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline": {
                "initial_epds": initial_epds,
                "selected_epds": selected_epds,
                "rejected_count": len(rejected_epds),
                "recipe_type": process.matches.get("type"),
            },
            "indicators": list(avg_impacts.keys()),
            "product": {
                "name": name,
                "names_by_language": base_names,
                "hs_classification": hs_classes,
                "categories": [x["text"] or x["class_id"] for x in hs_classes],
                "hs_code": hs_classes[-1]["class_id"]
                if hs_classes
                else process.hs_class,
                "target_location": process.loc,
            },
            "market": process.market,
        },
        "epds": [
            {
                "epd_uuid": e.uuid,
                "physical": e.material.to_dict(),
                "impacts": e.lcia_results,
            }
            for e in epd_entries
        ],
        "average": {"physical": avg_physical, "impacts": avg_impacts},
        "previous": {"impacts": {x["name"]: x["values"] for x in process.lcia_results}},
        "rejected": [{"epd_uuid": u, "reasons": r} for (u, r) in rejected_epds],
    }
    return report


def fit_image_in_box_top(reader, x0, top_y, box_w, box_h):
    iw, ih = reader.getSize()
    aspect = iw / ih
    w, h = box_w, box_w / aspect
    if h > box_h:
        h = box_h
        w = h * aspect
    x = x0 + (box_w - w) / 2
    y = top_y - h
    return x, y, w, h


def draw_wrapped_text(c, text, x, y, max_width, line_height=12):
    words = text.split()
    lines, current = [], ""

    for w in words:
        test = f"{current} {w}".strip()
        if c.stringWidth(test, "Helvetica", 11) <= max_width:
            current = test
        else:
            lines.append(current)
            current = w
    if current:
        lines.append(current)

    for line in lines:
        c.drawString(x, y, line)
        y -= line_height

    return y


def draw_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    c, page_w, page_h = (
        canvas.Canvas(str(reports_dir / f"{report_uuid}.pdf"), pagesize=A4),
        *A4,
    )

    def fit_image(reader, margin=40, y_offset=0):
        iw, ih = reader.getSize()
        aspect = iw / ih
        mw, mh = page_w - 2 * margin, page_h - 2 * margin
        w, h = mw, mw / aspect
        if h > mh:
            h, w = mh, mh * aspect
        return (page_w - w) / 2, (page_h - h) / 2 + y_offset, w, h

    def img_page(title, path, centered=True, y_offset=0):
        c.setFont("Helvetica-Bold", 16)
        (c.drawCentredString if centered else c.drawString)(
            page_w / 2 if centered else 40,
            page_h - 20 if centered else page_h - 40,
            title,
        )
        r = ImageReader(path)
        x, y, w, h = fit_image(r, y_offset=y_offset)
        c.drawImage(
            path, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto"
        )
        c.showPage()

    def save_fig(fig):
        path = tempfile.mktemp(".png")
        fig.savefig(path, bbox_inches="tight", dpi=120)
        plt.close(fig)
        return path

    df = pd.DataFrame(
        [
            {"epd_uuid": e["epd_uuid"], **flatten_impacts(e["impacts"])}
            for e in report["epds"]
        ]
    )
    df_avg = pd.DataFrame(
        [
            flatten_impacts(
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
    declared_unit = detect_declared_unit(report["average"]["physical"])

    def impact_series(frame: pd.DataFrame, column: str) -> pd.Series:
        if column not in frame:
            return pd.Series(dtype=float)
        return frame[column].dropna()

    p = report["meta"]["pipeline"]
    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.bar(["Initial"], [p["initial_epds"]], color="#4C78A8", label="Initial")
    ax.bar(["Processed"], [p["selected_epds"]], color="#2ECC71", label="Selected")
    ax.bar(
        ["Processed"],
        [p["initial_epds"] - p["selected_epds"]],
        bottom=[p["selected_epds"]],
        color="#E74C3C",
        label="Rejected",
    )
    ax.set_title("EPD Processing Summary")
    ax.set_ylabel("Count")
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.legend(fontsize=8)

    process_img = save_fig(fig)
    sankey_img = draw_market_structure_sankey(report, tempfile.mktemp(".png"))

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 40, "EPD Averaging Summary")

    pm = report.get("meta", {}).get("product", {})
    hs_classes = pm.get("hs_classification") or []

    cats = [
        f"{x.get('class_id', '').strip()}  {x.get('text', '').strip()}".strip()
        for x in hs_classes
        if x.get("class_id") or x.get("text")
    ]

    # ---- top text block ----
    c.setFont("Helvetica", 11)
    c.drawString(40, page_h - 62, f"Product: {pm.get('name', 'Unknown')}")
    product_names = pm.get("names_by_language", {}) or {}

    def _format_lang_name(lang: str) -> str:
        for key, value in product_names.items():
            if key.lower().startswith(lang):
                return value
        return "n/a"

    c.drawString(40, page_h - 78, "Product names:")
    c.drawString(60, page_h - 94, f"EN: {_format_lang_name('en')}")
    c.drawString(60, page_h - 110, f"FR: {_format_lang_name('fr')}")
    c.drawString(60, page_h - 126, f"DE: {_format_lang_name('de')}")
    c.drawString(40, page_h - 142, f"HS code: {pm.get('hs_code', 'n/a')}")
    c.drawString(40, page_h - 158, "HS Categories:")

    y = page_h - 172
    c.setFont("Helvetica", 9)

    max_cat_lines = 4
    for i, cat in enumerate(cats or ["n/a"]):
        if i >= max_cat_lines:
            c.drawString(40, y, "...")
            y -= 11
            break
        y = draw_wrapped_text(
            c,
            cat,
            40,
            y,
            max_width=page_w - 80,
            line_height=11,
        )
        y -= 1

    # ---- dynamic layout below text ----
    gap = 14
    section_title_gap = 14
    usable_bottom = 35

    remaining_h = y - gap - usable_bottom
    top_box_h = remaining_h * 0.52
    bottom_box_h = remaining_h * 0.48

    # middle section
    y -= gap
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "EPD Processing")
    y -= section_title_gap

    r1 = ImageReader(process_img)
    x1, y1, w1, h1 = fit_image_in_box_top(
        r1, 40, y, page_w - 80, top_box_h - section_title_gap
    )
    c.drawImage(r1, x1, y1, width=w1, height=h1, preserveAspectRatio=True, mask="auto")
    y = y1 - gap

    # bottom section
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Market")
    y -= section_title_gap

    if sankey_img:
        r2 = ImageReader(sankey_img)
        x2, y2, w2, h2 = fit_image_in_box_top(
            r2, 40, y, page_w - 80, bottom_box_h - section_title_gap
        )
        c.drawImage(
            r2, x2, y2, width=w2, height=h2, preserveAspectRatio=True, mask="auto"
        )

    c.showPage()

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 40, "Overview of Input EPDs")

    y = page_h - 72
    row_h = 14

    def draw_epd_table_header(y):
        c.setFont("Helvetica", 9)
        c.drawString(40, y, "EPD UUID")
        c.drawString(240, y, "Mass [kg]")
        c.drawString(300, y, "Volume [m³]")
        c.drawString(360, y, "Surface [m²]")
        c.drawString(420, y, "Length [m]")
        c.drawString(480, y, "Unit count")
        y -= 10
        c.line(40, y, page_w - 40, y)
        return y - 12

    y = draw_epd_table_header(y)

    for e in report["epds"]:
        if y < 60:
            c.showPage()
            c.setFont("Helvetica-Bold", 16)
            c.drawString(40, page_h - 40, "Overview of Input EPDs")
            y = draw_epd_table_header(page_h - 72)

        phys = e["physical"]
        c.setFont("Helvetica", 8)
        c.drawString(40, y, str(e["epd_uuid"])[:32])
        c.drawRightString(
            280, y, "-" if phys.get("mass") is None else f"{phys['mass']:.4g}"
        )
        c.drawRightString(
            340, y, "-" if phys.get("volume") is None else f"{phys['volume']:.4g}"
        )
        c.drawRightString(
            400, y, "-" if phys.get("surface") is None else f"{phys['surface']:.4g}"
        )
        c.drawRightString(
            460, y, "-" if phys.get("length") is None else f"{phys['length']:.4g}"
        )
        c.drawRightString(
            520,
            y,
            "-" if phys.get("unit_count") is None else f"{phys['unit_count']:.4g}",
        )
        y -= row_h

    c.showPage()

    fields = [
        "mass",
        "volume",
        "surface",
        "length",
        "unit_count",
        "gross_density",
        "grammage",
        "linear_density",
        "layer_thickness",
        "cross_sectional_area",
        "weight_per_piece",
    ]
    titles = {
        "mass": "Mass [kg]",
        "volume": "Volume [m^3]",
        "surface": "Surface [m^2]",
        "length": "Length [m]",
        "unit_count": "Unit count [unit]",
        "gross_density": "Gross density [kg/m^3]",
        "grammage": "Grammage [kg/m^2]",
        "linear_density": "Linear density [kg/m]",
        "layer_thickness": "Layer thickness [m]",
        "cross_sectional_area": "Cross-sectional area [m^2]",
        "weight_per_piece": "Weight per piece [kg]",
    }
    fig, axes = plt.subplots(3, 4, figsize=(10, 8))
    axes = axes.flatten()
    for ax, f in zip(axes[:11], fields):
        vals, avg = df_phys[f].dropna(), df_phys_avg[f].iloc[0]
        if len(vals) > 0:
            if vals.nunique() > 1:
                ax.boxplot([vals], positions=[1], widths=0.5)
            if pd.notna(avg):
                ax.scatter([1], [avg], color="red", s=35, zorder=3)
        ax.set_title(titles[f], fontsize=9)
        ax.set_xticks([1])
        ax.set_xticklabels([""])
        ax.grid(axis="y", linestyle="--", alpha=0.25)
        ax.tick_params(axis="y", labelsize=8)
    axes[11].axis("off")
    txt = (
        f"Declared unit appears to be based on {declared_unit}, because the average {declared_unit} equals 1."  # noqa: E501
        if declared_unit
        else "Declared unit could not be identified clearly."
    )
    axes[11].text(0.0, 0.8, txt, ha="left", va="top", fontsize=10, wrap=True)
    fig.legend(
        handles=[
            Line2D(
                [0],
                [0],
                color="red",
                marker="o",
                linestyle="None",
                markersize=6,
                label="Average",
            )
        ],
        loc="upper center",
        frameon=False,
        bbox_to_anchor=(0.5, 0.99),
    )
    fig.tight_layout(rect=[0.03, 0.03, 0.97, 0.95])
    img_page("Physical Properties and Declared Unit", save_fig(fig))

    inds = [
        "Climate change-Total",
        "Climate change-Fossil",
        "Climate change-Biogenic",
        "Climate change-Land use and land use change",
    ]
    names = {
        "Climate change-Total": "GWP total",
        "Climate change-Fossil": "GWP fossil",
        "Climate change-Biogenic": "GWP biogenic",
        "Climate change-Land use and land use change": "GWP luluc",
    }
    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    axes = axes.flatten()
    for ax, ind in zip(axes, inds):
        cols = [f"{ind}_A1-A3", f"{ind}_A4", f"{ind}_C1234", f"{ind}_D"]
        vals = []
        for c in cols:
            series = impact_series(df, c)
            avg_value = df_avg[c].iloc[0] if c in df_avg else 0.0
            # A4 can be derived at aggregate level and may not exist in source EPD rows.
            # In that case, show the derived aggregate value in the plot instead of a zero-only box.
            if c.endswith("_A4") and (
                len(series) == 0 or (series.abs() <= 1e-12).all()
            ) and abs(avg_value) > 1e-12:
                series = pd.Series([avg_value])
            vals.append(series)
        box_vals = [v for v in vals if len(v) > 0]
        box_pos = [p for p, v in zip([1, 3, 5, 7], vals) if len(v) > 0]
        if box_vals:
            ax.boxplot(box_vals, positions=box_pos, widths=0.6)
        ax.scatter(
            [1, 3, 5, 7],
            [df_avg[c].iloc[0] if c in df_avg else 0.0 for c in cols],
            color="red",
            s=40,
            zorder=3,
        )
        ax.set_xticks([1, 3, 5, 7])
        ax.set_xticklabels(["A1–A3", "A4", "C1–C4", "D"])
        ax.set_title(names[ind], fontsize=10)
        ax.set_ylabel("kg CO₂e per declared unit", fontsize=8)
        ax.grid(axis="y", linestyle="--", alpha=0.25)
    fig.legend(
        handles=[
            Line2D(
                [0],
                [0],
                color="red",
                marker="o",
                linestyle="None",
                markersize=6,
                label="Average",
            )
        ],
        loc="upper center",
        frameon=False,
        bbox_to_anchor=(0.5, 0.99),
    )
    fig.tight_layout(rect=[0.05, 0.03, 0.95, 0.95])
    img_page("Indicator Comparison", save_fig(fig))

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 40, "Averaging Method and Results Table")
    method = (
        "Method: market-weighted averaging. Country-level averages are combined using market share weights for the product HS code."  # noqa: E501
        if report.get("meta", {}).get("pipeline", {}).get("recipe_type")
        == "market-average"
        else "Method: arithmetic averaging. Matching EPDs are averaged with equal weight for each indicator and module."  # noqa: E501
    )
    c.setFont("Helvetica", 10)
    t = c.beginText(40, page_h - 62)
    for line in method.split(". "):
        t.textLine(line.strip() + ("." if not line.endswith(".") else ""))
    c.drawText(t)

    headers, xcols = ["Indicator", "Module", "Previous", "Current", "Change"], [
        40,
        230,
        290,
        360,
        445,
    ]

    def draw_headers(y0):
        for xh, hname in zip(xcols, headers):
            c.drawString(xh, y0, hname)
        c.line(40, y0 - 8, page_w - 40, y0 - 8)
        return y0 - 22

    y = draw_headers(page_h - 120)
    for _, row in build_impact_comparison_table(report).iterrows():
        if y < 50:
            c.showPage()
            c.setFont("Helvetica-Bold", 16)
            c.drawString(40, page_h - 40, "Averaging Method and Results Table (cont.)")
            c.setFont("Helvetica", 10)
            y = draw_headers(page_h - 72)
        c.drawString(40, y, str(row["Indicator"])[:33])
        c.drawString(230, y, str(row["Module"]))
        c.drawRightString(342, y, f"{row['Previous']:.3g}")
        c.drawRightString(420, y, f"{row['Current']:.3g}")
        rel_change = float(row.get("RelativeChange", 0.0))
        if abs(row["Current"] - row["Previous"]) <= 1e-12:
            icon, color = "→", "#6B7280"
        elif row["Current"] > row["Previous"]:
            icon = "↑"
            color = "#DC2626" if rel_change > 0.1 else "#F59E0B"
        else:
            icon = "↓"
            color = "#16A34A" if rel_change < -0.1 else "#10B981"
        c.setFillColor(HexColor(color))
        c.drawString(445, y, icon)
        c.setFillColor(HexColor("#000000"))
        y -= 14
    c.save()


def write_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    with (reports_dir / f"{report_uuid}.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
