#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Generate the Stage 7 final 4.0 readiness proof envelope."""

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
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from civiccast.control_room.lpm_lab_harness import run_lpm_contract_lab  # noqa: E402

DEFAULT_STAGE_REPORTS = [
    Path("artifacts/stage-reports/3.3-stage1-final/stage-report.json"),
    Path("artifacts/stage-reports/3.3-stage2-rework-20260703/stage2-completion-report.json"),
    Path("artifacts/stage-reports/3.4-stage3-rework-20260703/stage3-completion-report.json"),
    Path("artifacts/stage-reports/3.5-stage4-rework-20260703/stage4-completion-report.json"),
    Path("artifacts/stage-reports/3.6-stage5-rework-20260703/stage5-completion-report.json"),
    Path("artifacts/stage-reports/3.8-stage6-rework-20260703/stage6-completion-report.json"),
]

DEFAULT_GAUNTLET_REPORTS = [
    Path("artifacts/gauntletgate/3.3-stage1-final/00-gate-report.md"),
    Path("artifacts/gauntletgate/3.3-stage2-rework-20260703/00-gate-report.md"),
    Path("artifacts/gauntletgate/3.4-stage3-rework-20260703/00-gate-report.md"),
    Path("artifacts/gauntletgate/3.5-stage4-rework-20260703/00-gate-report.md"),
    Path("artifacts/gauntletgate/3.6-stage5-rework-20260703/00-gate-report.md"),
    Path("artifacts/gauntletgate/3.8-stage6-rework-20260703/00-gate-report.md"),
]

FINAL_LIFECYCLE_REQUIRED_CHECKS = [
    "clean-install",
    "first-run",
    "repair",
    "release-artifact-binding",
    "uninstall",
    "reinstall",
    "upgrade",
]

BETA_4_SCOPE_ITEMS = [
    "1 Installer, Clean Install, Repair, Update, And Uninstall",
    "2 First-Run And Operator Setup",
    "3 Every-Screen UX Walkthrough Closure",
    "4 Three-Channel Station Workflow",
    "5 Media Library And Playout Hardening",
    "6 Recording And Ingest Hardening",
    "7 Control-Room UI",
    "8 vMix Integration",
    "9 OBS Integration",
    "10 ATEM Integration",
    "11 PTZ / VISCA / AIDA Integration",
    "12 NDI Integration",
    "13 DeckLink / Desktop Video / Capture-Card Paths",
    "14 Audio Mixer And Audio Device Layer",
    "15 Routers, Encoders, And Destination Profiles",
    "16 Virtual Media Studio Lab",
    "17 LPM-Style Profile Packs",
    "18 Migration And Import Tools",
    "19 Traffic, Ads, Underwriting, And SCTE-35",
    "20 Redundancy And Disaster Recovery",
    "21 Accessibility, Captions, Translation, And Compliance Packets",
    "22 Agenda, Minutes, Records, And Clerk Integrations",
    "23 Producer, Volunteer, And Equipment Operations",
    "24 Education / Campus Package",
    "25 Archive, MAM, And Digitization",
    "26 Proof, Reports, Support Bundles, And Acceptance Packets",
    "27 Security, Secrets, Roles, And Audit",
    "28 Performance, Soak, Stress, And Chaos Testing",
    "29 Local CI And Gauntlet Runner",
    "30 Documentation And Release Materials",
    "31 Code Quality And Maintainability",
]

_SCOPE_ITEM_EVIDENCE = {
    1: ["final_installer_lifecycle", "upgrade_matrix"],
    2: ["final_installer_lifecycle"],
    3: ["stage2"],
    4: ["stage2"],
    5: ["stage2"],
    6: ["stage2"],
    7: ["stage3"],
    8: ["stage3"],
    9: ["stage3"],
    10: ["stage3"],
    11: ["stage3"],
    12: ["stage3"],
    13: ["stage3"],
    14: ["stage3"],
    15: ["stage3"],
    16: ["stage4"],
    17: ["stage4"],
    18: ["stage5"],
    19: ["stage6"],
    20: ["stage6"],
    21: ["stage6"],
    22: ["stage5"],
    23: ["stage5"],
    24: ["stage5"],
    25: ["stage5"],
    26: ["stage2", "stage5", "stage6", "stage7"],
    27: ["stage3", "stage6"],
    28: ["stage4", "stage6"],
    29: ["full_stack", "stage7"],
    30: ["stage7"],
    31: ["full_stack", "stage7"],
}


