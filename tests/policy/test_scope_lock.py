# SPDX-License-Identifier: Apache-2.0

from pathlib import Path

from scripts.policy.agent_decision_gate import evaluate_agent_decision
from scripts.policy.check_release_docs_consistency import evaluate_release_docs_consistency
from scripts.policy.check_rung_file_ownership import evaluate_rung_file_ownership
from scripts.policy.check_scope_lock import evaluate_scope_lock
from scripts.policy.scope_lock_utils import parse_release_plan


def _write_plan(root: Path) -> None:
    plan = root / "docs" / "spec" / "release-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        """
# Release plan

## 0.6 - Summary + signed records

Proves: an AI summary of a meeting passes operator review and exports as a signed PDF/A legal record

Scope:
- civiccast-summary creates sourced claims with transcript timestamp citations.
- civiccast-records exports signed transcript records as PDF/A.

Exit criteria:
- Operator review accepts the summary.
- Signed PDF/A legal record exists.

## 0.7 - Publish dashboard

Proves: reviewed records can be sent through a three-tier publish dashboard.

Scope:
- publish dashboard
- Internet Archive
- local NAS
- YouTube syndication
""",
        encoding="utf-8",
    )


def _write_scope_lock(root: Path, run_id: str = "run-1") -> Path:
    run = root / ".agent-runs" / run_id
    run.mkdir(parents=True)
    path = run / "scope-lock.yaml"
    path.write_text(
        """
current_rung: "0.6"
canonical_source: "docs/spec/release-plan.md"
rung_title: "Summary + signed records"
proves: "an AI summary of a meeting passes operator review and exports as a signed PDF/A legal record"
required_modules:
  - civiccast-summary
  - civiccast-records
allowed_feature_terms:
  - summary
  - sourced claim
  - transcript timestamp
  - PDF/A
  - signed transcript
  - records
forbidden_feature_terms_without_replan:
  - publish dashboard
  - Internet Archive
  - local NAS
  - YouTube
  - syndication
  - three-tier publish
scope_bullets:
  - civiccast-summary creates sourced claims with transcript timestamp citations.
exit_criteria:
  - Signed PDF/A legal record exists.
historical_evidence_paths:
  - docs/releases/v0.5.*-*.md
""",
        encoding="utf-8",
    )
    return path


def _fixture(root: Path) -> None:
    _write_plan(root)
    _write_scope_lock(root)


def test_scope_lock_passes_when_it_matches_release_plan(tmp_path: Path) -> None:
    _fixture(tmp_path)

    assert evaluate_scope_lock("run-1", run_dir=tmp_path / ".agent-runs", root=tmp_path) == []


def test_scope_lock_allows_required_module_named_in_rung_title(tmp_path: Path) -> None:
    _fixture(tmp_path)
    lock = tmp_path / ".agent-runs" / "run-1" / "scope-lock.yaml"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(
            "  - civiccast-summary", "  - Summary + signed records", 1
        ),
        encoding="utf-8",
    )

    assert evaluate_scope_lock("run-1", run_dir=tmp_path / ".agent-runs", root=tmp_path) == []


def test_scope_lock_rejects_required_module_absent_from_rung(tmp_path: Path) -> None:
    _fixture(tmp_path)
    lock = tmp_path / ".agent-runs" / "run-1" / "scope-lock.yaml"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace(
            "  - civiccast-summary", "  - unconfigured module", 1
        ),
        encoding="utf-8",
    )

    violations = evaluate_scope_lock("run-1", run_dir=tmp_path / ".agent-runs", root=tmp_path)

    assert any("required module `unconfigured module`" in item for item in violations)


def test_parse_release_plan_accepts_wp_headings_without_losing_numeric_rungs(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "native-recovery.md"
    plan_path.write_text(
        """
## 1. Purpose

### WP1 — Native payload and legally required captions

WP1 body.

#### Implementation detail

This detail remains in WP1.

### wp2: Installer lifecycle

WP2 body.

## 2 - Numeric release plan

