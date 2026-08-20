# SPDX-License-Identifier: Apache-2.0
"""Protect the native-Windows recovery ledger and no-scope-loss contract."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Was .agent-runs/native-windows/specs. Those six files are real design
# records, not agent scratch, and the native-repo migration hand-carried
# them into docs/design/ rather than losing them with the rest of that tree.
SPECS = ROOT / "docs" / "design"


def _normalized_prose(text: str) -> str:
    return " ".join(text.split())


def test_recovery_contract_preserves_mandatory_scope_and_owner_gates() -> None:
    contract = _normalized_prose(
        (SPECS / "spec-native-beta-recovery.md").read_text(encoding="utf-8")
    )
    bootstrap = _normalized_prose(
        (SPECS / "plan-sub-300mb-bootstrap.md").read_text(encoding="utf-8")
    )

    for phrase in (
        "Nothing is removed because it is",
        "Captions are legally required",
        "all 17 rows",
        # Venue mandate per the 2026-07-29 owner amendment: Windows Sandbox is
        # the primary cleanroom; a persistent VM covers only proof gaps
        # Sandbox cannot faithfully establish.
        "complete fresh-Windows Sandbox lifecycle matrix",
        "persistent-VM proof only for requirements Sandbox cannot",
        "no canonical audit-control record, exact verdict filename, or `AUDIT_PASS` token is required",
        "Scott Converse alone decides whether to merge, sign, tag, publish, or",
    ):
        assert phrase in contract

    for phrase in (
        "strictly smaller",
        "300,000,000 bytes",
        "an explicit owner-approved D2 amendment",
        "There is no model downgrade or caption-disabled success path",
        # 2026-08-07 owner decision (re-recorded after a Codex-crash loss):
        # large-v3 is an optional quality add-on, NOT mandatory for a
        # default station. The caption FLOOR tier is what is mandatory.
        # These phrases protect the ratified wording so it cannot be
        # silently reverted back to requiring large-v3.
        "large-v3` is not",
        "mandatory for a default station; it is an optional quality add-on",
        "caption floor tier is the mandatory requirement for a default station",
        "originally made weeks before 2026-08-07, was lost in a Codex crash",
        "non-negotiable and are unaffected: every default station",
    ):
        assert phrase in bootstrap

    # This test must keep failing if a future edit silently reintroduces
    # large-v3 (or any specific model tier) as a hard requirement for
    # station activation -- that framing was the pre-2026-08-07 bug.
    assert "`large-v3`, both Summary" not in bootstrap
    assert "Optional AI or translation models must use separate optional packs." not in bootstrap


def test_current_role_docs_do_not_restore_model_name_based_roles() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    old_handoff = (ROOT / "docs" / "process" / "handoff-2026-07-02-3.3-to-4.0-coder.md").read_text(
        encoding="utf-8"
    )

    assert "Claude = coder, Codex = auditor" not in agents
    assert "Claude = coder, Codex = auditor" not in claude
    # The pinned sentence tracks the owner's CURRENT seat assignment: the
    # 2026-07-25 recovery handoff named Codex; the owner transferred the
    # seat to Claude on 2026-07-29 (recorded in the recovery spec's
    # owner-amendment section). The assignment mechanism -- owner handoff,
    # never model-name-based role inference -- is what this test protects.
    assert "transferred from Codex to Claude on 2026-07-29" in claude
    assert "Do not infer a role" in claude
    assert "Superseded source-control rule" in old_handoff
    assert "scoped commits and pushes are authorized" in _normalized_prose(old_handoff)