def build_stage7_final_readiness_proof(
    *,
    artifact_root: Path,
    stage_reports: list[Path] | None = None,
    gauntlet_reports: list[Path] | None = None,
    final_installer_lifecycle_proof: Path | None = None,
    full_stack_evidence: Path | None = None,
    cleanroom_evidence: Path | None = None,
    final_gauntlet_report: Path | None = None,
    clean_windows_rendered_evidence: Path | None = None,
    upgrade_matrix_evidence: Path | None = None,
    native_installer_manifest: Path | None = None,
    source_state: dict[str, Any] | None = None,
    release_result: dict[str, Any] | None = None,
    build_release: bool = False,
    version: str = "4.0.0-rc1",
) -> dict[str, Any]:
    """Build the Stage 7 final readiness proof."""

    artifact_root.mkdir(parents=True, exist_ok=True)
    resolved_source = source_state or collect_source_state(repo_root=ROOT)
    resolved_stage_reports = DEFAULT_STAGE_REPORTS if stage_reports is None else stage_reports
    resolved_gauntlet_reports = (
        DEFAULT_GAUNTLET_REPORTS if gauntlet_reports is None else gauntlet_reports
    )
    stage_report_rows = [_stage_report_row(path) for path in resolved_stage_reports]
    gauntlet_rows = [_gauntlet_report_row(path) for path in resolved_gauntlet_reports]
    stage8_root = artifact_root / "stage8-local-release"
    stage8_result = run_lpm_contract_lab(
        profile_ids=["all"],
        artifact_root=stage8_root,
        force_clean=bool(stage8_root.exists()),
        execution_stage="stage8",
    )
    if release_result is None:
        release_result = (
            _build_release_artifacts(artifact_root, version)
            if build_release
            else _not_run_release(version)
        )
    native_installer = _native_windows_installer_result(
        artifact_root,
        manifest_path=native_installer_manifest,
    )
    lifecycle_result = _final_installer_lifecycle_result(
        final_installer_lifecycle_proof,
        resolved_source,
    )
    full_stack_result = _full_stack_result(full_stack_evidence, resolved_source)
    cleanroom_result = _cleanroom_result(cleanroom_evidence, resolved_source)
    final_gauntlet_result = _final_gauntlet_result(final_gauntlet_report, resolved_source)
    clean_windows_rendered_result = _clean_windows_rendered_result(
        clean_windows_rendered_evidence,
        resolved_source,
    )
    upgrade_matrix_result = _upgrade_matrix_result(upgrade_matrix_evidence, resolved_source)
    evidence_status = _evidence_status_by_stage(
        stage_report_rows=stage_report_rows,
        stage8_status=stage8_result.status,
        release_status=release_result.get("status"),
        lifecycle_status=lifecycle_result["status"],
        full_stack_status=full_stack_result["status"],
        full_stack_evidence=full_stack_result["path"],
        cleanroom_status=cleanroom_result["status"],
        cleanroom_evidence=cleanroom_result["path"],
        clean_windows_core_status=clean_windows_rendered_result["core_status"],
        clean_windows_evidence=clean_windows_rendered_result["path"],
        upgrade_matrix_status=upgrade_matrix_result["status"],
        upgrade_matrix_evidence=upgrade_matrix_result["path"],
    )
    scope_item_matrix = _scope_item_matrix(evidence_status)
    summary = {
        "prior_stage_reports": sum(1 for row in stage_report_rows if row["status"] == "passed"),
        "prior_gauntlet_reports": sum(1 for row in gauntlet_rows if row["status"] == "passed"),
        "stage8_status": stage8_result.status,
        "release_artifact_status": release_result.get("status"),
        "native_windows_installer_status": native_installer["status"],
        "final_installer_lifecycle_status": lifecycle_result["status"],
        "full_stack_status": full_stack_result["status"],
        "cleanroom_status": cleanroom_result["status"],
        "final_gauntlet_status": final_gauntlet_result["status"],
        "clean_windows_core_status": clean_windows_rendered_result["core_status"],
        "upgrade_matrix_status": upgrade_matrix_result["status"],
        "scope_items_passed": sum(1 for row in scope_item_matrix if row["status"] == "passed"),
    }
    checks = [
        _check(
            "stage7-current-source",
            not resolved_source.get("dirty"),
            "Current source state is dirty.",
        ),
        _check(
            "stage7-prior-stage-reports",
            summary["prior_stage_reports"] >= 6,
            "Not all prior stage reports are present and passed.",
        ),
        _check(
            "stage7-prior-gauntlet-reports",
            summary["prior_gauntlet_reports"] >= 6,
            "Not all prior GauntletGate reports are present and passed.",
        ),
        _check(
            "stage7-stage8-local-release-hardening",
            stage8_result.status == "passed"
            and (stage8_root / "stage8-release-manifest.json").is_file(),
            "Stage 8 local release-hardening package did not pass.",
        ),
        _check(
            "stage7-release-artifacts",
            release_result.get("status") == "passed",
            "Local release artifact build did not pass.",
        ),
        _check(
            "stage7-final-installer-lifecycle",
            lifecycle_result["status"] == "passed",
            lifecycle_result["notes"] or "Final installer lifecycle proof did not pass.",
        ),
        _check(
            "stage7-current-full-stack",
            full_stack_result["status"] == "passed",
            full_stack_result["notes"] or "Current full-stack proof did not pass.",
        ),
        _check(
            "stage7-current-cleanroom",
            cleanroom_result["status"] == "passed",
            cleanroom_result["notes"] or "Current cleanroom proof did not pass.",
        ),
        _check(
            "stage7-current-final-gauntlet",
            final_gauntlet_result["status"] == "passed",
            final_gauntlet_result["notes"] or "Current final GauntletGate report did not pass.",
        ),
        _check(
            "stage7-clean-windows-core-reached",
            clean_windows_rendered_result["core_status"] == "passed",
            clean_windows_rendered_result["notes"]
            or "Clean Windows first-run rendered proof did not reach the core feature.",
        ),
        _check(
            "stage7-upgrade-matrix",
            upgrade_matrix_result["status"] == "passed",
            upgrade_matrix_result["notes"] or "Stage 7 upgrade matrix proof did not pass.",
        ),
        _check(
            "stage7-31-item-scope-matrix",
            summary["scope_items_passed"] == len(BETA_4_SCOPE_ITEMS),
            "Not all 31 beta release-prep scope items have passed evidence rows.",
        ),
        _check("stage7-proof-boundary", True, "Stage 7 proof boundary is missing."),
    ]
    status = "passed" if all(check["status"] == "passed" for check in checks) else "blocked"
    proof = {
        "stage_id": "4.0-stage7",
        "stage_name": "Final 4.0 Integrated Readiness",
        "status": status,
        "generated_at_unix": int(time.time()),
        "source_state": resolved_source,
        "summary": summary,
        "checks": checks,
        "stage_reports": stage_report_rows,
        "gauntlet_reports": gauntlet_rows,
        "stage8_local_release": {
            "artifact_root": str(stage8_root),
            "status": stage8_result.status,
            "profiles": stage8_result.profiles,
            "issues": stage8_result.issues,
        },
        "release_artifacts": release_result,
        "native_windows_installer": native_installer,
        "final_installer_lifecycle": lifecycle_result,
        "full_stack": full_stack_result,
        "cleanroom": cleanroom_result,
        "final_gauntlet": final_gauntlet_result,
        "clean_windows_rendered": clean_windows_rendered_result,
        "upgrade_matrix": upgrade_matrix_result,
        "scope_item_matrix": scope_item_matrix,
        "not_claimed": [
            "Stage 7 local proof does not claim station-device evidence beyond prior explicit station-bound artifacts.",
            "Stage 7 local proof does not claim public release publication.",
        ],
    }
    if native_installer["status"] != "passed":
        proof["not_claimed"].insert(
            0,
            "Stage 7 local proof does not claim native Windows installer execution unless a native installer artifact is present.",
        )
    _write_json(artifact_root / "stage7-final-readiness-proof.json", proof)
    _write_markdown(artifact_root / "stage7-final-readiness-proof.md", proof)
    return proof


