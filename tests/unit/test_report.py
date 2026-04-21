from materia_epd.pipeline.report import build_impact_comparison_table
from materia_epd.pipeline.report import flatten_impacts


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
