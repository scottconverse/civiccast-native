# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from scripts.policy.stop_validator import validate_state_file


def _write_pipeline_fixture(root: Path) -> Path:
    (root / ".pipelines").mkdir(parents=True)
    (root / ".pipelines" / "feature.yaml").write_text(
        "stages:\n"
        "  - name: manifest\n"
        "  - name: research\n"
        "  - name: plan\n"
        "  - name: execute\n"
        "  - name: policy\n"
        "  - name: manager\n",
        encoding="utf-8",
    )
    run_dir = root / ".agent-runs" / "run-1"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.yaml").write_text("type: feature\n", encoding="utf-8")
    return run_dir


def _write_state(run_dir: Path, **overrides: str) -> Path:
    state = {
        "active_run": "true",
        "current_stage": "manifest",
        "last_completed_gate": "run-start",
        "next_required_action": "wait for human manifest approval",
        "stop_condition": "human_approval_gate",
        "final_response_allowed": "true",
        "continuing_to": "manifest approval",
    }
    state.update(overrides)
    path = run_dir / "active-control-state.md"
    path.write_text("\n".join(f"{key}: {value}" for key, value in state.items()), encoding="utf-8")
    return path


def test_human_gate_must_match_resume_stage_from_run_log(tmp_path: Path) -> None:
    run_dir = _write_pipeline_fixture(tmp_path)
    state_path = _write_state(run_dir, current_stage="manifest")
    (run_dir / "run.log").write_text(
        "2026-05-14T00:00:00Z | manifest | COMPLETE | approved\n",
        encoding="utf-8",
    )

    result = validate_state_file(state_path)

    assert result.allowed is False
    assert "human_approval_gate is stale" in result.reason
    assert "research" in result.reason


def test_failed_gate_requires_matching_failed_or_blocked_run_log_event(
    tmp_path: Path,
) -> None:
    run_dir = _write_pipeline_fixture(tmp_path)
    state_path = _write_state(
        run_dir,
        current_stage="policy",
        stop_condition="failed_gate_needs_user_direction",
        next_required_action="user direction needed for failed policy gate",
        continuing_to="policy repair",
    )
    (run_dir / "run.log").write_text(
        "2026-05-14T00:00:00Z | manifest | COMPLETE | approved\n"
        "2026-05-14T00:01:00Z | policy | COMPLETE | stale success\n",
        encoding="utf-8",
    )

    result = validate_state_file(state_path)

    assert result.allowed is False
    assert "no FAILED/BLOCKED event" in result.reason


def test_failed_gate_accepts_matching_blocked_run_log_event(tmp_path: Path) -> None:
    run_dir = _write_pipeline_fixture(tmp_path)
    state_path = _write_state(
        run_dir,
        current_stage="policy",
        stop_condition="failed_gate_needs_user_direction",
        next_required_action="user direction needed for failed policy gate",
        continuing_to="policy repair",
    )
    (run_dir / "run.log").write_text(
        "2026-05-14T00:00:00Z | policy | BLOCKED | policy command failed\n",
        encoding="utf-8",
    )

    result = validate_state_file(state_path)

    assert result.allowed is True
