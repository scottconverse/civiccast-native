# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 W1/W4 — operator-facing docs must describe AI model selection truthfully.

Cheap docs-consistency guards (the W1/W4 suggested CI grep) so the operator
prose cannot silently drift back to the pre-S13 "single hard-wired model" world
while the product ships operator-selectable models with paid cloud tiers:

* W1 (docs half) — ``technical-ops-reference.md`` must describe operator-selectable
  models, the adaptive 12B-vs-e4b summary default, and the cloud tiers / per-token
  cost (not the stale "Summaries use local Ollama gemma4:e4b" hard-wired line).
* W4 — ``admin-guide.md`` and ``meeting-operator-guide.md`` must document the
  cloud/frontier capability before an operator meets it: default OFF, per-token
  $USD cost, content leaving the station, and consent.

The grep is intentionally behavioral (substring presence), not exact-wording, so
it survives copy edits but fails closed if a whole concept disappears.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TECH_OPS = REPO_ROOT / "docs" / "technical-ops-reference.md"
ADMIN_GUIDE = REPO_ROOT / "docs" / "admin-guide.md"
OPERATOR_GUIDE = REPO_ROOT / "docs" / "meeting-operator-guide.md"


def _read_lower(path: Path) -> str:
    return path.read_text(encoding="utf-8").lower()


def test_technical_ops_reference_describes_selectable_models_and_adaptive_default() -> None:
    # W1 (docs half): the AI section must read as operator-selectable + adaptive,
    # not the old hard-wired single-model world.
    text = _read_lower(TECH_OPS)

    # Operator-selectable surface is named.
    assert "ai models" in text
    assert "operator-selectable" in text or "operator selection" in text

    # The adaptive 12B-vs-e4b summary default is described (both tags + the 16 GB rule).
    assert "adaptive" in text
    assert "gemma4:12b" in text
    assert "gemma4:e4b" in text
    assert "16 gb" in text

    # Cloud tiers + per-token cost are present (no longer silent).
    assert "cloud" in text
    assert "per-token" in text or "per token" in text


def test_technical_ops_reference_drops_the_stale_hardwired_summary_line() -> None:
    # The specific pre-S13 misleading sentence must be gone.
    text = _read_lower(TECH_OPS)
    assert "summaries use local ollama `gemma4:e4b`" not in text


def test_admin_guide_documents_cloud_cost_and_consent() -> None:
    # W4: the admin guide is where a setup_admin reads about enabling cloud BEFORE doing it.
    text = _read_lower(ADMIN_GUIDE)

    assert "cloud" in text
    assert "frontier" in text
    assert "per-token" in text or "per token" in text
    # The four highest-stakes facts: default off, content egress, consent, who can enable.
    assert "default off" in text
    assert (
        "third-party provider" in text or "leaves the station" in text or "content leaves" in text
    )
    assert "consent" in text
    assert "setup_admin" in text


def test_meeting_operator_guide_notes_cloud_default_off_and_cost() -> None:
    # W4: a one-paragraph operator-facing note — default off, paid, content leaves the box.
    text = _read_lower(OPERATOR_GUIDE)

    assert "ai models" in text
    assert "cloud" in text
    assert "per token" in text or "per-token" in text
    assert "default" in text  # "off by default" / "default" posture stated
    assert "admin" in text  # turning cloud on is the admin's job
