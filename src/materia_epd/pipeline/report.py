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
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from materia_epd.core.constants import ATTR, NS
from materia_epd.epd.models import IlcdProcess
from materia_epd.geo.locations import get_location_attribute, get_location_color


def extract_product_metadata(process: IlcdProcess) -> tuple[str, list[str]]:
    root = process.root
    for xp in [
        ".//common:baseName",
        ".//common:name/common:baseName",
        ".//common:shortDescription",
        ".//common:name",
    ]:
        nodes = root.findall(xp, NS)
        if nodes:
            name = next(
                (
                    n.text.strip()
                    for n in nodes
                    if n is not None
                    and n.text
                    and n.attrib.get(ATTR.LANG, "").lower().startswith("en")
                ),
                None,
            ) or next(
                (n.text.strip() for n in nodes if n is not None and n.text and n.text.strip()),
                None,
            )
            if name:
                break
    else:
        name = "Unknown product"

    cats = []
    for c in root.findall(".//common:classification", NS):
        cname = c.attrib.get("name")
        if cname and cname.lower() != "hs classification":
            cats.append(cname.strip())
        for cls in c.findall("common:class", NS):
            txt = (cls.text or "").strip() or (cls.attrib.get(ATTR.CLASS_ID) or "").strip()
            if txt:
                cats.append(txt)
    return name, list(dict.fromkeys(cats))


def flatten_impacts(impacts: list[dict]) -> dict:
    row = {}
    for imp in impacts:
        n, v = imp["name"], imp["values"]
        row[f"{n}_A1-A3"] = v.get("A1-A3") or 0
        row[f"{n}_C1234"] = sum(v.get(k) or 0 for k in ("C1", "C2", "C3", "C4"))
        row[f"{n}_D"] = v.get("D") or 0
    return row


def detect_declared_unit(avg_physical: dict) -> str | None:
    labels = {"mass": "mass", "volume": "volume", "surface": "surface", "length": "length", "unit_count": "unit count"}
    return next((labels[k] for k in labels if avg_physical.get(k) is not None and abs(avg_physical[k] - 1.0) < 1e-9), None)


def build_impact_comparison_table(report: Dict[str, Any]) -> pd.DataFrame:
    prev, cur = report.get("previous", {}).get("impacts", {}), report.get("average", {}).get("impacts", {})
    rows = []
    for ind, cv in cur.items():
        for mod in sorted(set(prev.get(ind, {})) | set(cv)):
            p, c = float(prev.get(ind, {}).get(mod, 0.0)), float(cv.get(mod, 0.0))
            rows.append({"Indicator": ind, "Module": mod, "Previous": p, "Current": c, "Direction": "no-change" if abs(c - p) <= 1e-12 else ("increase" if c > p else "decrease")})
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
    ax.set(xlim=(0, 1), ylim=(0, 1)); ax.axis("off")
    fig.patch.set_facecolor("white"); ax.set_facecolor("white")
    lx, rx, w = 0.16, 0.82, 0.026
    sink, cursor = sum(heights), 0.5 + sum(heights) / 2

    def ribbon(x0, x1, y0t, y0b, y1t, y1b, color):
        c1, c2 = x0 + 0.37 * (x1 - x0), x1 - 0.37 * (x1 - x0)
        v = [(x0, y0t), (c1, y0t), (c2, y1t), (x1, y1t), (x1, y1b), (c2, y1b), (c1, y0b), (x0, y0b), (x0, y0t)]
        ax.add_patch(PathPatch(MplPath(v, [1, 4, 4, 4, 2, 4, 4, 4, 79]), facecolor=color, edgecolor="none"))

    def box(x, y0, bw, bh, color):
        ax.add_patch(FancyBboxPatch((x, y0), bw, bh, boxstyle="round,pad=0,rounding_size=0.004", facecolor=color, edgecolor="none"))

    for (loc, _), h, t in zip(items, heights, tops):
        b, t2 = t - h, cursor
        cursor -= h
        ribbon(lx + w, rx, t, b, t2, cursor, get_location_color(loc).get("rgba") or [0.5, 0.5, 0.5, 0.25])

    for (loc, share), h, t in zip(items, heights, tops):
        box(lx, t - h, w, h, get_location_color(loc).get("hex") or "#6B7280")
        ax.text(lx - 0.02, t - h / 2, f"{get_location_attribute(loc, 'Name') or loc}  {share:.1%}", ha="right", va="center", fontsize=10.5, color="#222222")

    p = report.get("meta", {}).get("product", {})
    target = p.get("target_location")
    box(rx, 0.5 - sink / 2, w, sink, get_location_color(target).get("hex") or "#00A1DE")
    ax.text(rx + 0.03, 0.5, f"{get_location_attribute(target, 'Name') or 'Target market'} market ({p.get('name', 'Product')})", va="center", fontsize=12.5, color="#1f2937")
    plt.savefig(output_png, bbox_inches="tight", dpi=240, facecolor="white"); plt.close(fig)
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
    name, categories = extract_product_metadata(process)
    process.get_lcia_results()
    report = {
        "meta": {
            "report_uuid": report_uuid,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline": {"initial_epds": initial_epds, "selected_epds": selected_epds, "rejected_count": len(rejected_epds), "recipe_type": process.matches.get("type")},
            "indicators": list(avg_impacts.keys()),
            "product": {"name": name, "categories": categories, "hs_code": process.hs_class, "target_location": process.loc},
            "market": process.market,
        },
        "epds": [{"epd_uuid": e.uuid, "physical": e.material.to_dict(), "impacts": e.lcia_results} for e in epd_entries],
        "average": {"physical": avg_physical, "impacts": avg_impacts},
        "previous": {"impacts": {x["name"]: x["values"] for x in process.lcia_results}},
        "rejected": [{"epd_uuid": u, "reasons": r} for (u, r) in rejected_epds],
    }
    return report


