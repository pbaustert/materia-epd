from __future__ import annotations

from materia_epd.pipeline.stages import PipelineStage
from materia_epd.pipeline.context import EpdPipelineContext


class Pipeline:
    def __init__(self, stages: list[PipelineStage]):
        self.stages = stages

    def run(self, ctx: EpdPipelineContext) -> EpdPipelineContext:
        for stage in self.stages:
            if ctx.stopped:
                break
            stage.run(ctx)
        return ctx
