from __future__ import annotations
import json
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import PathPatch, FancyBboxPatch
from matplotlib.path import Path as MplPath
import tempfile
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from materia_epd.epd.models import IlcdProcess
from materia_epd.geo.locations import get_location_attribute, get_location_color


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
    """
    Build the report. If `rejected_epds` is provided, it will include:
      - pipeline.rejected_epds
      - pipeline.rejected_count
      - a 'rejected' array with items { epd_uuid, reasons }
    """
    rejected_epds = rejected_epds or []

    process_name = (
        process.matches.get("name")
        or process.matches.get("product_name")
        or process.matches.get("product")
        or "Unknown product"
    )
    categories = (
        process.matches.get("categories")
        or process.matches.get("product_categories")
        or []
    )
    process.get_lcia_results()
    previous_impacts = {x["name"]: x["values"] for x in process.lcia_results}

    report: Dict[str, Any] = {
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
                "name": process_name,
                "categories": categories,
                "hs_code": process.hs_class,
                "target_location": process.loc,
            },
            "market": process.market,
        },
        "epds": [],
        "average": {
            "physical": avg_physical,
            "impacts": avg_impacts,
        },
        "previous": {"impacts": previous_impacts},
        "rejected": [
            {"epd_uuid": uuid, "reasons": reasons} for (uuid, reasons) in rejected_epds
        ],
    }

    for epd in epd_entries:
        report["epds"].append(
            {
                "epd_uuid": epd.uuid,
                "physical": epd.material.to_dict(),
                "impacts": epd.lcia_results,
            }
        )

    return report


def _direction(prev_value: float, new_value: float, tolerance: float = 1e-12) -> str:
    delta = new_value - prev_value
    if abs(delta) <= tolerance:
        return "no-change"
    return "increase" if delta > 0 else "decrease"


def _build_impact_comparison_table(report: Dict[str, Any]) -> pd.DataFrame:
    previous = report.get("previous", {}).get("impacts", {})
    current = report.get("average", {}).get("impacts", {})

    rows = []
    for indicator, curr_values in current.items():
        prev_values = previous.get(indicator, {})
        for module in sorted(set(prev_values) | set(curr_values)):
            prev_value = float(prev_values.get(module, 0.0))
            curr_value = float(curr_values.get(module, 0.0))
            rows.append(
                {
                    "Indicator": indicator,
                    "Module": module,
                    "Previous": prev_value,
                    "Current": curr_value,
                    "Delta": curr_value - prev_value,
                    "Direction": _direction(prev_value, curr_value),
                }
            )
    return pd.DataFrame(rows)


def _draw_market_structure_sankey(report: Dict[str, Any], output_png: str):
    market = report.get("meta", {}).get("market", {})
    if not market:
        return None

    items = sorted(market.items(), key=lambda kv: kv[1], reverse=True)
    fig, ax = plt.subplots(figsize=(11, 6), dpi=240)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    left_x, right_x = 0.16, 0.82
    node_w = 0.026

    values = [v for _, v in items]
    top, bottom = 0.90, 0.10
    gap = 0.020
    avail = top - bottom - gap * (len(values) - 1)
    scale = avail / sum(values)
    heights = [v * scale for v in values]

    tops = []
    y = top
    for h in heights:
        tops.append(y)
        y -= h + gap

    sink_total = sum(heights)
    sink_top = 0.5 + sink_total / 2
    cursor = sink_top

    def ribbon(x0, x1, y0t, y0b, y1t, y1b, color):
        c1 = x0 + 0.37 * (x1 - x0)
        c2 = x1 - 0.37 * (x1 - x0)
        verts = [
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
        codes = [1, 4, 4, 4, 2, 4, 4, 4, 79]
        ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=color, edgecolor="none"))

    def rounded_box(x, y, w, h, fc):
        ax.add_patch(
            FancyBboxPatch(
                (x, y),
                w,
                h,
                boxstyle="round,pad=0,rounding_size=0.004",
                facecolor=fc,
                edgecolor="none",
            )
        )

    for (loc, _), h, t in zip(items, heights, tops):
        b = t - h
        t2 = cursor
        b2 = t2 - h
        cursor = b2
        color = get_location_color(loc).get("rgba") or [0.5, 0.5, 0.5, 0.25]
        ribbon(left_x + node_w, right_x, t, b, t2, b2, color)

    for (loc, share), h, t in zip(items, heights, tops):
        loc_hex = get_location_color(loc).get("hex") or "#6B7280"
        rounded_box(left_x, t - h, node_w, h, loc_hex)
        yc = t - h / 2
        name = get_location_attribute(loc, "Name") or loc
        ax.text(
            left_x - 0.02,
            yc,
            f"{name}  {share:.1%}",
            ha="right",
            va="center",
            fontsize=10.5,
            color="#222222",
        )

    import_country = report.get("meta", {}).get("product", {}).get("name", "Product")
    target_loc = report.get("meta", {}).get("product", {}).get("target_location")
    target_name = get_location_attribute(target_loc, "Name") or "Target market"
    target_hex = get_location_color(target_loc).get("hex") or "#00A1DE"
    rounded_box(right_x, 0.5 - sink_total / 2, node_w, sink_total, target_hex)
    ax.text(
        right_x + 0.03,
        0.5,
        f"{target_name} market ({import_country})",
        va="center",
        fontsize=12.5,
        color="#1f2937",
    )

    plt.savefig(output_png, bbox_inches="tight", dpi=240, facecolor="white")
    plt.close(fig)
    return output_png


