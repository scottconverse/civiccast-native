# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Build-DownloadOnlyPayload.ps1 -- shared builder/cleanup for the Gate A
# download-only lane's <gate-a-download-only-lane> filtered payload
# directory (setup.exe + packs\, no station\). Factored out of
# Run-GateA.ps1 into its own dot-sourceable script so tests/gate_a can
# exercise the builder directly (pwsh -NoProfile) without invoking the whole
# harness.
#
# HARDENED <gate-a-download-only-lane-review>: the filtered payload's packs\
# tree is built ENTIRELY from real directory entries -- every pack file is
# hard-linked (New-Item -ItemType HardLink, same NTFS volume, effectively
# instant, appears to every consumer -- including VSMB -- as an ordinary
# file with no reparse point), falling back to Copy-Item only if
# hard-linking fails (e.g. a cross-volume kit-staging layout). NEVER a
# junction: Host-Launch-Sandbox-Test.ps1's own Resolve-PhysicalPath resolves
# the OUTER MappedFolder HostFolder through reparse points precisely because
# VSMB is not trusted to traverse a reparse hop -- a junction planted INSIDE
# the mapped tree is exactly the pattern that hardening exists to avoid, and
# this builder must never reintroduce it one level down.
#
# Cleanup (Remove-DownloadOnlyPayload / Restore-DownloadOnlyKitDownload) is
# idempotent and safe to call from a try/finally on every exit path
# (success, judge FAIL, BUSY/HARNESS_ERROR, or a thrown harness error): it
# restores the sandbox-lab\kit-download junction to the real, full kit and
# removes the filtered payload directory outright. Deleting the filtered
# directory is safe because it contains only regular files, hard links, and
# real subdirectories -- NEVER a reparse point -- so a plain recursive
# delete cannot walk through a junction and reach anything outside this
# tree. This whole discipline exists because the repo already lost a 26 GB
# pinned kit exactly that way once: a junction left behind by a prior run
# let the next job's `actions/checkout` `git clean -ffdx` walk through it
# and delete the real target (see gate-a-station-acceptance.yml's dirty job,
# "Unlink the pinned previous-kit junction" step, and its own header
# comment for the incident, 2026-09-02, candidate #23).

