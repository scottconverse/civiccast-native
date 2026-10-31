# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy checks for current release-candidate docs and version surfaces."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

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
CURRENT_CANDIDATE_TAG = f"v{CURRENT_VERSION}"
# The source version can be the next owner-held candidate while the published
# public release remains current. Public release links come from the authored
# release-truth manifest; the helper's default tag follows the published release.
PUBLISHED_RELEASE_TAG = yaml.safe_load(
    (ROOT / "docs" / "releases" / "release-truth.yaml").read_text(encoding="utf-8")
)["current"]

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


def test_windows_install_guide_pins_published_helper_and_verification_flow() -> None:
    install_doc = (ROOT / "INSTALL-WINDOWS.md").read_text(encoding="utf-8")
    normalized = " ".join(install_doc.split()).casefold()

    assert PUBLISHED_RELEASE_TAG.casefold() in normalized
    assert f"releases/tag/{PUBLISHED_RELEASE_TAG}".casefold() in normalized
    assert "download_windows_release_artifacts.ps1" in normalized
    assert "-install" in normalized
    assert "all five runtime packs and all six signed station packs" in normalized
    assert "sha-256" in normalized
    assert "authenticode signature" in normalized
    assert "install-progress.log" in normalized
    assert "actual nonzero exit is reported as failure" in normalized


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
    downloader = (ROOT / "scripts" / "download_windows_release_artifacts.ps1").read_text(
        encoding="utf-8"
    )
    assert f'$Tag = "{PUBLISHED_RELEASE_TAG}"' in downloader
    assert '$Version = ""' in downloader
    assert "$Version = $Tag -replace '^v', ''" in downloader
    assert '$Tag -ne "v$Version"' in downloader


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
    normalized = " ".join(text.replace("**", "").split()).casefold()
    # The false "nothing changed since rc6" claim must never return.
    assert "only installer unit tests and the version stamp changed" not in normalized
    assert PUBLISHED_RELEASE_TAG.casefold() in normalized
    assert f"releases/tag/{PUBLISHED_RELEASE_TAG}".casefold() in normalized
    if CURRENT_CANDIDATE_TAG.casefold() != PUBLISHED_RELEASE_TAG.casefold():
        # The heading may describe a beta or RC preparation. Locate the actual
        # source-version declaration rather than hard-coding a heading label.
        sections = [
            " ".join(section.replace("**", "").split()).casefold()
            for section in re.split(r"(?m)^## .+\n", text)[1:]
        ]
        candidates = [
            section
            for section in sections
            if f"`{CURRENT_CANDIDATE_TAG}` is an unpublished candidate".casefold() in section
        ]
        assert len(candidates) == 1, "README must distinguish the unpublished source candidate"
        candidate_section = candidates[0]
        published_section = normalized.split("## current published package", 1)[1].split("## ", 1)[
            0
        ]
        assert (
            f"`{CURRENT_CANDIDATE_TAG}` is an unpublished candidate".casefold() in candidate_section
        )
        assert "not available as a public release" in candidate_section
        assert "signed" in published_section
        assert f"releases/tag/{PUBLISHED_RELEASE_TAG}".casefold() in published_section
    assert (
        "historical beta 11 host result: 72 hours across public, government, and education, "
        "with 99.78% live caption-input coverage" in normalized
    )
    assert "result remains beta 11 evidence and does not qualify later packages" in normalized
    assert "216 healthy scheduled checkpoints" in normalized
    assert "verification record" in normalized
    assert "72-hour report" in normalized


def test_architecture_doc_names_current_release() -> None:
    """ARCHITECTURE.md's release-posture line must name the published release.

    Regression guard: this doc named a two-releases-old public-beta line as
    "current" for two full release cycles before an audit caught it. Nothing
    in ACTIVE_RELEASE_SURFACES' stale-marker scan would have caught that,
    because the drift wasn't a leftover old-version string -- it was a
    release-posture claim that was simply never updated.
    """
    text = ARCHITECTURE_DOC.read_text(encoding="utf-8")
    # Public release posture follows the release-truth manifest even while
    # the source tree advances to an unpublished candidate.
    assert PUBLISHED_RELEASE_TAG in text, (
        f"ARCHITECTURE.md's release-posture paragraph does not name {PUBLISHED_RELEASE_TAG}"
    )