Numeric body.
""",
        encoding="utf-8",
    )

    plan = parse_release_plan(plan_path)

    assert plan["WP1"].title == "Native payload and legally required captions"
    assert "This detail remains in WP1." in plan["WP1"].body
    assert "WP2 body." not in plan["WP1"].body
    assert plan["WP2"].title == "Installer lifecycle"
    assert plan["2"].title == "Numeric release plan"


def test_scope_lock_missing_fails_before_product_work(tmp_path: Path) -> None:
    _write_plan(tmp_path)

    violations = evaluate_scope_lock("run-1", run_dir=tmp_path / ".agent-runs", root=tmp_path)

    assert any("scope-lock.yaml missing" in item for item in violations)


def test_scope_lock_title_mismatch_is_scope_conflict(tmp_path: Path) -> None:
    _fixture(tmp_path)
    lock = tmp_path / ".agent-runs" / "run-1" / "scope-lock.yaml"
    lock.write_text(
        lock.read_text(encoding="utf-8").replace("Summary + signed records", "Publish dashboard"),
        encoding="utf-8",
    )

    violations = evaluate_scope_lock("run-1", run_dir=tmp_path / ".agent-runs", root=tmp_path)

    assert any(
        "SCOPE_CONFLICT" in item and "release-plan.md says v0.6" in item for item in violations
    )


def test_rung_file_ownership_blocks_future_rung_paths_and_commit_message(tmp_path: Path) -> None:
    _fixture(tmp_path)

    violations = evaluate_rung_file_ownership(
        "run-1",
        run_dir=tmp_path / ".agent-runs",
        root=tmp_path,
        commit_message="feat: add publish dashboard foundation",
        paths=[
            "civiccast/publish/PublishDashboardScreen.tsx",
            "docs/releases/evidence/v0.6-publish-dashboard-smoke.md",
        ],
    )

    assert any("commit message contains `publish dashboard`" in item for item in violations)
    assert any(
        "PublishDashboardScreen" in item or "publish dashboard" in item for item in violations
    )


def test_release_docs_consistency_blocks_v06_publish_dashboard_claim(tmp_path: Path) -> None:
    _fixture(tmp_path)
    (tmp_path / "README.md").write_text(
        "Current work: v0.6 publish dashboard in progress\n", encoding="utf-8"
    )

    violations = evaluate_release_docs_consistency(
        "run-1",
        run_dir=tmp_path / ".agent-runs",
        root=tmp_path,
    )

    assert any("README.md:1" in item and "SCOPE_CONFLICT" in item for item in violations)


def test_release_docs_consistency_exempts_historical_evidence_paths(tmp_path: Path) -> None:
    _fixture(tmp_path)
    historical = tmp_path / "docs" / "releases" / "v0.5.0-verification.md"
    historical.parent.mkdir(parents=True, exist_ok=True)
    historical.write_text(
        "Historical note: v0.6 publish dashboard was discussed during prior planning.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "Current work: v0.6 publish dashboard in progress\n", encoding="utf-8"
    )

    violations = evaluate_release_docs_consistency(
        "run-1",
        run_dir=tmp_path / ".agent-runs",
        root=tmp_path,
    )

    assert not any("v0.5.0-verification.md" in item for item in violations)
    assert any("README.md:1" in item and "SCOPE_CONFLICT" in item for item in violations)


def test_start_rung_work_blocks_prompt_that_conflicts_with_release_plan(tmp_path: Path) -> None:
    _fixture(tmp_path)

    result = evaluate_agent_decision(
        tmp_path / ".agent-runs",
        intent="start_rung_work",
        claimed_stop_condition="scope_conflict",
        run_id="run-1",
        claimed_rung="0.6",
        prompt_text="Begin v0.6 publish-dashboard work",
    )

    assert result.allowed is False
    assert "SCOPE_CONFLICT" in result.reason
    assert "v0.6 is Summary + signed records" in result.reason


def test_start_rung_work_allows_matching_prompt(tmp_path: Path) -> None:
    _fixture(tmp_path)

    result = evaluate_agent_decision(
        tmp_path / ".agent-runs",
        intent="start_rung_work",
        claimed_stop_condition="scope_conflict",
        run_id="run-1",
        claimed_rung="0.6",
        prompt_text="Begin v0.6 Summary + signed records work",
    )

    assert result.allowed is True
