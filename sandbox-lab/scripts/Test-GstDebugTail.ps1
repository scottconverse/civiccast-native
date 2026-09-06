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
            Assert-Equal 'scenario1 content length == MaxBytes exactly (source was static, 5 MB > 1 MB bound)' 1048576 $split1.ContentLength
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
        Assert-Equal 'scenario2 (growing-file bound) content length == MaxBytes EXACTLY, never more, despite the source growing well past it during the copy' ([int64]$maxBytes2) $split2.ContentLength
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
    $expectedTail = $patternBytes[($patternBytes.Length - $maxBytes3)..($patternBytes.Length - 1)]
    $actualTailBytes = New-Object byte[] $split3.ContentLength
    [Array]::Copy($bytes3, $bytes3.Length - $split3.ContentLength, $actualTailBytes, 0, $split3.ContentLength)
    $tailMatches = ($actualTailBytes.Length -eq $expectedTail.Length)
    if ($tailMatches) {
        for ($i = 0; $i -lt $expectedTail.Length; $i++) {
            if ($actualTailBytes[$i] -ne $expectedTail[$i]) { $tailMatches = $false; break }
        }
    }
    Assert-True 'scenario3 kept content is byte-for-byte the LAST MaxBytes bytes of the source (not the head, not some other slice)' $tailMatches

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

} finally {
    Remove-Item -Recurse -Force $tmpRoot -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "GstDebugTail unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
