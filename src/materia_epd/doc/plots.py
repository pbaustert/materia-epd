import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator
from matplotlib.patches import FancyBboxPatch, PathPatch
from matplotlib.path import Path as MplPath
import pandas as pd
from typing import Any, Dict
import squarify
from collections import defaultdict

from materia_epd.geo.locations import get_location_attribute, get_location_color
from materia_epd.doc.utils import get_report_data, detect_declared_unit


def _get_region_hierarchy(location: str) -> tuple[str, str]:
    loc_class = get_location_attribute(location, "Class")
    if loc_class == "Region":
        return location, location
    if loc_class == "Sub-region":
        parent = get_location_attribute(location, "Parent")
        return parent, location
    if loc_class == "Country":
        parent = get_location_attribute(location, "Parent")
        grandparent = get_location_attribute(parent, "Parent")
        return grandparent, parent
    return "GLO", "GLO"


def _get_rects(sizes, x, y, dx, dy):
    rects = squarify.normalize_sizes(sizes, dx, dy)
    rects = squarify.squarify(rects, x, y, dx, dy)
    return rects


def _add_patch(ax, rect, color, label):
    ax.add_patch(
        plt.Rectangle(
            (rect["x"], rect["y"]),
            rect["dx"],
            rect["dy"],
            facecolor=color,
            edgecolor="white",
            linewidth=0.5,
        )
    )

    def split_text(text):
        text = text.split()
        if len(text) > 1:
            split = len(text) // 2
            text = " ".join(text[:split]) + "\n" + " ".join(text[split:])
        return text

    def label_adjustment(text, dx, dy):
        rotation = 90 if dy > dx else 0
        available_length = dy if rotation else dx
        available_height = dx if rotation else dy
        required_length = len(text) * 1.7
        required_height = 3.2
        if available_length >= required_length and available_height >= required_height:
            return text, 8, rotation
        elif (
            available_length >= required_length / 2
            and available_height >= required_height * 2
        ):
            text = split_text(text)
            return text, 8, rotation
        elif (
            available_length >= required_length / 2
            and available_height >= required_height / 2
        ):
            return text, 4, rotation
        elif (
            available_length >= required_length / 2
            and available_height >= required_height
        ):
            text = split_text(text)
            return text, 4, rotation
        else:
            return "", 8, rotation

    label, fontsize, rotation = label_adjustment(label, rect["dx"], rect["dy"])

    ax.text(
        rect["x"] + rect["dx"] / 2,
        rect["y"] + rect["dy"] / 2,
        label,
        ha="center",
        va="center",
        fontsize=fontsize,
        rotation=rotation,
        color="white",
        fontweight="bold",
    )

    return ax


def processing_summary(p):
    initial = p.get("initial_epds", 0)
    selected = p.get("selected_epds", 0)
    rejected = initial - selected
    fig, ax = plt.subplots(figsize=(3, 3))
    ax.bar(["EPDs"], [selected], color="#2ECC71", label="Success")
    ax.bar(["EPDs"], [rejected], bottom=[selected], color="#E74C3C", label="Failure")
    ax.set_ylabel("Count", fontsize=10)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    fig.tight_layout()
    return fig


def gwp_total(df_avg) -> plt.Figure:
    ind = "GWP-Total"
    modules = ["A1-A3", "A4", "C1-C4", "D"]
    values = []
    for mod in modules:
        values.append(df_avg[f"{ind}_{mod}"].iloc[0])
    fig, ax = plt.subplots(figsize=(4.5, 3.5), dpi=240)
    bars = ax.bar(
        modules,
        values,
        color=["#264653", "#2A9D8F", "#E9C46A", "#E76F51"],
    )
    ax.bar_label(bars, fmt="%.2f", fontsize=8)
    ax.set_title("GWP-total")
    ax.set_ylabel("kg CO₂e / declared unit")
    ax.grid(axis="y", alpha=0.2)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    return fig


def market_sankey(report: Dict[str, Any]) -> str | None:
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
    fig, ax = plt.subplots(figsize=(5, 5), dpi=240)
    ax.set(xlim=(0, 1), ylim=(0, 1))
    ax.axis("off")
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    lx, rx, w = 0.16, 0.82, 0.026
    sink = sum(heights)
    cursor = 0.5 + sink / 2
    for (loc, _), h, t in zip(items, heights, tops):
        c1, c2 = lx + 0.37 * (rx - lx), rx - 0.37 * (rx - lx)
        ax.add_patch(
            PathPatch(
                MplPath(
                    [
                        (lx + w, t),
                        (c1, t),
                        (c2, cursor),
                        (rx, cursor),
                        (rx, cursor - h),
                        (c2, cursor - h),
                        (c1, t - h),
                        (lx + w, t - h),
                        (lx + w, t),
                    ],
                    [1, 4, 4, 4, 2, 4, 4, 4, 79],
                ),
                facecolor=get_location_color(loc).get("rgba") or [0.5, 0.5, 0.5, 0.25],
                edgecolor="none",
            )
        )
        cursor -= h
    for (loc, share), h, t in zip(items, heights, tops):
        ax.add_patch(
            FancyBboxPatch(
                (lx, t - h),
                w,
                h,
                boxstyle="round,pad=0,rounding_size=0.004",
                facecolor=get_location_color(loc).get("hex") or "#6B7280",
                edgecolor="none",
            )
        )
        ax.text(
            lx - 0.02,
            t - h / 2,
            f"{get_location_attribute(loc, 'ISO3') or loc}  {share:.1%}",
            ha="right",
            va="center",
            fontsize=10,
            color="#222222",
        )
    target = report.get("meta", {}).get("product", {}).get("target_location")
    ax.add_patch(
        FancyBboxPatch(
            (rx, 0.5 - sink / 2),
            w,
            sink,
            boxstyle="round,pad=0,rounding_size=0.004",
            facecolor="#A9A9A9",
            edgecolor="none",
        )
    )
    ax.text(
        rx + 0.03,
        0.5,
        f"{get_location_attribute(target, 'ISO3')}",
        va="center",
        fontsize=10,
        color="#1f2937",
    )
    return fig


