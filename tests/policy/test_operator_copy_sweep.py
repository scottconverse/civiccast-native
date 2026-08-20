# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 operator copy sweep and known-minor-risk allowlist."""

from __future__ import annotations

from pathlib import Path

JARGON_TOKENS = ("/api/", "DATABASE_URL", "console.log", "localhost")


class TestNoOperatorApiJargon:
    def test_operator_copy_checker_exists_and_rejects_api_jargon(self) -> None:
        checker_path = Path("scripts/policy/check_operator_copy.py")

        assert checker_path.exists()

        text = checker_path.read_text(encoding="utf-8")
        for token in JARGON_TOKENS:
            assert token in text
        assert "v1.1-known-minor-risks.md" in text


class TestKnownMinorRisksAllowlist:
    def test_known_minor_risk_allowlist_entries_include_impact_and_rationale(
        self,
    ) -> None:
        allowlist_path = Path("docs/releases/evidence/v1.1-known-minor-risks.md")

        text = allowlist_path.read_text(encoding="utf-8")

        assert "file:line" in text.lower()
        assert "operator-facing impact" in text.lower()
        assert "deferral rationale" in text.lower()
