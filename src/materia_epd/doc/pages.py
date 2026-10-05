from svglib.svglib import svg2rlg
from reportlab.graphics import renderPDF
import matplotlib.pyplot as plt
from dataclasses import dataclass
from io import BytesIO

from materia_epd.doc.plots import (
    processing_summary,
    gwp_total,
    market_sankey,
    component_treemap,
    region_treemap,
)
from materia_epd.doc.utils import (
    get_report_data,
    detect_declared_unit,
    format_value,
    draw_header,
    increment_version,
)
from materia_epd.core.constants import METHOD_DESCRIPTION, PHYS_TITLES


@dataclass
class Slot:
    x: float
    y: float
    width: float
    height: float
    padding: float = 5

    @property
    def content_x(self) -> float:
        return self.x + self.padding

    @property
    def content_y(self) -> float:
        return self.y - self.padding

    @property
    def content_width(self) -> float:
        return max(0, self.width - 2 * self.padding)

    @property
    def content_height(self) -> float:
        return max(0, self.height - 2 * self.padding)

    @property
    def bottom(self) -> float:
        return self.y - self.height

    def draw_figure(self, c, fig, y_start=None, align_top=True):
        svg_buffer = BytesIO()
        fig.savefig(svg_buffer, format="svg", bbox_inches="tight")
        svg_buffer.seek(0)
        drawing = svg2rlg(svg_buffer)
        box_w = self.content_width
        box_h = (
            self.content_height
            if y_start is None
            else max(0, y_start - self.bottom - self.padding)
        )
        aspect = drawing.width / drawing.height
        if box_w / aspect <= box_h:
            w, h = box_w, box_w / aspect
        else:
            w, h = box_h * aspect, box_h
        scale = w / drawing.width
        drawing.scale(scale, scale)
        x = self.content_x + (box_w - w) / 2
        y = (
            (y_start or self.content_y) - h
            if align_top
            else self.bottom + self.padding + (box_h - h) / 2
        )
        renderPDF.draw(drawing, c, x, y)
        plt.close(fig)
        return y

    def draw_text(
        self, c, text: str, y_start: float, line_height: float = 12, font_size: int = 10
    ):
        c.setFont("Helvetica", font_size)
        lines = []
        current = ""
        for word in text.split():
            test = f"{current} {word}".strip()
            if c.stringWidth(test, "Helvetica", font_size) <= self.content_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        y = y_start
        for line in lines:
            c.drawString(self.content_x, y, line)
            y -= line_height
        return y

    def draw_title(self, c, title: str, font_size: int = 12):
        c.setFont("Helvetica-Bold", font_size)
        c.drawString(self.content_x, self.content_y, title)


@dataclass
class SlotGrid:
    page_w: float
    page_h: float
    cols: int = 2
    rows: int = 3
    margin: float = 40
    col_gap: float = 20
    row_gap: float = 15

    def __post_init__(self):
        usable_w = self.page_w - 2 * self.margin
        usable_h = self.page_h - 2 * self.margin
        self.col_width = (usable_w - (self.cols - 1) * self.col_gap) / self.cols
        self.row_height = (usable_h - (self.rows - 1) * self.row_gap) / self.rows

    def get(self, col: int, row: int) -> Slot:
        x = self.margin + col * (self.col_width + self.col_gap)
        y = self.page_h - self.margin - row * (self.row_height + self.row_gap)
        return Slot(x, y, self.col_width, self.row_height)


