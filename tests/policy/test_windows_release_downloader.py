# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy checks for the Windows release artifact downloader."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOWNLOADER = ROOT / "scripts" / "download_windows_release_artifacts.ps1"
INSTALL_DOC = ROOT / "INSTALL-WINDOWS.md"
# Derived from the single source of truth so these checks can't drift on a bump.
CURRENT_VERSION = (
    (ROOT / "civiccast" / "_version.py")
    .read_text(encoding="utf-8")
    .split('__version__ = "', 1)[1]
    .split('"', 1)[0]
)


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
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    release_url = f"releases/tag/v{CURRENT_VERSION}"

    assert f"`v{CURRENT_VERSION}`" in source
    if release_url in readme:
        # The framing the line ships under. It moves with the release posture;
        # what must not move is the pairing -- a doc that offers the download
        # names the scope, and a doc that withholds it says so.
        assert "controlled beta" in source
    else:
        assert release_url not in source
        assert "unpublished repair candidate" in source
        assert "no approved public Windows installer" in source


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
