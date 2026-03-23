from typing import Protocol

from materia_epd.pipeline.context import EpdPipelineContext
from materia_epd.core.constants import _TOL_ABS
from materia_epd.pipeline.report import build_report
from materia_epd.epd.filters import (
    UUIDFilter,
    UnitConformityFilter,
    LocationFilter,
    get_filtered_epds,
    get_locfiltered_epds,
)
from materia_epd.core.constants import MASS_KWARGS
from materia_epd.core.physics import Material
from materia_epd.metrics.averaging import (
    average_impacts,
    average_material_properties,
    market_weighted_impacts,
)


class PipelineStage(Protocol):
    name: str

    def run(self, ctx: EpdPipelineContext) -> None:
        ...


class PrefilterByUuidStage:
    name = "prefilter-by-uuid"

    def run(self, ctx: EpdPipelineContext) -> None:
        matched_epds, _ = get_filtered_epds(
            ctx.all_epds, UUIDFilter(ctx.process.matches)
        )

        ctx.matched_epds = matched_epds

        matched_uuids = {epd.uuid for epd in matched_epds}
        for uuid in ctx.process.matches["uuids"]:
            if uuid not in matched_uuids:
                ctx.missing_epds.append((uuid, "EPD was not found in provided folder."))

        ctx.add_diagnostic(
            kind="info",
            message="UUID prefilter completed.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            requested=len(ctx.process.matches["uuids"]),
            matched=len(ctx.matched_epds),
            missing=len(ctx.missing_epds),
        )

        if not ctx.matched_epds:
            ctx.add_diagnostic(
                kind="error",
                message="No matching EPDs found after UUID prefilter.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
            )
            ctx.stop(success=False)


class FilterByUnitStage:
    name = "filter-by-unit"

    def run(self, ctx: EpdPipelineContext) -> None:
        filtered_epds, rejected_epds = get_filtered_epds(
            ctx.matched_epds, UnitConformityFilter(ctx.active_material_kwargs)
        )

        ctx.filtered_epds = filtered_epds
        ctx.rejected_epds = rejected_epds

        ctx.add_diagnostic(
            kind="info",
            message="Unit conformity filter completed.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            dec_unit=ctx.active_dec_unit,
            input_epds=len(ctx.matched_epds),
            filtered=len(ctx.filtered_epds),
            rejected=len(ctx.rejected_epds),
        )

        if not ctx.filtered_epds:
            ctx.add_diagnostic(
                kind="warning",
                message="No EPDs passed unit conformity filtering.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
                dec_unit=ctx.active_dec_unit,
            )


class FallbackToMassStage:
    name = "fallback-to-mass"

    def run(self, ctx: EpdPipelineContext) -> None:
        if ctx.filtered_epds:
            return

        ctx.used_mass_fallback = True

        ctx.add_diagnostic(
            kind="warning",
            message="Switched to mass-based functional unit.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            previous_dec_unit=ctx.active_dec_unit,
            new_dec_unit="mass",
        )

        ctx.active_material_kwargs = MASS_KWARGS
        ctx.active_dec_unit = "mass"

        filtered_epds, rejected_epds = get_filtered_epds(
            ctx.matched_epds, UnitConformityFilter(ctx.active_material_kwargs)
        )

        ctx.filtered_epds = filtered_epds
        ctx.rejected_epds = rejected_epds

        ctx.add_diagnostic(
            kind="info",
            message="Mass fallback filtering completed.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            dec_unit=ctx.active_dec_unit,
            filtered=len(ctx.filtered_epds),
            rejected=len(ctx.rejected_epds),
        )

        if not ctx.filtered_epds:
            ctx.add_diagnostic(
                kind="error",
                message="No EPDs passed filtering even after mass fallback.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
            )
            ctx.stop(success=False)


class ComputeAveragePropertiesStage:
    name = "compute-average-properties"

    def run(self, ctx: EpdPipelineContext) -> None:
        for epd in ctx.filtered_epds:
            epd.get_lcia_results()

        avg_properties = average_material_properties(ctx.filtered_epds)
        mat = Material(**avg_properties)
        mat.rescale(ctx.active_material_kwargs)
        ctx.avg_properties = mat.to_dict()

        ctx.add_diagnostic(
            kind="info",
            message="Average material properties computed.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            selected_epds=len(ctx.filtered_epds),
            dec_unit=ctx.active_dec_unit,
        )


