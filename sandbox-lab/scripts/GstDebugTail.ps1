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
      Round-3 review findings 1-2: stream-copy at most the LAST -MaxBytes
      bytes of a file that may (a) still be open for write by a live
      GStreamer worker and (b) still be growing while this copy runs.

      (1) Opens with FileShare.ReadWrite, not FileShare.Read
      ([System.IO.File]::OpenRead's default) -- a live GST_DEBUG_FILE has
      no read-sharing on the WRITER's side, so FileShare.Read alone
      throws "being used by another process" (measured directly against
      a file held open for write by a separate process; Copy-Item on the
      identical file succeeds, because it goes through a different Win32
      CopyFile path that tolerates this share mode).

      (2) The 200 MB bound is enforced on the READ LOOP itself -- exactly
      -MaxBytes bytes are read and written, counted down per chunk,
      regardless of how large the source grows during the copy. The
      previous version snapshotted Length once and let CopyTo run to
      whatever EOF happened to be by the time it got there, so a file
      that kept growing during the copy (the expected, live case for
      GST_DEBUG_FILE) could end up with MORE than 200 MB kept.

      A one-line ASCII banner is written first (round-3 finding 3) so a
      reader of the file's own bytes -- not just this checkpoint's note
      file -- knows content was dropped; the caller (In-Sandbox-Soak.ps1's
      Copy-StationLogs) additionally writes the destination under a
      "<name>.tailNNNmb" filename for the same reason.

      Round-4 review finding 3: the OUTPUT FILE (banner + content), not
      just the content, is bounded to AT MOST -MaxBytes total -- the
      previous version wrote a full -MaxBytes of content IN ADDITION to
      the banner, so the file on disk ended up banner-length bytes OVER
      the stated bound (measured: 186 bytes over for a ~186-byte banner).
      The banner's length is computed FIRST and subtracted from the
      content budget before the read position is even chosen, so the
      retained content still ends at the source's true (as of copy time)
      end-of-file -- it does not additionally give up its own last
      banner-length bytes to make room; the seek start position itself
      moves forward by exactly the banner's length instead.

      .PARAMETER SourcePath
      The live GST_DEBUG_FILE (or a rotated/*.gstdebug sibling) to read
      from. May still be open for write by another process.

      .PARAMETER DestPath
      Where to write the (bannered, bounded) copy. Overwritten if it
      already exists.

      .PARAMETER MaxBytes
      The bound (200 MB in production) on the TOTAL output file
      (banner + content). If the source is currently shorter than the
      content budget this leaves, the whole source is copied (startPos
      clamps to 0) -- this function is only ever called by a caller that
      already confirmed the source exceeds the bound, but it is safe
      standalone either way.
    #>
    param([string]$SourcePath, [string]$DestPath, [long]$MaxBytes)
    $srcStream = [System.IO.File]::Open($SourcePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $currentLength = $srcStream.Length
        $banner = "# sandbox-lab TRUNCATED: kept at most the LAST $([math]::Round($MaxBytes / 1MB, 0)) MB of this file (it was $([math]::Round($currentLength / 1MB, 1)) MB when listed for copy -- it may have grown further since); earlier content was dropped, not the whole file.`r`n"
        $bannerBytes = [System.Text.Encoding]::ASCII.GetBytes($banner)
        # Round-4 review finding 3: content budget computed BEFORE seeking,
        # and the seek position itself is derived from THIS (post-banner)
        # budget -- not from the raw -MaxBytes -- so the retained window
        # still reaches the source's true end, and the total file (banner
        # + content) never exceeds -MaxBytes.
        $contentBudget = [Math]::Max(0, $MaxBytes - $bannerBytes.Length)
        $startPos = [Math]::Max(0, $currentLength - $contentBudget)
        $null = $srcStream.Seek($startPos, [System.IO.SeekOrigin]::Begin)
        $destStream = [System.IO.File]::Create($DestPath)
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

      Two independent controls, both applied:
        - PERIODIC checkpoints ("checkpoint-cycleN" labels) are only
          captured on the FIRST one seen (an early baseline, so a run
          that fails quickly still has SOMETHING) and every -EveryN'th
          one thereafter -- never every single one.
        - A NON-periodic label ('final', or an early-failure label like
          'onair-poll-timeout') is always ATTEMPTED, since these mark
          genuinely significant moments a human would want evidence for
          -- but still subject to the SAME aggregate cap as everything
          else, below.
        - Regardless of the above, once the running total of bytes
          already captured THIS RUN reaches -AggregateCapBytes, every
          further capture (periodic or not, including 'final') is
          skipped -- the cap is a hard ceiling on total disk/shipped
          volume for the whole run, not just a per-checkpoint throttle.

      .PARAMETER IsPeriodicCheckpoint
      $true only for the recurring "checkpoint-cycleN" rollup label;
      $false for 'final', 'onair-poll-timeout', or any other one-off
      label.

      .PARAMETER PeriodicCheckpointIndex
      1-based count of periodic checkpoints seen so far, INCLUDING this
      one. Ignored when -IsPeriodicCheckpoint is $false.

      .PARAMETER EveryN
      Capture every Nth periodic checkpoint (plus always the 1st).
      Production default: 10.

      .PARAMETER AggregateBytesSoFar
      Running total of bytes actually written to gst-debug\ so far this
      run (across every previous capture, truncated or not).

      .PARAMETER AggregateCapBytes
      Hard per-run ceiling. Production default: 600 MB.

      .OUTPUTS
      [pscustomobject] @{ should_capture; reason }
    #>
    param(
        [bool]$IsPeriodicCheckpoint,
        [int]$PeriodicCheckpointIndex,
        [int]$EveryN,
        [long]$AggregateBytesSoFar,
        [long]$AggregateCapBytes
    )
    if ($AggregateBytesSoFar -ge $AggregateCapBytes) {
        return [pscustomobject]@{
            should_capture = $false
            reason = "aggregate cap reached ($AggregateBytesSoFar >= $AggregateCapBytes bytes already captured this run) -- further GST_DEBUG_FILE captures skipped for the rest of this run"
        }
    }
    if (-not $IsPeriodicCheckpoint) {
        return [pscustomobject]@{
            should_capture = $true
            reason = 'non-periodic checkpoint (final, or an early-failure label) -- always attempted, subject to the aggregate cap'
        }
    }
    if ($PeriodicCheckpointIndex -le 1 -or ($PeriodicCheckpointIndex % $EveryN) -eq 0) {
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