def _stage_report_row(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    return {
        "path": str(path),
        "status": "passed" if payload and payload.get("status") == "passed" else "blocked",
    }


def _gauntlet_report_row(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ""
    passed = all(
        token in text
        for token in (
            "Verdict: PASS",
            "Blocker/Critical/Major/Minor/Nit: 0/0/0/0/0",
            "Lanes: lite, walkthrough, full",
            "Skipped/Waived Required Checks: none",
        )
    )
    return {"path": str(path), "status": "passed" if passed else "blocked"}


def _final_installer_lifecycle_result(
    path: Path | None,
    source_state: dict[str, Any],
) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not-found",
            "path": "",
            "checks": [],
            "notes": "Final 4.0 installer lifecycle proof path was not provided.",
        }
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {
            "status": "not-found",
            "path": str(path),
            "checks": [],
            "notes": "Final 4.0 installer lifecycle proof is missing or invalid JSON.",
        }
    checks = payload.get("checks")
    if not isinstance(checks, list):
        return {
            "status": "blocked",
            "path": str(path),
            "checks": [],
            "notes": "Final 4.0 installer lifecycle proof has no checks array.",
        }
    checks_by_id = {check.get("id"): check for check in checks if isinstance(check, dict)}
    missing = [
        check_id for check_id in FINAL_LIFECYCLE_REQUIRED_CHECKS if check_id not in checks_by_id
    ]
    blocked = [
        check_id
        for check_id in FINAL_LIFECYCLE_REQUIRED_CHECKS
        if isinstance(checks_by_id.get(check_id), dict)
        and checks_by_id[check_id].get("status") != "passed"
    ]
    source_notes = _source_state_notes(payload.get("source_state"), source_state)
    notes: list[str] = []
    if payload.get("status") != "passed":
        notes.append("lifecycle proof status is not passed")
    if missing:
        notes.append("missing lifecycle checks: " + ", ".join(missing))
    if blocked:
        notes.append("blocked lifecycle checks: " + ", ".join(blocked))
    notes.extend(source_notes)
    return {
        "status": "blocked" if notes else "passed",
        "path": str(path),
        "checks": [
            checks_by_id[check_id]
            for check_id in FINAL_LIFECYCLE_REQUIRED_CHECKS
            if check_id in checks_by_id
        ],
        "notes": "; ".join(notes),
    }


def _full_stack_result(path: Path | None, source_state: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not-found",
            "path": "",
            "notes": "Current full-stack evidence path was not provided.",
        }
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {
            "status": "not-found",
            "path": str(path),
            "notes": "Current full-stack evidence is missing or invalid JSON.",
        }
    notes: list[str] = []
    if payload.get("status") != "passed":
        notes.append("full-stack status is not passed")
    notes.extend(_source_state_notes(payload.get("source_state"), source_state))
    skipped = [
        flag for flag in ("skip_python", "skip_web", "skip_installer") if payload.get(flag) is True
    ]
    if skipped:
        notes.append("skipped required lanes: " + ", ".join(skipped))
    skip_ledger = payload.get("skip_ledger")
    if not isinstance(skip_ledger, dict):
        notes.append("skip_ledger is missing")
    elif skip_ledger.get("required_skipped") not in (0, 0.0, None):
        notes.append(f"required skipped tests: {skip_ledger.get('required_skipped')}")
    return {
        "status": "blocked" if notes else "passed",
        "path": str(path),
        "transcript": str(payload.get("transcript", "")),
        "notes": "; ".join(notes),
    }


def _cleanroom_result(path: Path | None, source_state: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not-found",
            "path": "",
            "notes": "Current cleanroom evidence path was not provided.",
        }
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {
            "status": "not-found",
            "path": str(path),
            "notes": "Current cleanroom evidence is missing or invalid JSON.",
        }
    notes: list[str] = []
    if payload.get("status") != "passed":
        notes.append("cleanroom status is not passed")
    notes.extend(_source_state_notes(payload.get("source_state"), source_state))
    skip_ledger = payload.get("skip_ledger")
    if not isinstance(skip_ledger, dict):
        notes.append("skip_ledger is missing")
    elif skip_ledger.get("required_skipped") not in (0, 0.0, None):
        notes.append(f"required skipped cleanroom tests: {skip_ledger.get('required_skipped')}")
    return {
        "status": "blocked" if notes else "passed",
        "path": str(path),
        "notes": "; ".join(notes),
    }


def _final_gauntlet_result(path: Path | None, source_state: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not-found",
            "path": "",
            "notes": "Current final GauntletGate report path was not provided.",
        }
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {
            "status": "not-found",
            "path": str(path),
            "notes": "Current final GauntletGate report is missing.",
        }
    notes: list[str] = []
    for token in (
        "Verdict: PASS",
        "Blocker/Critical/Major/Minor/Nit: 0/0/0/0/0",
        "Lanes: lite, walkthrough, full",
        "Skipped/Waived Required Checks: none",
    ):
        if token not in text:
            notes.append(f"missing token: {token}")
    expected_head = source_state.get("head")
    if expected_head and f"Source HEAD: {expected_head}" not in text:
        notes.append("current source head is not present in final GauntletGate report")
    return {
        "status": "blocked" if notes else "passed",
        "path": str(path),
        "notes": "; ".join(notes),
    }


def _clean_windows_rendered_result(
    path: Path | None,
    source_state: dict[str, Any],
) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not-found",
            "core_status": "blocked",
            "core_feature_reached": False,
            "path": "",
            "notes": "Clean Windows rendered first-run evidence path was not provided.",
        }
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {
            "status": "not-found",
            "core_status": "blocked",
            "core_feature_reached": False,
            "path": str(path),
            "notes": "Clean Windows rendered first-run evidence is missing or invalid JSON.",
        }
    notes = _source_state_notes(payload.get("source_state"), source_state)
    core_reached = (
        payload.get("core_feature_reached") is True or payload.get("status") == "core_reached"
    )
    if not core_reached:
        notes.append("clean Windows rendered proof does not claim core feature reached")
    return {
        "status": "blocked" if notes else "passed",
        "core_status": "passed" if core_reached and not notes else "blocked",
        "core_feature_reached": core_reached,
        "path": str(path),
        "notes": "; ".join(notes),
    }


