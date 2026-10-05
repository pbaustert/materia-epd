from typing import Protocol
from collections import defaultdict
import numpy as np

from materia_epd.pipeline.context import EpdPipelineContext
from materia_epd.core.constants import _TOL_ABS
from materia_epd.epd.filters import (
    UUIDFilter,
    UnitConformityFilter,
    LocationFilter,
    get_filtered_epds,
    get_locfiltered_epds,
)
from materia_epd.core.physics import Material
from materia_epd.metrics.averaging import (
    average_impacts,
    average_material_properties,
    market_weighted_impacts,
)
from materia_epd.geo.locations import get_transport_impact_per_kg
from materia_epd.geo.locations import get_location_attribute
from materia_epd.resources import get_tech_shares
from materia_epd.doc.report import build_report_json


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
                kind="error",
                message="No EPDs passed unit conformity filtering.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
                dec_unit=ctx.active_dec_unit,
            )


class ComputeAveragePropertiesStage:
    name = "compute-average-properties"

    def run(self, ctx: EpdPipelineContext) -> None:
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
                missing_mass=mass is None,
                missing_required_prop=prop_value is None,
                required_prop=required_prop,
            )
            ctx.stop(success=False)


class ComputeAverageImpactsStage:
    name = "compute-average-impacts"

    def run(self, ctx: EpdPipelineContext) -> None:
        for epd in ctx.filtered_epds:
            epd.get_lcia_results()
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
            epd.get_lcia_results()
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
        normalized_components: list[dict[str, float | str]] = []
        for component in components:
            process_uuid = component.get("uuid")
            quantity = component.get("quantity")
            unit = component.get("unit")

            normalized_components.append(
                {
                    "uuid": process_uuid,
                    "quantity": float(quantity),
                    "unit": unit,
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
        mass_composition = []

        for component in ctx.assembled_components:
            component_uuid = component["uuid"]
            result = ctx.results_registry.get(component_uuid, {})
            component_name = result["report"]["meta"]["product"]["names_by_language"][
                "en"
            ]
            mat = Material(**result["avg_properties"])

            rescal_kwargs = {
                "surface": None,
                "mass": None,
                "unit_count": None,
                "weight_per_piece": None,
                "length": None,
                "layer_thickness": None,
                "linear_density": None,
                "cross_sectional_area": None,
                "gross_density": None,
                "grammage": None,
                "volume": None,
            }

            if component["unit"] == "kg":
                rescal_kwargs["mass"] = component["quantity"]

            if component["unit"] == "m3":
                rescal_kwargs["volume"] = component["quantity"]

            if component["unit"] == "m2":
                rescal_kwargs["surface"] = component["quantity"]

            if component["unit"] == "m":
                rescal_kwargs["length"] = component["quantity"]

            if component["unit"] == "unit":
                rescal_kwargs["unit_count"] = component["quantity"]

            mat.rescale(rescal_kwargs)
            component_quantities = mat.to_dict()
            component_mass = component_quantities["mass"]

            mass_composition.append({"name": component_name, "mass": component_mass})

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
        ctx.mass_composition = mass_composition
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
            component_uuid = component["uuid"]
            quantity = component["quantity"]
            impacts = ctx.component_impacts.get(component_uuid, {})

            for indicator, modules in impacts.items():
                indicator_modules = aggregated.setdefault(indicator, {})
                for module, value in modules.items():
                    if module == "A4":
                        indicator_modules["A1-A3"] = indicator_modules.get(
                            "A1-A3", 0.0
                        ) + (quantity * float(value))
                    else:
                        indicator_modules[module] = indicator_modules.get(
                            module, 0.0
                        ) + (quantity * float(value))

        ctx.avg_gwps = {
            indicator: {module: round(value, 6) for module, value in modules.items()}
            for indicator, modules in aggregated.items()
        }

        ctx.unmatched_epds = []
        ctx.add_diagnostic(
            kind="info",
            message="Aggregated assembled impacts.",
            stage=self.name,
            process_uuid=ctx.process.uuid,
            indicators=len(ctx.avg_gwps),
            components=len(ctx.assembled_components),
        )


class AssembledPropertiesStage:
    name = "assembled-properties"

    def run(self, ctx: EpdPipelineContext) -> None:
        if ctx.process and hasattr(ctx.process, "material") and ctx.process.material:
            mat = Material(**ctx.process.material.to_dict())
            mat._compute()
            ctx.avg_properties = mat.to_dict()


class DeriveTransportA4C2ImpactsStage:
    name = "derive-transport-a4-c2-impacts"

    def run(self, ctx: EpdPipelineContext) -> None:
        if ctx.avg_gwps is None:
            return

        # Check if A4/C2 calculation should be skipped
        if ctx.matches.get("skip_a4_c2"):
            return

        mass = (ctx.avg_properties or {}).get("mass")
        if not isinstance(mass, (int, float)):
            ctx.add_diagnostic(
                kind="warning",
                message="Skipped A4/C2 because mass is unavailable.",
                stage=self.name,
                process_uuid=ctx.process.uuid,
            )
            return

        target_location = ctx.process.loc

        # Check if Greater Region should be used instead of market shares
        if ctx.matches.get("use_greater_region"):
            grouped_market = {"Greater Region": 1.0}

        else:
            grouped_market = self._aggregate_market_by_transport_location(
                ctx.process.market or {}, target_location
            )

        weighted_impacts_per_kg: dict[str, float] = {}
        total_share = 0.0
        for source_location, share in grouped_market.items():
            impacts_per_kg = get_transport_impact_per_kg(
                source_location, target_location
            )
            total_share += share
            for indicator, value in impacts_per_kg.items():
                weighted_impacts_per_kg[indicator] = (
                    weighted_impacts_per_kg.get(indicator, 0.0) + share * value
                )

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


class LoadRegressionDataStage:
    name = "load-regression-data"

    def run(self, ctx: EpdPipelineContext) -> None:
        regression_data = ctx.matches.get("data", [])
        uuids = [entry["uuid"] for entry in regression_data]
        ctx.process.matches["uuids"] = uuids

        ctx.regression_data = {
            entry["uuid"]: {
                "technology": entry.get("technology"),
                "secondary material": entry.get("secondary material"),
            }
            for entry in regression_data
        }


class RegressionImpactsStage:
    name = "compute-regression-impacts"
    regression_modules = ("A1-A3", "D")

    @staticmethod
    def _features(entry, techs, secondary=None):
        technology = entry["technology"]
        secondary = (
            float(entry["secondary material"]) if secondary is None else secondary
        )
        return [1.0] + [(technology == tech) for tech in techs[:-1]] + [secondary]

    def run(self, ctx: EpdPipelineContext) -> None:
        techs = ctx.matches["metadata"]["technology"]
        if "BOF" in techs:
            techs = [t for t in techs if t != "BOF"] + ["BOF"]

        targets = set()
        for epd in ctx.filtered_epds:
            epd.get_lcia_results()
            targets.update(
                (r["name"], module)
                for r in epd.lcia_results
                for module in self.regression_modules
                if module in r["values"]
            )

        secondary_by_tech = defaultdict(list)
        for entry in ctx.regression_data.values():
            secondary_by_tech[entry["technology"]].append(
                float(entry["secondary material"])
            )
        avg_secondary = {t: np.mean(v) for t, v in secondary_by_tech.items()}

        beta = {}
        for indicator, module in targets:
            X, y = [], []
            for epd in ctx.filtered_epds:
                entry = ctx.regression_data.get(epd.uuid)
                value = next(
                    (
                        r["values"].get(module)
                        for r in epd.lcia_results
                        if r["name"] == indicator
                    ),
                    None,
                )
                if entry is None or value is None:
                    ctx.add_diagnostic(
                        kind="warning",
                        message="Missing regression data."
                        if entry is None
                        else f"Missing {module} value.",
                        stage=self.name,
                        process_uuid=ctx.process.uuid,
                        epd_uuid=epd.uuid,
                        indicator=indicator,
                    )
                    continue
                X.append(self._features(entry, techs))
                y.append(float(value))
            if X:
                beta[indicator, module] = np.linalg.lstsq(
                    np.asarray(X, dtype=float), np.asarray(y, dtype=float), rcond=None
                )[0]

        market_impacts = {}
        for country in ctx.process.market:
            tech_mix = get_tech_shares(country, ctx.process.hs_class)
            country_impacts = defaultdict(dict)

            for (indicator, module), coefficients in beta.items():
                country_impacts[indicator][module] = float(
                    sum(
                        share
                        * (
                            coefficients[0]
                            + (
                                coefficients[techs[:-1].index(tech) + 1]
                                if tech != "BOF"
                                else 0
                            )
                            + coefficients[-1] * avg_secondary.get(tech, 0)
                        )
                        for tech, share in tech_mix.items()
                        if share > 0
                    )
                )

            country_epds = get_locfiltered_epds(
                ctx.filtered_epds, LocationFilter({country})
            )
            if country_epds:
                for indicator, modules in average_impacts(
                    [epd.lcia_results for epd in country_epds]
                ).items():
                    for module, value in modules.items():
                        if module not in self.regression_modules:
                            country_impacts[indicator][module] = value

            market_impacts[country] = {
                indicator: dict(modules)
                for indicator, modules in country_impacts.items()
            }

        ctx.regression_models = {
            f"{ind} {mod}": {
                "intercept": float(coeffs[0]),
                "tech_coeffs": {
                    tech: float(coeffs[i + 1]) for i, tech in enumerate(techs[:-1])
                },
                "secondary_coeff": float(coeffs[-1]),
            }
            for (ind, mod), coeffs in beta.items()
        }

        ctx.market_impacts = market_impacts
        ctx.avg_gwps = market_weighted_impacts(ctx.process.market, market_impacts)
        ctx.unmatched_epds = []


class BuildReportStage:
    name = "build-report"

    def run(self, ctx: EpdPipelineContext) -> None:
        initial_candidates = len(ctx.process.matches.get("uuids", []))
        if not initial_candidates:
            initial_candidates = len(ctx.assembled_components)

        ctx.report = build_report_json(
            report_uuid=ctx.process.uuid,
            process=ctx.process,
            epd_entries=ctx.filtered_epds,
            avg_impacts=ctx.avg_gwps,
            avg_physical=ctx.avg_properties,
            initial_epds=initial_candidates,
            selected_epds=len(ctx.filtered_epds) or len(ctx.assembled_components),
            rejected_epds=ctx.rejected_epds + ctx.missing_epds + ctx.unmatched_epds,
            mass_composition=ctx.mass_composition,
            regression_models=ctx.regression_models
            if hasattr(ctx, "regression_models")
            else None,
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
        T = gwps.get("GWP-Total", {})
        F = gwps.get("GWP-Fossil", {})
        B = gwps.get("GWP-Biogenic", {})
        L = gwps.get("GWP-LULUC", {})

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
