from types import SimpleNamespace

from materia_epd.pipeline.context import EpdPipelineContext
from materia_epd.pipeline.stages import ValidateMassConversionStage


def _build_ctx(avg_properties: dict, dec_unit: str = "volume") -> EpdPipelineContext:
    return EpdPipelineContext(
        process=SimpleNamespace(uuid="proc-1"),
        active_dec_unit=dec_unit,
        avg_properties=avg_properties,
    )


def test_validate_mass_conversion_passes_when_mass_and_property_are_present():
    stage = ValidateMassConversionStage()
    ctx = _build_ctx(avg_properties={"volume": 1.0, "mass": 780.0, "gross_density": 780.0})

    stage.run(ctx)

    assert ctx.success is True
    assert ctx.stopped is False


def test_validate_mass_conversion_fails_when_mass_is_missing():
    stage = ValidateMassConversionStage()
    ctx = _build_ctx(avg_properties={"volume": 1.0, "mass": None, "gross_density": 580.0})

    stage.run(ctx)

    assert ctx.success is False
    assert ctx.stopped is True
    assert any(d["kind"] == "error" for d in ctx.diagnostics)


def test_validate_mass_conversion_fails_when_property_is_missing():
    stage = ValidateMassConversionStage()
    ctx = _build_ctx(avg_properties={"volume": 1.0, "mass": 580.0, "gross_density": None})

    stage.run(ctx)

    assert ctx.success is False
    assert ctx.stopped is True
    assert any(d["kind"] == "error" for d in ctx.diagnostics)


def test_validate_mass_conversion_skips_when_declared_unit_is_mass():
    stage = ValidateMassConversionStage()
    ctx = _build_ctx(avg_properties={"mass": 1.0}, dec_unit="mass")

    stage.run(ctx)

    assert ctx.success is True
    assert ctx.stopped is False
    assert ctx.diagnostics == []