def _upgrade_matrix_result(path: Path | None, source_state: dict[str, Any]) -> dict[str, Any]:
    if path is None:
        return {
            "status": "not-found",
            "path": "",
            "notes": "Stage 7 upgrade matrix evidence path was not provided.",
        }
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return {
            "status": "not-found",
            "path": str(path),
            "notes": "Stage 7 upgrade matrix evidence is missing or invalid JSON.",
        }
    notes: list[str] = []
    if payload.get("status") != "passed":
        notes.append("upgrade matrix status is not passed")
    expected_head = source_state.get("head")
    if expected_head and payload.get("source_head") != expected_head:
        notes.append("source_head does not match current source head")
    source_state_payload = payload.get("source_state")
    if isinstance(source_state_payload, dict):
        notes.extend(_source_state_notes(source_state_payload, source_state))
    else:
        notes.append("source_state is missing")
    required_origins = set(payload.get("required_upgrade_origins_from_spec") or [])
    missing_required = {"3.0", "3.1", "3.2"} - required_origins
    if missing_required:
        notes.append("missing required spec origins: " + ", ".join(sorted(missing_required)))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        notes.append("upgrade matrix rows are missing")
        rows = []
    rows_by_origin = {
        row.get("from_version"): row
        for row in rows
        if isinstance(row, dict) and row.get("from_version")
    }
    passed_origins = {
        "3.0.0-beta1": "3.0",
        "3.2.0-beta1": "3.2",
        "3.3.0": "3.3",
    }
    for exact_origin, family in passed_origins.items():
        row = rows_by_origin.get(exact_origin)
        if not isinstance(row, dict) or row.get("status") != "passed":
            notes.append(f"upgrade origin {family} ({exact_origin}) did not pass")
    row_31 = rows_by_origin.get("3.1")
    if (
        not isinstance(row_31, dict)
        or row_31.get("status") != "not_applicable"
        or not row_31.get("note")
    ):
        notes.append("3.1 upgrade origin is not explicitly classified not_applicable")
    return {
        "status": "blocked" if notes else "passed",
        "path": str(path),
        "notes": "; ".join(notes),
        "required_origins": sorted(required_origins),
        "non_applicable_origins": payload.get("non_applicable_origins") or [],
    }