def modular_summary_page(c, page_w, page_h, report):
    _, df_avg, _, _, rt = get_report_data(report)
    grid = SlotGrid(page_w, page_h)
    pm = report.get("meta", {}).get("product", {})
    p = report.get("meta", {}).get("pipeline", {})

    # ========== Slot (0,0): Product Description ==========
    slot = grid.get(0, 0)
    slot.draw_title(c, "Product Description")
    y = slot.content_y - 24
    y = slot.draw_text(c, "Name:", y, line_height=14, font_size=12)
    names = pm.get("names_by_language", {})
    for lang in ["fr", "en", "de"]:
        y = slot.draw_text(c, f"{lang.upper()}: {names.get(lang, '')}", y)
    y -= 14
    y = slot.draw_text(c, "Categories:", y, line_height=14, font_size=12)
    for x in pm.get("hs_classification", []):
        y = slot.draw_text(
            c, f"• {x.get('class_id', '')}  {x.get('text', '')}".strip(), y
        )

    # ========== Slot (1,0): Method & Processing ==========
    slot = grid.get(1, 0)
    slot.draw_title(c, "Method & Processing")
    y = slot.content_y - 24
    y = slot.draw_text(c, "Method:", y, line_height=14, font_size=12)
    y = slot.draw_text(c, f"{METHOD_DESCRIPTION.get(rt)}", y)
    y -= 14
    # Processing summary chart
    y = slot.draw_text(c, "EPD Processing:", y, line_height=14, font_size=12)
    proc_fig = processing_summary(p)
    slot.draw_figure(c, proc_fig, y, align_top=True)

    # Version info
    c.setFont("Helvetica", 8)
    c.drawString(
        slot.content_x,
        slot.bottom + 10,
        f"Data of run: {report.get('meta', {}).get('generated_at', '')}",
    )
    c.drawString(
        slot.content_x,
        slot.bottom,
        f"Version: {increment_version(report.get('meta', {}).get('version', ''), 'patch')}",  # noqa E501
    )

    # ========== Slot (0,1): Results Overview ==========
    slot = grid.get(0, 1)
    slot.draw_title(c, "Results Overview")
    y = slot.content_y - 24
    gwp_fig = gwp_total(df_avg)
    slot.draw_figure(c, gwp_fig, y, align_top=True)

    # ========== Slot (1,1): Declared Unit ==========
    slot = grid.get(1, 1)
    slot.draw_title(c, "Declared Unit")
    phys = report.get("average", {}).get("physical", {})
    y = slot.content_y - 24

    declared_unit = detect_declared_unit(phys)
    slot.draw_text(
        c,
        f"Declared unit: {declared_unit or 'unknown'}",
        y,
        line_height=14,
        font_size=10,
    )
    y -= 16

    for key, value in phys.items():
        if value is not None:
            title = PHYS_TITLES.get(key, key)
            slot.draw_text(
                c, f"{title}: {format_value(value)}", y, line_height=12, font_size=9
            )
            y -= 12

    # ========== Slot (0,2): Market Structure ==========
    slot = grid.get(0, 2)
    slot.draw_title(c, "Market Structure")
    y = slot.content_y - 24
    sankey_fig = market_sankey(report)
    slot.draw_figure(c, sankey_fig, y, align_top=True)

    # ========== Slot (1,2): Source Data ==========
    slot = grid.get(1, 2)
    if rt == "assembled":
        slot.draw_title(c, "Mass composition")
        c.setFont("Helvetica", 10)
        y = slot.content_y - 24
        mass_fig = component_treemap(report)
        slot.draw_figure(c, mass_fig, y, align_top=True)
    else:
        slot.draw_title(c, "Source data origins")
        c.setFont("Helvetica", 10)
        y = slot.content_y - 24
        region_fig = region_treemap(report)
        slot.draw_figure(c, region_fig, y, align_top=True)
    c.showPage()


def table_page(c, page_w, page_h, data, columns, title, get_row=None):
    get_row = get_row or (lambda x: x)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 40, title)
    y = draw_header(c, page_h - 72, columns, page_w, 10)

    for e in data:
        if y < 60:
            c.showPage()
            c.setFont("Helvetica-Bold", 16)
            c.drawString(40, page_h - 40, f"{title} (cont.)")
            y = draw_header(c, page_h - 72, columns, page_w, 10)
        c.setFont("Helvetica", 8)
        row = get_row(e)
        for col in columns:
            c.drawString(col[0], y, format_value(row[col[1]]))
        y -= 14
    c.showPage()


def img_page(c, page_h, title, fig):
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, page_h - 40, title)
    svg_buffer = BytesIO()
    fig.savefig(svg_buffer, format="svg", bbox_inches="tight")
    svg_buffer.seek(0)
    drawing = svg2rlg(svg_buffer)

    renderPDF.draw(
        drawing,
        c,
        40,
        40,
    )

    plt.close(fig)
    c.showPage()


def regression_model_page(c, page_w, page_h, report):
    models = report.get("regression_models", {})
    if not models:
        return

    rows = []
    for model_name, data in models.items():
        rows.append(
            {
                "Model": model_name,
                "Type": "Intercept (BOF primary steel)",
                "Value": data["intercept"],
                "Unit": "kgCO2e",
            }
        )
        for tech, coeff in data["tech_coeffs"].items():
            rows.append(
                {
                    "Model": model_name,
                    "Type": f"Coefficient for {tech}",
                    "Value": coeff,
                    "Unit": "kgCO2e",
                }
            )
        rows.append(
            {
                "Model": model_name,
                "Type": "Coefficient for Secondary Material",
                "Value": data["secondary_coeff"],
                "Unit": "kgCO2e/kg",
            }
        )

    columns = [(40, "Model"), (180, "Type"), (420, "Value"), (480, "Unit")]
    table_page(c, page_w, page_h, rows, columns, "Regression Models")
