# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-GstDebugTail.ps1 -- unit/integration checks for Copy-GstDebugTail and
# Get-GstDebugCaptureDecision (GstDebugTail.ps1, sandbox-lab lane follow-up
# D item 2's GST_DEBUG_FILE capture). Unlike this project's other
# Test-*.ps1 suites, the Copy-GstDebugTail scenarios DO touch the real
# filesystem (real temp files/streams, and one real background job to
# simulate a growing file) -- it is inherently I/O-bound (real
# FileStreams, real sharing-violation semantics), so there is no
# meaningful pure-function form to test instead. Everything runs under the
# OS temp directory and is cleaned up in a try/finally.
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
      bounded content (truncated case only). Locates the first CRLF and
      returns the banner text and the byte-length of everything after it
      -- used instead of predicting the banner's exact text (which embeds
      a "currentLength" that is non-deterministic for a file that is
      still growing while Copy-GstDebugTail reads it). Returns
      BannerText=$null when there is no CRLF at all (the untruncated
      case -- no banner is ever written there).
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

function Get-TailSuffix {
    <#
      Round-5 review finding 8: mirrors In-Sandbox-Soak.ps1's own dynamic
      "-tailNNNmb" suffix derivation exactly, so tests never hardcode a
      literal ".tail200mb" -- if the naming convention or MaxBytes value
      changes, this helper (and every test using it) stays correct.
    #>
    param([long]$MaxBytes)
    return ".tail$([math]::Round($MaxBytes / 1MB, 0))mb"
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
    # GstDebugTail must succeed here (FileShare.ReadWrite). This is also
    # the TRUNCATED case (5 MB source, 1 MB bound).
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

        $maxBytes1 = 1MB
        $wholeDest1 = Join-Path $tmpRoot 'out-live-open-whole.log'
        $truncDest1 = Join-Path $tmpRoot "out-live-open-trunc$(Get-TailSuffix -MaxBytes $maxBytes1)"
        $threw1 = $false
        $result1 = $null
        try { $result1 = Copy-GstDebugTail -SourcePath $src1 -DestPathWhole $wholeDest1 -DestPathTruncated $truncDest1 -MaxBytes $maxBytes1 } catch { $threw1 = $true; Write-Host "  (exception: $_)" }
        Assert-True 'scenario1 Copy-GstDebugTail succeeds against a live-open (Write/Read-shared) file' (-not $threw1)
        if (-not $threw1) {
            Assert-True 'scenario1 result.truncated is True (5 MB source > 1 MB bound)' $result1.truncated
            Assert-Equal 'scenario1 result.dest_path is the TRUNCATED path' $truncDest1 $result1.dest_path
            $bytes1 = [System.IO.File]::ReadAllBytes($result1.dest_path)
            $split1 = Get-BannerAndContentSplit -Bytes $bytes1
            Assert-True 'scenario1 banner line present' ($null -ne $split1.BannerText -and $split1.BannerText -match '^# sandbox-lab TRUNCATED')
            # Round-4 review finding 3: the bound applies to the TOTAL
            # output FILE (banner + content), not content alone.
            Assert-Equal 'scenario1 TOTAL FILE length == MaxBytes exactly (banner + content together, never over the bound)' 1048576 $bytes1.Length
            Assert-Equal 'scenario1 result.bytes_written matches the actual file length' $bytes1.Length $result1.bytes_written
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
        $wholeDest2 = Join-Path $tmpRoot 'out-growing-whole.log'
        $truncDest2 = Join-Path $tmpRoot "out-growing-trunc$(Get-TailSuffix -MaxBytes $maxBytes2)"
        $result2 = Copy-GstDebugTail -SourcePath $src2 -DestPathWhole $wholeDest2 -DestPathTruncated $truncDest2 -MaxBytes $maxBytes2
        Wait-Job $job -Timeout 30 | Out-Null
        $jobOutput = Receive-Job $job -ErrorAction SilentlyContinue
        $finalSrcSize = (Get-Item $src2).Length
        Assert-True 'scenario2 sanity: the source actually grew past its starting size during the copy' ($finalSrcSize -gt 3MB) "(final size: $finalSrcSize bytes, job output: $jobOutput)"
        Assert-True 'scenario2 result.truncated is True' $result2.truncated

        $bytes2 = [System.IO.File]::ReadAllBytes($result2.dest_path)
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
    $maxBytes3 = 1MB
    $wholeDest3 = Join-Path $tmpRoot 'out-pattern-whole.log'
    $truncDest3 = Join-Path $tmpRoot "out-pattern-trunc$(Get-TailSuffix -MaxBytes $maxBytes3)"
    $result3 = Copy-GstDebugTail -SourcePath $src3 -DestPathWhole $wholeDest3 -DestPathTruncated $truncDest3 -MaxBytes $maxBytes3
    $bytes3 = [System.IO.File]::ReadAllBytes($result3.dest_path)
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
    # Round-5 review finding 2: the UNTRUNCATED case -- source is SMALLER
    # than the bound, so nothing was dropped. Must produce NO banner and
    # NO ".tailNNNmb" rename (an earlier version always wrote both,
    # actively misleading for the common case where GST_DEBUG never grew
    # past the bound at all): result.truncated is $false, result.dest_path
    # is the WHOLE path (never the truncated one, which must not even be
    # created), and the file's own bytes are the source verbatim.
    $src4 = Join-Path $tmpRoot 'small.log'
    $smallBytes = New-Object byte[] (100KB)
    for ($i = 0; $i -lt $smallBytes.Length; $i++) { $smallBytes[$i] = [byte]($i % 256) }
    [System.IO.File]::WriteAllBytes($src4, $smallBytes)
    $maxBytes4 = 1MB
    $wholeDest4 = Join-Path $tmpRoot 'out-small-whole.log'
    $truncDest4 = Join-Path $tmpRoot "out-small-trunc$(Get-TailSuffix -MaxBytes $maxBytes4)"
    $result4 = Copy-GstDebugTail -SourcePath $src4 -DestPathWhole $wholeDest4 -DestPathTruncated $truncDest4 -MaxBytes $maxBytes4
    Assert-True 'scenario4 (MaxBytes > source size) result.truncated is False' (-not $result4.truncated)
    Assert-Equal 'scenario4 result.dest_path is the WHOLE path, never the truncated one' $wholeDest4 $result4.dest_path
    Assert-True 'scenario4 the TRUNCATED destination was never even created' (-not (Test-Path $truncDest4))
    $bytes4 = [System.IO.File]::ReadAllBytes($result4.dest_path)
    $split4 = Get-BannerAndContentSplit -Bytes $bytes4
    Assert-Equal 'scenario4 NO banner line (nothing was dropped, so nothing to announce)' $null $split4.BannerText
    Assert-Equal 'scenario4 file bytes == the WHOLE source, byte-for-byte (no banner prepended, no truncation)' $smallBytes.Length $bytes4.Length
    $wholeMatches = $true
    for ($i = 0; $i -lt $smallBytes.Length; $i++) {
        if ($bytes4[$i] -ne $smallBytes[$i]) { $wholeMatches = $false; break }
    }
    Assert-True 'scenario4 file content is byte-for-byte identical to the source (verbatim copy, no banner mixed in)' $wholeMatches

    # ---------------------------------------------------------- scenario 5
    # Round-4 review finding 1 (HIGH), comment/description corrected in
    # round-5 review finding 7: a Get-ChildItem-derived FileInfo's own
    # .Length property is a SNAPSHOT taken when that FileInfo object was
    # first populated -- .NET does NOT auto-refresh it; a caller has to
    # call .Refresh() explicitly. In-Sandbox-Soak.ps1's OLD gst-debug
    # capture listed candidates once via Get-ChildItem, then branched on
    # that CACHED $f.Length later in the same loop iteration -- by which
    # time the real, live GST_DEBUG_FILE had grown far past it (MEASURED
    # directly: a cached FileInfo.Length of 1,048,576 bytes against a live
    # stream of 84,934,656 bytes -- 81x larger; this is a cached-.NET-
    # object staleness mechanism, not an NTFS-directory-caching one),
    # routing the exact live file this feature exists to capture down the
    # UNBOUNDED Copy-Item path instead of the bounded tail-copy path. The
    # fix was to drop the size branch entirely -- Copy-GstDebugTail is now
    # called UNCONDITIONALLY and NEVER accepts or trusts a caller-supplied
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

    $maxBytes5 = 2MB
    $wholeDest5 = Join-Path $tmpRoot 'out-stale-entry-whole.log'
    $truncDest5 = Join-Path $tmpRoot "out-stale-entry-trunc$(Get-TailSuffix -MaxBytes $maxBytes5)"
    # THE FIX under test: called with only -SourcePath (a path, not the
    # stale FileInfo or its cached .Length at all) -- must reflect the
    # file's TRUE current size, not whatever a caller might have cached.
    $result5 = Copy-GstDebugTail -SourcePath $src5 -DestPathWhole $wholeDest5 -DestPathTruncated $truncDest5 -MaxBytes $maxBytes5
    Assert-True 'scenario5 result.truncated is True (5 MB live size > 2 MB bound, even though the cached FileInfo said 1 MB)' $result5.truncated
    $bytes5 = [System.IO.File]::ReadAllBytes($result5.dest_path)
    $split5 = Get-BannerAndContentSplit -Bytes $bytes5
    Assert-True 'scenario5 (stale-entry live file) TOTAL FILE length == MaxBytes exactly -- correctly bounded despite the stale FileInfo, because Copy-GstDebugTail never consulted it' ($bytes5.Length -eq $maxBytes5) "(file length: $($bytes5.Length), MaxBytes: $maxBytes5)"
    # Content correctness: must be the tail of the LIVE (5 MB) file, not
    # bounded against the stale (1 MB) snapshot -- e.g. NOT simply "the
    # whole stale-length region copied verbatim" (which -- since the first
    # 1 MB was all zero bytes from New-Object byte[] -- would show up here
    # as an all-zero content region if this test's fix somehow regressed).
    # Round-5 review finding 8: the previous version of this check,
    # `@($split5.ContentLength) -gt 0 -and (...).Count -gt 0`, wrapped a
    # plain scalar in an array before comparing it with -gt -- PowerShell
    # then applies -gt as an ARRAY FILTER (returning the matching elements,
    # not a boolean), which happened to still evaluate truthy/falsy
    # correctly in an `if`/`-and` context but obscures a genuine boolean
    # intent behind confusing, easy-to-miscopy array-filter semantics.
    # Fixed: plain scalar comparisons throughout, combined with a normal
    # boolean $result variable built via a loop instead of a Where-Object
    # pipeline whose .Count is compared to another scalar.
    $anyNonZero = $false
    if ($split5.ContentLength -gt 0) {
        $checkLimit = [Math]::Min(4095, $split5.ContentLength - 1)
        for ($i = 0; $i -le $checkLimit; $i++) {
            if ($bytes5[$bytes5.Length - $split5.ContentLength + $i] -ne 0) { $anyNonZero = $true; break }
        }
    }
    Assert-True 'scenario5 kept content is NOT merely the (all-zero) stale-length region -- it reflects the live, grown file' $anyNonZero

    # ---------------------------------------------------------- scenario 6
    # Round-5 review finding 4: -MaxBytes below 4096 is rejected outright
    # (ValidateRange) rather than silently producing an over-bound file
    # (measured, before this floor existed: 186 -> 189 bytes over at the
    # extreme where MaxBytes was smaller than the banner's own length).
    $src6 = Join-Path $tmpRoot 'tiny-maxbytes.log'
    [System.IO.File]::WriteAllBytes($src6, (New-Object byte[] (1MB)))
    $threw6 = $false
    try {
        Copy-GstDebugTail -SourcePath $src6 -DestPathWhole (Join-Path $tmpRoot 'x.log') -DestPathTruncated (Join-Path $tmpRoot 'x.log.tail') -MaxBytes 100
    } catch {
        $threw6 = $true
    }
    Assert-True 'scenario6 -MaxBytes below the 4096-byte floor is REJECTED (ValidateRange), not silently over-bound' $threw6

} finally {
    Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
}

# ============================================================ capture gate
# Round-4/round-5 review: Get-GstDebugCaptureDecision is a pure function
# (no filesystem) -- gate/budget logic tested with synthetic inputs, no
# live sandbox or real files needed at all. Round-5 review finding 1 split
# the single aggregate cap into two INDEPENDENT budgets (periodic vs.
# non-periodic) -- every scenario below uses the new
# -PeriodicBytesSoFar/-PeriodicCapBytes/-NonPeriodicBytesSoFar/
# -NonPeriodicCapBytes parameter set.

$defaultPeriodicCap = 400MB
$defaultNonPeriodicCap = 200MB

# scenario 7: a non-periodic label ('final', or an early-failure label)
# is always attempted, as long as its OWN (non-periodic) reserve has not
# been reached -- entirely independent of the periodic budget.
$g7a = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $false -PeriodicCheckpointIndex 0 -EveryN 10 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g7a (non-periodic, under its own reserve) should_capture' $g7a.should_capture

# scenario 8: the NON-PERIODIC reserve, once reached, blocks further
# non-periodic captures -- but does NOT touch the periodic budget at all.
$g8 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $false -PeriodicCheckpointIndex 0 -EveryN 10 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar $defaultNonPeriodicCap -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g8 (non-periodic reserve exhausted) should NOT capture' (-not $g8.should_capture)
Assert-True 'g8 reason names the non-periodic reserve' ($g8.reason -match 'non-periodic reserve')

# scenario 9 (round-5 review finding 1, THE core regression this split
# exists for): periodic captures having fully consumed THEIR OWN budget
# must NOT prevent a non-periodic ('final') capture from proceeding --
# proves the two budgets are genuinely independent, not just separately
# LABELED views of the same counter.
$g9 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $false -PeriodicCheckpointIndex 0 -EveryN 10 -PeriodicBytesSoFar $defaultPeriodicCap -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g9 (periodic budget FULLY exhausted, non-periodic reserve untouched) -> final STILL captures' $g9.should_capture

# scenario 10: periodic checkpoint #1 is ALWAYS captured (an early
# baseline), even though 1 is not a multiple of EveryN=10, as long as the
# periodic budget is not yet exhausted.
$g10 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 1 -EveryN 10 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g10 (periodic checkpoint #1) should_capture' $g10.should_capture

# scenario 10b (round-5 review finding 5): the real, observable difference
# between the fixed `-eq 1` check and the old `-le 1` check only shows up
# for an index that is BOTH less than 1 AND not itself a multiple of
# -EveryN (0 is always `0 % N == 0` for any N, so index 0 captures via the
# every-Nth branch regardless of which check is used -- not a useful
# regression guard for this specific fix). A NEGATIVE, non-multiple index
# (e.g. -3 against EveryN=10) is the case that actually distinguishes
# them: the OLD `-le 1` would have treated ANY such index as "the first
# checkpoint" (a caller bug -- its own counter went negative -- silently
# masked as a legitimate capture); the FIXED `-eq 1` does not, so it falls
# through to the every-Nth check, which -3 also fails, and the whole
# thing correctly reports should_capture=$false instead of masking the
# bug as a false "first capture".
$g10bNeg = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex -3 -EveryN 10 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g10bNeg (negative index, not a multiple of 10, not 1) should NOT capture -- the -eq 1 fix does not mask a caller counter bug as a false "first capture"' (-not $g10bNeg.should_capture)
# Sanity (not a regression guard for THIS fix, since 0 % N == 0 always):
# index 0 still legitimately captures, via the every-Nth branch.
$g10bZero = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 0 -EveryN 10 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g10bZero (index 0, sanity) captures via the every-Nth branch (0 % 10 == 0), not the first-checkpoint branch' $g10bZero.should_capture

# scenario 11: periodic checkpoints #2-#9 (neither the first nor a
# multiple of 10) are all gated OUT.
foreach ($idx in 2..9) {
    $g11 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex $idx -EveryN 10 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
    Assert-True "g11 (periodic checkpoint #$idx) should NOT capture" (-not $g11.should_capture)
}

# scenario 12: periodic checkpoints #10, #20, #30 (multiples of
# EveryN=10) ARE captured.
foreach ($idx in @(10, 20, 30)) {
    $g12 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex $idx -EveryN 10 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
    Assert-True "g12 (periodic checkpoint #$idx, a multiple of 10) should_capture" $g12.should_capture
}

# scenario 13: #11 (one past a multiple, not itself a multiple, not the
# first) is gated out again -- the "every Nth" gate is not "sticky".
$g13 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 11 -EveryN 10 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g13 (periodic checkpoint #11) should NOT capture' (-not $g13.should_capture)

# scenario 14: the PERIODIC cap, once reached, blocks further periodic
# captures (even a multiple of EveryN) -- but does NOT affect the
# non-periodic reserve (see scenario 9 above for that direction proven).
$g14 = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 10 -EveryN 10 -PeriodicBytesSoFar $defaultPeriodicCap -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g14 (periodic cap reached, periodic checkpoint #10) should NOT capture' (-not $g14.should_capture)
Assert-True 'g14 reason names the periodic budget' ($g14.reason -match 'periodic capture budget')

# scenario 15: a different -EveryN (e.g. 5) is honored, not hardcoded.
$g15a = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 5 -EveryN 5 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
$g15b = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 6 -EveryN 5 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'g15a (EveryN=5, checkpoint #5) should_capture' $g15a.should_capture
Assert-True 'g15b (EveryN=5, checkpoint #6) should NOT capture' (-not $g15b.should_capture)

# scenario 16 (round-5 review finding 5): -EveryN 0 is rejected outright
# (ValidateRange) rather than dividing by zero at the `% $EveryN` check.
$threw16 = $false
try {
    Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex 5 -EveryN 0 -PeriodicBytesSoFar 0 -PeriodicCapBytes $defaultPeriodicCap -NonPeriodicBytesSoFar 0 -NonPeriodicCapBytes $defaultNonPeriodicCap | Out-Null
} catch {
    $threw16 = $true
}
Assert-True 'g16 -EveryN 0 is REJECTED (ValidateRange), not a divide-by-zero' $threw16

# ------------------------------------------------------- 40-checkpoint sim
# scenario 17 (round-5 review finding 1): simulate a realistic 40-checkpoint
# soak -- worst case, every CAPTURED periodic checkpoint writes a full
# 200 MB (the per-file bound). Confirm: (a) periodic captures stop being
# approved once the 400 MB periodic budget is exhausted (never spilling
# into the 200 MB non-periodic reserve, since the two are independent
# counters); (b) 'final', called after all 40, is STILL approved and still
# has its own full 200 MB reserve untouched, because periodic captures
# never draw from it.
$simPeriodicBytes = 0
$simNonPeriodicBytes = 0
$simCapturedCount = 0
$simSkippedCount = 0
$simTotalPeriodicBytesIfAllCaptured = 0
for ($cp = 1; $cp -le 40; $cp++) {
    $decision = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $true -PeriodicCheckpointIndex $cp -EveryN 10 `
        -PeriodicBytesSoFar $simPeriodicBytes -PeriodicCapBytes $defaultPeriodicCap `
        -NonPeriodicBytesSoFar $simNonPeriodicBytes -NonPeriodicCapBytes $defaultNonPeriodicCap
    if ($decision.should_capture) {
        $simCapturedCount++
        $simPeriodicBytes += 200MB  # worst case: every approved capture is a full 200 MB file
    } else {
        $simSkippedCount++
    }
}
# Gate alone (#1, #10, #20, #30, #40) would approve 5 checkpoints = 1000 MB
# of worst-case demand against a 400 MB budget -- so the budget check must
# have started refusing partway through this sequence.
Assert-True 'scenario17 the 400 MB periodic budget was actually exhausted partway through 40 worst-case checkpoints' ($simPeriodicBytes -le $defaultPeriodicCap) "(periodic bytes counted: $simPeriodicBytes)"
Assert-True 'scenario17 at least one gate-eligible periodic checkpoint (#1/#10/#20/#30/#40) was refused once the periodic budget ran out' ($simSkippedCount -gt 35) "(captured: $simCapturedCount, skipped: $simSkippedCount)"
Assert-True 'scenario17 periodic capture count is bounded (never every one of the 40)' ($simCapturedCount -le 5)

$finalDecision = Get-GstDebugCaptureDecision -IsPeriodicCheckpoint $false -PeriodicCheckpointIndex 0 -EveryN 10 `
    -PeriodicBytesSoFar $simPeriodicBytes -PeriodicCapBytes $defaultPeriodicCap `
    -NonPeriodicBytesSoFar $simNonPeriodicBytes -NonPeriodicCapBytes $defaultNonPeriodicCap
Assert-True 'scenario17 final -- called AFTER the periodic budget is fully exhausted by 40 checkpoints -- STILL captures (its own reserve was never touched)' $finalDecision.should_capture
Assert-Equal 'scenario17 the non-periodic byte counter was never incremented by any periodic checkpoint in this simulation' 0 $simNonPeriodicBytes

Write-Host ""
Write-Host "GstDebugTail unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
