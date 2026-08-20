# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.2 release verification run evidence paths."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFY_RELEASE = ROOT / "scripts" / "verify-release.sh"
ACTIVE_RUN_ID = "2026-05-19-v1.2-ndi-output"
FORBIDDEN_V11_RUN_ID = "2026-05-17-v1.1-public-availability"


class TestVerifyReleaseRunId:
    def test_verify_release_defaults_or_requires_active_v12_run_id(self) -> None:
        script = VERIFY_RELEASE.read_text(encoding="utf-8")

        assert "CIVICCAST_RELEASE_RUN_ID" in script
        assert ACTIVE_RUN_ID in script

    def test_verify_release_does_not_write_evidence_to_v11_run_folder(self) -> None:
        script = VERIFY_RELEASE.read_text(encoding="utf-8")

        assert FORBIDDEN_V11_RUN_ID not in script

    def test_verify_release_a11y_receipts_use_active_run_variable(self) -> None:
        script = VERIFY_RELEASE.read_text(encoding="utf-8")
        receipt_lines = [
            line.strip() for line in script.splitlines() if "verify-release-evidence" in line
        ]

        assert receipt_lines
        assert all(
            "$RELEASE_RUN_ID" in line or "${RELEASE_RUN_ID}" in line for line in receipt_lines
        )
