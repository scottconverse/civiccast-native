# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.1 browser QA specs that live outside test-writer ownership."""

from __future__ import annotations

from pathlib import Path


class TestFrontendBrowserQaContracts:
    def test_required_playwright_specs_exist_for_v11_release_states(self) -> None:
        required_specs = [
            Path("civiccast/apps/portal-operator/e2e/first-run-wizard.spec.ts"),
            Path("civiccast/apps/portal-operator/e2e/preflight-v11.spec.ts"),
            Path("civiccast/apps/portal-operator/e2e/release-proof.spec.ts"),
            Path("civiccast/apps/portal-public/e2e/podcast-rss-release.spec.ts"),
        ]

        missing = [str(path) for path in required_specs if not path.exists()]

        assert missing == []

    def test_browser_qa_evidence_artifact_is_required_before_release(self) -> None:
        evidence_path = Path("docs/releases/evidence/v1.1-browser-qa.md")

        evidence = evidence_path.read_text(encoding="utf-8")

        for required_phrase in [
            "desktop",
            "mobile",
            "keyboard",
            "focus",
            "console",
            "zero serious or critical axe violations",
        ]:
            assert required_phrase in evidence.lower()
