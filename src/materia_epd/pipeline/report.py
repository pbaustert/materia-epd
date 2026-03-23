from __future__ import annotations
import json
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import tempfile
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from materia_epd.epd.models import IlcdProcess


def build_report(
    report_uuid: str,
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

    report: Dict[str, Any] = {
        "meta": {
            "report_uuid": report_uuid,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline": {
                "initial_epds": initial_epds,
                "selected_epds": selected_epds,
                "rejected_count": len(rejected_epds),
            },
            "indicators": list(avg_impacts.keys()),
        },
        "epds": [],
        "average": {
            "physical": avg_physical,
            "impacts": avg_impacts,
        },
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
    reader = ImageReader(stacked_img)
    x, y, w, h = fit_image(reader, page_w, page_h, margin=40, y_offset=-10)
    c.drawImage(
        stacked_img, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto"
    )
    c.showPage()

    # ---------------------- Physical data page ----------------------
    fig, axes = plt.subplots(3, 4, figsize=(10, 8))
    axes = axes.flatten()

    for ax, field in zip(axes[:11], physical_fields):
        values = df_phys[field].dropna()
        avg_value = df_phys_avg[field].iloc[0]

        if len(values) > 0:
            ax.boxplot([values], positions=[1], widths=0.5)
            if pd.notna(avg_value):
                ax.scatter([1], [avg_value], color="red", s=35, zorder=3)

        ax.set_xticks([1])
        ax.set_xticklabels([""])
        ax.set_title(physical_titles[field], fontsize=9)
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