def component_treemap(report: Dict[str, Any]) -> plt.Figure:
    mass_composition = report.get("mass_composition", [])
    labels = [c["name"] for c in mass_composition]
    sizes = [c["mass"] for c in mass_composition]
    fig, ax = plt.subplots(figsize=(5, 5), dpi=240)
    ax.axis("off")
    rects = _get_rects(sizes, 0, 0, 100, 100)
    cmap = plt.get_cmap("Blues")
    for i, (label, mass, rect) in enumerate(zip(labels, sizes, rects)):
        color = cmap(0.4 + 0.5 * i / max(len(rects), 1))
        label = f"{label+" "+str(mass)} kg"
        ax = _add_patch(ax, rect, color, label)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.invert_yaxis()
    fig.tight_layout()

    return fig


def region_treemap(report: Dict[str, Any]) -> plt.Figure:
    hierarchy = defaultdict(lambda: defaultdict(int))
    for epd in report.get("epds", []):
        location = epd.get("location")
        region, subregion = _get_region_hierarchy(location)
        hierarchy[region][subregion] += 1
    fig, ax = plt.subplots(figsize=(5, 5), dpi=240)
    ax.axis("off")
    region_sizes = {
        region: sum(subregions.values()) for region, subregions in hierarchy.items()
    }
    regions = list(region_sizes.keys())
    sizes = list(region_sizes.values())
    region_rects = _get_rects(sizes, 0, 0, 100, 100)
    for region, rect in zip(regions, region_rects):
        ax.add_patch(
            plt.Rectangle(
                (rect["x"], rect["y"]),
                rect["dx"],
                rect["dy"],
                facecolor="none",
                edgecolor="white",
                linewidth=6,
            )
        )
        subregions = hierarchy[region]
        sub_sizes = list(subregions.values())
        sub_labels = list(subregions.keys())
        sub_rects = _get_rects(sub_sizes, rect["x"], rect["y"], rect["dx"], rect["dy"])
        for sub_label, sub_size, sub_rect in zip(
            sub_labels,
            sub_sizes,
            sub_rects,
        ):
            label = f"{sub_label + " " + str(sub_size)}"
            color = get_location_color(sub_label).get("hex")
            ax = _add_patch(ax, sub_rect, color, label)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.invert_yaxis()
    fig.tight_layout()

    return fig


def physical_boxplots(fields, titles, report):
    declared_unit = detect_declared_unit(report.get("average", {}).get("physical", {}))
    _, _, df, df_avg, _ = get_report_data(report)
    fig, axes = plt.subplots(3, 4, figsize=(7.0, 10))
    axes = axes.flatten()
    for ax, f in zip(axes[: len(fields)], fields):
        vals = df[f].dropna() if f in df.columns else pd.Series(dtype=float)
        avg = df_avg[f].iloc[0] if f in df_avg.columns else None
        if len(vals) > 0 and vals.nunique() > 1:
            ax.boxplot([vals], positions=[1], widths=0.5)
        if pd.notna(avg):
            ax.scatter([1], [avg], color="red", s=35, zorder=3)
        ax.set_title(titles.get(f, f), fontsize=8)
        ax.set_xticks([1])
        ax.set_xticklabels([""])
        ax.grid(axis="y", linestyle="--", alpha=0.25)
        ax.tick_params(axis="y", labelsize=8)
    for ax in axes[len(fields) :]:  # noqa E203
        ax.axis("off")
    txt = f"Declared unit appears to be {declared_unit}."
    axes[-1].text(0.0, 0.8, txt, ha="left", va="top", fontsize=10, wrap=True)
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
    return fig


def gwp_boxplots(inds, report):
    df, df_avg, _, _, _ = get_report_data(report)
    fig, axes = plt.subplots(2, 2, figsize=(7, 10))
    axes = axes.flatten()
    mp, ml = [1, 3, 5, 7], ["A1-A3", "A4", "C1-C4", "D"]
    for ax, ind in zip(axes, inds):
        cols = [f"{ind}_A1-A3", f"{ind}_A4", f"{ind}_C1-C4", f"{ind}_D"]
        vals, positions = [], []
        for col, pos in zip(cols, mp):
            series = df[col].dropna() if col in df.columns else pd.Series(dtype=float)
            avg_val = df_avg[col].iloc[0] if col in df_avg.columns else 0.0
            if (
                col.endswith("_A4")
                and (len(series) == 0 or (series.abs() <= 1e-12).all())
                and abs(avg_val) > 1e-12
            ):
                series = pd.Series([avg_val])
            if len(series) > 0:
                vals.append(series)
                positions.append(pos)
        if vals:
            ax.boxplot(vals, positions=positions, widths=0.6)
        ax.scatter(
            mp,
            [df_avg[col].iloc[0] if col in df_avg.columns else 0.0 for col in cols],
            color="red",
            s=40,
            zorder=3,
        )
        ax.set_xticks(mp)
        ax.set_xticklabels(ml)
        ax.set_title(ind, fontsize=10)
        ax.set_ylabel("kg CO₂e per declared unit", fontsize=10)
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
    return fig
