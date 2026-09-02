# SPDX-License-Identifier: Apache-2.0
"""Truth contracts for the current owner-held release candidate."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CURRENT_RELEASE_TAG = (
    "v"
    + (
        (ROOT / "civiccast" / "_version.py")
        .read_text(encoding="utf-8")
        .split('__version__ = "', 1)[1]
        .split('"', 1)[0]
    )
)

FRONT_DOORS = (
    "README.md",
    "INSTALL-WINDOWS.md",
    "ARCHITECTURE.md",
    "SUPPORT.md",
    "docs/index.html",
    "docs/install-windows.html",
)


def test_current_candidate_surfaces_match_the_release_posture() -> None:
    for relative in FRONT_DOORS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        normalized = " ".join(text.lower().split())
        assert CURRENT_RELEASE_TAG in text, relative
        assert "owner-held unpublished candidate" in normalized, relative
        assert "no installer" in normalized or "no public installer" in normalized, relative
        assert "not a public or production release" in normalized, relative


def test_front_doors_name_the_current_candidate_state() -> None:
    for relative in FRONT_DOORS:
        text = " ".join((ROOT / relative).read_text(encoding="utf-8").lower().split())
        assert CURRENT_RELEASE_TAG.lower() in text, relative
        assert "owner-held unpublished candidate" in text, relative
        assert "not a public or production release" in text, relative


def test_front_doors_do_not_offer_an_unproven_candidate_download() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install_html = (ROOT / "docs/install-windows.html").read_text(encoding="utf-8")
    assert "releases/latest" not in readme
    assert "releases/latest" not in install_html
    assert "no installer" in readme.lower()
    assert "no public windows installer download" in install_html.lower()


def test_retired_tester_docs_do_not_masquerade_as_native_proof() -> None:
    selected = (
        "docs/tester/lpm-beta-test-handoff.md",
        "docs/tester/technical-walkthrough.md",
        "docs/tester/known-limitations.md",
        "docs/tester/SMARTSCREEN-WALKTHROUGH.md",
        "docs/install/windows-release-trust.md",
    )
    joined = "\n".join((ROOT / relative).read_text(encoding="utf-8") for relative in selected)
    lower = joined.lower()
    assert "retired" in lower or "historical" in lower
    assert "wsl2" in lower
    assert "civiccast-native" in lower


def test_migration_reference_docs_name_the_actual_head() -> None:
    reconciliation = (ROOT / "docs/spec/3.0/RECONCILIATION.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs/spec/3.0/ROADMAP.status.yaml").read_text(encoding="utf-8")
    assert "`0072_normalize_recording_file_uris`" in reconciliation
    assert "single-headed at 0060_recording_paywall_merge" not in roadmap
    assert "0072_normalize_recording_file_uris" in roadmap


def test_support_does_not_name_v17_as_the_current_release() -> None:
    support = (ROOT / "SUPPORT.md").read_text(encoding="utf-8")
    assert "latest completed source/runtime release is v1.7.0" not in support


def test_windows_setup_guidance_requires_visible_progress() -> None:
    for relative in ("README.md", "INSTALL-WINDOWS.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "heartbeat" in text.lower(), relative
        assert "visibly active" in text.lower(), relative
    assert 'no longer freezes ("Not Responding")' not in (ROOT / "README.md").read_text(
        encoding="utf-8"
    )


def test_user_manual_names_current_migration_and_limits_external_claims() -> None:
    manual = (ROOT / "docs" / "USER-MANUAL.md").read_text(encoding="utf-8")
    assert "single-headed at `0072_normalize_recording_file_uris`" in manual
    assert "0060_recording_paywall_merge â† HEAD" not in manual
    assert "record-of-record version" not in manual
    assert "major\n  mobile app stores" not in manual
    assert CURRENT_RELEASE_TAG in manual
    assert "candidate" in manual.lower()
