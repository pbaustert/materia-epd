from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from pathlib import Path
from materia_epd.epd.models import IlcdProcess


def build_report(
    report_uuid: str,
    epd_entries: List[IlcdProcess],
    avg_impacts: Dict[str, Dict[str, Any]],
    avg_physical: Dict[str, Any],
    initial_epds: int,
    selected_epds: int,
) -> Dict[str, Any]:
    report = {
        "meta": {
            "report_uuid": report_uuid,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "pipeline": {"initial_epds": initial_epds, "selected_epds": selected_epds},
            "indicators": list(avg_impacts.keys()),
        },
        "epds": [],
        "average": {
            "physical": avg_physical,
            "impacts": avg_impacts,
        },
    }

    for epd in epd_entries:
        report["epds"].append(
            {
                "epd_uuid": epd.uuid,
                "physical": epd.material.to_dict(),
                "impacts": epd.lcia_results,
            }
        )

    return report


def write_report(report: Dict[str, Any], out_path: Path, report_uuid: str):
    """
    Write the report dict to: <out_path>/reports/<report_uuid>.json

    Returns the written file path.
    """
    reports_dir = out_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    file_path = reports_dir / f"{report_uuid}.json"
    with file_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
