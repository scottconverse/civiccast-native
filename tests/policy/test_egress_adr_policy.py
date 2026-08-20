# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy tests for egress release ADR coverage."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_EGRESS_ADRS = {
    "continuity": "0015-egress-continuity-mechanism.md",
    "loudness": "0014-egress-loudness-target.md",
    "command_transport": "0017-egress-command-transport.md",
    "caption_embedding": "0018-egress-caption-embedding.md",
    "canonical_profile": "0016-egress-canonical-profile.md",
}


def test_required_egress_release_adrs_exist_and_are_accepted() -> None:
    adr_dir = REPO_ROOT / "docs" / "adr"

    for decision, filename in REQUIRED_EGRESS_ADRS.items():
        path = adr_dir / filename
        assert path.exists(), f"Missing egress {decision} ADR: {filename}"
        text = path.read_text(encoding="utf-8")
        assert "**Status:** Accepted" in text, f"Egress {decision} ADR is not accepted"