def draw_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    c, page_w, page_h = canvas.Canvas(str(reports_dir / f"{report_uuid}.pdf"), pagesize=A4), *A4

    def fit_image(reader, margin=40, y_offset=0):
        iw, ih = reader.getSize(); aspect = iw / ih
        mw, mh = page_w - 2 * margin, page_h - 2 * margin
        w, h = mw, mw / aspect
        if h > mh:
            h, w = mh, mh * aspect
        return (page_w - w) / 2, (page_h - h) / 2 + y_offset, w, h

    def img_page(title, path, centered=True, y_offset=0):
        c.setFont("Helvetica-Bold", 16)
        (c.drawCentredString if centered else c.drawString)(page_w / 2 if centered else 40, page_h - 20 if centered else page_h - 40, title)
        r = ImageReader(path); x, y, w, h = fit_image(r, y_offset=y_offset)
        c.drawImage(path, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto")
        c.showPage()

    def save_fig(fig):
        path = tempfile.mktemp(".png")
        fig.savefig(path, bbox_inches="tight", dpi=120)
        plt.close(fig)
        return path

    df = pd.DataFrame([{"epd_uuid": e["epd_uuid"], **flatten_impacts(e["impacts"])} for e in report["epds"]])
    df_avg = pd.DataFrame([flatten_impacts([{"name": n, "values": v} for n, v in report["average"]["impacts"].items()])])
    df_phys = pd.DataFrame([{"epd_uuid": e["epd_uuid"], **e["physical"]} for e in report["epds"]])
    df_phys_avg = pd.DataFrame([report["average"]["physical"]])
    declared_unit = detect_declared_unit(report["average"]["physical"])

    p = report["meta"]["pipeline"]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(["Initial"], [p["initial_epds"]], color="#4C78A8", label="Initial")
    ax.bar(["Processed"], [p["selected_epds"]], color="#2ECC71", label="Selected")
    ax.bar(["Processed"], [p["initial_epds"] - p["selected_epds"]], bottom=[p["selected_epds"]], color="#E74C3C", label="Rejected")
    ax.set_title("EPD Matching Summary"); ax.set_ylabel("Count"); ax.grid(axis="y", linestyle="--", alpha=0.25); ax.yaxis.set_major_locator(plt.MaxNLocator(integer=True)); ax.legend()

    c.setFont("Helvetica-Bold", 16); c.drawString(40, page_h - 40, "EPD Averaging Summary")
    pm = report.get("meta", {}).get("product", {}); cats = ", ".join(pm.get("categories") or []) or "n/a"
    c.setFont("Helvetica", 11); c.drawString(40, page_h - 62, f"Product: {pm.get('name', 'Unknown')}")
    c.drawString(40, page_h - 78, f"HS code: {pm.get('hs_code', 'n/a')}"); c.drawString(40, page_h - 94, f"Categories: {cats}")
    r = ImageReader(save_fig(fig)); x, y, w, h = fit_image(r, y_offset=-50)
    c.drawImage(r, x, y, width=w, height=h, preserveAspectRatio=True, mask="auto"); c.showPage()

    c.setFont("Helvetica-Bold", 16); c.drawString(40, page_h - 40, "Overview of Input EPDs")
    c.setFont("Helvetica", 10); y = page_h - 72
    c.drawString(40, y, "EPD UUID"); c.drawString(340, y, "Mass [kg]"); c.drawString(430, y, "Volume [m³]"); y -= 12
    c.line(40, y, page_w - 40, y); y -= 14
    for e in report["epds"][:28]:
        c.drawString(40, y, str(e["epd_uuid"])[:48])
        c.drawRightString(400, y, "-" if e["physical"].get("mass") is None else f"{e['physical']['mass']:.4g}")
        c.drawRightString(500, y, "-" if e["physical"].get("volume") is None else f"{e['physical']['volume']:.4g}")
        y -= 16
        if y < 60:
            break
    c.showPage()

    sankey_img = draw_market_structure_sankey(report, tempfile.mktemp(".png"))
    if sankey_img:
        img_page("Market Structure (Sankey)", sankey_img, centered=False)

    fields = ["mass", "volume", "surface", "length", "unit_count", "gross_density", "grammage", "linear_density", "layer_thickness", "cross_sectional_area", "weight_per_piece"]
    titles = {"mass": "Mass [kg]", "volume": "Volume [m^3]", "surface": "Surface [m^2]", "length": "Length [m]", "unit_count": "Unit count [unit]", "gross_density": "Gross density [kg/m^3]", "grammage": "Grammage [kg/m^2]", "linear_density": "Linear density [kg/m]", "layer_thickness": "Layer thickness [m]", "cross_sectional_area": "Cross-sectional area [m^2]", "weight_per_piece": "Weight per piece [kg]"}
    fig, axes = plt.subplots(3, 4, figsize=(10, 8)); axes = axes.flatten()
    for ax, f in zip(axes[:11], fields):
        vals, avg = df_phys[f].dropna(), df_phys_avg[f].iloc[0]
        if len(vals) > 0:
            if vals.nunique() > 1:
                ax.boxplot([vals], positions=[1], widths=0.5)
            if pd.notna(avg):
                ax.scatter([1], [avg], color="red", s=35, zorder=3)
        ax.set_title(titles[f], fontsize=9); ax.set_xticks([1]); ax.set_xticklabels([""]); ax.grid(axis="y", linestyle="--", alpha=0.25); ax.tick_params(axis="y", labelsize=8)
    axes[11].axis("off")
    txt = f"Declared unit appears to be based on {declared_unit}, because the average {declared_unit} equals 1." if declared_unit else "Declared unit could not be identified clearly."
    axes[11].text(0.0, 0.8, txt, ha="left", va="top", fontsize=10, wrap=True)
    fig.legend(handles=[Line2D([0], [0], color="red", marker="o", linestyle="None", markersize=6, label="Average")], loc="upper center", frameon=False, bbox_to_anchor=(0.5, 0.99))
    fig.tight_layout(rect=[0.03, 0.03, 0.97, 0.95])
    img_page("Physical Properties and Declared Unit", save_fig(fig))

    inds = ["Climate change-Total", "Climate change-Fossil", "Climate change-Biogenic", "Climate change-Land use and land use change"]
    names = {"Climate change-Total": "GWP total", "Climate change-Fossil": "GWP fossil", "Climate change-Biogenic": "GWP biogenic", "Climate change-Land use and land use change": "GWP luluc"}
    fig, axes = plt.subplots(2, 2, figsize=(10, 8)); axes = axes.flatten()
    for ax, ind in zip(axes, inds):
        cols = [f"{ind}_A1-A3", f"{ind}_C1234", f"{ind}_D"]
        ax.boxplot([df[c].dropna() for c in cols], positions=[1, 3, 5], widths=0.6)
        ax.scatter([1, 3, 5], [df_avg[c].iloc[0] for c in cols], color="red", s=40, zorder=3)
        ax.set_xticks([1, 3, 5]); ax.set_xticklabels(["A1–A3", "C1–C4", "D"]); ax.set_title(names[ind], fontsize=10)
        ax.set_ylabel("kg CO₂e per declared unit", fontsize=8); ax.grid(axis="y", linestyle="--", alpha=0.25)
    fig.legend(handles=[Line2D([0], [0], color="red", marker="o", linestyle="None", markersize=6, label="Average")], loc="upper center", frameon=False, bbox_to_anchor=(0.5, 0.99))
    fig.tight_layout(rect=[0.05, 0.03, 0.95, 0.95])
    img_page("Indicator Comparison", save_fig(fig))

    c.setFont("Helvetica-Bold", 16); c.drawString(40, page_h - 40, "Averaging Method and Results Table")
    method = "Method: market-weighted averaging. Country-level averages are combined using market share weights for the product HS code." if report.get("meta", {}).get("pipeline", {}).get("recipe_type") == "market-average" else "Method: arithmetic averaging. Matching EPDs are averaged with equal weight for each indicator and module."
    c.setFont("Helvetica", 10)
    t = c.beginText(40, page_h - 62)
    for line in method.split(". "):
        t.textLine(line.strip() + ("." if not line.endswith(".") else ""))
    c.drawText(t)

    headers, xcols = ["Indicator", "Module", "Previous", "Current", "Direction"], [40, 230, 290, 360, 445]
    def draw_headers(y0):
        for xh, hname in zip(xcols, headers):
            c.drawString(xh, y0, hname)
        c.line(40, y0 - 8, page_w - 40, y0 - 8)
        return y0 - 22

    y = draw_headers(page_h - 120)
    for _, row in build_impact_comparison_table(report).iterrows():
        if y < 50:
            c.showPage(); c.setFont("Helvetica-Bold", 16); c.drawString(40, page_h - 40, "Averaging Method and Results Table (cont.)"); c.setFont("Helvetica", 10)
            y = draw_headers(page_h - 72)
        c.drawString(40, y, str(row["Indicator"])[:33]); c.drawString(230, y, str(row["Module"]))
        c.drawRightString(342, y, f"{row['Previous']:.3g}"); c.drawRightString(420, y, f"{row['Current']:.3g}"); c.drawString(445, y, str(row["Direction"]))
        y -= 14
    c.save()


def write_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    with (reports_dir / f"{report_uuid}.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
