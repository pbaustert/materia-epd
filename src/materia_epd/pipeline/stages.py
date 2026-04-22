from typing import Protocol
from collections import defaultdict

from materia_epd.pipeline.context import EpdPipelineContext
from materia_epd.core.constants import _TOL_ABS
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
from materia_epd.geo.locations import get_transport_impact_per_kg
from materia_epd.geo.locations import get_location_attribute


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


class ValidateMassConversionStage:
    name = "validate-mass-conversion"

    _REQUIRED_PROP = {
        "volume": "gross_density",
        "surface": "grammage",
        "length": "linear_density",
        "unit_count": "weight_per_piece",
    }

    def run(self, ctx: EpdPipelineContext) -> None:
        if ctx.avg_properties is None:
            ctx.add_diagnostic(
                kind="error",
                message="Mass conversion validation failed.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
            )
            ctx.stop(success=False)
            return

        dec_unit = ctx.active_dec_unit
        if dec_unit == "mass":
            return

        mass = ctx.avg_properties.get("mass")
        required_prop = self._REQUIRED_PROP.get(dec_unit)
        prop_value = ctx.avg_properties.get(required_prop)
        
        if mass is None or prop_value is None:
            ctx.add_diagnostic(
                kind="error",
                message="Mass conversion validation failed.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
            )
            ctx.stop(success=False)


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


class SetAverageC1ToZeroStage:
    name = "set-average-c1-to-zero"

    def run(self, ctx: EpdPipelineContext) -> None:
        if ctx.avg_gwps is None:
            return

        for indicator_modules in ctx.avg_gwps.values():
            indicator_modules["C1"] = 0.0

        ctx.add_diagnostic(
            kind="info",
            message="Set averaged C1 impacts to zero.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            indicators=len(ctx.avg_gwps),
        )


class LoadAssembledComponentsStage:
    name = "load-assembled-components"

    def run(self, ctx: EpdPipelineContext) -> None:
        components = (ctx.matches or {}).get("components")
        if not isinstance(components, list) or not components:
            ctx.add_diagnostic(
                kind="error",
                message="Assembled pipeline requires a non-empty components list.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
            )
            ctx.stop(success=False)
            return

        normalized_components: list[dict[str, float | str]] = []
        for idx, component in enumerate(components):
            process_uuid = component.get("process_uuid")
            quantity = component.get("quantity")
            unit = component.get("unit")

            if not process_uuid or not isinstance(process_uuid, str):
                ctx.add_diagnostic(
                    kind="error",
                    message="Assembled component is missing a valid process_uuid.",
                    stage=self.name,
                    process_uuid=ctx.process.uuid,
                    component_index=idx,
                )
                ctx.stop(success=False)
                return

            if not isinstance(quantity, (int, float)) or quantity <= 0:
                ctx.add_diagnostic(
                    kind="error",
                    message="Assembled component quantity must be a positive number.",
                    stage=self.name,
                    process_uuid=ctx.process.uuid,
                    component_index=idx,
                    component_process_uuid=process_uuid,
                    quantity=quantity,
                )
                ctx.stop(success=False)
                return

            if unit is not None and not isinstance(unit, str):
                ctx.add_diagnostic(
                    kind="error",
                    message="Assembled component unit must be a string when provided.",
                    stage=self.name,
                    process_uuid=ctx.process.uuid,
                    component_index=idx,
                    component_process_uuid=process_uuid,
                )
                ctx.stop(success=False)
                return

            normalized_components.append(
                {
                    "process_uuid": process_uuid,
                    "quantity": float(quantity),
                    "unit": unit or "mass",
                }
            )

        ctx.assembled_components = normalized_components
        ctx.add_diagnostic(
            kind="info",
            message="Assembled components loaded.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            components=len(ctx.assembled_components),
        )


class ResolveComponentResultsStage:
    name = "resolve-component-results"

    def run(self, ctx: EpdPipelineContext) -> None:
        missing_components: list[str] = []
        resolved: dict[str, dict[str, dict[str, float]]] = {}
        reports: dict[str, dict] = {}

        for component in ctx.assembled_components:
            component_uuid = component["process_uuid"]
            result = ctx.results_registry.get(component_uuid, {})
            impacts = result.get("avg_gwps")
            if not isinstance(impacts, dict):
                missing_components.append(component_uuid)
                continue

            resolved[component_uuid] = impacts
            if isinstance(result.get("report"), dict):
                reports[component_uuid] = result["report"]

        if missing_components:
            ctx.add_diagnostic(
                kind="error",
                message="Missing precomputed component results for assembled pipeline.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
                missing_components=missing_components,
            )
            ctx.stop(success=False)
            return

        ctx.component_impacts = resolved
        ctx.component_reports = reports
        ctx.add_diagnostic(
            kind="info",
            message="Resolved precomputed impacts for assembled components.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            resolved_components=len(ctx.component_impacts),
        )


class AggregateComponentImpactsStage:
    name = "aggregate-component-impacts"

    def run(self, ctx: EpdPipelineContext) -> None:
        aggregated: dict[str, dict[str, float]] = defaultdict(dict)

        for component in ctx.assembled_components:
            component_uuid = component["process_uuid"]
            quantity = component["quantity"]
            impacts = ctx.component_impacts.get(component_uuid, {})

            for indicator, modules in impacts.items():
                indicator_modules = aggregated.setdefault(indicator, {})
                for module, value in modules.items():
                    indicator_modules[module] = indicator_modules.get(module, 0.0) + (
                        quantity * float(value)
                    )

        ctx.avg_gwps = {
            indicator: {module: round(value, 6) for module, value in modules.items()}
            for indicator, modules in aggregated.items()
        }

        ctx.unmatched_epds = []
        ctx.add_diagnostic(
            kind="info",
            message="Aggregated assembled impacts using quantity-weighted sum-product.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            indicators=len(ctx.avg_gwps),
            components=len(ctx.assembled_components),
        )


