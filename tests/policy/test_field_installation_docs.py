# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Keep field-installation guidance honest about trust and readiness.

The negative fixtures below are excerpts from ``git show
3074115c:docs/QUICKSTART-OPERATOR.md`` and
``git show 3074115c:docs/tester/START-HERE.md``.  They document actual claims
that previously made a checksum sidecar sound signed and treated an unfinished
installer screen as operational success.
"""

from __future__ import annotations

import re
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELD_DELIVERY_DOCUMENTS = (
    ROOT / "README.md",
    ROOT / "docs/QUICKSTART-OPERATOR.md",
    ROOT / "docs/index.html",
    ROOT / "docs/install/windows-release-trust.md",
    ROOT / "docs/tester/START-HERE.md",
    ROOT / "docs/tester/lpm-beta-test-handoff.md",
    ROOT / "docs/tester/nontechnical-walkthrough.md",
    ROOT / "docs/tester/technical-walkthrough.md",
    ROOT / "docs/tester/SMARTSCREEN-WALKTHROUGH.md",
)


def _normalized_plaintext(path: Path) -> str:
    """Normalize Markdown or HTML enough that formatting cannot hide a claim."""

    text = unescape(path.read_text(encoding="utf-8"))
    text = re.sub(r"<(?:script|style)\b.*?</(?:script|style)>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[`*_>#\[\]|']", " ", text)
    return re.sub(r"\s+", " ", text).casefold()


def _contains_affirmative_signed_metadata_claim(text: str) -> bool:
    """Return true for a sidecar/delivery-manifest signing claim, not its denial."""

    normalized = re.sub(r"\s+", " ", text).casefold()
    pattern = re.compile(r"\bsigned\s+(?:setup\.exe\.sidecar\.json|sidecar|delivery manifest)\b")
    for match in pattern.finditer(normalized):
        prefix = normalized[max(0, match.start() - 48) : match.start()]
        if re.search(r"\b(?:not|no|never)\s+(?:a\s+|the\s+|separately\s+)?$", prefix):
            continue
        return True
    return False


def _assert_no_false_completion_claims(text: str) -> None:
    assert "you re live" not in text
    assert "you are live" not in text
    pattern = re.compile(r"\bwaiting\b.{0,240}\b(?:everything|station)\b.{0,120}\binstalled\b")
    for match in pattern.finditer(text):
        prefix = text[max(0, match.start() - 64) : match.start()]
        if re.search(r"\b(?:do not|don t|never)\s+(?:assume|treat)(?:\s+that)?\s+$", prefix):
            continue
        raise AssertionError("Waiting must not be presented as proof that installation completed.")


def test_field_delivery_docs_do_not_claim_plain_metadata_is_signed() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in FIELD_DELIVERY_DOCUMENTS
        if _contains_affirmative_signed_metadata_claim(_normalized_plaintext(path))
    ]
    assert not offenders, f"Plain sidecar/delivery metadata is described as signed: {offenders}"


def test_quickstart_verifies_hash_and_authenticode_before_running_installer() -> None:
    quickstart = _normalized_plaintext(ROOT / "docs/QUICKSTART-OPERATOR.md")
    hash_check = quickstart.index("sha-256 against the trusted handoff")
    authenticode_check = quickstart.index("valid authenticode signature")
    run_installer = quickstart.index("run its branded")

    assert hash_check < run_installer
    assert authenticode_check < run_installer
    assert "matching hash alone is not proof of publisher identity" in quickstart


def test_quickstart_keeps_smartscreen_conditional_and_installation_distinct_from_cutover() -> None:
    quickstart = _normalized_plaintext(ROOT / "docs/QUICKSTART-OPERATOR.md")

    conditional_warning = quickstart.index("if windows shows windows protected your pc")
    verify_publisher = quickstart.index("verify that the publisher is scott converse")
    reject_mismatch = quickstart.index("choose don t run")
    proceed_after_checks = quickstart.index(
        "if the checks match the approved test kit, choose run anyway"
    )
    assert conditional_warning < verify_publisher < reject_mismatch < proceed_after_checks

    assert "on the station itself" in quickstart
    assert "recovery codes" in quickstart
    assert "system health is green" in quickstart
    assert "installation check, not yet a beta release or production-readiness claim" in quickstart
    assert "not a production cutover instruction" in quickstart
    assert "wait for the station owner s cutover decision" in quickstart
    _assert_no_false_completion_claims(quickstart)


def test_actual_pre_correction_claims_fail_the_same_detectors(tmp_path: Path) -> None:
    """Prove the guards reject the real 3074115c field-guide regressions."""

    old_start_here = tmp_path / "START-HERE.md"
    old_start_here.write_text(
        "a SHA256SUMS.txt checksum file, and a signed setup.exe.sidecar.json are attached",
        encoding="utf-8",
    )
    assert _contains_affirmative_signed_metadata_claim(_normalized_plaintext(old_start_here))
    assert _contains_affirmative_signed_metadata_claim("Use the signed delivery manifest.")
    assert not _contains_affirmative_signed_metadata_claim("It is not a signed sidecar.")
    _assert_no_false_completion_claims(
        "Do not assume waiting means everything is installed.".casefold()
    )
    # Exercise each real defect independently: an earlier 'You're live'
    # assertion must not mask a detector that misses the later Waiting claim.
    old_quickstart = tmp_path / "QUICKSTART-OPERATOR.md"
    for excerpt in (
        "## 6. You're live",
        "An item says Waiting and never starts. Everything you need is already "
        "installed at that point - the station is running.",
    ):
        old_quickstart.write_text(excerpt, encoding="utf-8")
        old_text = _normalized_plaintext(old_quickstart)
        try:
            _assert_no_false_completion_claims(old_text)
        except AssertionError:
            pass
        else:  # pragma: no cover - each fixture must fail independently.
            raise AssertionError(f"An actual pre-correction claim was accepted: {excerpt}")
