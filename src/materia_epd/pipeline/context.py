from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EpdPipelineContext:
    process: Any | None = None
    matches: dict[str, Any] | None = None
    all_epds: list[Any] = field(default_factory=list)

    matched_epds: list[Any] = field(default_factory=list)
    filtered_epds: list[Any] = field(default_factory=list)
    rejected_epds: list[tuple[str, str]] = field(default_factory=list)
    missing_epds: list[tuple[str, str]] = field(default_factory=list)
    unmatched_epds: list[tuple[str, str]] = field(default_factory=list)

    market_epds: dict[str, list[Any]] = field(default_factory=dict)
    market_impacts: dict[str, Any] = field(default_factory=dict)

    avg_properties: dict[str, Any] | None = None
    avg_gwps: dict[str, Any] | None = None
    report: Any | None = None

    used_mass_fallback: bool = False
    recipe_type: str | None = None
    active_material_kwargs: dict[str, Any] | None = None
    active_dec_unit: str | None = None

    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    stopped: bool = False
    success: bool = True

    def add_diagnostic(self, kind: str, message: str, **extra: Any) -> None:
        self.diagnostics.append(
            {
                "kind": kind,
                "message": message,
                **extra,
            }
        )

    def stop(self, success: bool = False) -> None:
        self.stopped = True
        self.success = success
