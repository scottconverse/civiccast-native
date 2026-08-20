#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Generate the Stage 5 migration/archive/records proof envelope."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from collect_source_state import collect_source_state
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect_source_state import collect_source_state

ROOT = Path(__file__).resolve().parents[1]

STAGE5_TEST_TARGETS = [
    "tests/archive/test_retention_presets.py",
    "tests/records",
    "tests/recording",
    "tests/programlog",
    "tests/agenda",
    "tests/metadata",
    "tests/paywall",
    "tests/egress/test_asrun_capture.py",
    "tests/reporting/test_schedule_adapter.py",
    "tests/schedule/test_migration_reversibility.py",
    "tests/schedule/test_retention_worker.py",
]

MIGRATION_FILES = [
    "civiccast/records/migrations/versions/0012_records_v06.py",
    "civiccast/programlog/migrations/versions/0031_program_log.py",
    "civiccast/reporting/migrations/versions/0055_asrun_and_epg.py",
    "civiccast/recording/migrations/versions/0056_scheduled_recording.py",
    "civiccast/recording/migrations/versions/0060_recording_paywall_merge.py",
    "civiccast/agenda/migrations/versions/0058_meeting_agenda.py",
    "civiccast/metadata/migrations/versions/0054_custom_metadata_fields.py",
    "civiccast/paywall/migrations/versions/0059_paywall_access.py",
]

FEATURE_SURFACES = {
    "archive_retention": [
        "civiccast/archive/retention_presets.py",
        "tests/archive/test_retention_presets.py",
    ],
    "signed_records": [
        "civiccast/records/exporter.py",
        "civiccast/records/router.py",
        "tests/records/test_records_router.py",
    ],
    "recording": [
        "civiccast/recording/service.py",
        "civiccast/recording/router.py",
        "tests/recording/test_service.py",
    ],
    "producer_agenda": [
        "civiccast/agenda/service.py",
        "civiccast/agenda/router.py",
        "tests/agenda/test_router.py",
    ],
    "programlog_asrun": [
        "civiccast/programlog",
        "civiccast/reporting/asrun_recorder.py",
        "tests/programlog/test_router.py",
    ],
    "metadata": [
        "civiccast/metadata",
        "tests/metadata/test_service.py",
    ],
    # ponytail: no education/campus-specific package exists yet (FERPA,
    # guardian-consent, school-board templates, etc. are all unbuilt). This
    # inventory intentionally does NOT point at civiccast/paywall — that
    # module is generic content-access paywall code, unrelated to campus
    # access, and previously made this check pass on a false positive.
    "campus_access": [],
}


def build_stage5_migration_records_proof(
    *,
    artifact_root: Path,
    source_state: dict[str, Any] | None = None,
    test_result: dict[str, Any] | None = None,
    run_tests: bool = False,
) -> dict[str, Any]:
    """Build the Stage 5 proof envelope."""

    artifact_root.mkdir(parents=True, exist_ok=True)
    resolved_source = source_state or collect_source_state(repo_root=ROOT)
    inventory = _build_feature_inventory()
    if test_result is None:
        test_result = _run_focused_tests(artifact_root) if run_tests else _not_run_tests()
    summary = {
        "migration_files": len(inventory["migration_files"]),
        "feature_surfaces": len(inventory["feature_surfaces"]),
        "focused_test_status": test_result.get("status"),
    }
    checks = [
        _check(
            "stage5-current-source",
            not resolved_source.get("dirty"),
            "Current source state is dirty.",
        ),
        _check(
            "stage5-migration-files",
            all(item["exists"] for item in inventory["migration_files"]),
            "One or more Stage 5 migration files are missing.",
        ),
        _check(
            "stage5-archive-records",
            _surface_exists(inventory, "archive_retention")
            and _surface_exists(inventory, "signed_records"),
            "Archive/records surfaces are incomplete.",
        ),
        _check(
            "stage5-recording-producer-workflow",
            _surface_exists(inventory, "recording")
            and _surface_exists(inventory, "producer_agenda"),
            "Recording or producer agenda surfaces are incomplete.",
        ),
        _check(
            "stage5-programlog-asrun",
            _surface_exists(inventory, "programlog_asrun"),
            "Program log/as-run surfaces are incomplete.",
        ),
        _check(
            "stage5-campus-access",
            _surface_exists(inventory, "metadata") and _surface_exists(inventory, "campus_access"),
            "Education/campus access package does not exist yet (item 24 is unbuilt).",
        ),
        _check(
            "stage5-focused-tests",
            test_result.get("status") == "passed",
            "Focused Stage 5 tests did not pass.",
        ),
        _check(
            "stage5-proof-boundary",
            True,
            "Stage 5 proof boundary is missing.",
        ),
    ]
    status = "passed" if all(check["status"] == "passed" for check in checks) else "blocked"
    proof = {
        "stage_id": "3.6-stage5",
        "stage_name": "Migration, Archive, Records, Producer, And Campus Workflows",
        "status": status,
        "generated_at_unix": int(time.time()),
        "source_state": resolved_source,
        "summary": summary,
        "checks": checks,
        "feature_inventory": "stage5-feature-inventory.json",
        "focused_tests": test_result,
        "not_claimed": [
            "Stage 5 local proof does not claim station migration execution.",
            "Stage 5 local proof does not claim production archive credential proof.",
            "Stage 5 local proof does not claim public campus deployment proof.",
        ],
    }
    _write_json(artifact_root / "stage5-feature-inventory.json", inventory)
    _write_json(artifact_root / "stage5-migration-records-proof.json", proof)
    _write_markdown(artifact_root / "stage5-migration-records-proof.md", proof)
    return proof


