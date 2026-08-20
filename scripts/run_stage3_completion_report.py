# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Generate the Stage 3 completion report."""

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
    "device-inventory",
    "cue-builder-dry-run-live-fire",
    "test-mode-and-on-air-mode",
    "safe-state-panic-and-rollback",
    "adapter-vmix-http-api",
    "adapter-obs-websocket-5",
    "adapter-atem-simulator",
    "adapter-visca-udp-52381",
    "adapter-ndi-gateway",
    "adapter-decklink-profile",
    "adapter-usb-capture-profile",
    "adapter-audio-layer",
    "adapter-videohub-router",
    "adapter-encoder-headend",
    "audit-and-source-binding",
]

_SUMMARY_MINIMUMS = {
    "devices": 12,
    "cues": 14,
    "dry_run_plans": 14,
    "test_mode_events": 14,
    "on_air_events": 5,
    "adapter_contracts": 9,
    "failure_modes": 14,
    "audit_records": 19,
}

_REQUIRED_DOC_TOPICS = [
    "device inventory",
    "cue builder",
    "dry run",
    "live fire",
    "test mode",
    "on-air mode",
    "safe-state panic",
    "rollback",
    "vmix http/api",
    "obs obs-websocket 5.x",
    "atem simulator",
    "ptz",
    "visca",
    "ndi",
    "ndi discovery",
    "decklink",
    "usb capture",
    "audio",
    "audio mixer",
    "videohub",
    "router",
    "encoder",
    "destination profiles",
    "audit",
    "support bundle",
    "keyring",
]


def build_stage3_completion_report(
    *,
    artifact_root: Path,
    adapter_proof: Path,
    operator_docs: Path = Path("docs/ops/stage3-control-room-device-adapters.md"),
    source_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Stage 3 report."""

    artifact_root.mkdir(parents=True, exist_ok=True)
    resolved_source = source_state or collect_source_state(repo_root=Path.cwd())
    proof = _read_json(adapter_proof)
    required_checks = [_current_source_gate(resolved_source)]
    required_checks.append(_proof_gate(proof, adapter_proof, resolved_source))
    required_checks.append(_docs_gate(operator_docs))
    summary = proof.get("summary", {}) if isinstance(proof, dict) else {}

    checks_by_id = {}
    if isinstance(proof, dict) and isinstance(proof.get("checks"), list):
        checks_by_id = {
            check.get("id"): check for check in proof["checks"] if isinstance(check, dict)
        }
    for check_id in _REQUIRED_PROOF_CHECKS:
        required_checks.append(_proof_check_gate(check_id, checks_by_id))
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
        "stage_id": "3.4-stage3",
        "stage_name": "Control Room And Device Adapter Depth",
        "status": status,
        "generated_at_unix": int(time.time()),
        "source_state": resolved_source,
        "adapter_proof": str(adapter_proof),
        "operator_docs": str(operator_docs),
        "summary": summary if isinstance(summary, dict) else {},
        "required_checks": required_checks,
    }
    _write_json(artifact_root / "stage3-completion-report.json", report)
    _write_markdown(artifact_root / "stage3-completion-report.md", report)
    return report


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _current_source_gate(source_state: dict[str, Any]) -> dict[str, str]:
    if source_state.get("dirty"):
        return {
            "id": "stage3-current-source",
            "status": "blocked",
            "notes": "Current source state is dirty.",
        }
    return {"id": "stage3-current-source", "status": "passed"}


def _proof_gate(
    proof: dict[str, Any] | None,
    adapter_proof: Path,
    source_state: dict[str, Any],
) -> dict[str, str]:
    if proof is None:
        return {
            "id": "stage3-control-room-adapter-proof",
            "status": "blocked",
            "notes": f"Adapter proof is missing or invalid: {adapter_proof}",
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
    check = {
        "id": "stage3-control-room-adapter-proof",
        "status": "blocked" if notes else "passed",
    }
    if notes:
        check["notes"] = "; ".join(notes)
    return check


def _docs_gate(operator_docs: Path) -> dict[str, str]:
    try:
        content = operator_docs.read_text(encoding="utf-8").lower()
    except FileNotFoundError:
        return {
            "id": "stage3-control-room-docs",
            "status": "blocked",
            "notes": f"Operator docs are missing: {operator_docs}",
        }
    missing = [topic for topic in _REQUIRED_DOC_TOPICS if topic not in content]
    if missing:
        return {
            "id": "stage3-control-room-docs",
            "status": "blocked",
            "notes": "Operator docs are missing required topics: " + ", ".join(missing),
        }
    return {"id": "stage3-control-room-docs", "status": "passed"}


def _proof_check_gate(check_id: str, checks_by_id: dict[Any, Any]) -> dict[str, str]:
    check = checks_by_id.get(check_id)
    if not isinstance(check, dict):
        return {
            "id": check_id,
            "status": "blocked",
            "notes": "Required Stage 3 proof check is missing.",
        }
    status = "passed" if check.get("status") == "passed" else "blocked"
    result = {"id": check_id, "status": status}
    if status != "passed":
        result["notes"] = "Required Stage 3 proof check did not pass."
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    blocked = sum(1 for check in report["required_checks"] if check["status"] == "blocked")
    passed = sum(1 for check in report["required_checks"] if check["status"] == "passed")
    lines = [
        "# Stage 3 Completion Report",
        "",
        f"Status: {report['status']}",
        f"Source HEAD: {report['source_state'].get('head')}",
        f"Adapter proof: {report['adapter_proof']}",
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
        default=Path("artifacts/stage-reports/3.4-stage3-final"),
    )
    parser.add_argument(
        "--adapter-proof",
        type=Path,
        default=Path(
            "artifacts/stage3-control-room/3.4-stage3-final/stage3-control-room-adapter-proof.json"
        ),
    )
    parser.add_argument(
        "--operator-docs",
        type=Path,
        default=Path("docs/ops/stage3-control-room-device-adapters.md"),
    )
    args = parser.parse_args()
    report = build_stage3_completion_report(
        artifact_root=args.artifact_root,
        adapter_proof=args.adapter_proof,
        operator_docs=args.operator_docs,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
