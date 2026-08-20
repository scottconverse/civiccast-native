# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy contract for the informational deterministic-detector workflow."""

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/deterministic-detectors.yml")


def _workflow() -> tuple[str, dict[str, object]]:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    return text, parsed


def test_mutation_job_covers_complete_changed_surface_and_rejects_fork_pr_compute() -> None:
    text, parsed = _workflow()
    mutation = parsed["jobs"]["mutation-report"]

    # Was "360" -- GitHub's default, not a measured need. mutation-report is
    # permanently informational and diff-scoped to the PR's changed non-test
    # files, so it has no business holding a runner for six hours. Capped with
    # every other job by scripts/policy/check_workflow_timeouts.py.
    assert mutation["timeout-minutes"] == "120"
    assert (
        mutation["if"] == "${{ github.event_name != 'pull_request' || "
        "github.event.pull_request.head.repo.full_name == github.repository }}"
    )
    assert "MUTATION_FILE_CAP" not in text
    assert 'SELECTED="$CHANGED"' in text
    assert "Files selected for mutation (complete changed surface)" in text


def test_mutation_job_uses_real_event_base_and_full_history() -> None:
    text, parsed = _workflow()
    mutation = parsed["jobs"]["mutation-report"]
    checkout = mutation["steps"][0]

    assert checkout["with"]["fetch-depth"] == "0"
    assert (
        "github.event.pull_request.base.ref || github.event.inputs.base || "
        "'program/native-windows'" in text
    )
    assert 'git fetch origin "$BASE_REF" --depth=1' not in text
    assert 'git fetch origin "$BASE_REF"' in text
    assert "RAW_CHANGED=$(git diff --name-only" in text
    assert "CHANGED=$(printf '%s\\n' \"$RAW_CHANGED\"" in text
    assert (
        "|| true"
        not in text.split("RAW_CHANGED=", 1)[1].split(
            'echo "### All changed non-test .py files"', 1
        )[0]
    )
    assert "### All changed non-test .py files" in text
    assert "### Files selected for mutation (complete changed surface)" in text
    assert (
        'echo \'source_paths = ["civiccast", "scripts", "prototype", "tools", "alembic"]\'' in text
    )
    assert 'echo \'also_copy = [".agent-runs", ".github", ".pipelines", "deploy", "docker", ' in text
    assert '".agent-runs"' in text
    assert '"docs", "security", "tester-handoff", "tests", "alembic.ini"' in text
    assert '"native-windows-build-toolchain.lock.json"' in text
    assert '"native-windows-runtime-dependencies.lock.json"' in text
    assert "echo 'runner = \"pytest -q --tb=no -x\"'" in text
    assert "--ignore=tests/policy/test_claims_evidence.py" in text
    assert "--ignore=tests/policy/test_shipped_payload_db_driver.py" in text
    # mutmut runs from an isolated copy.  These regression tests deliberately
    # change cwd to prove the real application resolves migrations from its
    # package location, but the harness copy cannot retain that root layout.
    # They remain in normal CI and are excluded only from mutation executions.
    assert "--deselect=tests/test_schema_check.py::test_expected_head_does_not_depend_on_current_working_directory" in text
    assert "--deselect=tests/test_schema_check.py::test_schema_check_reports_current_from_non_repo_working_directory" in text
    assert "mutmut excludes these modules from mutation executions" in text
    assert 'echo -n "only_mutate = ["' in text
    assert "sed 's/.*/\"&\",/'" in text


def test_mutation_execution_cannot_fail_open() -> None:
    text, _ = _workflow()
    mutation = text.split("  mutation-report:", 1)[1]

    assert "uv run mutmut run 2>&1 | tee mutmut-run.log || true" not in mutation
    assert (
        'uv run mutmut results 2>&1 | tee results.log | tee -a "$GITHUB_STEP_SUMMARY" '
        "|| true" not in mutation
    )
    assert "exit 0" not in mutation
    assert 'test "$run_status" -eq 0' in mutation
    assert 'test "$results_status" -eq 0' in mutation
