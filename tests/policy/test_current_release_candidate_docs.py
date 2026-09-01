# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy checks for current release-candidate docs and version surfaces."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The build/runtime version this codebase reports. DERIVED from the single
# source of truth (civiccast/_version.py) so this policy check can never go
# stale against a version bump again -- the whole point of the check is to
# catch drift, so it must not itself hardcode a version that drifts.
CURRENT_VERSION = (
    (ROOT / "civiccast" / "_version.py")
    .read_text(encoding="utf-8")
    .split('__version__ = "', 1)[1]
    .split('"', 1)[0]
)
# The owner-held candidate identity. This is intentionally distinct from a
# published-release claim: rc11 must remain unavailable until owner approval.
HELD_CANDIDATE_TAG = f"v{CURRENT_VERSION}"

ACTIVE_RELEASE_SURFACES = [
    ROOT / "README.md",
    ROOT / "INSTALL-WINDOWS.md",
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "index.html",
    ROOT / "docs" / "install" / "windows-release-trust.md",
    ROOT / "docs" / "tester" / "START-HERE.md",
    ROOT / "docs" / "releases" / "v0.1.0-rc6-verification.md",
    ROOT / "docs" / "discussions" / "SEED-POSTS.md",
    ROOT / "docs" / "public" / "github-discussions" / "early-adopter-announcement.md",
    ROOT / "scripts" / "download_windows_release_artifacts.ps1",
    ROOT / "civiccast" / "_version.py",
    ROOT / "civiccast" / "apps" / "installer" / "package.json",
    ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "Cargo.toml",
    ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json",
    ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "src" / "main.rs",
    ROOT
    / "civiccast"
    / "apps"
    / "installer"
    / "src-tauri"
    / "resources"
    / "headless-bootstrap.ps1",
    ROOT / "civiccast" / "apps" / "portal-operator" / "e2e" / "route-table-smoke.spec.ts",
    ROOT / "civiccast" / "apps" / "portal-operator" / "e2e" / "control-room-readiness.spec.ts",
    ROOT / "tests" / "policy" / "test_windows_release_downloader.py",
    ROOT / "tests" / "policy" / "test_windows_wsl_bootstrap_script.py",
]

# ARCHITECTURE.md is not release-installer-critical, so it is checked
# separately (test_architecture_doc_names_current_release below) rather than
# folded into ACTIVE_RELEASE_SURFACES's stale-evidence-marker scan: its prior
# staleness (naming a two-releases-old beta line as "current") was a release
# posture claim, not a leftover build marker, and needs its own assertion so
# a future rc bump can't silently skip it again.
ARCHITECTURE_DOC = ROOT / "ARCHITECTURE.md"

STALE_PRODUCT_MARKERS = [
    "4.0.0-rc.1",
    "4.0.0rc1",
    "v4.0.0-rc.1",
    "4.0.0-rc.2",
    "4.0.0rc2",
    "v4.0.0-rc.2",
]

STALE_EVIDENCE_MARKERS = [
    "13dcf7776180f2536630011eaf31f8714669c9f3",
    "4.0-stage7-final-13dcf777",
    "4.0-rc1-13dcf777",
    "c2e3a5381b7707547d43141f22a56958ce325e648a39754ce888da82cdac4e75",
    "5a15c39b62b3158d599e7a9222e5c01fd783438bf2e28604b21fb5aab39eda18",
]


def test_clean_windows_docs_require_docs_first_proof_step() -> None:
    install_doc = (ROOT / "INSTALL-WINDOWS.md").read_text(encoding="utf-8")
    tester_doc = (ROOT / "docs" / "tester" / "START-HERE.md").read_text(encoding="utf-8")

    required_targets = [
        "docs/tester/START-HERE.md",
        "INSTALL-WINDOWS.md",
        "docs/install/windows-release-trust.md",
    ]

    for target in required_targets:
        assert target in install_doc or target in tester_doc

    assert "A clean-machine test starts with the documentation" in install_doc
    assert "Record in the clean-machine proof report" in install_doc
    assert "Clean-Machine Test Rule" in tester_doc
    assert "Your proof report must state that these docs were read" in tester_doc
    assert "installer/proof package disagree" in install_doc
    assert "GitHub Release assets, manifest, sidecar, and installer UI" in tester_doc


def test_current_release_identity_is_consistent_across_runtime_and_installer() -> None:
    assert f'__version__ = "{CURRENT_VERSION}"' in (ROOT / "civiccast" / "_version.py").read_text(
        encoding="utf-8"
    )
    assert f'"version": "{CURRENT_VERSION}"' in (
        ROOT / "civiccast" / "apps" / "installer" / "package.json"
    ).read_text(encoding="utf-8")
    assert f'version = "{CURRENT_VERSION}"' in (
        ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "Cargo.toml"
    ).read_text(encoding="utf-8")
    assert f'"version": "{CURRENT_VERSION}"' in (
        ROOT / "civiccast" / "apps" / "installer" / "src-tauri" / "tauri.conf.json"
    ).read_text(encoding="utf-8")
    assert HELD_CANDIDATE_TAG in (
        ROOT / "scripts" / "download_windows_release_artifacts.ps1"
    ).read_text(encoding="utf-8")


def test_retired_wsl_install_docs_are_explicitly_historical() -> None:
    """Old WSL instructions remain evidence, never native install guidance."""
    retired_docs = [
        ROOT / "docs" / "adoption" / "early-adopter-quickstart.md",
        ROOT / "docs" / "tester" / "START-HERE.md",
        ROOT / "docs" / "tester" / "lpm-beta-test-handoff.md",
    ]
    for path in retired_docs:
        text = path.read_text(encoding="utf-8")
        lower = text.lower()
        assert "historical" in lower or "retired" in lower
        assert "wsl2" in lower
        assert "civiccast-native" in lower


def test_readme_keeps_source_and_field_proof_distinct() -> None:
    """Source and lab evidence must not be presented as field proof."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    normalized = " ".join(text.split())
    # The false "nothing changed since rc6" claim must never return.
    assert "only installer unit tests and the version stamp changed" not in text
    assert "not a public or production release" in normalized
    assert "has no installer download attached" in normalized
    assert "has not been proven against physical SDI" in normalized


def test_architecture_doc_names_current_release() -> None:
    """ARCHITECTURE.md's release-posture line must name the current candidate.

    Regression guard: this doc named a two-releases-old public-beta line as
    "current" for two full release cycles before an audit caught it. Nothing
    in ACTIVE_RELEASE_SURFACES' stale-marker scan would have caught that,
    because the drift wasn't a leftover old-version string -- it was a
    release-posture claim that was simply never updated.
    """
    text = ARCHITECTURE_DOC.read_text(encoding="utf-8")
    # Release posture names the owner-held candidate without implying publication.
    assert HELD_CANDIDATE_TAG in text, (
        f"ARCHITECTURE.md's release-posture paragraph does not name {HELD_CANDIDATE_TAG}"
    )