function New-DownloadOnlyPayload {
    <#
      .SYNOPSIS
      Build a filtered payload directory containing ONLY setup.exe and a
      hard-linked packs\ tree (no reparse points anywhere), and refuse if
      the result would carry a station\ directory.

      .PARAMETER KitPhysicalDir
      The resolved, physical (non-reparse) directory of the current
      candidate's full kit.

      .PARAMETER InstallerExePath
      Full path to the current candidate's setup.exe.

      .PARAMETER PayloadDir
      Destination directory to build. Any existing content at this path is
      removed first, so this must never be pointed at a directory the caller
      cares about.

      .PARAMETER CopyFailThresholdBytes
      <gate-a-download-only-lane-review-2> MAJOR: the hard-link -> Copy-Item
      fallback is silent by default in the sense that a handful of odd files
      copying instead of linking is not, by itself, a problem worth failing
      the run over. What IS a problem is the same-volume assumption between
      the kit (typically under C:\CivicCastTester\kit-staging on this
      runner) and the payload directory breaking wholesale -- that would
      make every single pack file fall back to a real byte-for-byte copy,
      silently spending the lane's I/O and time budget on tens of GB of
      copying instead of near-instant hard-linking. If the TOTAL bytes
      copied via fallback exceeds this threshold (default 1 GB), this
      function throws rather than warns -- a small fallback stays a warning
      only. See the summary file and Write-Warning/throw messages below for
      the exact numbers.

      .PARAMETER ForceCopyFallback
      TEST-ONLY HOOK. Forces every file through the Copy-Item fallback path
      without even attempting a hard link, so
      tests/gate_a/test_gate_a_download_only_payload.py can deterministically
      exercise the fallback counters and the CopyFailThresholdBytes throw
      without needing a real cross-volume environment. Run-GateA.ps1's own
      real invocation never sets this.

      .OUTPUTS
      A PSCustomObject with PayloadDir, InstallerName, FileCount,
      HardLinkCount, CopyFallbackCount, CopyFallbackBytes, and SummaryPath,
      for logging/assertions by the caller.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$KitPhysicalDir,
        [Parameter(Mandatory = $true)][string]$InstallerExePath,
        [Parameter(Mandatory = $true)][string]$PayloadDir,
        [long]$CopyFailThresholdBytes = 1GB,
        [switch]$ForceCopyFallback
    )

    if (-not (Test-Path -LiteralPath $InstallerExePath)) {
        throw "New-DownloadOnlyPayload: installer not found at $InstallerExePath"
    }
    $packsSourceDir = Join-Path $KitPhysicalDir 'packs'
    if (-not (Test-Path -LiteralPath $packsSourceDir)) {
        throw "New-DownloadOnlyPayload: no packs\ directory found at $packsSourceDir -- the current kit must carry runtime packs for a download-only install to side-load (the sandbox has no network)"
    }

    if (Test-Path -LiteralPath $PayloadDir) {
        Remove-DownloadOnlyPayload -PayloadDir $PayloadDir
    }
    New-Item -ItemType Directory -Force -Path $PayloadDir | Out-Null

    $installerName = Split-Path -Leaf $InstallerExePath
    Copy-Item -LiteralPath $InstallerExePath -Destination (Join-Path $PayloadDir $installerName) -Force

    $packsDestDir = Join-Path $PayloadDir 'packs'
    New-Item -ItemType Directory -Force -Path $packsDestDir | Out-Null

    # Recurse the source packs\ tree and reproduce it file-by-file: real
    # directories (New-Item -ItemType Directory), hard-linked files (falling
    # back to a copy only if the hard link itself fails -- e.g. cross-volume
    # staging, or -ForceCopyFallback for tests). Never a junction/symlink at
    # any level.
    $sourceFiles = @(Get-ChildItem -LiteralPath $packsSourceDir -Recurse -File -Force)
    $hardLinkCount = 0
    $copyFallbackCount = 0
    [long]$copyFallbackBytes = 0
    foreach ($file in $sourceFiles) {
        $relative = $file.FullName.Substring($packsSourceDir.Length).TrimStart('\', '/')
        $destPath = Join-Path $packsDestDir $relative
        $destDir = Split-Path -Parent $destPath
        if ($destDir -and -not (Test-Path -LiteralPath $destDir)) {
            New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        }
        $linked = $false
        if (-not $ForceCopyFallback) {
            try {
                New-Item -ItemType HardLink -Path $destPath -Target $file.FullName -ErrorAction Stop | Out-Null
                $linked = $true
                $hardLinkCount++
            } catch {
                $linked = $false
            }
        }
        if (-not $linked) {
            Copy-Item -LiteralPath $file.FullName -Destination $destPath -Force
            $copyFallbackCount++
            $copyFallbackBytes += $file.Length
        }
    }

    $stationDir = Join-Path $PayloadDir 'station'
    if (Test-Path -LiteralPath $stationDir) {
        throw "New-DownloadOnlyPayload: filtered payload unexpectedly contains station\ at $stationDir -- refusing to run the download-only lane against a payload that still carries a station directory"
    }

    # <gate-a-download-only-lane-review-2> MAJOR (a): ALWAYS print a summary
    # line, whether or not anything fell back -- the fallback path must
    # never be silent.
    $summaryLine = "download-only payload: $($sourceFiles.Count) files, $hardLinkCount hard-linked, $copyFallbackCount copied ($copyFallbackBytes bytes)"
    Write-Host $summaryLine

    # <gate-a-download-only-lane-review-2> MAJOR (b): write the numbers into
    # evidence. Written HOST-SIDE, next to the payload directory (i.e. as a
    # sibling of $PayloadDir, not inside it -- the payload directory itself
    # is deleted by Remove-DownloadOnlyPayload during cleanup and must not be
    # the only place this record lives). Run-GateA.ps1 copies this file into
    # the run's evidence directory once judging is done.
    $summaryPath = Join-Path (Split-Path -Parent $PayloadDir) 'DOWNLOAD-ONLY-PAYLOAD.txt'
    $summaryBody = @(
        "checked_utc=$((Get-Date).ToUniversalTime().ToString('o'))",
        "PAYLOAD_DIR=$PayloadDir",
        "TOTAL_FILES=$($sourceFiles.Count)",
        "HARD_LINK_COUNT=$hardLinkCount",
        "COPY_FALLBACK_COUNT=$copyFallbackCount",
        "COPY_FALLBACK_BYTES=$copyFallbackBytes",
        "COPY_FAIL_THRESHOLD_BYTES=$CopyFailThresholdBytes",
        $summaryLine
    ) -join [Environment]::NewLine
    Set-Content -Path $summaryPath -Value $summaryBody -Encoding UTF8

    # <gate-a-download-only-lane-review-2> MAJOR (c): fail closed if the
    # fallback wasn't small. A handful of odd files copying is a warning; a
    # broken same-volume assumption (every file falling back) must not
    # silently let the lane spend its budget copying instead of
    # hard-linking -- throw instead, naming the exact numbers and pointing
    # at the summary file.
    if ($copyFallbackCount -gt 0 -and $copyFallbackBytes -gt $CopyFailThresholdBytes) {
        throw "New-DownloadOnlyPayload: $copyFallbackCount file(s) fell back to Copy-Item totaling $copyFallbackBytes bytes, over the $CopyFailThresholdBytes-byte threshold -- the same-volume hard-link assumption between the kit and the payload directory appears broken; refusing to silently spend the lane's budget copying instead of hard-linking. See $summaryPath."
    } elseif ($copyFallbackCount -gt 0) {
        Write-Warning "New-DownloadOnlyPayload: $copyFallbackCount file(s) fell back to Copy-Item totaling $copyFallbackBytes bytes (within the $CopyFailThresholdBytes-byte threshold) -- see $summaryPath."
    }

    [PSCustomObject]@{
        PayloadDir        = $PayloadDir
        InstallerName     = $installerName
        FileCount         = $sourceFiles.Count
        HardLinkCount     = $hardLinkCount
        CopyFallbackCount = $copyFallbackCount
        CopyFallbackBytes = $copyFallbackBytes
        SummaryPath       = $summaryPath
    }
}

