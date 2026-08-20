# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from scripts.policy.final_response_gate import evaluate_final_response_gate


def _write_state(run_dir: Path, run_id: str, **overrides: str) -> Path:
    fields = {
        "active_run": "true",
        "current_stage": "civiccast-scope-authority-repair",
        "last_completed_gate": "v0.5.0 released",
        "next_required_action": "finish and verify pipeline scope-authority gates before product work resumes",
        "stop_condition": "scope_conflict",
        "final_response_allowed": "true",
        "continuing_to": "pipeline scope-authority repair only",
    }
    fields.update(overrides)
    path = run_dir / run_id / "active-control-state.md"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(f"{key}: {value}" for key, value in fields.items()), encoding="utf-8")
    return path


def test_scope_repair_stop_is_stale_after_scope_receipt_exists(tmp_path: Path) -> None:
    run_dir = tmp_path / ".agent-runs"
    run_id = "run-1"
    _write_state(run_dir, run_id)
    (run_dir / run_id / "scope-lock-receipt.txt").write_text(
        "scope_lock: PASS\ncanonical_rung: 0.6 Summary + signed records\n",
        encoding="utf-8",
    )

    results = evaluate_final_response_gate(run_dir, require_active_run=True)

    assert any(not result.allowed for result in results)
    assert any("stale scope_conflict" in result.reason for result in results)


def test_human_manifest_gate_remains_valid_stop(tmp_path: Path) -> None:
    run_dir = tmp_path / ".agent-runs"
    _write_state(
        run_dir,
        "run-1",
        current_stage="manifest",
        last_completed_gate="scope-authority repair pushed",
        next_required_action="run the feature pipeline manifest gate",
        stop_condition="human_approval_gate",
        continuing_to="run-pipeline feature run-1",
    )

    results = evaluate_final_response_gate(run_dir, require_active_run=True)

    assert all(result.allowed for result in results)
