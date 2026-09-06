# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# GstDebugTail.ps1 -- dot-sourceable Copy-GstDebugTail (sandbox-lab lane
# follow-up D, item 2's GST_DEBUG_FILE capture), extracted the same way
# ServiceStartFailureCheck.ps1/CaptionsOffCheck.ps1/WorkerStdoutParser.ps1/
# CpuSampler.ps1/WorkerEnv.ps1 already were, so it is unit-testable
# (Test-GstDebugTail.ps1) against real temp files/streams instead of only
# ever being exercised inside a live sandbox soak.

function Copy-GstDebugTail {
    <#
      .SYNOPSIS
      Copy a GST_DEBUG_FILE (or a rotated/*.gstdebug sibling) into the
      evidence tree, truncating to at most -MaxBytes ONLY when the source
      actually exceeds it -- an untouched file is copied verbatim, with no
      banner and no ".tailNNNmb" rename (round-5 review finding 2: an
      earlier version always wrote a TRUNCATED banner and a `.tailNNNmb`
      suffix even when nothing was dropped, which is actively misleading
      for the common case where GST_DEBUG never grew past the bound at
      all).

      Round-3 review findings 1-2 (still in force): opens with
      FileShare.ReadWrite, not FileShare.Read ([System.IO.File]::OpenRead's
      default) -- a live GST_DEBUG_FILE has no read-sharing on the
      WRITER's side, so FileShare.Read alone throws "being used by another
      process" (measured directly against a file held open for write by a
      separate process; Copy-Item on the identical file succeeds, because
      it goes through a different Win32 CopyFile path that tolerates this
      share mode). When truncation IS needed, the 200 MB bound is enforced
      on the READ LOOP itself -- exactly -MaxBytes bytes are read and
      written, counted down per chunk, regardless of how large the source
      grows during the copy.

      Round-4 review finding 3 (still in force): when truncating, the
      OUTPUT FILE (banner + content), not just the content, is bounded to
      AT MOST -MaxBytes total. The banner's length is computed FIRST and
      subtracted from the content budget before the read position is even
      chosen, so the retained content still ends at the source's true (as
      of copy time) end-of-file.

      Round-5 review finding 4: -MaxBytes below the banner's own length
      would make even an EMPTY content budget exceed the bound (measured:
      186 -> 189 bytes over at the extreme). Rather than truncate the
      banner text itself (which could cut it off mid-sentence in a
      caller-visible way), -MaxBytes is validated to be at least 4096
      bytes -- comfortably larger than any realistic banner text -- so
      this situation cannot arise at all; production always passes 200 MB
      or a per-run-cap-derived residual (see In-Sandbox-Soak.ps1's own
      floor-check before ever calling this with a residual value).

      .PARAMETER SourcePath
      The live GST_DEBUG_FILE (or a rotated/*.gstdebug sibling) to read
      from. May still be open for write by another process.

      .PARAMETER DestPathWhole
      Where to write an UNTRUNCATED copy (source was already <= -MaxBytes)
      -- a plain, verbatim copy, no banner, no rename.

      .PARAMETER DestPathTruncated
      Where to write a TRUNCATED copy (source exceeded -MaxBytes) -- the
      bannered, bounded tail. Only one of -DestPathWhole/-DestPathTruncated
      is ever actually written to; which one is reported back in the
      returned object's .dest_path.

      .PARAMETER MaxBytes
      The bound (200 MB in production, or a smaller per-run-cap-derived
      residual -- see In-Sandbox-Soak.ps1) on the TOTAL truncated output
      file (banner + content). Must be at least 4096 bytes.

      .OUTPUTS
      [pscustomobject] @{ truncated; dest_path; bytes_written }
    #>
    param(
        [string]$SourcePath,
        [string]$DestPathWhole,
        [string]$DestPathTruncated,
        [ValidateRange(4096, [long]::MaxValue)]
        [long]$MaxBytes
    )
    $srcStream = [System.IO.File]::Open($SourcePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $currentLength = $srcStream.Length

        if ($currentLength -le $MaxBytes) {
            # Round-5 review finding 2: nothing to drop -- copy verbatim,
            # no banner, no rename. (Streamed manually, not Copy-Item: this
            # function already owns an open, FileShare.ReadWrite handle on
            # a possibly-live file; reusing it avoids a second open/share
            # negotiation against the same live file.)
            $destStream = [System.IO.File]::Create($DestPathWhole)
            try {
                $bufferSize = [Math]::Min([int64]1MB, [Math]::Max([int64]1, $currentLength))
                $buffer = New-Object byte[] ([int]$bufferSize)
                while ($true) {
                    $read = $srcStream.Read($buffer, 0, $buffer.Length)
                    if ($read -le 0) { break }
                    $destStream.Write($buffer, 0, $read)
                }
            } finally { $destStream.Dispose() }
            return [pscustomobject]@{
                truncated = $false
                dest_path = $DestPathWhole
                bytes_written = (Get-Item -LiteralPath $DestPathWhole).Length
            }
        }

        $banner = "# sandbox-lab TRUNCATED: kept at most the LAST $([math]::Round($MaxBytes / 1MB, 0)) MB of this file (it was $([math]::Round($currentLength / 1MB, 1)) MB when listed for copy -- it may have grown further since); earlier content was dropped, not the whole file.`r`n"
        $bannerBytes = [System.Text.Encoding]::ASCII.GetBytes($banner)
        # Round-4 review finding 3: content budget computed BEFORE seeking,
        # and the seek position itself is derived from THIS (post-banner)
        # budget -- not from the raw -MaxBytes -- so the retained window
        # still reaches the source's true end, and the total file (banner
        # + content) never exceeds -MaxBytes. The -MaxBytes >= 4096 floor
        # (round-5 finding 4) guarantees $contentBudget is always
        # meaningfully positive here.
        $contentBudget = [Math]::Max(0, $MaxBytes - $bannerBytes.Length)
        $startPos = [Math]::Max(0, $currentLength - $contentBudget)
        $null = $srcStream.Seek($startPos, [System.IO.SeekOrigin]::Begin)
        $destStream = [System.IO.File]::Create($DestPathTruncated)
        try {
            $destStream.Write($bannerBytes, 0, $bannerBytes.Length)

            $bufferSize = [Math]::Min([int64]1MB, [Math]::Max([int64]1, $contentBudget))
            $buffer = New-Object byte[] ([int]$bufferSize)
            $remaining = $contentBudget
            while ($remaining -gt 0) {
                $toRead = [int]([Math]::Min($bufferSize, $remaining))
                $read = $srcStream.Read($buffer, 0, $toRead)
                if ($read -le 0) { break }
                $destStream.Write($buffer, 0, $read)
                $remaining -= $read
            }
        } finally { $destStream.Dispose() }
        return [pscustomobject]@{
            truncated = $true
            dest_path = $DestPathTruncated
            bytes_written = (Get-Item -LiteralPath $DestPathTruncated).Length
        }
    } finally { $srcStream.Dispose() }
}

function Get-GstDebugCaptureDecision {
    <#
      .SYNOPSIS
      Round-4 review finding 2: pure gating decision for WHETHER a given
      Copy-StationLogs invocation should even attempt a GST_DEBUG_FILE
      capture at all -- extracted so the gate itself is unit-testable
      without a live soak. Without this gate, gst-debug capture ran on
      EVERY checkpoint (every ~3 minutes, plus 'final') with no aggregate
      bound and no dedupe -- measured to project to roughly 8 GB shipped
      over a 2-hour soak (up to 200 MB per checkpoint x ~40 checkpoints).

      Round-5 review finding 1: a SINGLE shared aggregate cap let periodic
      checkpoints (#1, #10, #20, ...) consume the entire cap before
      'final' (or an early-failure label) ever ran -- starving the
      captures that matter most out of the run's own evidence budget.
      Fixed by splitting into TWO INDEPENDENT budgets, never one shared
      pool: periodic checkpoints draw ONLY against -PeriodicCapBytes
      (production default 400 MB); non-periodic labels ('final', an
      early-failure label) draw ONLY against -NonPeriodicCapBytes
      (production default 200 MB) -- a periodic checkpoint can never
      exhaust the reserve 'final' needs, and vice versa.

      Two independent controls, both applied:
        - PERIODIC checkpoints ("checkpoint-cycleN" labels) are only
          captured on the FIRST one seen (an early baseline, so a run
          that fails quickly still has SOMETHING) and every -EveryN'th
          one thereafter -- never every single one -- AND only while
          -PeriodicBytesSoFar is under -PeriodicCapBytes.
        - A NON-periodic label ('final', or an early-failure label like
          'onair-poll-timeout') is always ATTEMPTED, since these mark
          genuinely significant moments a human would want evidence for
          -- but only while -NonPeriodicBytesSoFar is under
          -NonPeriodicCapBytes, its OWN separate reserve.

      .PARAMETER IsPeriodicCheckpoint
      $true only for the recurring "checkpoint-cycleN" rollup label;
      $false for 'final', 'onair-poll-timeout', or any other one-off
      label.

      .PARAMETER PeriodicCheckpointIndex
      1-based count of periodic checkpoints seen so far, INCLUDING this
      one. Ignored when -IsPeriodicCheckpoint is $false. Round-5 review
      finding 5: the "is this the first one" check is now `-eq 1`, not
      `-le 1` -- an index of 0 or negative would indicate this function's
      own caller failed to increment its counter before calling, a real
      bug this function should surface as "not the first" (falling
      through to the every-Nth check) rather than silently treating as
      if it legitimately were checkpoint #1.

      .PARAMETER EveryN
      Capture every Nth periodic checkpoint (plus always the 1st).
      Production default: 10. Round-5 review finding 5: validated to be
      at least 1 -- `-EveryN 0` would divide by zero at the `% $EveryN`
      check below.

      .PARAMETER PeriodicBytesSoFar
      Running total of bytes actually written to gst-debug\ by PERIODIC
      captures so far this run. Ignored when -IsPeriodicCheckpoint is
      $false.

      .PARAMETER PeriodicCapBytes
      Hard per-run ceiling on periodic captures alone. Production
      default: 400 MB.

      .PARAMETER NonPeriodicBytesSoFar
      Running total of bytes actually written to gst-debug\ by
      NON-periodic captures ('final', early-failure labels) so far this
      run. Ignored when -IsPeriodicCheckpoint is $true.

      .PARAMETER NonPeriodicCapBytes
      Hard per-run ceiling on non-periodic captures alone -- a RESERVE
      that periodic captures can never touch. Production default: 200 MB.

      .OUTPUTS
      [pscustomobject] @{ should_capture; reason }
    #>
    param(
        [bool]$IsPeriodicCheckpoint,
        [int]$PeriodicCheckpointIndex,
        [ValidateRange(1, 100000)]
        [int]$EveryN,
        [long]$PeriodicBytesSoFar,
        [long]$PeriodicCapBytes,
        [long]$NonPeriodicBytesSoFar,
        [long]$NonPeriodicCapBytes
    )
    if (-not $IsPeriodicCheckpoint) {
        if ($NonPeriodicBytesSoFar -ge $NonPeriodicCapBytes) {
            return [pscustomobject]@{
                should_capture = $false
                reason = "non-periodic reserve exhausted ($NonPeriodicBytesSoFar >= $NonPeriodicCapBytes bytes already captured by 'final'/early-failure labels this run) -- further such captures skipped for the rest of this run"
            }
        }
        return [pscustomobject]@{
            should_capture = $true
            reason = 'non-periodic checkpoint (final, or an early-failure label) -- always attempted, subject to its OWN reserved cap (never shared with periodic checkpoints)'
        }
    }
    if ($PeriodicBytesSoFar -ge $PeriodicCapBytes) {
        return [pscustomobject]@{
            should_capture = $false
            reason = "periodic capture budget exhausted ($PeriodicBytesSoFar >= $PeriodicCapBytes bytes already captured by periodic checkpoints this run) -- further periodic captures skipped for the rest of this run (the non-periodic/'final' reserve is untouched by this)"
        }
    }
    if ($PeriodicCheckpointIndex -eq 1 -or ($PeriodicCheckpointIndex % $EveryN) -eq 0) {
        return [pscustomobject]@{
            should_capture = $true
            reason = "periodic checkpoint #$PeriodicCheckpointIndex (the first one, or a multiple of the every-$EveryN gate)"
        }
    }
    return [pscustomobject]@{
        should_capture = $false
        reason = "periodic checkpoint #$PeriodicCheckpointIndex is neither the first nor a multiple of the every-$EveryN gate -- skipped to bound total capture volume/count across the run"
    }
}