class ComputeAverageImpactsStage:
    name = "compute-average-impacts"

    def run(self, ctx: EpdPipelineContext) -> None:
        ctx.avg_gwps = average_impacts([epd.lcia_results for epd in ctx.filtered_epds])
        ctx.unmatched_epds = []

        ctx.add_diagnostic(
            kind="info",
            message="Simple average impacts computed without market weighting.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            selected_epds=len(ctx.filtered_epds),
            unmatched_epds=len(ctx.unmatched_epds),
        )


class ComputeMarketAverageImpactsStage:
    name = "compute-market-average-impacts"

    def run(self, ctx: EpdPipelineContext) -> None:
        market_epds = {
            country: list(
                get_locfiltered_epds(ctx.filtered_epds, LocationFilter({country}))
            )
            for country in ctx.process.market
        }
        ctx.market_epds = market_epds

        matched_market_uuids = {
            epd.uuid for country_epds in market_epds.values() for epd in country_epds
        }

        ctx.unmatched_epds = []
        for epd in ctx.filtered_epds:
            if epd.uuid not in matched_market_uuids:
                ctx.unmatched_epds.append(
                    (epd.uuid, "EPD has no appropriate location in market.")
                )

        ctx.market_impacts = {
            country: average_impacts([epd.lcia_results for epd in country_epds])
            for country, country_epds in market_epds.items()
        }

        ctx.avg_gwps = market_weighted_impacts(ctx.process.market, ctx.market_impacts)

        ctx.add_diagnostic(
            kind="info",
            message="Market-based average impacts computed.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            market_countries=len(ctx.process.market),
            matched_countries=len(ctx.market_impacts),
            unmatched_epds=len(ctx.unmatched_epds),
        )


class BuildReportStage:
    name = "build-report"

    def run(self, ctx: EpdPipelineContext) -> None:
        ctx.report = build_report(
            report_uuid=ctx.process.uuid,
            epd_entries=ctx.filtered_epds,
            avg_impacts=ctx.avg_gwps,
            avg_physical=ctx.avg_properties,
            initial_epds=len(ctx.process.matches["uuids"]),
            selected_epds=len(ctx.filtered_epds),
            rejected_epds=ctx.rejected_epds + ctx.missing_epds + ctx.unmatched_epds,
        )

        ctx.add_diagnostic(
            kind="info",
            message="Report built successfully.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            selected_epds=len(ctx.filtered_epds),
            rejected=len(ctx.rejected_epds),
            missing=len(ctx.missing_epds),
            unmatched=len(ctx.unmatched_epds),
        )


class ValidateAveragedImpactsStage:
    name = "validate-averaged-impacts"

    def run(self, ctx: EpdPipelineContext) -> None:
        gwps = ctx.avg_gwps
        T = gwps.get("Climate change-Total", {})
        F = gwps.get("Climate change-Fossil", {})
        B = gwps.get("Climate change-Biogenic", {})
        L = gwps.get("Climate change-Land use and land use change", {})

        # 1. Biogenic balance correction
        A = B.get("A1-A3", 0.0)
        C3 = B.get("C3", 0.0)
        C4 = B.get("C4", 0.0)

        imbalance = A + C3 + C4

        if abs(imbalance) > _TOL_ABS:
            # Push correction to C4
            new_C4 = C4 - imbalance

            B["C4"] = new_C4
            ctx.add_diagnostic(
                kind="warning",
                message="Biogenic carbon imbalance corrected.",
                stage=self.name,
                old_C4=C4,
                new_C4=new_C4,
                imbalance=imbalance,
            )

        # 2. Recompute all totals from components
        for module in set(T) | set(F) | set(B) | set(L):
            fossil = F.get(module, 0.0)
            bio = B.get(module, 0.0)
            luluc = L.get(module, 0.0)

            new_total = fossil + bio + luluc
            old_total = T.get(module, 0.0)

            if abs(new_total - old_total) > _TOL_ABS:
                rel_change = (
                    None
                    if abs(old_total) < 1e-12
                    else (new_total - old_total) / abs(old_total)
                )
                T[module] = new_total

                ctx.add_diagnostic(
                    kind="warning",
                    message="Total climate change value corrected to match components.",
                    stage=self.name,
                    module=module,
                    old_total=old_total,
                    new_total=new_total,
                    relative_change=rel_change,
                )

        ctx.add_diagnostic(
            kind="info",
            message="Averaged climate change indicators validated.",
            stage=self.name,
        )
