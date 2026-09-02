# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy contracts for current-facing beta handoff documentation."""

from __future__ import annotations

import importlib
from pathlib import Path


class TestBetaHandoffDocsPolicy:
    def test_current_facing_install_docs_reject_placeholders(self, tmp_path: Path) -> None:
        checker = importlib.import_module("scripts.policy.check_beta_handoff_docs")
        docs_root = tmp_path / "docs"
        target = docs_root / "installer" / "beta-tester-handoff.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "\n".join(
                [
                    "# Beta tester handoff",
                    "",
                    "TODO: replace this placeholder with the real clean Windows install proof.",
                    "Use fake-success credentials until external providers are available.",
                ]
            ),
            encoding="utf-8",
        )

        result = checker.check_beta_handoff_docs(docs_root)

        assert result.status == "failed"
        assert any("placeholder" in finding.message.lower() for finding in result.findings)
        assert any("fake-success" in finding.message.lower() for finding in result.findings)

    def test_historical_false_proof_context_is_allowed(self, tmp_path: Path) -> None:
        checker = importlib.import_module("scripts.policy.check_beta_handoff_docs")
        docs_root = tmp_path / "docs"
        target = docs_root / "releases" / "evidence" / "v1.2-placeholder-retraction.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "\n".join(
                [
                    "# Historical false-proof context",
                    "",
                    "This historical note records that prior placeholder credentials were rejected.",
                    "Current beta handoff instructions require blocked states until proof is recorded.",
                ]
            ),
            encoding="utf-8",
        )

        result = checker.check_beta_handoff_docs(docs_root)

        assert result.status == "passed"
        assert result.findings == []

    def test_banned_tokens_do_not_match_inside_ordinary_words(self, tmp_path: Path) -> None:
        checker = importlib.import_module("scripts.policy.check_beta_handoff_docs")
        docs_root = tmp_path / "docs"
        target = docs_root / "USER-MANUAL.md"
        target.parent.mkdir(parents=True)
        target.write_text(
            "ActivityPub interoperates with Mastodon and similar services.\n",
            encoding="utf-8",
        )

        result = checker.check_beta_handoff_docs(docs_root)

        assert result.status == "passed"
        assert result.findings == []
