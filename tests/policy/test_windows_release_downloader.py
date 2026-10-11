# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy checks for the Windows release artifact downloader."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOWNLOADER = ROOT / "scripts" / "download_windows_release_artifacts.ps1"
INSTALL_DOC = ROOT / "INSTALL-WINDOWS.md"
RELEASE_TRUTH = ROOT / "docs" / "releases" / "release-truth.yaml"
# Download defaults and public installation guidance track the published
# release, which can differ from the next source candidate in `_version.py`.
# release-truth.yaml is the authored source for that public target.
PUBLISHED_RELEASE_TAG = yaml.safe_load(RELEASE_TRUTH.read_text(encoding="utf-8"))["current"]
PUBLISHED_RELEASE_VERSION = PUBLISHED_RELEASE_TAG.removeprefix("v")


def test_windows_release_downloader_verifies_manifest_hashes() -> None:
    source = DOWNLOADER.read_text(encoding="utf-8")

    assert f'$Version = "{PUBLISHED_RELEASE_VERSION}"' in source
    assert 'release-artifacts-manifest.json"' in source
    assert 'clean-windows-proof-kit.zip"' in source
    assert 'windows-tester-package.zip"' in source
    assert "Get-FileHash" in source
    assert "Expand-Archive" in source
    assert "browser_download_url" in source
    assert "sha256" in source


def test_windows_install_doc_matches_current_release_posture() -> None:
    source = INSTALL_DOC.read_text(encoding="utf-8")
    assert f"`{PUBLISHED_RELEASE_TAG}`" in source
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


@pytest.mark.parametrize("scenario", ["complete", "traversal", "conflict", "index-mismatch"])
def test_station_archive_verification_and_safe_extraction(tmp_path: Path, scenario: str) -> None:
    """Execute the actual PS5.1 extraction path using a small six-pack ZIP."""
    powershell = shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is required for the Windows downloader")
    files = {
        f"station/{name}.ccpack": name.encode()
        for name in (
            "core",
            "captions-floor",
            "captions-whistle",
            "summary-gemma4-12b",
            "summary-gemma4-e4b",
            "translation-translategemma-4b",
        )
    }
    index = {
        "manifest": {
            "product_version": PUBLISHED_RELEASE_VERSION,
            "packs": [
                {
                    "filename": Path(path).name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "required": True,
                }
                for path, data in files.items()
            ],
        }
    }
    if scenario == "index-mismatch":
        index["manifest"]["packs"][0]["sha256"] = "0" * 64
    files["station/station-index.json"] = json.dumps(index).encode()
    index_hash = hashlib.sha256(files["station/station-index.json"]).hexdigest()
    files["station/SHA256SUMS.txt"] = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {Path(path).name}\n" for path, data in files.items()
    ).encode()
    manifest = {
        "schema_version": 1,
        "archive_format": "zip",
        "archive_name": "station-models.zip",
        "station_index_sha256": index_hash,
        "unpacked_files": [
            {"path": path, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for path, data in files.items()
        ],
    }
    archive = tmp_path / "station-models.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path, data in files.items():
            bundle.writestr(path, data)
        if scenario == "traversal":
            bundle.writestr("../escape.txt", b"unsafe")
    manifest_path = tmp_path / "station-models.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    root = tmp_path / "kit"
    root.mkdir()
    if scenario == "conflict":
        (root / "station").mkdir()
        (root / "station/core.ccpack").write_bytes(b"existing data")
    definitions = DOWNLOADER.read_text(encoding="utf-8").split(
        "New-Item -ItemType Directory -Force -Path $Destination | Out-Null", 1
    )[0]
    runner = tmp_path / "run.ps1"
    runner.write_text(
        definitions + "\n$m = Get-Content -LiteralPath $args[0] -Raw | ConvertFrom-Json\n"
        "Install-StationArchive -ArchivePath $args[1] -Root $args[2] -Manifest $m\n",
        encoding="utf-8",
    )
    # The downloader has named parameters; use a separate invocation body so
    # fixture paths cannot bind to the release downloader's positional options.
    body = (
        runner.read_text(encoding="utf-8")
        .replace("$args[0]", "'" + str(manifest_path).replace("'", "''") + "'")
        .replace("$args[1]", "'" + str(archive).replace("'", "''") + "'")
        .replace("$args[2]", "'" + str(root).replace("'", "''") + "'")
    )
    runner.write_text(body, encoding="utf-8")
    result = subprocess.run(
        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(runner)],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if scenario == "complete":
        assert result.returncode == 0, result.stdout + result.stderr
        assert {
            str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
            for p in root.rglob("*")
            if p.is_file()
        } == files
    else:
        assert result.returncode != 0, result.stdout + result.stderr
        assert not (tmp_path / "escape.txt").exists()
        if scenario == "conflict":
            assert (root / "station/core.ccpack").read_bytes() == b"existing data"
