from types import SimpleNamespace

from materia_epd.pipeline.context import EpdPipelineContext
from materia_epd.pipeline.recipes import RecipeFactory
from materia_epd.pipeline.stages import (
    AggregateComponentImpactsStage,
    AggregateComponentPropertiesStage,
    LoadAssembledComponentsStage,
    ResolveComponentResultsStage,
)


def _assembled_ctx(matches=None, results_registry=None):
    return EpdPipelineContext(
        process=SimpleNamespace(uuid="proc-assembled", matches=matches or {}),
        matches=matches or {},
        results_registry=results_registry or {},
    )


def test_load_assembled_components_stage_normalizes_payload():
    matches = {
        "type": "assembled",
        "components": [
            {"process_uuid": "cement", "quantity": 300, "unit": "kg"},
            {"process_uuid": "water", "quantity": 180},
        ],
    }
    ctx = _assembled_ctx(matches=matches)

    LoadAssembledComponentsStage().run(ctx)

    assert ctx.stopped is False
    assert len(ctx.assembled_components) == 2
    assert ctx.assembled_components[1]["unit"] == "mass"


def test_resolve_component_results_stage_stops_when_component_missing():
    matches = {
        "type": "assembled",
        "components": [{"process_uuid": "cement", "quantity": 300, "unit": "kg"}],
    }
    ctx = _assembled_ctx(matches=matches, results_registry={})
    ctx.assembled_components = matches["components"]

    ResolveComponentResultsStage().run(ctx)

    assert ctx.stopped is True
    assert ctx.success is False
    assert any(d["kind"] == "error" for d in ctx.diagnostics)


def test_aggregate_component_impacts_stage_computes_sum_product():
    matches = {
        "type": "assembled",
        "components": [
            {"process_uuid": "cement", "quantity": 2.0, "unit": "kg"},
            {"process_uuid": "water", "quantity": 3.0, "unit": "kg"},
        ],
    }
    ctx = _assembled_ctx(matches=matches)
    ctx.assembled_components = matches["components"]
    ctx.component_impacts = {
        "cement": {
            "Climate change-Total": {"A1-A3": 1.5, "C1": 0.2},
            "Climate change-Fossil": {"A1-A3": 1.2},
        },
        "water": {
            "Climate change-Total": {"A1-A3": 0.1, "C1": 0.0},
            "Climate change-Fossil": {"A1-A3": 0.08},
        },
    }

    AggregateComponentImpactsStage().run(ctx)

    assert ctx.avg_gwps["Climate change-Total"]["A1-A3"] == 3.3
    assert ctx.avg_gwps["Climate change-Total"]["C1"] == 0.4
    assert ctx.avg_gwps["Climate change-Fossil"]["A1-A3"] == 2.64


def test_aggregate_component_properties_stage_sums_additive_fields():
    matches = {
        "type": "assembled",
        "components": [
            {"process_uuid": "cement", "quantity": 2.0, "unit": "kg"},
            {"process_uuid": "water", "quantity": 3.0, "unit": "kg"},
        ],
    }
    results_registry = {
        "cement": {
            "avg_properties": {"mass": 1.0, "volume": 0.5, "gross_density": 2.0}
        },
        "water": {
            "avg_properties": {"mass": 1.0, "volume": 1.0, "gross_density": 1.0}
        },
    }
    ctx = _assembled_ctx(matches=matches, results_registry=results_registry)
    ctx.assembled_components = matches["components"]

    AggregateComponentPropertiesStage().run(ctx)

    assert ctx.avg_properties["mass"] == 5.0
    assert ctx.avg_properties["volume"] == 4.0
    assert ctx.avg_properties["gross_density"] is None


def test_recipe_factory_builds_assembled_recipe():
    ctx = EpdPipelineContext(matches={"type": "assembled"})

    stages = RecipeFactory().build(ctx)

    names = [stage.name for stage in stages]
    assert names[:4] == [
        "load-assembled-components",
        "resolve-component-results",
        "aggregate-component-impacts",
        "aggregate-component-properties",
    ]
    assert names[-1] == "build-report"
