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

PUBLIC_SURFACES = (
    "README.md",
    "INSTALL-WINDOWS.md",
    "ARCHITECTURE.md",
    "CAPABILITIES.md",
    "FAQ.md",
    "SUPPORT.md",
    "docs/index.html",
    "docs/install-windows.html",
    "docs/adoption/early-adopter-quickstart.md",
    "docs/adoption/release-policy.md",
    "docs/tester/START-HERE.md",
    "docs/tester/lpm-beta-test-handoff.md",
    "docs/tester/technical-walkthrough.md",
    "docs/tester/known-limitations.md",
    "docs/tester/SMARTSCREEN-WALKTHROUGH.md",
    "docs/install/windows-release-trust.md",
)

FRONT_DOORS = (
    "README.md",
    "INSTALL-WINDOWS.md",
    "ARCHITECTURE.md",
    "SUPPORT.md",
    "docs/index.html",
    "docs/install-windows.html",
)


def _is_public_release(root: Path = ROOT) -> bool:
    readme = (root / "README.md").read_text(encoding="utf-8")
    return (
        f"https://github.com/scottconverse/civiccast/releases/tag/{CURRENT_RELEASE_TAG}" in readme
    )


def test_current_candidate_surfaces_match_the_release_posture() -> None:
    release_url = f"https://github.com/scottconverse/civiccast/releases/tag/{CURRENT_RELEASE_TAG}"
    release_link_surfaces = (
        "README.md",
        "INSTALL-WINDOWS.md",
        "ARCHITECTURE.md",
        "SUPPORT.md",
        "docs/index.html",
        "docs/install-windows.html",
        "docs/adoption/early-adopter-quickstart.md",
        "docs/tester/START-HERE.md",
        "docs/tester/lpm-beta-test-handoff.md",
        "docs/tester/technical-walkthrough.md",
        "docs/tester/known-limitations.md",
        "docs/tester/SMARTSCREEN-WALKTHROUGH.md",
        "docs/install/windows-release-trust.md",
    )
    for relative in release_link_surfaces:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert CURRENT_RELEASE_TAG in text, relative
        if not _is_public_release():
            assert release_url not in text, relative
            assert any(
                marker in text.lower()
                for marker in ("unpublished", "not approved", "no approved", "testing paused")
            ), relative


def test_front_doors_name_the_current_candidate_state() -> None:
    for relative in FRONT_DOORS:
        text = (ROOT / relative).read_text(encoding="utf-8").lower()
        assert CURRENT_RELEASE_TAG.lower() in text, relative
        if _is_public_release():
            assert "public" in text and "beta" in text, relative
        else:
            assert any(
                marker in text
                for marker in ("unpublished", "not approved", "no approved", "testing paused")
            ), relative


def test_front_doors_do_not_offer_an_unproven_candidate_download() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    install_html = (ROOT / "docs/install-windows.html").read_text(encoding="utf-8")
    exact = f"https://github.com/scottconverse/civiccast/releases/tag/{CURRENT_RELEASE_TAG}"
    if not _is_public_release():
        assert exact not in readme
        assert exact not in install_html
    assert "releases/latest" not in readme
    assert "releases/latest" not in install_html


def test_linked_tester_docs_hold_current_candidate_for_proof() -> None:
    selected = (
        "docs/tester/lpm-beta-test-handoff.md",
        "docs/tester/technical-walkthrough.md",
        "docs/tester/known-limitations.md",
        "docs/tester/SMARTSCREEN-WALKTHROUGH.md",
        "docs/install/windows-release-trust.md",
    )
    joined = "\n".join((ROOT / relative).read_text(encoding="utf-8") for relative in selected)
    assert CURRENT_RELEASE_TAG in joined
    if not _is_public_release():
        assert (
            f"https://github.com/scottconverse/civiccast/releases/tag/{CURRENT_RELEASE_TAG}"
            not in joined
        )
        assert "unpublished" in joined.lower() or "not approved" in joined.lower()


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


def test_changelog_does_not_describe_current_rc11_as_rc9_equivalent() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    rc11 = changelog.split("## [1.0.0-rc11]", 1)[1].split("\n## [", 1)[0]
    assert "No product or\ninstaller-behavior change from rc9" not in rc11
    assert "rc9 installer passed a full clean-VM" not in rc11
    assert "published as a public prerelease" in rc11.lower()
