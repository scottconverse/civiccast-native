# SPDX-License-Identifier: Apache-2.0
"""Protect the native-Windows recovery ledger and no-scope-loss contract."""

from __future__ import annotations

import csv
import hashlib
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RECOVERY = ROOT / ".agent-runs" / "native-windows" / "recovery-2026-07-25"
SPECS = ROOT / ".agent-runs" / "native-windows" / "specs"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_prose(text: str) -> str:
    return " ".join(text.split())


def test_recovery_inventory_preserves_all_218_visible_rows() -> None:
    ledger = RECOVERY / "inventory" / "recovery-inventory-218.csv"
    with ledger.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) == 218
    assert [int(row["row"]) for row in rows] == list(range(1, 219))
    assert len({row["visible_path"] for row in rows}) == 218
    assert Counter(row["original_status"] for row in rows) == {
        " M": 141,
        "??": 77,
    }
    assert sum(int(row["expanded_file_count"]) for row in rows) == 1_911

    visible_counts = Counter(row["classification"] for row in rows)
    assert visible_counts == {
        "intended source": 93,
        "tests": 81,
        "documentation": 23,
        "generated evidence": 20,
        "temporary material": 1,
    }

    expanded_counts: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        expanded_counts[row["classification"]] += int(row["expanded_file_count"])
    assert dict(expanded_counts) == {
        "tests": 83,
        "intended source": 94,
        "documentation": 28,
        "generated evidence": 1_705,
        "temporary material": 1,
    }

    dispositions = Counter(row["disposition"] for row in rows)
    assert dispositions == {
        "committed to recovery branch": 197,
        "excluded: local generated evidence": 20,
        "excluded: zero-byte temporary file": 1,
    }
    assert _sha256(ledger) == ("7257fe2d2f042178c6a0fe66d049413be3e8210792dd7cc4bed9bbe21f57996f")


def test_recovery_preserves_the_inherited_handoff_byte_for_byte() -> None:
    handoff = ROOT / "docs" / "process" / "CODEX-NATIVE-BETA-HANDOFF-2026-07-24.md"

    assert _sha256(handoff) == ("bb458026ffb4ecebb07a8065859406197422fe21603aad23c200171a658ed522")


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
