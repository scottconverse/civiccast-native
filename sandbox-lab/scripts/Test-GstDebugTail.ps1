# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-GstDebugTail.ps1 -- unit/integration checks for Copy-GstDebugTail,
# Get-GstDebugCaptureDecision, Get-GstDebugEffectiveMaxBytes, and
# Get-ByteSizeLabel (GstDebugTail.ps1, sandbox-lab lane follow-up D item
# 2's GST_DEBUG_FILE capture). Unlike this project's other Test-*.ps1
# suites, the Copy-GstDebugTail scenarios DO touch the real filesystem
# (real temp files/streams, and real background jobs to simulate a
# growing/trickling source) -- it is inherently I/O-bound (real
# FileStreams, real sharing-violation semantics, real elapsed-time
# behavior), so there is no meaningful pure-function form to test instead.
# Everything runs under the OS temp directory and is cleaned up in a
# try/finally.
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
      a snapshot length that varies test to test). Returns BannerText=$null
      when there is no CRLF at all (the untruncated case -- no banner is
      ever written there).
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

# Round-7 review finding 3: this test file used to maintain its OWN
# parallel mirror of the production suffix-naming logic (a bare
# MB-only [math]::Round), which drifted from the real
# Get-ByteSizeLabel the moment round-6 made that function KB-aware
# (".tail0mb" in the stale mirror vs the real ".tail4kb" production would
# actually produce) -- silently making every test's OWN destination-path
# prediction wrong in exactly the cases most worth testing. Fixed by
# calling the REAL, dot-sourced production function directly; this
# helper can never drift again because it has nothing left to drift.
function Get-TailSuffix {
    param([long]$MaxBytes)
    return ".tail$((Get-ByteSizeLabel -Bytes $MaxBytes).ToLowerInvariant())"
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
    # the TRUNCATED case (5 MB source, 1 MB bound -- already over the
    # bound at the moment this function takes its one-time snapshot).
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
            Assert-True 'scenario1 result.truncated is True (5 MB snapshot > 1 MB bound)' $result1.truncated
            Assert-True 'scenario1 result.partial is False (no deadline involved)' (-not $result1.partial)
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
    # Round-7 review finding 1 REPLACED the growth-detection mechanism
    # entirely with a ONE-TIME SNAPSHOT contract: Copy-GstDebugTail reads
    # the source's length exactly once, at open time, and commits to that
    # snapshot for the whole call -- content the source gains AFTER that
    # snapshot is simply not part of this capture. This scenario proves
    # exactly that: the source is already over the bound at open time
    # (truncated case, same as scenario 1), and then a REAL background job
    # keeps appending to it for the whole duration of the copy -- the
    # output must be determined ENTIRELY by what existed at snapshot time,
    # completely unaffected by everything the background job adds
    # afterward.
    $src2 = Join-Path $tmpRoot 'growing-ignored.log'
    $maxBytes2 = 2MB
    $originalBytes2 = New-Object byte[] (3MB)  # already over the 2 MB bound at snapshot time
    for ($i = 0; $i -lt $originalBytes2.Length; $i++) { $originalBytes2[$i] = [byte]($i % 251) }  # recognizable, non-zero pattern
    [System.IO.File]::WriteAllBytes($src2, $originalBytes2)
    $job2 = Start-Job -ScriptBlock {
        param($path)
        $ws = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        try {
            $ws.Seek(0, [System.IO.SeekOrigin]::End) | Out-Null
            # A DIFFERENT, all-0xFF pattern for everything appended AFTER
            # the original content -- if any of THIS ever showed up in the
            # captured output, that would prove the snapshot contract was
            # violated (growth leaking into a call that already committed
            # to its own earlier snapshot).
            $chunk = New-Object byte[] (256KB)
            for ($i = 0; $i -lt $chunk.Length; $i++) { $chunk[$i] = 0xFF }
            for ($i = 0; $i -lt 40; $i++) {
                $ws.Write($chunk, 0, $chunk.Length)
                $ws.Flush()
                Start-Sleep -Milliseconds 25
            }
        } finally { $ws.Dispose() }
    } -ArgumentList $src2
    try {
        $wholeDest2 = Join-Path $tmpRoot 'out-growing-ignored-whole.log'
        $truncDest2 = Join-Path $tmpRoot "out-growing-ignored-trunc$(Get-TailSuffix -MaxBytes $maxBytes2)"
        $result2 = Copy-GstDebugTail -SourcePath $src2 -DestPathWhole $wholeDest2 -DestPathTruncated $truncDest2 -MaxBytes $maxBytes2
        Wait-Job $job2 -Timeout 30 | Out-Null
        $finalSrcSize2 = (Get-Item $src2).Length
        Assert-True 'scenario2 sanity: the source DID keep growing during/after the copy (background job kept appending)' ($finalSrcSize2 -gt $originalBytes2.Length) "(final size: $finalSrcSize2 bytes)"
        Assert-True 'scenario2 result.truncated is True (3 MB snapshot > 2 MB bound)' $result2.truncated
        Assert-True 'scenario2 result.partial is False (this is the SNAPSHOT contract, not a deadline hit)' (-not $result2.partial)

        $bytes2 = [System.IO.File]::ReadAllBytes($result2.dest_path)
        $split2 = Get-BannerAndContentSplit -Bytes $bytes2
        Assert-True 'scenario2 banner line present' ($null -ne $split2.BannerText -and $split2.BannerText -match '^# sandbox-lab TRUNCATED')
        Assert-Equal 'scenario2 TOTAL FILE length == MaxBytes EXACTLY, determined by the ORIGINAL 3 MB snapshot alone' ([int64]$maxBytes2) $bytes2.Length
        # THE core snapshot-contract proof: every content byte must come
        # from the ORIGINAL (pre-growth) pattern -- none of the 0xFF bytes
        # the background job appended afterward may appear anywhere in
        # the captured content.
        $anyGrowthByteLeaked = $false
        for ($i = ($bytes2.Length - $split2.ContentLength); $i -lt $bytes2.Length; $i++) {
            if ($bytes2[$i] -eq 0xFF) { $anyGrowthByteLeaked = $true; break }
        }
        Assert-True 'scenario2 NONE of the content reflects growth that happened during/after this call -- the snapshot is the whole and only truth for this capture' (-not $anyGrowthByteLeaked)
    } finally {
        Remove-Job $job2 -Force -ErrorAction SilentlyContinue
    }

    # --------------------------------------------------------- scenario 2b
    # Round-7 review finding 1's own explicit test list, item "grow-past
    # bounded": the source starts UNDER the bound (untruncated at snapshot
    # time) and grows PAST the bound during/after the copy via a real
    # background job. Under the NEW snapshot contract this must be the
    # UNTRUNCATED case -- exactly what was on disk at the one-time
    # snapshot, verbatim, no banner, completely unaffected by the later
    # growth (the inverse of round-6's own now-removed
    # detect-and-convert-to-truncated behavior, which this round replaced
    # for the reasons in Copy-GstDebugTail's own header: that mechanism's
    # bounded-grace-window implementation could keep a single call open
    # indefinitely against a sufficiently slow/trickling writer).
    $src2b = Join-Path $tmpRoot 'growing-under-bound.log'
    $maxBytes2b = 2MB
    $originalBytes2b = New-Object byte[] (200KB)  # well under the 2 MB bound at snapshot time
    for ($i = 0; $i -lt $originalBytes2b.Length; $i++) { $originalBytes2b[$i] = [byte]($i % 251) }
    [System.IO.File]::WriteAllBytes($src2b, $originalBytes2b)
    $job2b = Start-Job -ScriptBlock {
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
    } -ArgumentList $src2b
    try {
        $wholeDest2b = Join-Path $tmpRoot 'out-growing-under-bound-whole.log'
        $truncDest2b = Join-Path $tmpRoot "out-growing-under-bound-trunc$(Get-TailSuffix -MaxBytes $maxBytes2b)"
        $result2b = Copy-GstDebugTail -SourcePath $src2b -DestPathWhole $wholeDest2b -DestPathTruncated $truncDest2b -MaxBytes $maxBytes2b
        Wait-Job $job2b -Timeout 30 | Out-Null
        $finalSrcSize2b = (Get-Item $src2b).Length
        Assert-True 'scenario2b sanity: the source DID grow past the 2 MB bound eventually (background job kept appending)' ($finalSrcSize2b -gt $maxBytes2b) "(final size: $finalSrcSize2b bytes)"
        # THE new contract: untruncated, because the SNAPSHOT (taken at
        # open time, before any of that growth happened) was under the
        # bound -- regardless of what the source becomes afterward.
        Assert-True 'scenario2b result.truncated is False (snapshot was under the bound; later growth is irrelevant to this call)' (-not $result2b.truncated)
        Assert-True 'scenario2b result.partial is False' (-not $result2b.partial)
        Assert-Equal 'scenario2b result.dest_path is the WHOLE path' $wholeDest2b $result2b.dest_path
        Assert-True 'scenario2b the TRUNCATED destination was never even created' (-not (Test-Path $truncDest2b))
        Assert-Equal 'scenario2b bytes_written == exactly the snapshot length (200 KB), not the eventual grown size' $originalBytes2b.Length $result2b.bytes_written
        $bytes2b = [System.IO.File]::ReadAllBytes($result2b.dest_path)
        Assert-Equal 'scenario2b file length == the snapshot length exactly' $originalBytes2b.Length $bytes2b.Length
        $matches2b = $true
        for ($i = 0; $i -lt $originalBytes2b.Length; $i++) {
            if ($bytes2b[$i] -ne $originalBytes2b[$i]) { $matches2b = $false; break }
        }
        Assert-True 'scenario2b captured content is byte-for-byte the ORIGINAL (pre-growth) snapshot content, verbatim' $matches2b
    } finally {
        Remove-Job $job2b -Force -ErrorAction SilentlyContinue
    }

    # --------------------------------------------------------- scenario 2c
    # Round-7 review finding 1's explicit test list, item "trickle writer
    # terminates within the deadline": THE regression test for the actual
    # bug this round fixes. Round-6's own grace-window mechanism reset on
    # EVERY successful read, so a source trickling in even 1 byte per
    # 200 ms could keep a single Copy-GstDebugTail call open indefinitely
    # -- and because this function runs SYNCHRONOUSLY inside In-Sandbox-
    # Soak.ps1's own poll loop, a call that never returns starves the
    # host's 6-minute rollup-stall bound into firing a FALSE STALL on an
    # otherwise healthy run. A real background job trickles 1 byte every
    # 50 ms for 3 full seconds (60 iterations) -- comfortably longer than
    # any reasonable single-copy budget if this function were still
    # waiting around for it. The snapshot contract means this call should
    # return almost immediately regardless, having captured only what
    # existed at open time.
    $src2c = Join-Path $tmpRoot 'trickle.log'
    $maxBytes2c = 2MB
    [System.IO.File]::WriteAllBytes($src2c, (New-Object byte[] (500KB)))
    $job2c = Start-Job -ScriptBlock {
        param($path)
        $ws = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Write, [System.IO.FileShare]::Read)
        try {
            $ws.Seek(0, [System.IO.SeekOrigin]::End) | Out-Null
            $one = [byte[]]@(1)
            for ($i = 0; $i -lt 60; $i++) {
                $ws.Write($one, 0, 1)
                $ws.Flush()
                Start-Sleep -Milliseconds 50
            }
        } finally { $ws.Dispose() }
    } -ArgumentList $src2c
    try {
        Start-Sleep -Milliseconds 20  # let the trickle job actually start first
        $wholeDest2c = Join-Path $tmpRoot 'out-trickle-whole.log'
        $truncDest2c = Join-Path $tmpRoot "out-trickle-trunc$(Get-TailSuffix -MaxBytes $maxBytes2c)"
        $stopwatch2c = [System.Diagnostics.Stopwatch]::StartNew()
        $result2c = Copy-GstDebugTail -SourcePath $src2c -DestPathWhole $wholeDest2c -DestPathTruncated $truncDest2c -MaxBytes $maxBytes2c
        $stopwatch2c.Stop()
        # The trickle job's own full run is ~3000 ms (60 x 50 ms) -- a
        # generous 2-second ceiling here proves this call did NOT wait
        # around for it (measured directly: this call actually completes
        # in well under 200 ms in practice; 2000 ms leaves comfortable
        # headroom for a loaded CI box without weakening the regression
        # guard's real point, which is "does not hang for seconds").
        Assert-True 'scenario2c (trickle writer) Copy-GstDebugTail returns well within 2000 ms, proving it does not wait for a still-trickling source' ($stopwatch2c.ElapsedMilliseconds -lt 2000) "(elapsed: $($stopwatch2c.ElapsedMilliseconds) ms)"
        Assert-True 'scenario2c result.truncated is False (500 KB snapshot < 2 MB bound)' (-not $result2c.truncated)
        Assert-True 'scenario2c result.partial is False (returned on its own, not via the deadline)' (-not $result2c.partial)
        Assert-Equal 'scenario2c bytes_written == exactly the snapshot length (500 KB), none of the trickle' 512000 $result2c.bytes_written
    } finally {
        Remove-Job $job2c -Force -ErrorAction SilentlyContinue
    }

    # --------------------------------------------------------- scenario 2d
    # Round-7 review finding 2: with the snapshot rule, a genuine
    # untruncated copy of a STATIC (non-growing) source costs 0 ms of
    # extra waiting -- no more 500 ms grace window "just in case" the way
    # round-6's own (now-removed) implementation spent even when nothing
    # was wrong at all. MEASURED directly: a 2 MB static copy actually
    # completes in ~50 ms in practice; asserted here against a 200 ms
    # ceiling (comfortable headroom for a loaded box, while still failing
    # loudly if a future change reintroduces any kind of artificial wait).
    $src2d = Join-Path $tmpRoot 'static-timing.log'
    [System.IO.File]::WriteAllBytes($src2d, (New-Object byte[] (2MB)))
    $wholeDest2d = Join-Path $tmpRoot 'out-static-timing-whole.log'
    $truncDest2d = Join-Path $tmpRoot "out-static-timing-trunc$(Get-TailSuffix -MaxBytes 200MB)"
    $stopwatch2d = [System.Diagnostics.Stopwatch]::StartNew()
    $result2d = Copy-GstDebugTail -SourcePath $src2d -DestPathWhole $wholeDest2d -DestPathTruncated $truncDest2d -MaxBytes 200MB
    $stopwatch2d.Stop()
    Assert-True 'scenario2d (static file) Copy-GstDebugTail completes in under 200 ms -- no artificial grace-window wait' ($stopwatch2d.ElapsedMilliseconds -lt 200) "(elapsed: $($stopwatch2d.ElapsedMilliseconds) ms)"
    Assert-True 'scenario2d result.truncated is False' (-not $result2d.truncated)
    Assert-Equal 'scenario2d bytes_written == the exact static source size' 2097152 $result2d.bytes_written

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
    Assert-True 'scenario3 kept content is byte-for-byte the LAST (MaxBytes - banner) bytes of the source -- ends at the snapshot''s true end, not the head, not some other slice' $tailMatches

    # ---------------------------------------------------------- scenario 4
    # Round-5 review finding 2: the UNTRUNCATED case -- source is SMALLER
    # than the bound, so nothing was dropped. Must produce NO banner and
    # NO ".tailNNN(kb|mb)" rename (an earlier version always wrote both,
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
    # Length; it always takes its OWN one-time snapshot from its own
    # freshly opened stream (round-7 review finding 1's own contract),
    # never from a FileInfo any caller might have cached earlier.
    $src5 = Join-Path $tmpRoot 'stale-entry.log'
    [System.IO.File]::WriteAllBytes($src5, (New-Object byte[] (1MB)))
    $staleFileInfo = Get-ChildItem -LiteralPath $src5 -File
    $staleLengthBeforeGrowth = $staleFileInfo.Length
    # Grow the file well past the (soon to be stale) cached FileInfo's own
    # .Length, via a SEPARATE handle, BEFORE calling Copy-GstDebugTail --
    # mirrors a live GStreamer worker continuing to write after this run's
    # own candidate listing already captured a FileInfo for it, but before
    # this run's own capture attempt actually starts.
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
    # file's TRUE current size (its own fresh snapshot, taken now), not
    # whatever a caller might have cached earlier.
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
    # Round-5 review finding 8 (still in force): plain scalar comparisons
    # throughout, never an array wrapped around a scalar and compared with
    # -gt (which PowerShell applies as an array FILTER, not a boolean).
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

    # --------------------------------------------------------- scenario 2e
    # Round-7 review finding 1's own -WholeCopyDeadlineSeconds safety net
    # -- purely defensive (a slow/contended disk, never a growth-detection
    # mechanism, which the snapshot rule already made unnecessary). A
    # deliberately tiny deadline (0 seconds -- guaranteed to already be in
    # the past by the time the read loop's first iteration checks it)
    # against a source with real content to copy proves the loop actually
    # stops, marks the result partial, and renames the destination to
    # "<name>.partial" rather than leaving an unbannered, incomplete file
    # sitting at its otherwise-legitimate name (round-7 finding 7's own
    # principle, applied here too).
    $src2e = Join-Path $tmpRoot 'deadline.log'
    [System.IO.File]::WriteAllBytes($src2e, (New-Object byte[] (2MB)))
    $wholeDest2e = Join-Path $tmpRoot 'out-deadline-whole.log'
    $truncDest2e = Join-Path $tmpRoot "out-deadline-trunc$(Get-TailSuffix -MaxBytes 200MB)"
    $result2e = Copy-GstDebugTail -SourcePath $src2e -DestPathWhole $wholeDest2e -DestPathTruncated $truncDest2e -MaxBytes 200MB -WholeCopyDeadlineSeconds 0
    Assert-True 'scenario2e result.partial is True (the 0-second deadline fired)' $result2e.partial
    Assert-True 'scenario2e result.truncated is also True (partial implies truncated -- an incomplete capture is never reported as a clean, complete one)' $result2e.truncated
    Assert-Equal 'scenario2e result.dest_path carries the ".partial" suffix' "$wholeDest2e.partial" $result2e.dest_path
    Assert-True 'scenario2e the ".partial" file actually exists on disk' (Test-Path $result2e.dest_path)
    Assert-True 'scenario2e the ORIGINAL (unrenamed) whole-copy path does NOT exist -- never left at the legitimate name' (-not (Test-Path $wholeDest2e))

} finally {
    Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
}