class AggregateComponentPropertiesStage:
    name = "aggregate-component-properties"

    _ADDITIVE_FIELDS = {"mass", "volume", "surface", "length", "unit_count"}
    _NON_ADDITIVE_FIELDS = {
        "gross_density",
        "grammage",
        "linear_density",
        "layer_thickness",
        "cross_sectional_area",
        "weight_per_piece",
    }

    def run(self, ctx: EpdPipelineContext) -> None:
        totals: dict[str, float] = {key: 0.0 for key in self._ADDITIVE_FIELDS}
        missing_properties: list[str] = []

        for component in ctx.assembled_components:
            component_uuid = component["process_uuid"]
            quantity = component["quantity"]
            result = ctx.results_registry.get(component_uuid, {})
            props = result.get("avg_properties")
            if not isinstance(props, dict):
                missing_properties.append(component_uuid)
                continue

            for field in self._ADDITIVE_FIELDS:
                value = props.get(field)
                if isinstance(value, (int, float)):
                    totals[field] += quantity * float(value)

        if missing_properties:
            ctx.add_diagnostic(
                kind="warning",
                message="Some assembled components had no properties; additive totals are partial.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
                missing_components=missing_properties,
            )

        ctx.avg_properties = {**totals, **{k: None for k in self._NON_ADDITIVE_FIELDS}}
        ctx.add_diagnostic(
            kind="info",
            message="Aggregated additive physical properties for assembled product.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            properties=sorted(self._ADDITIVE_FIELDS),
        )


class DeriveTransportA4C2ImpactsStage:
    name = "derive-transport-a4-c2-impacts"

    def run(self, ctx: EpdPipelineContext) -> None:
        if ctx.avg_gwps is None:
            return

        mass = (ctx.avg_properties or {}).get("mass")
        if not isinstance(mass, (int, float)):
            ctx.add_diagnostic(
                kind="warning",
                message="Skipped A4/C2 transport derivation because mass is unavailable.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
            )
            return

        target_location = ctx.process.loc
        grouped_market = self._aggregate_market_by_transport_location(
            ctx.process.market or {}, target_location
        )
        weighted_impacts_per_kg: dict[str, float] = {}
        total_share = 0.0
        missing_locations: list[str] = []
        for source_location, share in grouped_market.items():
            impacts_per_kg = get_transport_impact_per_kg(source_location, target_location)
            if not impacts_per_kg:
                missing_locations.append(source_location)
                continue

            total_share += share
            for indicator, value in impacts_per_kg.items():
                weighted_impacts_per_kg[indicator] = (
                    weighted_impacts_per_kg.get(indicator, 0.0) + share * value
                )

        if total_share <= 0:
            ctx.add_diagnostic(
                kind="warning",
                message="Skipped A4 transport derivation because no transport factors were available for market entries.",  # noqa: E501
                stage=self.name,
                process_uuid=ctx.process.uuid,
                missing_locations=missing_locations,
            )
            return

        for indicator, weighted_value in weighted_impacts_per_kg.items():
            per_kg = weighted_value / total_share
            a4_value = per_kg * mass
            indicator_modules = ctx.avg_gwps.setdefault(indicator, {})
            indicator_modules["A4"] = round(a4_value, 6)

        local_c2_impacts = (
            get_transport_impact_per_kg(target_location, target_location)
            if target_location
            else {}
        )
        for indicator, per_kg in local_c2_impacts.items():
            c2_value = per_kg * mass
            indicator_modules = ctx.avg_gwps.setdefault(indicator, {})
            indicator_modules["C2"] = round(c2_value, 6)

        ctx.add_diagnostic(
            kind="info",
            message="Derived A4/C2 transport impacts from mass and location data.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            mass=mass,
            target_location=target_location,
            grouped_market=grouped_market,
            missing_locations=missing_locations,
            local_c2_available=bool(local_c2_impacts),
        )

    @staticmethod
    def _aggregate_market_by_transport_location(
        market: dict[str, float], target_location: str | None
    ) -> dict[str, float]:
        grouped_market: dict[str, float] = {}
        for source_location, share in market.items():
            if source_location == "RoW":
                continue

            if target_location and source_location == target_location:
                grouped_key = target_location
            else:
                try:
                    parent = get_location_attribute(source_location, "Parent")
                except Exception:
                    parent = None
                grouped_key = parent or source_location

            grouped_market[grouped_key] = grouped_market.get(grouped_key, 0.0) + share

        return grouped_market


class BuildReportStage:
    name = "build-report"

    def run(self, ctx: EpdPipelineContext) -> None:
        from materia_epd.pipeline.report import build_report

        initial_candidates = len(ctx.process.matches.get("uuids", []))
        if not initial_candidates:
            initial_candidates = len(ctx.assembled_components)

        ctx.report = build_report(
            report_uuid=ctx.process.uuid,
            process=ctx.process,
            epd_entries=ctx.filtered_epds,
            avg_impacts=ctx.avg_gwps,
            avg_physical=ctx.avg_properties,
            initial_epds=initial_candidates,
            selected_epds=len(ctx.filtered_epds) or len(ctx.assembled_components),
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

        if imbalance < 0 and abs(imbalance) > _TOL_ABS:
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
