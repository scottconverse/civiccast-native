# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for Phase 0 claims-retraction policy checks."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _policy_module():
    try:
        return importlib.import_module("scripts.policy.check_claims_retraction")
    except ModuleNotFoundError:  # pragma: no cover - expected red state before implementation
        pytest.fail(
            "scripts.policy.check_claims_retraction must exist and expose "
            "evaluate_claims_retraction(root: Path) -> list[str]."
        )


def _evaluate(root: Path) -> list[str]:
    module = _policy_module()
    assert hasattr(module, "evaluate_claims_retraction"), (
        "scripts.policy.check_claims_retraction must expose "
        "evaluate_claims_retraction(root: Path) -> list[str]."
    )
    return module.evaluate_claims_retraction(root)


def _assert_violation_for(root: Path, expected_path: str, expected_text: str) -> None:
    violations = _evaluate(root)
    assert violations, f"Expected a claims-retraction violation for {expected_path}."
    joined = "\n".join(violations)
    assert expected_path in joined
    assert expected_text.lower() in joined.lower()


@pytest.mark.parametrize(
    ("relative_path", "claim", "expected_text"),
    [
        ("README.md", "valid PDF/A-3B signed record", "valid PDF/A-3B signed record"),
        ("docs/USER-MANUAL.md", "signed PDF/A-3B record", "signed PDF/A-3B record"),
        ("docs/API-REFERENCE.md", "PDF/A-3B signed record", "PDF/A-3B signed record"),
        (
            "docs/ops/staff-route-protection.md",
            "legally defensible signed record",
            "legally defensible signed record",
        ),
        ("civiccast/records/README.md", "legally defensible PDF/A", "legally defensible PDF/A"),
        (
            "civiccast/apps/portal-operator/README.md",
            "legal signed record",
            "legal signed record",
        ),
        (
            "docs/index.html",
            "The fixture artifact includes an RFC 3161-style timestamp proof.",
            "RFC 3161-style timestamp proof",
        ),
        (
            "docs/ops/credential-matrix.md",
            "The fixture artifact has PDF/A-3B conformance.",
            "PDF/A-3B conformance",
        ),
        (
            "README.md",
            "The fixture artifact conformance is guaranteed for export.",
            "conformance",
        ),
    ],
)
def test_current_facing_unqualified_claim_families_fail(
    tmp_path: Path,
    relative_path: str,
    claim: str,
    expected_text: str,
) -> None:
    _write(tmp_path / relative_path, f"Current v1.0.0 status: {claim}\n")

    _assert_violation_for(tmp_path, relative_path, expected_text)


def test_qualified_fixture_language_passes_for_current_facing_surfaces(tmp_path: Path) -> None:
    _write(
        tmp_path / "README.md",
        "In v1.0.0, signed PDF/A-3B record language describes a deterministic "
        "contract fixture, not a valid PDF/A-3B document in v1.0.0.\n",
    )
    _write(
        tmp_path / "docs" / "USER-MANUAL.md",
        "The RFC 3161-style timestamp proof is fixture metadata for a deterministic "
        "contract fixture, not a real timestamped PDF/A-3B artifact in v1.0.0.\n",
    )
    _write(
        tmp_path / "civiccast" / "records" / "README.md",
        "Any legal signed record wording is limited to deterministic contract fixture "
        "coverage and is not a legally defensible signed record in v1.0.0.\n",
    )

    assert _evaluate(tmp_path) == []


def test_historical_evidence_passes_only_with_explicit_fixture_context(tmp_path: Path) -> None:
    _write(
        tmp_path / "docs" / "releases" / "evidence" / "v0.6-signed-record-export-proof.md",
        "Historical deterministic fixture proof: the v0.6 export exercised signed "
        "PDF/A-3B record contract text as a deterministic contract fixture, not a valid "
        "PDF/A-3B document in v1.0.0.\n",
    )

    assert _evaluate(tmp_path) == []


def test_historical_evidence_without_fixture_context_fails(tmp_path: Path) -> None:
    relative_path = "docs/releases/evidence/v0.6-signed-record-export-proof.md"
    _write(
        tmp_path / relative_path,
        "The v0.6 release evidence proves a valid PDF/A-3B signed record export.\n",
    )

    _assert_violation_for(tmp_path, relative_path, "valid PDF/A-3B signed record")


def test_bare_valid_pdfa3b_document_claim_fails_unless_qualified(tmp_path: Path) -> None:
    relative_path = "civiccast/records/CHANGELOG.md"
    _write(
        tmp_path / relative_path,
        "The current export is a valid PDF/A-3B document for public records requests.\n",
    )

    _assert_violation_for(tmp_path, relative_path, "valid PDF/A-3B document")


def test_runtime_warning_stale_through_v010_language_fails(tmp_path: Path) -> None:
    relative_path = "civiccast/app.py"
    _write(
        tmp_path / relative_path,
        '_LOG.warning("Staff routes remain unauthenticated through v0.10; deploy carefully.")\n',
    )

    _assert_violation_for(tmp_path, relative_path, "through v0.10")


def test_runtime_warning_current_v100_language_passes(tmp_path: Path) -> None:
    _write(
        tmp_path / "civiccast" / "app.py",
        '_LOG.warning("In v1.0.0, protect staff routes behind an authenticating reverse proxy '
        'until server-verified identity ships.")\n',
    )

    assert _evaluate(tmp_path) == []


def test_run_all_invokes_claims_retraction_policy_check() -> None:
    from scripts.policy import run_all

    checks = {name: args[0] for name, args in run_all.CHECKS}

    assert checks.get("check_claims_retraction") == "check_claims_retraction.py"