function Remove-DownloadOnlyPayload {
    <#
      .SYNOPSIS
      Delete the filtered payload directory outright. Safe because it never
      contains a reparse point (every entry is a real file, a hard link, or
      a real directory) -- a recursive delete cannot walk through a junction
      and reach anything outside this tree. No-ops if the directory does not
      exist. Never throws (best-effort cleanup, callable from a `finally`).
    #>
    param([Parameter(Mandatory = $true)][string]$PayloadDir)
    if (-not (Test-Path -LiteralPath $PayloadDir)) { return }
    try {
        Remove-Item -LiteralPath $PayloadDir -Recurse -Force -ErrorAction Stop
    } catch {
        Write-Warning "Remove-DownloadOnlyPayload: failed to remove ${PayloadDir}: $_"
    }
}

function Restore-DownloadOnlyKitDownload {
    <#
      .SYNOPSIS
      Idempotent: repoints $KitDownloadPath (an NTFS junction) back at
      $KitPhysicalDir (the real, full current kit) if -- and only if -- it
      is not already pointed there. Safe to call unconditionally from a
      try/finally on every exit path, including one where the filtered
      payload was never built (nothing to restore, and this function
      no-ops). Never throws (best-effort cleanup, callable from a
      `finally`).
    #>
    param(
        [Parameter(Mandatory = $true)][string]$KitDownloadPath,
        [Parameter(Mandatory = $true)][string]$KitPhysicalDir
    )
    try {
        if (-not (Test-Path -LiteralPath $KitDownloadPath)) { return }
        $item = Get-Item -LiteralPath $KitDownloadPath -Force -ErrorAction SilentlyContinue
        if (-not $item -or -not $item.LinkType) { return }
        $currentTarget = @($item.Target) | Select-Object -First 1
        if ($currentTarget -eq $KitPhysicalDir) { return }
        $item.Delete()
        New-Item -ItemType Junction -Path $KitDownloadPath -Target $KitPhysicalDir | Out-Null
        Write-Host "Restore-DownloadOnlyKitDownload: kit-download -> $KitPhysicalDir (restored)"
    } catch {
        Write-Warning "Restore-DownloadOnlyKitDownload: failed to restore ${KitDownloadPath} -> ${KitPhysicalDir}: $_"
    }
}