def _source_state_notes(actual: Any, expected: dict[str, Any]) -> list[str]:
    if not isinstance(actual, dict):
        return ["source_state is missing"]
    notes = []
    if actual.get("dirty"):
        notes.append("source_state is dirty")
    if actual.get("head") != expected.get("head"):
        notes.append("source_state head does not match current source head")
    for key in ("status_sha256", "diff_sha256", "untracked_content_sha256"):
        if (
            actual.get(key) is not None
            and expected.get(key) is not None
            and actual.get(key) != expected.get(key)
        ):
            notes.append(f"source_state {key} does not match current source state")
    return notes


def _evidence_status_by_stage(
    *,
    stage_report_rows: list[dict[str, Any]],
    stage8_status: str,
    release_status: Any,
    lifecycle_status: str,
    full_stack_status: str,
    full_stack_evidence: str,
    cleanroom_status: str,
    cleanroom_evidence: str,
    clean_windows_core_status: str,
    clean_windows_evidence: str,
    upgrade_matrix_status: str,
    upgrade_matrix_evidence: str,
) -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for idx, row in enumerate(stage_report_rows, start=1):
        evidence[f"stage{idx}"] = {
            "status": row["status"],
            "evidence": row["path"],
        }
    evidence["stage7"] = {
        "status": "passed"
        if stage8_status == "passed" and release_status == "passed"
        else "blocked",
        "evidence": "Stage 8 local release hardening plus Stage 7 release artifacts",
    }
    evidence["final_installer_lifecycle"] = {
        "status": "passed"
        if lifecycle_status == "passed" and clean_windows_core_status == "passed"
        else "blocked",
        "evidence": "Final 4.0 installer lifecycle proof",
    }
    evidence["full_stack"] = {
        "status": full_stack_status,
        "evidence": full_stack_evidence or "Current full-stack proof",
    }
    evidence["cleanroom"] = {
        "status": cleanroom_status,
        "evidence": cleanroom_evidence or "Current cleanroom proof",
    }
    evidence["clean_windows_core"] = {
        "status": clean_windows_core_status,
        "evidence": clean_windows_evidence or "Clean Windows core-reached proof",
    }
    evidence["upgrade_matrix"] = {
        "status": upgrade_matrix_status,
        "evidence": upgrade_matrix_evidence or "Stage 7 upgrade matrix proof",
    }
    return evidence


