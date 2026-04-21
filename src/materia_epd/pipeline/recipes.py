from __future__ import annotations

from materia_epd.pipeline.stages import (
    PipelineStage,
    PrefilterByUuidStage,
    FilterByUnitStage,
    FallbackToMassStage,
    ComputeAveragePropertiesStage,
    ValidateMassConversionStage,
    ComputeAverageImpactsStage,
    ComputeMarketAverageImpactsStage,
    SetAverageC1ToZeroStage,
    DeriveTransportA4C2ImpactsStage,
    ValidateAveragedImpactsStage,
    BuildReportStage,
)
from materia_epd.pipeline.context import EpdPipelineContext


class RecipeFactory:
    def build(self, ctx: EpdPipelineContext) -> list[PipelineStage]:
        if ctx.matches.get("type") == "average":
            return [
                PrefilterByUuidStage(),
                FilterByUnitStage(),
                FallbackToMassStage(),
                ComputeAveragePropertiesStage(),
                ValidateMassConversionStage(),
                ComputeAverageImpactsStage(),
                SetAverageC1ToZeroStage(),
                DeriveTransportA4C2ImpactsStage(),
                ValidateAveragedImpactsStage(),
                BuildReportStage(),
            ]
        if ctx.matches.get("type") == "market-average":
            return [
                PrefilterByUuidStage(),
                FilterByUnitStage(),
                FallbackToMassStage(),
                ComputeAveragePropertiesStage(),
                ValidateMassConversionStage(),
                ComputeMarketAverageImpactsStage(),
                SetAverageC1ToZeroStage(),
                DeriveTransportA4C2ImpactsStage(),
                ValidateAveragedImpactsStage(),
                BuildReportStage(),
            ]
        else:
            raise ValueError(f"Unknown pipeline type: {ctx.matches.get('type')}")
