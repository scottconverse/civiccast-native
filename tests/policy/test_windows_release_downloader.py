# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy checks for the Windows release artifact downloader."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOWNLOADER = ROOT / "scripts" / "download_windows_release_artifacts.ps1"
INSTALL_DOC = ROOT / "INSTALL-WINDOWS.md"
RELEASE_TRUTH = ROOT / "docs" / "releases" / "release-truth.yaml"
# Derived from the single source of truth so these checks can't drift on a bump.
CURRENT_VERSION = (
    (ROOT / "civiccast" / "_version.py")
    .read_text(encoding="utf-8")
    .split('__version__ = "', 1)[1]
    .split('"', 1)[0]
)
# The product-identity version (CURRENT_VERSION, above) and the actual
# downloadable GitHub Release tag are NOT the same thing once a release-prep
# bump lands ahead of a publish: see check_v17_adoption_gate.py's
# REQUIRED_DOCS, which deliberately hardcodes the published tag separately
# from its own CURRENT_RELEASE_TAG for exactly this reason. Derive the
# published tag from docs/releases/release-truth.yaml's authored `current`
# field -- the sole authored source for release state -- rather than
# assuming it always equals civiccast/_version.py's value.
PUBLISHED_RELEASE_TAG = yaml.safe_load(RELEASE_TRUTH.read_text(encoding="utf-8"))["current"]


def test_windows_release_downloader_verifies_manifest_hashes() -> None:
    source = DOWNLOADER.read_text(encoding="utf-8")

    assert f'$Version = "{CURRENT_VERSION}"' in source
    assert 'release-artifacts-manifest.json"' in source
    assert 'clean-windows-proof-kit.zip"' in source
    assert 'windows-tester-package.zip"' in source
    assert "Get-FileHash" in source
    assert "Expand-Archive" in source
    assert "browser_download_url" in source
    assert "sha256" in source


def test_windows_install_doc_matches_current_release_posture() -> None:
    source = INSTALL_DOC.read_text(encoding="utf-8")
    assert f"`v{CURRENT_VERSION}`" in source
    assert f"civiccast-native/releases/tag/{PUBLISHED_RELEASE_TAG}" in source


def test_downloader_falls_back_to_release_asset_digest_when_unlisted() -> None:
    """Regression guard for the rc.3 clean-machine-proof gap.

    The release-artifacts manifest is built by one CI job (Linux/portable
    outputs) and never lists artifacts a separate job uploads directly (the
    Windows installer, proof kit, tester package). The downloader must not
    hard-fail when a requested file isn't in that manifest -- it must fall
    back to the GitHub Release asset's own server-computed digest, which is
    what a tester's local `Get-FileHash` will actually match against.
    """
    source = DOWNLOADER.read_text(encoding="utf-8")

    assert "function Get-ExpectedSha256" in source
    assert "$Asset.digest" in source
    assert "not listed in the release-artifacts manifest" in source
    # Get-ManifestEntry must no longer throw on a miss -- callers branch on
    # a null return instead, which is what makes the fallback reachable.
    manifest_entry_fn = source[
        source.index("function Get-ManifestEntry") : source.index("function Get-ExpectedSha256")
    ]
    assert "throw" not in manifest_entry_fn


def test_native_candidate_mode_asset_names_match_the_publisher() -> None:
    """The downloader's NativeCandidate mode must name exactly the assets
    scripts/release/publish_beta_candidate.py uploads, pinned against that
    script's own constants so a rename on either side fails here.
    """
    from scripts.release import publish_beta_candidate as publisher

    source = DOWNLOADER.read_text(encoding="utf-8")

    assert '"NativeCandidate"' in source
    assert f'$NativeSetupName = "{publisher.SETUP_ASSET_NAME}"' in source
    assert f'$NativeSumsName = "{publisher.SHA256SUMS_ASSET_NAME}"' in source
    assert f'$NativeSidecarSuffix = "{publisher.SIDECAR_SUFFIX}"' in source
    assert f'$NativePackSuffix = "{publisher.PACK_SUFFIX}"' in source
    # Default repository is the native repo, and the native mode is the
    # default there; the rc-line modes are kept for the old repository.
    assert '$Repository = "scottconverse/civiccast-native"' in source
    assert 'if ($Repository -eq "scottconverse/civiccast-native") {' in source
    assert '$AssetSet = "NativeCandidate"' in source
    assert "[switch]$IncludePacks" in source
    # Every native asset is hash-verified against SHA256SUMS.txt, and the
    # sidecar cross-checked against the same setup.exe line.
    assert "function Read-Sha256Sums" in source
    assert "Assert-Sha256 -Path $setupPath -ExpectedHash $sums[$NativeSetupName]" in source
    assert "Assert-Sha256 -Path $packPath -ExpectedHash $sums[$packAsset.name]" in source
    assert "[string]$sidecar.sha256 -ne $sums[$NativeSetupName]" in source