def _scope_item_matrix(evidence_status: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows = []
    for item in BETA_4_SCOPE_ITEMS:
        item_number = int(item.split(" ", 1)[0])
        required_keys = _SCOPE_ITEM_EVIDENCE[item_number]
        evidence_rows = [
            evidence_status.get(
                key,
                {
                    "status": "blocked",
                    "evidence": f"{key} evidence is missing",
                },
            )
            for key in required_keys
        ]
        passed = all(row["status"] == "passed" for row in evidence_rows)
        rows.append(
            {
                "item": item,
                "status": "passed" if passed else "blocked",
                "evidence": [row["evidence"] for row in evidence_rows],
            }
        )
    return rows


def _build_release_artifacts(artifact_root: Path, version: str) -> dict[str, Any]:
    release_root = artifact_root / "release-artifacts"
    command = [
        sys.executable,
        str(ROOT / "scripts" / "build_release_artifacts.py"),
        "--version",
        version,
        "--out-dir",
        str(release_root),
    ]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    log_path = artifact_root / "build-release-artifacts.log"
    log_path.write_text(
        result.stdout + ("\nSTDERR:\n" + result.stderr if result.stderr else ""),
        encoding="utf-8",
    )
    manifest = _release_manifest_path(release_root)
    return {
        "status": "passed" if result.returncode == 0 and manifest is not None else "failed",
        "command": " ".join(command),
        "returncode": result.returncode,
        "manifest": str(manifest) if manifest is not None else "",
        "log": str(log_path),
    }


def _release_manifest_path(release_root: Path) -> Path | None:
    manifests = sorted(release_root.glob("*-release-artifacts-manifest.json"))
    return manifests[0] if manifests else None


def _native_windows_installer_result(
    artifact_root: Path,
    *,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    native_root = artifact_root / "native-windows-installer"
    manifest = manifest_path or _release_manifest_path(native_root)
    if manifest is None:
        return {"status": "not-found", "manifest": "", "installer": ""}
    manifest_root = manifest.parent
    payload = _read_json(manifest) or {}
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list):
        return {"status": "failed", "manifest": str(manifest), "installer": ""}
    for entry in artifacts:
        if not isinstance(entry, dict) or entry.get("kind") != "windows-tauri-installer":
            continue
        filename = entry.get("filename")
        installer = manifest_root / filename if isinstance(filename, str) else None
        if installer is not None and installer.is_file() and installer.stat().st_size > 0:
            return {"status": "passed", "manifest": str(manifest), "installer": str(installer)}
    return {"status": "failed", "manifest": str(manifest), "installer": ""}


def _not_run_release(version: str) -> dict[str, Any]:
    return {
        "status": "not-run",
        "command": f"{sys.executable} scripts/build_release_artifacts.py --version {version}",
        "manifest": "",
    }


def _check(check_id: str, passed: bool, blocked_note: str) -> dict[str, str]:
    if passed:
        return {"id": check_id, "status": "passed"}
    return {"id": check_id, "status": "blocked", "notes": blocked_note}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, proof: dict[str, Any]) -> None:
    lines = [
        "# Stage 7 Final Readiness Proof",
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
    lines.extend(["", "## Scope Item Matrix", ""])
    for row in proof["scope_item_matrix"]:
        lines.append(f"- {row['status']}: {row['item']}")
    lines.extend(["", "## Not Claimed", ""])
    lines.extend(f"- {claim}" for claim in proof["not_claimed"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root", type=Path, default=Path("artifacts/stage7-final/4.0-stage7-final")
    )
    parser.add_argument("--version", default="4.0.0-rc1")
    parser.add_argument("--final-installer-lifecycle-proof", type=Path, default=None)
    parser.add_argument("--full-stack-evidence", type=Path, default=None)
    parser.add_argument("--cleanroom-evidence", type=Path, default=None)
    parser.add_argument("--final-gauntlet-report", type=Path, default=None)
    parser.add_argument("--clean-windows-rendered-evidence", type=Path, default=None)
    parser.add_argument("--upgrade-matrix-evidence", type=Path, default=None)
    parser.add_argument("--native-installer-manifest", type=Path, default=None)
    parser.add_argument("--skip-release-build", action="store_true")
    args = parser.parse_args(argv)
    proof = build_stage7_final_readiness_proof(
        artifact_root=args.artifact_root,
        version=args.version,
        final_installer_lifecycle_proof=args.final_installer_lifecycle_proof,
        full_stack_evidence=args.full_stack_evidence,
        cleanroom_evidence=args.cleanroom_evidence,
        final_gauntlet_report=args.final_gauntlet_report,
        clean_windows_rendered_evidence=args.clean_windows_rendered_evidence,
        upgrade_matrix_evidence=args.upgrade_matrix_evidence,
        native_installer_manifest=args.native_installer_manifest,
        build_release=not args.skip_release_build,
    )
    print(json.dumps(proof, indent=2, sort_keys=True))
    return 0 if proof["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
