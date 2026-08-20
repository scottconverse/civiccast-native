# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11c honesty guard (master Sec. 7): the build fails if any public-facing string
AFFIRMATIVELY claims EAS capability. Disclaimers ("not an EAS device", "does not
provide EAS") are required and allowed; an un-negated claim is the failure.

CivicCast displays public-safety information; it is not an EAS device, does not relay
the FCC Part 11 signal, and generates no SAME headers. This test is the tripwire that
keeps that line from eroding into the product copy.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Phrases that, said affirmatively, would be a false EAS claim.
_FORBIDDEN_CLAIMS = (
    "eas-compliant",
    "eas compliant",
    "provides eas",
    "eas certified",
    "eas-certified",
    "eas device",
    "eas relay",
    "eas origination",
    "eas capable",
    "eas-capable",
    "part 11 compliant",
)
# A claim on the same line as any of these is a disclaimer (allowed).
_NEGATIONS = (
    "not ",
    "never",
    "n't",
    "without",
    "no ",
    "isn",
    "does not",
    "cannot",
    "non-eas",
    "nothing",
)

# The files whose strings reach operators / the public. The EAS module + the public CG
# overlay path + the operator EAS UI. (This test file is excluded — it names the claims.)
_SCAN_GLOBS = (
    "civiccast/eas/*.py",
    "civiccast/cg/router.py",
    "civiccast/cg/service.py",
    "civiccast/apps/portal-operator/src/screens/EasScreen.tsx",
    "civiccast/apps/portal-operator/src/components/EasPostureBanner.tsx",
)


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for pattern in _SCAN_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    return files


def test_no_affirmative_eas_claim_in_public_strings() -> None:
    violations: list[str] = []
    for path in _scanned_files():
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw.lower()
            if any(neg in line for neg in _NEGATIONS):
                continue  # a disclaimer line — allowed
            for claim in _FORBIDDEN_CLAIMS:
                if claim in line:
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {raw.strip()}")
    assert not violations, (
        "Affirmative EAS claim(s) found (master Sec. 7 honesty line):\n" + "\n".join(violations)
    )


def test_eas_posture_disclaimer_is_present() -> None:
    """Somewhere in the EAS surface, the not-an-EAS-device posture must be stated."""
    corpus = "\n".join(p.read_text(encoding="utf-8").lower() for p in _scanned_files())
    assert "not an eas device" in corpus, (
        "The required EAS posture disclaimer ('not an EAS device') is missing from the "
        "EAS-facing surface."
    )


def test_scan_actually_found_files() -> None:
    # Guard the guard: if the globs silently match nothing, the honesty test is hollow.
    found = {p.name for p in _scanned_files()}
    assert "models.py" in found  # civiccast/eas/models.py at minimum
    if not (REPO_ROOT / "civiccast/apps/portal-operator/src/screens/EasScreen.tsx").exists():
        pytest.fail("EasScreen.tsx is missing — the operator EAS UI must exist for slice 3.")
