# SPDX-License-Identifier: Apache-2.0
"""Tests for the GitHub Actions workflow-cost budget check
(``scripts/policy/check_actions_budget.py``), focused on the
``BUDGET_EXCEPTIONS`` ledger added 2026-08-24 for
``gate-a-station-acceptance.yml``.

Mirrors ``tests/policy/test_workflow_runners.py``'s treatment of
``SELF_HOSTED_ALLOWLIST``: the ledger is an exception mechanism, not a
loophole, so these tests cover both (a) today's real ledger data is honest
(every entry has a reason, matches the file it excuses) and (b) the
enforcement mechanism itself actually catches a malformed or drifted entry,
not just that current data happens to comply.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.policy.check_actions_budget as budget_mod
from scripts.policy.check_actions_budget import (
    BUDGET_EXCEPTIONS,
    validate_workflow,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_A_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "gate-a-station-acceptance.yml"


# --------------------------------------------------------------------------
# The real ledger, as-is: honest data.
# --------------------------------------------------------------------------


def test_every_budget_exception_carries_a_reason() -> None:
    # The ledger is an exception ledger, not a loophole: each entry must say
    # WHY the default (cancel-in-progress: true / retention-days: 1) cannot
    # apply here, dated so it can be revisited.
    for workflow_name, settings in BUDGET_EXCEPTIONS.items():
        assert workflow_name.endswith(".yml"), workflow_name
        assert settings, f"{workflow_name}: exception entry has no settings"
        for setting_name, (_value, reason) in settings.items():
            assert reason.strip(), f"{workflow_name}:{setting_name} has an empty reason"
            assert len(reason.strip()) > 20, (
                f"{workflow_name}:{setting_name} reason is suspiciously short "
                "to be a real, dated justification"
            )


def test_gate_a_workflow_file_exists() -> None:
    assert GATE_A_WORKFLOW.is_file(), f"expected workflow at {GATE_A_WORKFLOW}"


def test_gate_a_is_registered_in_the_ledger_for_both_known_deviations() -> None:
    entry = BUDGET_EXCEPTIONS.get("gate-a-station-acceptance.yml")
    assert entry is not None, "gate-a-station-acceptance.yml is missing from BUDGET_EXCEPTIONS"
    assert set(entry.keys()) == {"cancel_in_progress", "retention_days"}


def test_gate_a_workflow_passes_with_its_ledgered_exceptions() -> None:
    """The real file, as committed, must produce zero violations once its
    two ledgered deviations (cancel-in-progress: false, retention-days:
    90/14) are honestly declared -- this is the concrete case the ledger
    mechanism was added for."""
    text = GATE_A_WORKFLOW.read_text(encoding="utf-8-sig")
    assert validate_workflow(GATE_A_WORKFLOW, text) == []


def test_gate_a_workflow_actually_uses_its_ledgered_values() -> None:
    """Guards against the ledger and the file silently drifting apart: the
    file must still actually contain the exact values the ledger excuses,
    not some other value that only happens to also pass for unrelated
    reasons."""
    text = GATE_A_WORKFLOW.read_text(encoding="utf-8-sig")
    assert "cancel-in-progress: false" in text
    assert "retention-days: 90" in text
    assert "retention-days: 14" in text


# --------------------------------------------------------------------------
# Enforcement mechanics: prove the ledger actually fails closed, using a
# synthetic ledger + synthetic workflow so these tests do not depend on
# today's real data staying exactly as it is.
# --------------------------------------------------------------------------


def test_empty_reason_fails_the_ledger_check() -> None:
    """Direct proof the enforcement catches an empty reason -- not just that
    today's real entries happen to comply with
    test_every_budget_exception_carries_a_reason above."""
    malformed: dict[str, dict[str, tuple[object, str]]] = {
        "fake-workflow.yml": {"cancel_in_progress": (False, "")},
    }
    with pytest.raises(AssertionError):
        for workflow_name, settings in malformed.items():
            for setting_name, (_value, reason) in settings.items():
                assert reason.strip(), f"{workflow_name}:{setting_name} has an empty reason"


def test_whitespace_only_reason_fails_the_ledger_check() -> None:
    malformed: dict[str, dict[str, tuple[object, str]]] = {
        "fake-workflow.yml": {"retention_days": (frozenset({7}), "   \n  ")},
    }
    with pytest.raises(AssertionError):
        for workflow_name, settings in malformed.items():
            for setting_name, (_value, reason) in settings.items():
                assert reason.strip(), f"{workflow_name}:{setting_name} has an empty reason"


_SYNTHETIC_WORKFLOW_TEMPLATE = """
name: synthetic
on:
  push:
    branches: [main]
concurrency:
  group: {group}
  cancel-in-progress: {cancel_in_progress}
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: evidence
          path: out/
          retention-days: {retention_days}