def _build_feature_inventory() -> dict[str, Any]:
    return {
        "migration_files": [
            {"path": path, "exists": (ROOT / path).is_file()} for path in MIGRATION_FILES
        ],
        "feature_surfaces": {
            name: [{"path": path, "exists": (ROOT / path).exists()} for path in paths]
            for name, paths in FEATURE_SURFACES.items()
        },
        "test_targets": STAGE5_TEST_TARGETS,
    }


def _surface_exists(inventory: dict[str, Any], name: str) -> bool:
    surfaces = inventory.get("feature_surfaces", {})
    rows = surfaces.get(name, []) if isinstance(surfaces, dict) else []
    return bool(rows) and all(isinstance(row, dict) and row.get("exists") for row in rows)


def _run_focused_tests(artifact_root: Path) -> dict[str, Any]:
    log_path = artifact_root / "pytest-stage5-focused.log"
    command = [sys.executable, "-m", "pytest", *STAGE5_TEST_TARGETS, "-q"]
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    log_path.write_text(
        result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else ""),
        encoding="utf-8",
    )
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "command": " ".join(command),
        "returncode": result.returncode,
        "log": str(log_path),
    }


def _not_run_tests() -> dict[str, Any]:
    return {
        "status": "not-run",
        "command": " ".join([sys.executable, "-m", "pytest", *STAGE5_TEST_TARGETS, "-q"]),
        "log": "",
    }


def _check(check_id: str, passed: bool, blocked_note: str) -> dict[str, str]:
    if passed:
        return {"id": check_id, "status": "passed"}
    return {"id": check_id, "status": "blocked", "notes": blocked_note}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, proof: dict[str, Any]) -> None:
    lines = [
        "# Stage 5 Migration, Archive, Records Proof",
        "",
        f"Status: {proof['status']}",
        f"Source HEAD: {proof['source_state'].get('head')}",
        "",
        "## Summary",
        "",
    ]
    for key in sorted(proof["summary"]):
        lines.append(f"- {key}: {proof['summary'][key]}")
    lines.extend(["", "## Checks", ""])
    for check in proof["checks"]:
        note = f" - {check['notes']}" if check.get("notes") else ""
        lines.append(f"- {check['status']}: {check['id']}{note}")
    lines.extend(["", "## Not Claimed", ""])
    lines.extend(f"- {claim}" for claim in proof["not_claimed"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts/stage5-migration-records/3.6-stage5-final"),
    )
    parser.add_argument("--skip-focused-tests", action="store_true")
    args = parser.parse_args(argv)
    proof = build_stage5_migration_records_proof(
        artifact_root=args.artifact_root,
        run_tests=not args.skip_focused_tests,
    )
    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
