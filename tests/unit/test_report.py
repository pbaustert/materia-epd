from pathlib import Path

from materia_epd.pipeline.report import build_impact_comparison_table
from materia_epd.pipeline.report import draw_report
from materia_epd.pipeline.report import flatten_impacts


def _physical_template():
    return {
        "mass": 1.0,
        "volume": None,
        "surface": None,
        "length": None,
        "unit_count": None,
        "gross_density": None,
        "grammage": None,
        "linear_density": None,
        "layer_thickness": None,
        "cross_sectional_area": None,
        "weight_per_piece": None,
    }


def test_flatten_impacts_includes_a4_module():
    impacts = [
        {
            "name": "Climate change-Total",
            "values": {"A1-A3": 10.0, "A4": 2.5, "C1": 1.0, "D": -0.5},
        }
    ]

    flattened = flatten_impacts(impacts)

    assert flattened["Climate change-Total_A1-A3"] == 10.0
    assert flattened["Climate change-Total_A4"] == 2.5
    assert flattened["Climate change-Total_C1234"] == 1.0
    assert flattened["Climate change-Total_D"] == -0.5


def test_build_impact_comparison_table_adds_a4_when_missing():
    report = {
        "previous": {"impacts": {"Climate change-Total": {"A1-A3": 1.0}}},
        "average": {"impacts": {"Climate change-Total": {"A1-A3": 1.2}}},
    }

    table = build_impact_comparison_table(report)
    a4_rows = table[
        (table["Indicator"] == "Climate change-Total") & (table["Module"] == "A4")
    ]

    assert len(a4_rows) == 1
    row = a4_rows.iloc[0]
    assert row["Previous"] == 0.0
    assert row["Current"] == 0.0


def test_draw_report_does_not_shadow_canvas_with_indicator_columns(tmp_path: Path):
    report = {
        "epds": [
            {
                "epd_uuid": "epd-1",
                "impacts": [
                    {
                        "name": "Climate change-Total",
                        "values": {"A1-A3": 10.0, "C1": 1.0, "D": -0.5},
                    },
                    {
                        "name": "Climate change-Fossil",
                        "values": {"A1-A3": 5.0},
                    },
                    {
                        "name": "Climate change-Biogenic",
                        "values": {"A1-A3": 2.0},
                    },
                    {
                        "name": "Climate change-Land use and land use change",
                        "values": {"A1-A3": 1.0},
                    },
                ],
                "physical": _physical_template(),
            }
        ],
        "average": {
            "impacts": {
                "Climate change-Total": {"A1-A3": 10.0, "A4": 2.5, "C1": 1.0, "D": -0.5},
                "Climate change-Fossil": {"A1-A3": 5.0},
                "Climate change-Biogenic": {"A1-A3": 2.0},
                "Climate change-Land use and land use change": {"A1-A3": 1.0},
            },
            "physical": _physical_template(),
        },
        "previous": {
            "impacts": {
                "Climate change-Total": {"A1-A3": 9.0, "A4": 2.0, "C1": 1.0, "D": -0.5}
            }
        },
        "meta": {
            "pipeline": {
                "initial_epds": 1,
                "selected_epds": 1,
                "recipe_type": "market-average",
            },
            "product": {"name": "Test Product"},
        },
    }

    draw_report(report, tmp_path, "shadowing-regression")

    assert (tmp_path / "reports" / "shadowing-regression.pdf").exists()