"""

# The exact group value _has_concurrency requires by default (see
# check_actions_budget._has_concurrency) -- used by tests that are not
# exercising the cancel-in-progress ledger path, so the base concurrency
# rule is satisfied on its own and only the setting under test varies.
_COMPLIANT_GROUP = "${{ github.workflow }}-${{ github.ref }}"
_NONSTANDARD_GROUP = "synthetic-nonstandard-group"


def _synthetic_text(
    cancel_in_progress: str, retention_days: int, group: str = _NONSTANDARD_GROUP
) -> str:
    return _SYNTHETIC_WORKFLOW_TEMPLATE.format(
        cancel_in_progress=cancel_in_progress, retention_days=retention_days, group=group
    )


def test_cancel_in_progress_exception_applies_only_when_value_matches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        budget_mod,
        "BUDGET_EXCEPTIONS",
        {
            "synthetic.yml": {
                "cancel_in_progress": (False, "test: synthetic reason for a synthetic workflow")
            }
        },
    )
    workflow = tmp_path / ".github" / "workflows" / "synthetic.yml"
    workflow.parent.mkdir(parents=True)

    # Ledger says cancel-in-progress must be False for this file to be
    # excused. The file matches -- no violation.
    matching_text = _synthetic_text(cancel_in_progress="false", retention_days=1)
    assert budget_mod.validate_workflow(workflow, matching_text) == []

    # The file now says `true` -- the base rule *wants* true, but this
    # synthetic workflow's non-standard group name (`synthetic-nonstandard-
    # group`, not the required `${{ github.workflow }}-${{ github.ref }}`
    # template) means it never satisfies `_has_concurrency` on its own
    # either way. The exception only forgives the EXACT declared deviation
    # (false), so a drifted `true` here still fails closed rather than
    # silently passing "because true is nominally more correct."
    drifted_text = _synthetic_text(cancel_in_progress="true", retention_days=1)
    violations = budget_mod.validate_workflow(workflow, drifted_text)
    assert violations
    assert any("concurrency" in v for v in violations)


def test_cancel_in_progress_exception_does_not_apply_to_other_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        budget_mod,
        "BUDGET_EXCEPTIONS",
        {
            "synthetic.yml": {
                "cancel_in_progress": (False, "test: synthetic reason for a synthetic workflow")
            }
        },
    )
    other_workflow = tmp_path / ".github" / "workflows" / "not-synthetic.yml"
    other_workflow.parent.mkdir(parents=True)
    text = _synthetic_text(cancel_in_progress="false", retention_days=1)
    violations = budget_mod.validate_workflow(other_workflow, text)
    assert violations
    assert any("concurrency" in v for v in violations)


def test_retention_days_exception_applies_only_to_ledgered_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        budget_mod,
        "BUDGET_EXCEPTIONS",
        {
            "synthetic.yml": {
                "retention_days": (
                    frozenset({7, 30}),
                    "test: synthetic reason for a synthetic workflow",
                )
            }
        },
    )
    workflow = tmp_path / ".github" / "workflows" / "synthetic.yml"
    workflow.parent.mkdir(parents=True)

    for allowed in (7, 30):
        text = _synthetic_text(
            cancel_in_progress="true", retention_days=allowed, group=_COMPLIANT_GROUP
        )
        assert budget_mod.validate_workflow(workflow, text) == [], allowed

    # A value that is neither the default (1) nor ledgered (7, 30) still
    # fails closed.
    not_ledgered_text = _synthetic_text(
        cancel_in_progress="true", retention_days=14, group=_COMPLIANT_GROUP
    )
    violations = budget_mod.validate_workflow(workflow, not_ledgered_text)
    assert violations
    assert any("retention-days" in v for v in violations)


def test_retention_days_default_of_one_still_passes_regardless_of_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The ledger only ADDS permitted values -- it never removes the
    always-allowed default of retention-days: 1."""
    monkeypatch.setattr(
        budget_mod,
        "BUDGET_EXCEPTIONS",
        {
            "synthetic.yml": {
                "retention_days": (
                    frozenset({7}),
                    "test: synthetic reason for a synthetic workflow",
                )
            }
        },
    )
    workflow = tmp_path / ".github" / "workflows" / "synthetic.yml"
    workflow.parent.mkdir(parents=True)
    text = _synthetic_text(cancel_in_progress="true", retention_days=1, group=_COMPLIANT_GROUP)
    assert budget_mod.validate_workflow(workflow, text) == []


def test_no_ledger_entry_means_no_exception(tmp_path: Path) -> None:
    """Baseline: a file with no BUDGET_EXCEPTIONS entry at all gets no
    special treatment -- uses the REAL module-level BUDGET_EXCEPTIONS
    (unpatched), so this also proves an arbitrary unregistered filename
    never accidentally inherits gate-a-station-acceptance.yml's exceptions."""
    workflow = tmp_path / ".github" / "workflows" / "totally-unregistered-workflow.yml"
    workflow.parent.mkdir(parents=True)
    text = _synthetic_text(cancel_in_progress="false", retention_days=14)
    violations = budget_mod.validate_workflow(workflow, text)
    assert violations
    assert any("concurrency" in v for v in violations)
    assert any("retention-days" in v for v in violations)
