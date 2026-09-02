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

<gate-a-download-only-lane-review-2> MAJOR: two more tests exercise the
hard-link -> Copy-Item fallback path deterministically, via the
``-ForceCopyFallback`` test-only hook on ``New-DownloadOnlyPayload`` (it
forces every file through the copy path without even attempting a hard
link, so this does not depend on a real cross-volume environment):

- with a generous ``-CopyFailThresholdBytes``, the fallback is counted
  correctly (``HardLinkCount`` 0, ``CopyFallbackCount`` matching the fixture
  file count, ``CopyFallbackBytes`` > 0) and the host-side
  ``DOWNLOAD-ONLY-PAYLOAD.txt`` summary is written with matching numbers --
  never throws.
- with a tiny ``-CopyFailThresholdBytes`` (1 byte), the same fallback now
  exceeds the threshold and the function throws -- proving the fail-closed
  path actually fires, not just that its code exists in source.

Requires ``pwsh`` (PowerShell 7+, the same shell every Gate A workflow step
uses) on PATH, AND a Windows host. Skips cleanly -- never fails the suite --
when either is absent, per the review's own instruction.

<gate-a-download-only-lane-review-3>: the ``pwsh``-only guard was not
enough. GitHub's ``ubuntu-latest`` images ship PowerShell 7 preinstalled, so
``shutil.which("pwsh")`` finds one there too, and this module's own driver
scripts actually ran on the ``randomized-suite`` and ``Unit tests`` (both
``ubuntu-latest``) CI lanes -- where they failed, not skipped, because the
harness this module tests is Windows-only at the filesystem level:
``Build-DownloadOnlyPayload.ps1``'s own ``Restore-DownloadOnlyKitDownload``
creates an NTFS directory junction (``New-Item -ItemType Junction``), and
this module's first driver template simulates the harness's ordinary
``kit-download`` junction the same way to set up its fixture. NTFS
junctions do not exist on Linux's ext4, so ``New-Item -ItemType Junction``
throws there even under a real ``pwsh``, and the driver's nonzero exit
surfaced as a hard test FAILURE (``AssertionError: driver script failed
(exit 1)``), not a skip. The guard now also requires ``platform.system() ==
"Windows"`` -- correct, not incidental: Gate A's download-only lane only
ever runs on the project's self-hosted Windows sandbox-lab runner (see
``docs/ops/gate-a.md``), so this module has nothing meaningful to prove on
any other platform regardless of what shells happen to be installed there.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_BUILDER = _REPO_ROOT / "sandbox-lab" / "scripts" / "Build-DownloadOnlyPayload.ps1"

_PWSH = shutil.which("pwsh")
_IS_WINDOWS = platform.system() == "Windows"

if _PWSH is None:
    _SKIP_REASON = "pwsh not found on PATH"
elif not _IS_WINDOWS:
    _SKIP_REASON = (
        "Gate A's download-only lane builder is Windows-only (NTFS directory junctions, "
        "created both by Build-DownloadOnlyPayload.ps1 itself and by this module's own "
        "fixture setup) -- it cannot run on a non-Windows platform even when pwsh "
        f"(PowerShell 7, preinstalled on many Linux CI images) is present; platform.system() "
        f"reported {platform.system()!r}"
    )
else:
    _SKIP_REASON = ""

pytestmark = pytest.mark.skipif(_PWSH is None or not _IS_WINDOWS, reason=_SKIP_REASON)


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


