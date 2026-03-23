from __future__ import annotations

from materia_epd.pipeline.stages import (
    PipelineStage,
    PrefilterByUuidStage,
    FilterByUnitStage,
    FallbackToMassStage,
    ComputeAveragePropertiesStage,
    ComputeAverageImpactsStage,
    ComputeMarketAverageImpactsStage,
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
                ComputeAverageImpactsStage(),
                ValidateAveragedImpactsStage(),
                BuildReportStage(),
            ]
        if ctx.matches.get("type") == "market-average":
            return [
                PrefilterByUuidStage(),
                FilterByUnitStage(),
                FallbackToMassStage(),
                ComputeAveragePropertiesStage(),
                ComputeMarketAverageImpactsStage(),
                ValidateAveragedImpactsStage(),
                BuildReportStage(),
            ]
        else:
            raise ValueError(f"Unknown pipeline type: {ctx.matches.get('type')}")
