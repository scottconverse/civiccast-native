#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Generate the Stage 4 completion report."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

try:
    from collect_source_state import collect_source_state
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from collect_source_state import collect_source_state

_REQUIRED_PROOF_CHECKS = [
    "stage4-lpm-stage45-lab",
    "stage4-virtual-media-studio-bundle",
    "stage4-proof-boundary",
]

_SUMMARY_MINIMUMS = {
    "profiles": 3,
    "api_fixture_events": 10,
    "stateful_simulator_events": 20,
    "software_probe_events": 2,
    "bundle_files": 3,
}

_REQUIRED_DOC_TOPICS = [
    "virtual media studio",
    "stage 4",
    "stage 4-5",
    "lpm contract lab",
    "obs",
    "vmix",
    "atem",
    "visca",
    "ndi",
    "decklink",
    "usb capture",
    "software probe",
    "station-device evidence",
    "not claimed",
    "support bundle",
    "reusable bundle",
]


def build_stage4_completion_report(
    *,
    artifact_root: Path,
    virtual_lab_proof: Path,
    operator_docs: Path = Path("docs/ops/stage4-virtual-media-studio.md"),
    source_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Stage 4 report."""

    artifact_root.mkdir(parents=True, exist_ok=True)
    resolved_source = source_state or collect_source_state(repo_root=Path.cwd())
    proof = _read_json(virtual_lab_proof)
    required_checks = [_current_source_gate(resolved_source)]
    required_checks.append(_proof_gate(proof, virtual_lab_proof, resolved_source))
    required_checks.append(_docs_gate(operator_docs))
    proof_checks = {}
    if isinstance(proof, dict) and isinstance(proof.get("checks"), list):
        proof_checks = {
            check.get("id"): check for check in proof["checks"] if isinstance(check, dict)
        }
    for check_id in _REQUIRED_PROOF_CHECKS:
        required_checks.append(_proof_check_gate(check_id, proof_checks))
    summary = proof.get("summary", {}) if isinstance(proof, dict) else {}
    for key, minimum in _SUMMARY_MINIMUMS.items():
        if not isinstance(summary, dict) or summary.get(key, 0) < minimum:
            required_checks.append(
                {
                    "id": f"summary-{key}",
                    "status": "blocked",
                    "notes": f"Expected at least {minimum}; got {summary.get(key) if isinstance(summary, dict) else None}.",
                }
            )
    status = (
        "passed" if all(check["status"] == "passed" for check in required_checks) else "blocked"
    )
    report = {
        "stage_id": "3.5-stage4",
        "stage_name": "Virtual Media Studio And Reusable Local Lab",
        "status": status,
        "generated_at_unix": int(time.time()),
        "source_state": resolved_source,
        "virtual_lab_proof": str(virtual_lab_proof),
        "operator_docs": str(operator_docs),
        "summary": summary if isinstance(summary, dict) else {},
        "required_checks": required_checks,
    }
    _write_json(artifact_root / "stage4-completion-report.json", report)
    _write_markdown(artifact_root / "stage4-completion-report.md", report)
    return report


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _current_source_gate(source_state: dict[str, Any]) -> dict[str, str]:
    if source_state.get("dirty"):
        return {
            "id": "stage4-current-source",
            "status": "blocked",
            "notes": "Current source state is dirty.",
        }
    return {"id": "stage4-current-source", "status": "passed"}


def _proof_gate(
    proof: dict[str, Any] | None,
    virtual_lab_proof: Path,
    source_state: dict[str, Any],
) -> dict[str, str]:
    if proof is None:
        return {
            "id": "stage4-virtual-lab-proof",
            "status": "blocked",
            "notes": f"Virtual lab proof is missing or invalid: {virtual_lab_proof}",
        }
    notes = []
    if proof.get("status") != "passed":
        notes.append("proof status is not passed")
    proof_source = proof.get("source_state")
    if not isinstance(proof_source, dict):
        notes.append("proof source_state is missing")
    else:
        if proof_source.get("dirty"):
            notes.append("proof was generated from a dirty worktree")
        if proof_source.get("head") != source_state.get("head"):
            notes.append("proof head does not match current source head")
    check = {"id": "stage4-virtual-lab-proof", "status": "blocked" if notes else "passed"}
    if notes:
        check["notes"] = "; ".join(notes)
    return check


def _docs_gate(operator_docs: Path) -> dict[str, str]:
    try:
        content = operator_docs.read_text(encoding="utf-8").lower()
    except FileNotFoundError:
        return {
            "id": "stage4-virtual-lab-docs",
            "status": "blocked",
            "notes": f"Operator docs are missing: {operator_docs}",
        }
    missing = [topic for topic in _REQUIRED_DOC_TOPICS if topic not in content]
    if missing:
        return {
            "id": "stage4-virtual-lab-docs",
            "status": "blocked",
            "notes": "Operator docs are missing required topics: " + ", ".join(missing),
        }
    return {"id": "stage4-virtual-lab-docs", "status": "passed"}


def _proof_check_gate(check_id: str, checks_by_id: dict[Any, Any]) -> dict[str, str]:
    check = checks_by_id.get(check_id)
    if not isinstance(check, dict):
        return {
            "id": check_id,
            "status": "blocked",
            "notes": "Required Stage 4 proof check is missing.",
        }
    status = "passed" if check.get("status") == "passed" else "blocked"
    result = {"id": check_id, "status": status}
    if status != "passed":
        result["notes"] = "Required Stage 4 proof check did not pass."
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    blocked = sum(1 for check in report["required_checks"] if check["status"] == "blocked")
    passed = sum(1 for check in report["required_checks"] if check["status"] == "passed")
    lines = [
        "# Stage 4 Completion Report",
        "",
        f"Status: {report['status']}",
        f"Source HEAD: {report['source_state'].get('head')}",
        f"Virtual lab proof: {report['virtual_lab_proof']}",
        f"Operator docs: {report['operator_docs']}",
        f"Required checks: {passed} passed, {blocked} blocked",
        "",
        "## Summary",
        "",
    ]
    for key in sorted(report["summary"]):
        lines.append(f"- {key}: {report['summary'][key]}")
    lines.extend(["", "## Required Checks", ""])
    for check in report["required_checks"]:
        note = f" - {check['notes']}" if check.get("notes") else ""
        lines.append(f"- {check['status']}: {check['id']}{note}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path("artifacts/stage-reports/3.5-stage4-final"),
    )
    parser.add_argument(
        "--virtual-lab-proof",
        type=Path,
        default=Path("artifacts/stage4-virtual-lab/3.5-stage4-final/stage4-virtual-lab-proof.json"),
    )
    parser.add_argument(
        "--operator-docs",
        type=Path,
        default=Path("docs/ops/stage4-virtual-media-studio.md"),
    )
    args = parser.parse_args()
    report = build_stage4_completion_report(
        artifact_root=args.artifact_root,
        virtual_lab_proof=args.virtual_lab_proof,
        operator_docs=args.operator_docs,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
