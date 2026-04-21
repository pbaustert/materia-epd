from types import SimpleNamespace

from materia_epd.pipeline.context import EpdPipelineContext
from materia_epd.pipeline.stages import DeriveTransportA4ImpactsStage
import materia_epd.pipeline.stages as stages


def test_derive_transport_a4_impacts_market_weighted(monkeypatch):
    monkeypatch.setattr(
        stages,
        "get_location_attribute",
        lambda code, attr: {
            "DEU": "Western Europe",
            "FRA": "Western Europe",
            "CHN": "Eastern Asia",
        }.get(code)
        if attr == "Parent"
        else None,
    )
    monkeypatch.setattr(
        stages,
        "get_transport_impact_per_kg",
        lambda src, tgt: {
            "Western Europe": {
                "Climate change-Total": 0.0636,
                "Climate change-Fossil": 0.0636,
            },
            "Eastern Asia": {
                "Climate change-Total": 0.3657,
                "Climate change-Fossil": 0.3657,
            },
            "LUX": {"Climate change-Total": 0.0209, "Climate change-Fossil": 0.0209},
        }.get(src, {}),
    )

    ctx = EpdPipelineContext(
        process=SimpleNamespace(
            uuid="proc-1",
            loc="LUX",
            market={"DEU": 0.5, "FRA": 0.2, "CHN": 0.2, "RoW": 0.1},
        ),
        avg_properties={"mass": 2.0},
        avg_gwps={"Climate change-Total": {"A1-A3": 1.0}},
    )

    DeriveTransportA4ImpactsStage().run(ctx)

    # RoW ignored => shares rescaled on 0.9; weighted per-kg = (0.7*0.0636 + 0.2*0.3657) / 0.9
    assert ctx.avg_gwps["Climate change-Total"]["A4"] == 0.261467
    assert ctx.avg_gwps["Climate change-Fossil"]["A4"] == 0.261467
