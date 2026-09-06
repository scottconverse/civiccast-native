# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-GstDebugTail.ps1 -- unit/integration checks for Copy-GstDebugTail
# (GstDebugTail.ps1, sandbox-lab lane follow-up D item 2's GST_DEBUG_FILE
# capture, round-3 review findings 1-3). Unlike this project's other
# Test-*.ps1 suites, this one DOES touch the real filesystem (real temp
# files/streams, and one real background job to simulate a growing file)
# -- Copy-GstDebugTail is inherently I/O-bound (real FileStreams, real
# sharing-violation semantics), so there is no meaningful pure-function
# form to test instead. Everything runs under the OS temp directory and
# is cleaned up in a try/finally.
#
# Run: pwsh -File sandbox-lab/scripts/Test-GstDebugTail.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'GstDebugTail.ps1')

$script:failures = 0
$script:total = 0

function Assert-Equal {
    param([string]$Name, $Expected, $Actual)
    $script:total++
    if ("$Expected" -ne "$Actual") {
        $script:failures++
        Write-Host "[FAIL] $Name -- expected '$Expected', got '$Actual'" -ForegroundColor Red
    } else {
        Write-Host "[PASS] $Name" -ForegroundColor Green
    }
}

function Assert-True {
    param([string]$Name, [bool]$Condition, [string]$Detail = '')
    $script:total++
    if ($Condition) {
        Write-Host "[PASS] $Name" -ForegroundColor Green
    } else {
        $script:failures++
        Write-Host "[FAIL] $Name $Detail" -ForegroundColor Red
    }
}

function Get-BannerAndContentSplit {
    <#
      The banner is one ASCII line terminated by CRLF, written before the
      bounded content. Locates the first CRLF and returns the banner text
      and the byte-length of everything after it -- used instead of
      predicting the banner's exact text (which embeds a "currentLength"
      that is non-deterministic for a file that is still growing while
      Copy-GstDebugTail reads it).
    #>
    param([byte[]]$Bytes)
    $crlfIndex = -1
    for ($i = 0; $i -lt ($Bytes.Length - 1); $i++) {
        if ($Bytes[$i] -eq 0x0D -and $Bytes[$i + 1] -eq 0x0A) { $crlfIndex = $i; break }
    }
    if ($crlfIndex -lt 0) {
        return [pscustomobject]@{ BannerText = $null; ContentLength = $null }
    }
    $bannerText = [System.Text.Encoding]::ASCII.GetString($Bytes, 0, $crlfIndex)
    $contentLength = $Bytes.Length - ($crlfIndex + 2)
    return [pscustomobject]@{ BannerText = $bannerText; ContentLength = $contentLength }
}

$tmpRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("gstdebugtail-test-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmpRoot | Out-Null

try {
    # ---------------------------------------------------------- scenario 1
    # Round-3 review finding 1: the source is held open for WRITE by
    # another handle, sharing only READ back (FileAccess.Write,
    # FileShare.Read) -- a plausible real shape for an actively-written
    # log file (tolerates concurrent readers, not concurrent writers).
    # MEASURED directly: [System.IO.File]::OpenRead (FileShare.Read on
    # the READER's own side) throws "being used by another process"
    # against exactly this writer shape -- the symmetric Windows sharing
    # check requires the NEW open's own share flags to also cover
    # whatever access the EXISTING handle holds (here: Write), which
    # FileShare.Read alone does not grant back. Copy-Item (a DIFFERENT
    # Win32 code path) succeeds against the identical file, which is
    # exactly what made the original bug so easy to miss. Copy-
    # GstDebugTail must succeed here (FileShare.ReadWrite).
    $src1 = Join-Path $tmpRoot 'live-open.log'
    [System.IO.File]::WriteAllBytes($src1, (New-Object byte[] (5MB)))
    $writer1 = [System.IO.File]::Open($src1, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    try {
        $openReadThrew = $false
        try { ([System.IO.File]::OpenRead($src1)).Dispose() } catch { $openReadThrew = $true }
        Assert-True 'scenario1 control: File.OpenRead (FileShare.Read) DOES throw against this writer shape (documents the bug being fixed)' $openReadThrew

        $copyItemOk = $true
        try { Copy-Item -LiteralPath $src1 -Destination (Join-Path $tmpRoot 'live-open-copyitem.log') -Force -ErrorAction Stop } catch { $copyItemOk = $false }
        Assert-True 'scenario1 control: Copy-Item DOES succeed against the same live-open file (matches the reported symptom)' $copyItemOk

        $dest1 = Join-Path $tmpRoot 'live-open.tail200mb'
        $threw1 = $false
        try { Copy-GstDebugTail -SourcePath $src1 -DestPath $dest1 -MaxBytes 1MB } catch { $threw1 = $true; Write-Host "  (exception: $_)" }
        Assert-True 'scenario1 Copy-GstDebugTail succeeds against a live-open (Write/Read-shared) file' (-not $threw1)
        if (-not $threw1) {
            $bytes1 = [System.IO.File]::ReadAllBytes($dest1)
            $split1 = Get-BannerAndContentSplit -Bytes $bytes1
            Assert-True 'scenario1 banner line present' ($null -ne $split1.BannerText -and $split1.BannerText -match '^# sandbox-lab TRUNCATED')
            # Round-4 review finding 3: the bound applies to the TOTAL
            # output FILE (banner + content), not content alone -- assert
            # the file itself never exceeds MaxBytes (algebraically
            # guaranteed to equal it exactly whenever the source has
            # enough data past the chosen start position, as here: 5 MB
            # of static source, 1 MB bound).
            Assert-Equal 'scenario1 TOTAL FILE length == MaxBytes exactly (banner + content together, never over the bound)' 1048576 $bytes1.Length
            Assert-True 'scenario1 content length == MaxBytes MINUS the banner (never the full MaxBytes on top of it)' ($split1.ContentLength -lt 1048576 -and $split1.ContentLength -gt 1048000) "(content length: $($split1.ContentLength))"
        }
    } finally {
        $writer1.Dispose()
    }

    # ---------------------------------------------------------- scenario 2
    # Round-3 review finding 2: the source keeps GROWING (a second process
    # -- a real background job, not a same-thread simulation -- appends to
    # it) for the whole duration of the copy. Regardless of how large the
    # source grows, the copy must never keep more than EXACTLY -MaxBytes
    # bytes of content. The OLD implementation (Length snapshotted once,
    # then CopyTo to whatever EOF happened to be by the time it got there)
    # would have kept MORE than MaxBytes here -- this is the regression
    # guard for that specific defect.
    $src2 = Join-Path $tmpRoot 'growing.log'
    $maxBytes2 = 2MB
    [System.IO.File]::WriteAllBytes($src2, (New-Object byte[] (3MB)))  # already over the bound before growth starts
    $job = Start-Job -ScriptBlock {
        param($path)
        $ws = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        try {
            $ws.Seek(0, [System.IO.SeekOrigin]::End) | Out-Null
            $chunk = New-Object byte[] (256KB)
            for ($i = 0; $i -lt 40; $i++) {
                $ws.Write($chunk, 0, $chunk.Length)
                $ws.Flush()
                Start-Sleep -Milliseconds 25
            }
        } finally { $ws.Dispose() }
    } -ArgumentList $src2
    try {
        Start-Sleep -Milliseconds 50  # let the job start actively growing the file first
        $dest2 = Join-Path $tmpRoot 'growing.tail200mb'
        Copy-GstDebugTail -SourcePath $src2 -DestPath $dest2 -MaxBytes $maxBytes2
        Wait-Job $job -Timeout 30 | Out-Null
        $jobOutput = Receive-Job $job -ErrorAction SilentlyContinue
        $finalSrcSize = (Get-Item $src2).Length
        Assert-True 'scenario2 sanity: the source actually grew past its starting size during the copy' ($finalSrcSize -gt 3MB) "(final size: $finalSrcSize bytes, job output: $jobOutput)"

        $bytes2 = [System.IO.File]::ReadAllBytes($dest2)
        $split2 = Get-BannerAndContentSplit -Bytes $bytes2
        Assert-True 'scenario2 banner line present' ($null -ne $split2.BannerText -and $split2.BannerText -match '^# sandbox-lab TRUNCATED')
        # Round-4 review finding 3: assert the TOTAL FILE (banner +
        # content), never just content, against the bound -- this holds
        # exactly regardless of the growing file's own final size or the
        # banner's exact text length (banner-length cancels out
        # algebraically: total = bannerLength + (MaxBytes - bannerLength)).
        Assert-Equal 'scenario2 (growing-file bound) TOTAL FILE length == MaxBytes EXACTLY, never more, despite the source growing well past it during the copy' ([int64]$maxBytes2) $bytes2.Length
    } finally {
        Remove-Job $job -Force -ErrorAction SilentlyContinue
    }

    # ---------------------------------------------------------- scenario 3
    # Content correctness: the kept bytes really are the TAIL of the
    # source, not some other slice. A recognizable, non-repeating-enough
    # byte pattern (a counting sequence, not all-zero) makes an accidental
    # false-positive match against the wrong slice implausible.
    $src3 = Join-Path $tmpRoot 'pattern.log'
    $patternBytes = New-Object byte[] (4MB)
    for ($i = 0; $i -lt $patternBytes.Length; $i++) { $patternBytes[$i] = [byte]($i % 256) }
    [System.IO.File]::WriteAllBytes($src3, $patternBytes)
    $dest3 = Join-Path $tmpRoot 'pattern.tail200mb'
    $maxBytes3 = 1MB
    Copy-GstDebugTail -SourcePath $src3 -DestPath $dest3 -MaxBytes $maxBytes3
    $bytes3 = [System.IO.File]::ReadAllBytes($dest3)
    $split3 = Get-BannerAndContentSplit -Bytes $bytes3
    Assert-True 'scenario3 TOTAL FILE length <= MaxBytes (banner + content together)' ($bytes3.Length -le $maxBytes3) "(file length: $($bytes3.Length), MaxBytes: $maxBytes3)"
    # Round-4 review finding 3: the retained content is (MaxBytes - banner
    # length) bytes, not a full MaxBytes -- derive the expected slice from
    # the ACTUALLY MEASURED content length (split3.ContentLength) rather
    # than re-deriving the banner's exact byte length by hand here, so
    # this test stays correct regardless of exactly how long the banner
    # text turns out to be.
    $expectedTail = $patternBytes[($patternBytes.Length - $split3.ContentLength)..($patternBytes.Length - 1)]
    $actualTailBytes = New-Object byte[] $split3.ContentLength
    [Array]::Copy($bytes3, $bytes3.Length - $split3.ContentLength, $actualTailBytes, 0, $split3.ContentLength)
    $tailMatches = ($actualTailBytes.Length -eq $expectedTail.Length)
    if ($tailMatches) {
        for ($i = 0; $i -lt $expectedTail.Length; $i++) {
            if ($actualTailBytes[$i] -ne $expectedTail[$i]) { $tailMatches = $false; break }
        }
    }
    Assert-True 'scenario3 kept content is byte-for-byte the LAST (MaxBytes - banner) bytes of the source -- ends at the true EOF, not the head, not some other slice' $tailMatches

    # ---------------------------------------------------------- scenario 4
    # Sanity: called standalone (not via the real caller, which only ever
    # invokes this when source > MaxBytes) with MaxBytes exceeding the
    # source's actual size -- startPos clamps to 0 and the whole source is
    # copied (short of MaxBytes, since the read loop stops once genuinely
    # out of source data).
    $src4 = Join-Path $tmpRoot 'small.log'
    $smallBytes = New-Object byte[] (100KB)
    for ($i = 0; $i -lt $smallBytes.Length; $i++) { $smallBytes[$i] = [byte]($i % 256) }
    [System.IO.File]::WriteAllBytes($src4, $smallBytes)
    $dest4 = Join-Path $tmpRoot 'small.tail200mb'
    Copy-GstDebugTail -SourcePath $src4 -DestPath $dest4 -MaxBytes 1MB
    $bytes4 = [System.IO.File]::ReadAllBytes($dest4)
    $split4 = Get-BannerAndContentSplit -Bytes $bytes4
    Assert-Equal 'scenario4 (MaxBytes > source size) content length == the WHOLE source, not padded/truncated' $smallBytes.Length $split4.ContentLength
    Assert-True 'scenario4 TOTAL FILE length <= MaxBytes' ($bytes4.Length -le 1MB) "(file length: $($bytes4.Length))"

    # ---------------------------------------------------------- scenario 5
    # Round-4 review finding 1 (HIGH): a Get-ChildItem-derived FileInfo's
    # own .Length property is a SNAPSHOT taken when that FileInfo object
    # was first populated -- .NET does NOT auto-refresh it; a caller has
    # to call .Refresh() explicitly. In-Sandbox-Soak.ps1's OLD gst-debug
    # capture listed candidates once via Get-ChildItem, then branched on
    # that cached $f.Length later in the same loop iteration -- by which
    # time the real, live GST_DEBUG_FILE had grown far past it (MEASURED
    # directly: a directory-entry snapshot of 1,048,576 bytes against a
    # live stream of 84,934,656 bytes -- 81x larger), routing the exact
    # live file this feature exists to capture down the UNBOUNDED
    # Copy-Item path instead of the bounded tail-copy path. The fix was to
    # drop the size branch entirely -- Copy-GstDebugTail is now called
    # UNCONDITIONALLY and NEVER accepts or trusts a caller-supplied
    # Length; it always re-stats via its own freshly opened stream
    # (Copy-GstDebugTail's own $srcStream.Length, read after this test's
    # OWN growth already happened). This regression guard reproduces the
    # stale-FileInfo precondition directly, then proves the fix (driven
    # only by -SourcePath, a live path, never a pre-fetched Length) still
    # produces a correctly bounded, correctly-tailed capture.
    $src5 = Join-Path $tmpRoot 'stale-entry.log'
    [System.IO.File]::WriteAllBytes($src5, (New-Object byte[] (1MB)))
    $staleFileInfo = Get-ChildItem -LiteralPath $src5 -File
    $staleLengthBeforeGrowth = $staleFileInfo.Length
    # Grow the file well past the (soon to be stale) cached FileInfo's own
    # .Length, via a SEPARATE handle -- mirrors a live GStreamer worker
    # continuing to write after this run's own candidate listing already
    # captured a FileInfo for it.
    $writer5 = [System.IO.File]::Open($src5, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
    try {
        $writer5.Seek(0, [System.IO.SeekOrigin]::End) | Out-Null
        # Filled with a non-zero pattern (0xAA throughout) -- the FIRST
        # 1 MB of the file (written via WriteAllBytes above) is all-zero
        # by construction (New-Object byte[] default-initializes to zero),
        # so a non-zero pattern here makes "the kept content reflects the
        # live/grown region, not the stale/original one" directly
        # checkable byte-for-byte below.
        $extra = New-Object byte[] (4MB)
        for ($i = 0; $i -lt $extra.Length; $i++) { $extra[$i] = 0xAA }
        $writer5.Write($extra, 0, $extra.Length)
        $writer5.Flush()
    } finally {
        $writer5.Dispose()
    }
    $liveLengthNow = (Get-Item -LiteralPath $src5).Length
    Assert-Equal 'scenario5 setup sanity: the file really did grow to 5 MB total' 5242880 $liveLengthNow
    Assert-True 'scenario5 reproduces the bug precondition: the OLD (unrefreshed) FileInfo.Length is now genuinely STALE vs. the live file' ($staleFileInfo.Length -eq $staleLengthBeforeGrowth -and $staleFileInfo.Length -lt $liveLengthNow) "(cached FileInfo.Length: $($staleFileInfo.Length), live length: $liveLengthNow)"

    $dest5 = Join-Path $tmpRoot 'stale-entry.tail200mb'
    $maxBytes5 = 2MB
    # THE FIX under test: called with only -SourcePath (a path, not the
    # stale FileInfo or its cached .Length at all) -- must reflect the
    # file's TRUE current size, not whatever a caller might have cached.
    Copy-GstDebugTail -SourcePath $src5 -DestPath $dest5 -MaxBytes $maxBytes5
    $bytes5 = [System.IO.File]::ReadAllBytes($dest5)
    $split5 = Get-BannerAndContentSplit -Bytes $bytes5
    Assert-True 'scenario5 (stale-entry live file) TOTAL FILE length == MaxBytes exactly -- correctly bounded despite the stale FileInfo, because Copy-GstDebugTail never consulted it' ($bytes5.Length -eq $maxBytes5) "(file length: $($bytes5.Length), MaxBytes: $maxBytes5)"
    # Content correctness: must be the tail of the LIVE (5 MB) file, not
    # bounded against the stale (1 MB) snapshot -- e.g. NOT simply "the
    # whole stale-length region copied verbatim" (which -- since the first
    # 1 MB was all zero bytes from New-Object byte[] -- would show up here
    # as an all-zero content region if this test's fix somehow regressed).
    $anyNonZero = @($split5.ContentLength) -gt 0 -and (0..([Math]::Min(4095, $split5.ContentLength - 1)) | Where-Object {
        $bytes5[$bytes5.Length - $split5.ContentLength + $_] -ne 0
    }).Count -gt 0
    Assert-True 'scenario5 kept content is NOT merely the (all-zero) stale-length region -- it reflects the live, grown file' $anyNonZero

} finally {
    Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
}

# ============================================================ capture gate
# Round-4 review finding 2: Get-GstDebugCaptureDecision is a pure function
# (no filesystem) -- gate/aggregate-cap logic tested with synthetic inputs,
# no live sandbox or real files needed at all.

# scenario 6: a non-periodic label ('final', or an early-failure label)
# is always attempted, as long as the aggregate cap has not been reached.
$g6a = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $false -PeriodicCheckpointIndex 0 -EveryN 10 -AggregateBytesSoFar 0 -AggregateCapBytes 600MB
Assert-True 'g6a (non-periodic, under cap) should_capture' $g6a.should_capture

# scenario 7: the aggregate cap overrides EVERYTHING, including a
# non-periodic ('final'-shaped) label.
$g7 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $false -PeriodicCheckpointIndex 0 -EveryN 10 -AggregateBytesSoFar 600MB -AggregateCapBytes 600MB
Assert-True 'g7 (aggregate cap reached, non-periodic) should NOT capture' (-not $g7.should_capture)
Assert-True 'g7 reason names the aggregate cap' ($g7.reason -match 'aggregate cap')

# scenario 8: periodic checkpoint #1 is ALWAYS captured (an early
# baseline), even though 1 is not a multiple of EveryN=10.
$g8 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 1 -EveryN 10 -AggregateBytesSoFar 0 -AggregateCapBytes 600MB
Assert-True 'g8 (periodic checkpoint #1) should_capture' $g8.should_capture

# scenario 9: periodic checkpoints #2-#9 (neither the first nor a
# multiple of 10) are all gated OUT.
foreach ($idx in 2..9) {
    $g9 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex $idx -EveryN 10 -AggregateBytesSoFar 0 -AggregateCapBytes 600MB
    Assert-True "g9 (periodic checkpoint #$idx) should NOT capture" (-not $g9.should_capture)
}

# scenario 10: periodic checkpoints #10, #20, #30 (multiples of
# EveryN=10) ARE captured.
foreach ($idx in @(10, 20, 30)) {
    $g10 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex $idx -EveryN 10 -AggregateBytesSoFar 0 -AggregateCapBytes 600MB
    Assert-True "g10 (periodic checkpoint #$idx, a multiple of 10) should_capture" $g10.should_capture
}

# scenario 11: #11 (one past a multiple, not itself a multiple, not the
# first) is gated out again -- the "every Nth" gate is not "sticky".
$g11 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 11 -EveryN 10 -AggregateBytesSoFar 0 -AggregateCapBytes 600MB
Assert-True 'g11 (periodic checkpoint #11) should NOT capture' (-not $g11.should_capture)

# scenario 12: the aggregate cap also overrides a periodic checkpoint
# that would otherwise be captured (e.g. #10, a multiple of 10).
$g12 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 10 -EveryN 10 -AggregateBytesSoFar 601MB -AggregateCapBytes 600MB
Assert-True 'g12 (aggregate cap reached, periodic checkpoint #10) should NOT capture' (-not $g12.should_capture)

# scenario 13: a different -EveryN (e.g. 5) is honored, not hardcoded.
$g13a = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 5 -EveryN 5 -AggregateBytesSoFar 0 -AggregateCapBytes 600MB
$g13b = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 6 -EveryN 5 -AggregateBytesSoFar 0 -AggregateCapBytes 600MB
Assert-True 'g13a (EveryN=5, checkpoint #5) should_capture' $g13a.should_capture
Assert-True 'g13b (EveryN=5, checkpoint #6) should NOT capture' (-not $g13b.should_capture)

Write-Host ""
Write-Host "GstDebugTail unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