# Second driver: forces the Copy-Item fallback via -ForceCopyFallback (a
# test-only hook on New-DownloadOnlyPayload) against a fixture kit with two
# pack files, and reports both the function's own return value (when it
# doesn't throw) and the host-side DOWNLOAD-ONLY-PAYLOAD.txt summary file's
# raw content -- the summary is written BEFORE the fail-closed throw
# decision, so it must exist and carry accurate numbers on both the
# within-threshold and over-threshold runs.
_FORCE_COPY_DRIVER_TEMPLATE = r"""
param(
    [Parameter(Mandatory=$true)][string]$Builder,
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$ResultPath,
    [Parameter(Mandatory=$true)][long]$CopyFailThresholdBytes
)
$ErrorActionPreference = 'Stop'
. $Builder

$kit = Join-Path $Root 'kit'
$payload = Join-Path $Root 'payload'

New-Item -ItemType Directory -Force -Path $kit | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $kit 'packs') | Out-Null
Set-Content -Path (Join-Path $kit 'setup.exe') -Value 'fake installer bytes' -Encoding UTF8
Set-Content -Path (Join-Path $kit 'packs\a.ccpack') -Value 'fake pack bytes AAAAAAAAAA' -Encoding UTF8
Set-Content -Path (Join-Path $kit 'packs\b.ccpack') -Value 'fake pack bytes BBBBBBBBBB' -Encoding UTF8

$threw = $false
$errorMessage = $null
$buildResult = $null
try {
    $buildResult = New-DownloadOnlyPayload -KitPhysicalDir $kit -InstallerExePath (Join-Path $kit 'setup.exe') -PayloadDir $payload -ForceCopyFallback -CopyFailThresholdBytes $CopyFailThresholdBytes
} catch {
    $threw = $true
    $errorMessage = "$_"
}

$summaryPath = Join-Path $Root 'DOWNLOAD-ONLY-PAYLOAD.txt'
$summaryExists = Test-Path -LiteralPath $summaryPath
$summaryContent = if ($summaryExists) { Get-Content -LiteralPath $summaryPath -Raw } else { $null }
$payloadExistsAfter = Test-Path -LiteralPath $payload

$result = [ordered]@{
    threw                = [bool]$threw
    error_message        = $errorMessage
    return_hard_link_count     = if ($buildResult) { $buildResult.HardLinkCount } else { $null }
    return_copy_fallback_count = if ($buildResult) { $buildResult.CopyFallbackCount } else { $null }
    return_copy_fallback_bytes = if ($buildResult) { $buildResult.CopyFallbackBytes } else { $null }
    summary_exists       = [bool]$summaryExists
    summary_content      = $summaryContent
    payload_exists_after = [bool]$payloadExistsAfter
}
$result | ConvertTo-Json -Depth 5 | Set-Content -Path $ResultPath -Encoding UTF8
"""


def _run_force_copy_driver(tmp_path: Path, copy_fail_threshold_bytes: int) -> dict:
    driver_path = tmp_path / "force_copy_driver.ps1"
    driver_path.write_text(_FORCE_COPY_DRIVER_TEMPLATE, encoding="utf-8")
    result_path = tmp_path / "force_copy_result.json"

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
            "-CopyFailThresholdBytes",
            str(copy_fail_threshold_bytes),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    # The driver itself never re-throws (it catches New-DownloadOnlyPayload's
    # exception and records it in the JSON result) -- a nonzero exit here
    # means the DRIVER script itself broke, not the fail-closed path under
    # test, so it is always a hard test failure.
    assert proc.returncode == 0, (
        f"driver script failed (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    return json.loads(result_path.read_text(encoding="utf-8"))


def test_download_only_payload_builder_counts_forced_copy_fallback_within_threshold(
    tmp_path: Path,
) -> None:
    # A generous threshold -- the two tiny fixture pack files' combined
    # fallback bytes are nowhere near it, so this must NOT throw.
    result = _run_force_copy_driver(tmp_path, copy_fail_threshold_bytes=1_000_000_000)

    assert result["threw"] is False, result["error_message"]
    assert result["return_hard_link_count"] == 0, (
        "-ForceCopyFallback must force every file through the copy path, never a hard link"
    )
    assert result["return_copy_fallback_count"] == 2
    assert result["return_copy_fallback_bytes"] > 0

    # (a) the summary line is always printed -- (b) it is written to the
    # host-side evidence file with matching numbers, even on the
    # within-threshold (non-throwing) path.
    assert result["summary_exists"] is True
    summary = result["summary_content"]
    assert "HARD_LINK_COUNT=0" in summary
    assert "COPY_FALLBACK_COUNT=2" in summary
    assert f"COPY_FALLBACK_BYTES={result['return_copy_fallback_bytes']}" in summary
    assert "download-only payload: 2 files, 0 hard-linked, 2 copied" in summary


def test_download_only_payload_builder_fails_closed_when_forced_copy_fallback_exceeds_tiny_threshold(
    tmp_path: Path,
) -> None:
    # (c) fail closed: a 1-byte threshold is smaller than any real file's
    # fallback bytes, so this MUST throw -- proving the fail-closed branch
    # actually fires rather than only existing in source.
    result = _run_force_copy_driver(tmp_path, copy_fail_threshold_bytes=1)

    assert result["threw"] is True
    assert "over the 1-byte threshold" in result["error_message"]
    assert "same-volume hard-link assumption" in result["error_message"]

    # The summary file is written BEFORE the throw decision -- fail-closed
    # must still leave an accurate evidence trail behind, not just an
    # exception with no record of what was copied.
    assert result["summary_exists"] is True
    assert "COPY_FALLBACK_COUNT=2" in result["summary_content"]

    # New-DownloadOnlyPayload throwing mid-build leaves a partial payload
    # directory on disk -- this is expected and is exactly what
    # Run-GateA.ps1's own try/finally (wrapping the payload build itself,
    # not just the steps after it) exists to clean up; this driver does not
    # call the cleanup functions, so it is asserted present here rather than
    # silently ignored.
    assert result["payload_exists_after"] is True