def draw_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    file_path = reports_dir / f"{report_uuid}.pdf"

    def fit_image(reader, page_w, page_h, margin=40, y_offset=0):
        img_w, img_h = reader.getSize()
        aspect = img_w / img_h
        max_w = page_w - 2 * margin
        max_h = page_h - 2 * margin
        w = max_w
        h = w / aspect
        if h > max_h:
            h = max_h
            w = h * aspect
        x = (page_w - w) / 2
        y = (page_h - h) / 2 + y_offset
        return x, y, w, h

    def flatten_impacts(impacts):
        row = {}
        for imp in impacts:
            name = imp["name"]
            values = imp["values"]
            row[f"{name}_A1-A3"] = values.get("A1-A3") or 0
            row[f"{name}_C1234"] = sum(
                values.get(k) or 0 for k in ("C1", "C2", "C3", "C4")
            )
            row[f"{name}_D"] = values.get("D") or 0
        return row

    def detect_declared_unit(avg_physical):
        qty_labels = {
            "mass": "mass",
            "volume": "volume",
            "surface": "surface",
            "length": "length",
            "unit_count": "unit count",
        }

        for key in ("mass", "volume", "surface", "length", "unit_count"):
            value = avg_physical.get(key)
            if value is not None and abs(value - 1.0) < 1e-9:
                return qty_labels[key]
        return None

    # ---------------------- Extract impacts ----------------------
    df = pd.DataFrame(
        [
            {"epd_uuid": epd["epd_uuid"], **flatten_impacts(epd["impacts"])}
            for epd in report["epds"]
        ]
    )
    df_avg = pd.DataFrame(
        [
            flatten_impacts(
                [
                    {"name": name, "values": values}
                    for name, values in report["average"]["impacts"].items()
                ]
            )
        ]
    )

    # ---------------------- Extract physical data ----------------------
    physical_fields = [
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

    physical_titles = {
        "mass": "Mass",
        "volume": "Volume",
        "surface": "Surface",
        "length": "Length",
        "unit_count": "Unit count",
        "gross_density": "Gross density",
        "grammage": "Grammage",
        "linear_density": "Linear density",
        "layer_thickness": "Layer thickness",
        "cross_sectional_area": "Cross-sectional area",
        "weight_per_piece": "Weight per piece",
    }

    units_titles = {
        "mass": "kg",
        "length": "m",
        "surface": "m^2",
        "volume": "m^3",
        "unit_count": "unit",
        "gross_density": "kg/m^3",
        "grammage": "kg/m^2",
        "linear_density": "kg/m",
        "layer_thickness": "m",
        "cross_sectional_area": "m^2",
        "weight_per_piece": "kg",
    }

    df_phys = pd.DataFrame(
        [{"epd_uuid": epd["epd_uuid"], **epd["physical"]} for epd in report["epds"]]
    )
    df_phys_avg = pd.DataFrame([report["average"]["physical"]])

    declared_unit = detect_declared_unit(report["average"]["physical"])

    # ---------------------- Simple pipeline chart ----------------------
    p = report["meta"]["pipeline"]
    rejected_count = p["initial_epds"] - p["selected_epds"]

    fig, ax = plt.subplots(figsize=(6, 4))

    ax.bar(["Initial"], [p["initial_epds"]], color="#4C78A8", label="Initial")
    ax.bar(["Processed"], [p["selected_epds"]], color="#2ECC71", label="Selected")
    ax.bar(
        ["Processed"],
        [rejected_count],
        bottom=[p["selected_epds"]],
        color="#E74C3C",
        label="Rejected",
    )

    ax.set_title("EPD Matching Summary")
    ax.set_ylabel("Count")
    ax.grid(axis="y", linestyle="--", alpha=0.25)
    ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
    ax.legend()

    stacked_img = tempfile.mktemp(".png")
    fig.savefig(stacked_img, bbox_inches="tight", dpi=120)
    plt.close(fig)

    # ---------------------- PDF ----------------------
    c = canvas.Canvas(str(file_path), pagesize=A4)
    page_w, page_h = A4

    # Page 1
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 40, "EPD Averaging Summary")
    c.setFont("Helvetica", 11)
    product_meta = report.get("meta", {}).get("product", {})
    categories = ", ".join(product_meta.get("categories") or []) or "n/a"
    c.drawString(40, page_h - 62, f"Product: {product_meta.get('name', 'Unknown')}")
    c.drawString(40, page_h - 78, f"HS code: {product_meta.get('hs_code', 'n/a')}")
    c.drawString(40, page_h - 94, f"Categories: {categories}")

    reader = ImageReader(stacked_img)
    x, y, w, h = fit_image(reader, page_w, page_h, margin=40, y_offset=-50)
    c.drawImage(
        stacked_img, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto"
    )
    c.showPage()

    # ---------------------- Input EPD overview page ----------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 40, "Overview of Input EPDs")
    c.setFont("Helvetica", 10)
    y = page_h - 72
    c.drawString(40, y, "EPD UUID")
    c.drawString(340, y, "Mass [kg]")
    c.drawString(430, y, "Volume [m³]")
    y -= 12
    c.line(40, y, page_w - 40, y)
    y -= 14
    for epd in report["epds"][:28]:
        c.drawString(40, y, str(epd["epd_uuid"])[:48])
        mass = epd["physical"].get("mass")
        volume = epd["physical"].get("volume")
        c.drawRightString(400, y, "-" if mass is None else f"{mass:.4g}")
        c.drawRightString(500, y, "-" if volume is None else f"{volume:.4g}")
        y -= 16
        if y < 60:
            break
    c.showPage()

    # ---------------------- Market structure (Sankey) ----------------------
    sankey_img = tempfile.mktemp(".png")
    if _draw_market_structure_sankey(report, sankey_img):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, page_h - 40, "Market Structure (Sankey)")
        reader_market = ImageReader(sankey_img)
        x, y, w, h = fit_image(reader_market, page_w, page_h, margin=40)
        c.drawImage(
            sankey_img, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto"
        )
        c.showPage()

    # ---------------------- Physical data page ----------------------
    fig, axes = plt.subplots(3, 4, figsize=(10, 8))
    axes = axes.flatten()

    for ax, field in zip(axes[:11], physical_fields):
        values = df_phys[field].dropna()
        avg_value = df_phys_avg[field].iloc[0]

        # --- draw boxplot + average marker ---
        if len(values) > 0:
            vals = values.dropna()
            if vals.nunique() > 1:
                ax.boxplot([vals], positions=[1], widths=0.5)

            if pd.notna(avg_value):
                ax.scatter([1], [avg_value], color="red", s=35, zorder=3)

        # --- title with units ---
        title = physical_titles[field]
        unit = units_titles.get(field)

        if unit:
            title = f"{title} [{unit}]"

        ax.set_title(title, fontsize=9)
        ax.set_xticks([1])
        ax.set_xticklabels([""])
        ax.grid(axis="y", linestyle="--", alpha=0.25)
        ax.tick_params(axis="y", labelsize=8)

    # last panel for declared unit text
    axes[11].axis("off")
    declared_unit_text = (
        f"Declared unit appears to be based on {declared_unit}, "
        f"because the average {declared_unit} equals 1."
        if declared_unit
        else "Declared unit could not be identified clearly."
    )
    axes[11].text(
        0.0,
        0.8,
        declared_unit_text,
        ha="left",
        va="top",
        fontsize=10,
        wrap=True,
    )

    avg_proxy = Line2D(
        [0],
        [0],
        color="red",
        marker="o",
        linestyle="None",
        markersize=6,
        label="Average",
    )
    fig.legend(
        handles=[avg_proxy],
        loc="upper center",
        frameon=False,
        bbox_to_anchor=(0.5, 0.99),
    )
    fig.tight_layout(rect=[0.03, 0.03, 0.97, 0.95])

    physical_img = tempfile.mktemp(".png")
    fig.savefig(physical_img, dpi=120, bbox_inches="tight")
    plt.close(fig)

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(
        page_w / 2, page_h - 20, "Physical Properties and Declared Unit"
    )
    reader_phys = ImageReader(physical_img)
    x, y, w, h = fit_image(reader_phys, page_w, page_h, margin=40)
    c.drawImage(
        physical_img, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto"
    )
    c.showPage()

    # ---------------------- Impact boxplots page ----------------------
    inds = [
        "Climate change-Total",
        "Climate change-Fossil",
        "Climate change-Biogenic",
        "Climate change-Land use and land use change",
    ]

    ind_titles = {
        "Climate change-Total": "GWP total",
        "Climate change-Fossil": "GWP fossil",
        "Climate change-Biogenic": "GWP biogenic",
        "Climate change-Land use and land use change": "GWP luluc",
    }

    fig, axes = plt.subplots(2, 2, figsize=(10, 8))
    axes = axes.flatten()

    for ax, ind in zip(axes, inds):
        cols = [f"{ind}_A1-A3", f"{ind}_C1234", f"{ind}_D"]
        ax.boxplot([df[c].dropna() for c in cols], positions=[1, 3, 5], widths=0.6)

        avg_values = [df_avg[c].iloc[0] for c in cols]
        ax.scatter([1, 3, 5], avg_values, color="red", s=40, zorder=3)

        ax.set_xticks([1, 3, 5])
        ax.set_xticklabels(["A1–A3", "C1–C4", "D"])
        ax.set_title(ind_titles[ind], fontsize=10)
        ax.set_ylabel("kg CO₂e per declared unit", fontsize=8)
        ax.grid(axis="y", linestyle="--", alpha=0.25)

    avg_proxy = Line2D(
        [0],
        [0],
        color="red",
        marker="o",
        linestyle="None",
        markersize=6,
        label="Average",
    )
    fig.legend(
        handles=[avg_proxy],
        loc="upper center",
        frameon=False,
        bbox_to_anchor=(0.5, 0.99),
    )
    fig.tight_layout(rect=[0.05, 0.03, 0.95, 0.95])

    combined_img = tempfile.mktemp(".png")
    fig.savefig(combined_img, dpi=120, bbox_inches="tight")
    plt.close(fig)

    c.setFont("Helvetica-Bold", 16)
    c.drawCentredString(page_w / 2, page_h - 20, "Indicator Comparison")
    reader2 = ImageReader(combined_img)
    x, y, w, h = fit_image(reader2, page_w, page_h, margin=40)
    c.drawImage(
        combined_img, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto"
    )
    c.showPage()

    # ---------------------- Method + tabular comparison page ----------------------
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 40, "Averaging Method and Results Table")
    recipe_type = report.get("meta", {}).get("pipeline", {}).get("recipe_type")
    if recipe_type == "market-average":
        method = (
            "Method: market-weighted averaging. Country-level averages are combined "
            "using market share weights for the product HS code."
        )
    else:
        method = (
            "Method: arithmetic averaging. Matching EPDs are averaged with equal "
            "weight for each indicator and module."
        )
    c.setFont("Helvetica", 10)
    method_text = c.beginText(40, page_h - 62)
    for line in method.split(". "):
        method_text.textLine(line.strip() + ("." if not line.endswith(".") else ""))
    c.drawText(method_text)

    table_df = _build_impact_comparison_table(report).head(20)
    y = page_h - 120
    headers = ["Indicator", "Module", "Previous", "Current", "Direction"]
    x_cols = [40, 230, 290, 360, 445]
    for xh, hname in zip(x_cols, headers):
        c.drawString(xh, y, hname)
    y -= 8
    c.line(40, y, page_w - 40, y)
    y -= 14
    for _, row in table_df.iterrows():
        c.drawString(40, y, str(row["Indicator"])[:33])
        c.drawString(230, y, str(row["Module"]))
        c.drawRightString(342, y, f"{row['Previous']:.3g}")
        c.drawRightString(420, y, f"{row['Current']:.3g}")
        c.drawString(445, y, str(row["Direction"]))
        y -= 14
        if y < 50:
            break

    c.save()


def write_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    """
    Write the report dict to: <out_path>/reports/<report_uuid>.json

    Returns the written file path.
    """
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    file_path = reports_dir / f"{report_uuid}.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
