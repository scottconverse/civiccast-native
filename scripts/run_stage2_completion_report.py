# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Generate the Stage 2 completion report."""

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

_REQUIRED_OPERATOR_CHECKS = [
    "every-screen-walkthrough",
    "three-channel-station",
    "media-library-and-playout",
    "live-ui-api-workflow",
    "recording-and-ingest",
    "generated-media-record-stop-output",
    "as-run-and-proof",
    "live-failure-scenarios",
    "failure-visibility",
    "support-bundle",
]

_SUMMARY_MINIMUMS = {
    "channels": 3,
    "scheduled_items": 9,
    "recording_sources": 8,
    "as_run_entries": 9,
    "support_bundle_files": 6,
    "route_observations": 10,
    "failure_drills": 4,
}

_REQUIRED_DOC_TOPICS = [
    "three-channel station",
    "media library",
    "recording source",
    "as-run",
    "source-dropout",
    "destination-failure",
    "support bundle",
    "every-screen walkthrough",
    "live workflow rehearsal",
    "record-now",
    "stop recording",
    "failure drill",
]


def build_stage2_completion_report(
    *,
    artifact_root: Path,
    operator_proof: Path,
    operator_docs: Path = Path("docs/ops/stage2-operator-workflow.md"),
    source_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Stage 2 report."""

    artifact_root.mkdir(parents=True, exist_ok=True)
    resolved_source = source_state or collect_source_state(repo_root=Path.cwd())
    proof = _read_json(operator_proof)
    required_checks = [_current_source_gate(resolved_source)]
    required_checks.append(_operator_proof_gate(proof, operator_proof, resolved_source))
    required_checks.append(_operator_docs_gate(operator_docs))
    summary = proof.get("summary", {}) if isinstance(proof, dict) else {}

    if isinstance(proof, dict):
        proof_checks = proof.get("checks")
        if isinstance(proof_checks, list):
            checks_by_id = {
                check.get("id"): check for check in proof_checks if isinstance(check, dict)
            }
        else:
            checks_by_id = {}
        for check_id in _REQUIRED_OPERATOR_CHECKS:
            required_checks.append(_operator_check_gate(check_id, checks_by_id))
    else:
        for check_id in _REQUIRED_OPERATOR_CHECKS:
            required_checks.append(
                {
                    "id": check_id,
                    "status": "blocked",
                    "notes": "Operator proof JSON is missing or invalid.",
                }
            )

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
        "stage_id": "3.3-stage2",
        "stage_name": "Operator Workflow, Media, Recording, and Proof",
        "status": status,
        "generated_at_unix": int(time.time()),
        "source_state": resolved_source,
        "operator_proof": str(operator_proof),
        "operator_docs": str(operator_docs),
        "summary": summary if isinstance(summary, dict) else {},
        "required_checks": required_checks,
    }
    _write_json(artifact_root / "stage2-completion-report.json", report)
    _write_markdown(artifact_root / "stage2-completion-report.md", report)
    return report


def _current_source_gate(source_state: dict[str, Any]) -> dict[str, str]:
    if source_state.get("dirty"):
        return {
            "id": "stage2-current-source",
            "status": "blocked",
            "notes": "Current source state is dirty.",
        }
    return {
        "id": "stage2-current-source",
        "status": "passed",
    }


def _operator_docs_gate(operator_docs: Path) -> dict[str, str]:
    try:
        content = operator_docs.read_text(encoding="utf-8").lower()
    except FileNotFoundError:
        return {
            "id": "stage2-operator-docs",
            "status": "blocked",
            "notes": f"Operator docs are missing: {operator_docs}",
        }
    missing = [topic for topic in _REQUIRED_DOC_TOPICS if topic not in content]
    if missing:
        return {
            "id": "stage2-operator-docs",
            "status": "blocked",
            "notes": "Operator docs are missing required topics: " + ", ".join(missing),
        }
    return {
        "id": "stage2-operator-docs",
        "status": "passed",
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _operator_proof_gate(
    proof: dict[str, Any] | None,
    operator_proof: Path,
    source_state: dict[str, Any],
) -> dict[str, str]:
    if proof is None:
        return {
            "id": "stage2-operator-workflow-proof",
            "status": "blocked",
            "notes": f"Operator proof is missing or invalid: {operator_proof}",
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
        "id": "stage2-operator-workflow-proof",
        "status": "blocked" if notes else "passed",
    }
    if notes:
        check["notes"] = "; ".join(notes)
    return check


def _operator_check_gate(
    check_id: str,
    checks_by_id: dict[Any, Any],
) -> dict[str, str]:
    check = checks_by_id.get(check_id)
    if not isinstance(check, dict):
        return {
            "id": check_id,
            "status": "blocked",
            "notes": "Required operator proof check is missing.",
        }
    status = "passed" if check.get("status") == "passed" else "blocked"
    check = {
        "id": check_id,
        "status": status,
    }
    if status != "passed":
        check["notes"] = "Required operator proof check did not pass."
    return check


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    counts = {
        status: sum(1 for check in report["required_checks"] if check["status"] == status)
        for status in {"passed", "blocked"}
    }
    lines = [
        "# Stage 2 Completion Report",
        "",
        f"Status: {report['status']}",
        f"Source HEAD: {report['source_state'].get('head')}",
        f"Operator proof: {report['operator_proof']}",
        f"Operator docs: {report['operator_docs']}",
        f"Required checks: {counts.get('passed', 0)} passed, {counts.get('blocked', 0)} blocked",
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
        default=Path("artifacts/stage-reports/3.3-stage2"),
    )
    parser.add_argument(
        "--operator-proof",
        type=Path,
        default=Path(
            "artifacts/stage2-operator-workflow/3.3-stage2-final/stage2-operator-workflow-proof.json"
        ),
    )
    parser.add_argument(
        "--operator-docs",
        type=Path,
        default=Path("docs/ops/stage2-operator-workflow.md"),
    )
    args = parser.parse_args()
    report = build_stage2_completion_report(
        artifact_root=args.artifact_root,
        operator_proof=args.operator_proof,
        operator_docs=args.operator_docs,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
