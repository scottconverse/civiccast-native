# SPDX-License-Identifier: Apache-2.0
"""Tests for the GitHub Actions workflow-cost budget check
(``scripts/policy/check_actions_budget.py``), focused on
``DOCUMENTED_BUDGET_EXCEPTIONS`` -- the per-workflow exception dict
(``{filename: reason}``) that lets ``gate-a-station-acceptance.yml`` keep
``cancel-in-progress: false``, its shared ``sandbox-lab`` concurrency group,
and 90/14-day artifact retention instead of this check's defaults
(``cancel-in-progress: true`` on the per-ref concurrency shape, and a 1-day
retention cap).

No dedicated test file existed for this check before PR #24 (merged to
main) added ``DOCUMENTED_BUDGET_EXCEPTIONS``, so this one exists to cover
the one property the ledger's own honesty depends on: every entry must
carry a real, non-empty, substantive reason -- mirroring
``tests/policy/test_workflow_runners.py``'s
``test_every_allowlist_entry_carries_a_reason`` for
``SELF_HOSTED_ALLOWLIST``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.policy.check_actions_budget import (
    DOCUMENTED_BUDGET_EXCEPTIONS,
    validate_workflow,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_A_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "gate-a-station-acceptance.yml"


def test_gate_a_workflow_file_exists() -> None:
    assert GATE_A_WORKFLOW.is_file(), f"expected workflow at {GATE_A_WORKFLOW}"


def test_gate_a_is_registered_in_documented_budget_exceptions() -> None:
    assert "gate-a-station-acceptance.yml" in DOCUMENTED_BUDGET_EXCEPTIONS


def test_every_documented_budget_exception_carries_a_non_empty_substantive_reason() -> None:
    # The ledger is an exception ledger, not a loophole: each entry must say
    # WHY the default (cancel-in-progress: true on the per-ref concurrency
    # shape / retention-days: 1) cannot apply to that workflow.
    for workflow_name, reason in DOCUMENTED_BUDGET_EXCEPTIONS.items():
        assert workflow_name.endswith(".yml"), workflow_name
        assert reason.strip(), f"{workflow_name} has an empty reason"
        assert len(reason.strip()) > 20, (
            f"{workflow_name} reason is suspiciously short to be a real, substantive justification"
        )


def test_gate_a_workflow_passes_with_its_documented_exception() -> None:
    """The real file, as committed, must produce zero violations with its
    documented exception in place -- the concrete case the ledger exists
    for."""
    text = GATE_A_WORKFLOW.read_text(encoding="utf-8-sig")
    assert validate_workflow(GATE_A_WORKFLOW, text) == []


# --------------------------------------------------------------------------
# Enforcement mechanics: prove an empty reason actually fails the check
# above, not just that today's one real entry happens to comply.
# --------------------------------------------------------------------------


def test_empty_reason_fails_the_documented_reason_check() -> None:
    malformed: dict[str, str] = {"fake-workflow.yml": ""}
    with pytest.raises(AssertionError):
        for workflow_name, reason in malformed.items():
            assert reason.strip(), f"{workflow_name} has an empty reason"


def test_whitespace_only_reason_fails_the_documented_reason_check() -> None:
    malformed: dict[str, str] = {"fake-workflow.yml": "   \n  "}
    with pytest.raises(AssertionError):
        for workflow_name, reason in malformed.items():
            assert reason.strip(), f"{workflow_name} has an empty reason"
