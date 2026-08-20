# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.4 release-evidence policy checks."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _policy_module():
    try:
        return importlib.import_module("scripts.policy.check_v14_release_evidence")
    except ModuleNotFoundError:  # pragma: no cover - expected red state before implementation
        pytest.fail(
            "scripts.policy.check_v14_release_evidence must exist and expose "
            "evaluate_v14_release_evidence(root: Path) -> list[str]."
        )


def _evaluate(root: Path) -> list[str]:
    module = _policy_module()
    assert hasattr(module, "evaluate_v14_release_evidence")
    return module.evaluate_v14_release_evidence(root)


def test_blocked_v14_verification_can_exist_without_evidence(tmp_path: Path) -> None:
    _write(
        tmp_path / "docs" / "releases" / "v1.4-verification.md",
        "# v1.4 Verification\n\nRelease status: blocked - human proof gates remain open.\n",
    )

    assert _evaluate(tmp_path) == []


def test_promoted_v14_verification_requires_provider_and_walkthrough_evidence(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path / "docs" / "releases" / "v1.4-verification.md",
        "# v1.4 Verification\n\nRelease status: promoted for beta operations.\n",
    )

    violations = _evaluate(tmp_path)

    assert len(violations) == 3
    joined = "\n".join(violations)
    assert "v1.4-controlled-provider-proof.md" in joined
    assert "v1.4-nontechnical-operator-walkthrough.md" in joined
    assert "v1.4-technical-admin-walkthrough.md" in joined


def test_promoted_v14_verification_rejects_template_evidence(tmp_path: Path) -> None:
    _write(
        tmp_path / "docs" / "releases" / "v1.4-verification.md",
        "# v1.4 Verification\n\nRelease status: ready.\n",
    )
    _write(
        tmp_path / "docs" / "releases" / "evidence" / "v1.4-controlled-provider-proof.md",
        "Template: fill in after provider proof.\n",
    )
    _write(
        tmp_path / "docs" / "releases" / "evidence" / "v1.4-nontechnical-operator-walkthrough.md",
        "Observed session complete.\n",
    )
    _write(
        tmp_path / "docs" / "releases" / "evidence" / "v1.4-technical-admin-walkthrough.md",
        "Observed session complete.\n",
    )

    violations = _evaluate(tmp_path)

    assert len(violations) == 1
    assert "controlled live-provider proof" in violations[0]


def test_release_owner_waiver_can_close_missing_human_evidence(tmp_path: Path) -> None:
    _write(
        tmp_path / "docs" / "releases" / "v1.4-verification.md",
        "# v1.4 Verification\n\nRelease status: promoted with release-owner waiver.\n",
    )
    _write(
        tmp_path / "docs" / "releases" / "evidence" / "v1.4-release-owner-waiver.md",
        "Release owner: Scott Converse\nDecision: accept missing proof gates for this release.\n",
    )

    assert _evaluate(tmp_path) == []


def test_run_all_invokes_v14_release_evidence_policy_check() -> None:
    from scripts.policy import run_all

    checks = {name: args[0] for name, args in run_all.CHECKS}

    assert checks.get("check_v14_release_evidence") == "check_v14_release_evidence.py"
