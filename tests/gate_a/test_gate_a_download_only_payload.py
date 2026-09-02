# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Behavioral test for the Gate A download-only lane's filtered-payload
builder (``sandbox-lab/scripts/Build-DownloadOnlyPayload.ps1``).

<gate-a-download-only-lane-review> MAJOR 3: the other Gate A test modules in
this directory are static (they read PowerShell/YAML/Python source as text
and assert on strings) or exercise ``scripts/gate_a_verdict.py`` against
fixture evidence files. Neither actually RUNS the PowerShell builder this
lane depends on. This module does: it invokes the real
``New-DownloadOnlyPayload`` / ``Remove-DownloadOnlyPayload`` /
``Restore-DownloadOnlyKitDownload`` functions (dot-sourced, per
<gate-a-download-only-lane-review> MAJOR 3's own instruction) against a
fixture kit under ``tmp_path`` and asserts, from the real filesystem:

- every file the builder places under the payload directory (``setup.exe``,
  ``packs/a.ccpack``) is a REGULAR file -- no ``ReparsePoint`` attribute
  anywhere in the built tree. This is the actual, behavioural proof of
  BLOCKER 2's fix (hard-link every pack file instead of junctioning the
  whole ``packs`` directory) -- a static text-grep for "HardLink" in the
  source cannot prove the resulting tree is reparse-point-free.
- no ``station`` directory is present in the payload.
- the cleanup functions actually remove the payload directory and restore
  ``kit-download`` to point at the real kit, not leave it dangling or
  pointed at the (now-deleted) filtered payload -- the exact junction-
  hygiene property BLOCKER 1 exists to guarantee.

Requires ``pwsh`` (PowerShell 7+, the same shell every Gate A workflow step
uses) on PATH. Skips cleanly -- never fails the suite -- when it is absent,
per the review's own instruction.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILDER = _REPO_ROOT / "sandbox-lab" / "scripts" / "Build-DownloadOnlyPayload.ps1"

_PWSH = shutil.which("pwsh")

pytestmark = pytest.mark.skipif(_PWSH is None, reason="pwsh not found on PATH")


def test_builder_script_present() -> None:
    assert _BUILDER.is_file(), f"builder script missing at {_BUILDER}"


# A small PowerShell driver, written to a file under tmp_path rather than
# passed inline: builds a fixture kit (setup.exe, packs\a.ccpack,
# station\station-index.json), dot-sources the real builder script, runs the
# full build -> repoint -> cleanup cycle exactly as Run-GateA.ps1 does, and
# writes every assertion-relevant fact to a JSON result file for the Python
# test to read back -- keeping the actual assertions in Python, not
# PowerShell, so a failure reads like every other test in this suite.
_DRIVER_TEMPLATE = r"""
param(
    [Parameter(Mandatory=$true)][string]$Builder,
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$ResultPath
)
$ErrorActionPreference = 'Stop'
. $Builder

$kit = Join-Path $Root 'kit'
$payload = Join-Path $Root 'payload'
$kitDownload = Join-Path $Root 'kit-download'

New-Item -ItemType Directory -Force -Path $kit | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $kit 'packs') | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $kit 'station') | Out-Null
Set-Content -Path (Join-Path $kit 'setup.exe') -Value 'fake installer bytes' -Encoding UTF8
Set-Content -Path (Join-Path $kit 'packs\a.ccpack') -Value 'fake pack bytes' -Encoding UTF8
Set-Content -Path (Join-Path $kit 'station\station-index.json') -Value '{}' -Encoding UTF8

# Simulate Run-GateA.ps1's ordinary (non-download-only) kit-download
# junction pointing at the real, full kit -- the state the builder and
# repoint step run against on every real invocation.
New-Item -ItemType Junction -Path $kitDownload -Target $kit | Out-Null

$buildResult = New-DownloadOnlyPayload -KitPhysicalDir $kit -InstallerExePath (Join-Path $kit 'setup.exe') -PayloadDir $payload

# Repoint kit-download at the filtered payload, exactly as Run-GateA.ps1
# does immediately after building it.
$kdItem = Get-Item -LiteralPath $kitDownload -Force
if ($kdItem.LinkType) { $kdItem.Delete() }
New-Item -ItemType Junction -Path $kitDownload -Target $payload | Out-Null

$setupPresent = Test-Path (Join-Path $payload 'setup.exe')
$packFilePresent = Test-Path (Join-Path $payload 'packs\a.ccpack')
$stationAbsent = -not (Test-Path (Join-Path $payload 'station'))

$reparsePoints = @(Get-ChildItem -LiteralPath $payload -Recurse -Force |
    Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint })

# Cleanup -- the try/finally in Run-GateA.ps1 calls these two on every exit
# path; exercise them directly here.
Remove-DownloadOnlyPayload -PayloadDir $payload
Restore-DownloadOnlyKitDownload -KitDownloadPath $kitDownload -KitPhysicalDir $kit

$payloadRemoved = -not (Test-Path $payload)
$kdAfter = Get-Item -LiteralPath $kitDownload -Force
$kdTarget = @($kdAfter.Target) | Select-Object -First 1

$result = [ordered]@{
    setup_present       = [bool]$setupPresent
    pack_file_present   = [bool]$packFilePresent
    station_absent      = [bool]$stationAbsent
    reparse_point_count = $reparsePoints.Count
    reparse_point_names = @($reparsePoints | ForEach-Object { $_.FullName })
    hard_link_count     = $buildResult.HardLinkCount
    copy_fallback_count = $buildResult.CopyFallbackCount
    payload_removed     = [bool]$payloadRemoved
    kit_download_target = $kdTarget
    kit_physical        = $kit
}
$result | ConvertTo-Json -Depth 5 | Set-Content -Path $ResultPath -Encoding UTF8
"""


def test_download_only_payload_builder_produces_no_reparse_points_and_cleanup_restores_kit_download(
    tmp_path: Path,
) -> None:
    driver_path = tmp_path / "driver.ps1"
    driver_path.write_text(_DRIVER_TEMPLATE, encoding="utf-8")
    result_path = tmp_path / "result.json"

    proc = subprocess.run(
        [
            _PWSH,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(driver_path),
            "-Builder",
            str(_BUILDER),
            "-Root",
            str(tmp_path),
            "-ResultPath",
            str(result_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"driver script failed (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    result = json.loads(result_path.read_text(encoding="utf-8"))

    assert result["setup_present"] is True
    assert result["pack_file_present"] is True
    assert result["station_absent"] is True
    assert result["reparse_point_count"] == 0, (
        "payload must contain no reparse points at any level -- found: "
        f"{result['reparse_point_names']}"
    )
    # NTFS hard links require the source and destination on the same
    # volume; kit\ and payload\ are both built under the same tmp_path root
    # here, so the builder should succeed via a real hard link rather than
    # silently falling back to a copy -- assert that explicitly, not just
    # that the file exists (an always-copy fallback would still pass the
    # weaker assertion but defeats the point BLOCKER 2 exists to prove).
    assert result["hard_link_count"] >= 1
    assert result["copy_fallback_count"] == 0

    assert result["payload_removed"] is True
    assert result["kit_download_target"] == result["kit_physical"], (
        "cleanup must restore kit-download to the real kit, not leave it dangling or "
        "pointed at the (now-removed) filtered payload"
    )