# ======================================================= Get-ByteSizeLabel
# Round-7 review finding 4: pinned table, including the exact boundary
# case named in review (1048575 -> "1024KB", one byte short of 1 MB) and
# the explicit AwayFromZero rounding mode this function now uses.
$byteSizeLabelTable = @(
    @{ Bytes = 0; Expected = '0KB' }
    @{ Bytes = 4096; Expected = '4KB' }
    @{ Bytes = 512000; Expected = '500KB' }
    @{ Bytes = 1048575; Expected = '1024KB' }   # exactly 1 MB minus 1 byte -- still the KB branch
    @{ Bytes = 1048576; Expected = '1MB' }      # exactly 1 MB -- the MB branch's own lower boundary
    @{ Bytes = 1572864; Expected = '2MB' }      # 1.5 MB -- AwayFromZero rounds up, never down
    @{ Bytes = 209715200; Expected = '200MB' }
)
foreach ($row in $byteSizeLabelTable) {
    Assert-Equal "Get-ByteSizeLabel($($row.Bytes)) -> '$($row.Expected)'" $row.Expected (Get-ByteSizeLabel -Bytes $row.Bytes)
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

# ================================================= per-checkpoint cap (finding 6)
# Round-6 review finding 6: Get-GstDebugEffectiveMaxBytes is a pure
# three-way minimum -- tested with synthetic inputs, no filesystem needed.

# scenario 18: plenty of run-wide budget AND per-checkpoint budget left --
# the NORMAL per-file bound (200 MB here) is the binding constraint.
$e18 = Get-GstDebugEffectiveMaxBytes -NormalMaxBytes 200MB -KindBytesSoFar 0 -KindCapBytes $defaultPeriodicCap -PerCheckpointBytesSoFar 0 -PerCheckpointCapBytes 200MB
Assert-Equal 'e18 (plenty of budget everywhere) -> the normal 200 MB bound wins' ([int64]200MB) $e18

# scenario 19: run-wide (kind) budget is nearly exhausted -- IT is the
# binding constraint, even though per-checkpoint has plenty left.
$e19 = Get-GstDebugEffectiveMaxBytes -NormalMaxBytes 200MB -KindBytesSoFar (399MB) -KindCapBytes $defaultPeriodicCap -PerCheckpointBytesSoFar 0 -PerCheckpointCapBytes 200MB
Assert-Equal 'e19 (run-wide/kind budget nearly exhausted) -> that residual wins, not the normal bound' ([int64]1MB) $e19

# scenario 20 (THE core case round-6 finding 6 exists for): a single
# checkpoint has already captured 150 MB (e.g. from a first candidate
# file) against its OWN 200 MB per-checkpoint cap, while the run-wide
# periodic budget still has plenty left (only 150 MB used of 400 MB) --
# the PER-CHECKPOINT residual (50 MB) must be the binding constraint for
# a SECOND candidate file in the SAME checkpoint, even though the
# run-wide budget alone would have allowed a full 200 MB.
$e20 = Get-GstDebugEffectiveMaxBytes -NormalMaxBytes 200MB -KindBytesSoFar 150MB -KindCapBytes $defaultPeriodicCap -PerCheckpointBytesSoFar 150MB -PerCheckpointCapBytes 200MB
Assert-Equal 'e20 (per-checkpoint cap is the tightest constraint) -> 50 MB residual wins' ([int64]50MB) $e20

# scenario 21: two large candidate files in ONE checkpoint -- the second
# candidate's own effective bound must reflect what the FIRST candidate's
# copy already consumed of the per-checkpoint cap, simulating exactly
# In-Sandbox-Soak.ps1's own foreach loop (a single checkpoint's own
# running total accumulates across candidates within that one call).
$perCheckpointRunning = [int64]0
$firstCandidateBound = Get-GstDebugEffectiveMaxBytes -NormalMaxBytes 200MB -KindBytesSoFar 0 -KindCapBytes $defaultPeriodicCap -PerCheckpointBytesSoFar $perCheckpointRunning -PerCheckpointCapBytes 200MB
Assert-Equal 'e21 first candidate in the checkpoint gets the full 200 MB (nothing consumed yet)' ([int64]200MB) $firstCandidateBound
$perCheckpointRunning += $firstCandidateBound  # worst case: the first candidate actually used its whole bound
$secondCandidateBound = Get-GstDebugEffectiveMaxBytes -NormalMaxBytes 200MB -KindBytesSoFar $firstCandidateBound -KindCapBytes $defaultPeriodicCap -PerCheckpointBytesSoFar $perCheckpointRunning -PerCheckpointCapBytes 200MB
Assert-True 'e21 second candidate in the SAME checkpoint is refused (per-checkpoint cap already exhausted by the first) -- one checkpoint with 2 candidates cannot drain 400 MB of run-wide periodic budget by itself' ($secondCandidateBound -lt 4096) "(second candidate bound: $secondCandidateBound)"

# scenario 22: a fully exhausted budget (either kind) yields zero or
# negative -- never silently clamped back up to something positive by
# this function itself (the CALLER is responsible for checking against
# Copy-GstDebugTail's own 4096-byte floor, per this function's own
# .OUTPUTS doc).
$e22 = Get-GstDebugEffectiveMaxBytes -NormalMaxBytes 200MB -KindBytesSoFar $defaultPeriodicCap -KindCapBytes $defaultPeriodicCap -PerCheckpointBytesSoFar 0 -PerCheckpointCapBytes 200MB
Assert-True 'e22 (kind budget fully exhausted) -> zero or negative, not silently positive' ($e22 -le 0) "(got: $e22)"

Write-Host ""
Write-Host "GstDebugTail unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
