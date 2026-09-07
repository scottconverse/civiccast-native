# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# GstDebugTail.ps1 -- dot-sourceable Copy-GstDebugTail (sandbox-lab lane
# follow-up D, item 2's GST_DEBUG_FILE capture), extracted the same way
# ServiceStartFailureCheck.ps1/CaptionsOffCheck.ps1/WorkerStdoutParser.ps1/
# CpuSampler.ps1/WorkerEnv.ps1 already were, so it is unit-testable
# (Test-GstDebugTail.ps1) against real temp files/streams instead of only
# ever being exercised inside a live sandbox soak.

function Get-ByteSizeLabel {
    <#
      .SYNOPSIS
      Round-6 review finding 4: a compact, filename-safe byte-count label
      -- "200MB" for anything >= 1 MB, "512KB" below that. An earlier
      version always rendered MB with zero decimal places
      ([math]::Round($x/1MB,0)), which silently produced "0MB" (and a
      ".tail0mb" filename, and a banner claiming "the LAST 0 MB") for any
      residual per-run-cap budget under 512 KB -- a real, reachable case
      once the per-run/per-checkpoint caps can hand this function a small
      residual near the end of a run. Bytes below 1 KB still round to
      "0KB" (there is no lower unit to fall back to), but that floor is
      never actually reached in production: Copy-GstDebugTail's own
      -MaxBytes floor (round-5 review finding 4) already refuses anything
      under 4096 bytes, and every caller that derives a residual budget
      skips the capture outright once that residual drops below the same
      4096-byte floor -- so in practice this function only ever needs to
      render 4 KB and up.

      .OUTPUTS
      [string] -- e.g. "200MB", "512KB". No space (filename-safe).
    #>
    param([long]$Bytes)
    if ($Bytes -ge 1MB) { return "$([math]::Round($Bytes / 1MB, 0))MB" }
    return "$([math]::Round($Bytes / 1KB, 0))KB"
}

function Get-GstDebugEffectiveMaxBytes {
    <#
      .SYNOPSIS
      Round-6 review finding 6: pure three-way minimum, extracted so the
      per-checkpoint cap's interaction with the run-wide periodic/
      non-periodic budgets is unit-testable without a live soak. A single
      checkpoint can have MULTIPLE candidate files (the primary
      GST_DEBUG_FILE plus rotated/*.gstdebug siblings) -- without a bound
      on THIS CHECKPOINT's own total, one checkpoint with several large
      candidates could drain an entire run-wide budget (periodic or
      non-periodic) by itself. The effective bound for any single copy is
      the SMALLEST of: the normal per-file bound (200 MB in production),
      what remains of the relevant run-wide budget (periodic or
      non-periodic, whichever this checkpoint's label is), and what
      remains of this ONE checkpoint's own per-checkpoint cap.

      .PARAMETER NormalMaxBytes
      The ordinary per-file bound (200 MB in production).

      .PARAMETER KindBytesSoFar
      Bytes already captured this RUN by whichever kind (periodic or
      non-periodic) this checkpoint's label is.

      .PARAMETER KindCapBytes
      That kind's own run-wide cap (400 MB periodic / 200 MB non-periodic
      in production).

      .PARAMETER PerCheckpointBytesSoFar
      Bytes already captured by THIS ONE checkpoint (reset to 0 at the
      start of every Copy-StationLogs invocation -- never persists across
      checkpoints).

      .PARAMETER PerCheckpointCapBytes
      This checkpoint's own cap (200 MB in production).

      .OUTPUTS
      [long] -- may be zero or negative if a budget is already exhausted;
      callers are expected to check the result against a meaningful floor
      (Copy-GstDebugTail's own 4096-byte -MaxBytes minimum) before ever
      passing it through as an actual -MaxBytes value.
    #>
    param(
        [long]$NormalMaxBytes,
        [long]$KindBytesSoFar,
        [long]$KindCapBytes,
        [long]$PerCheckpointBytesSoFar,
        [long]$PerCheckpointCapBytes
    )
    $kindRemaining = $KindCapBytes - $KindBytesSoFar
    $checkpointRemaining = $PerCheckpointCapBytes - $PerCheckpointBytesSoFar
    return [Math]::Min($NormalMaxBytes, [Math]::Min($kindRemaining, $checkpointRemaining))
}

function Copy-GstDebugTail {
    <#
      .SYNOPSIS
      Copy a GST_DEBUG_FILE (or a rotated/*.gstdebug sibling) into the
      evidence tree, truncating to at most -MaxBytes ONLY when the source
      actually exceeds it -- an untouched file is copied verbatim, with no
      banner and no ".tailNNN" rename (round-5 review finding 2: an
      earlier version always wrote a TRUNCATED banner and a rename even
      when nothing was dropped, which is actively misleading for the
      common case where GST_DEBUG never grew past the bound at all).

      Round-6 review finding 1 (HIGH): the "whole copy" path -- taken
      whenever the source's length AT OPEN TIME was already <= -MaxBytes
      -- used to read straight to EOF with NO bound of its own, on the
      theory that "it was already under the bound, so it can't need
      truncating". That theory is false for a file still being actively
      written: the source can keep GROWING for the entire duration of
      this copy (this is, after all, the whole reason Copy-GstDebugTail
      exists), so a file that was 100 MB when opened but grows to
      1119 MB while a 120 MB bound copy is running got ALL 1119 MB copied
      -- MEASURED directly. Fixed by giving this path the SAME counted
      read loop the already-truncated path has always had, bounded to
      -MaxBytes: if real EOF is reached before the bound, this genuinely
      was untruncated (the common, cheap case -- no banner, no rename, as
      above). If the bound is hit WITHOUT reaching EOF (confirmed via one
      extra 1-byte probe read past the bound, so an exact source length of
      precisely -MaxBytes is never mistaken for "still growing"), the
      source grew past the bound mid-copy -- the tentative whole-file
      output (already written, unbannered) is discarded, and a TRUNCATED
      result is built instead: a banner (honestly describing this as the
      FIRST -MaxBytes-worth of the file, not the last -- this path never
      had the chance to seek to a true tail, since it did not know
      truncation would be needed until the copy was already under way)
      plus that same already-read content, trimmed to fit the banner's own
      length. This keeps the promise that -MaxBytes really is a hard
      ceiling on what this function ever writes, and lets a caller's
      budget accounting (In-Sandbox-Soak.ps1's own periodic/non-periodic
      caps) stay true regardless of which path is taken.

      Round-3 review findings 1-2 (still in force): opens with
      FileShare.ReadWrite, not FileShare.Read ([System.IO.File]::OpenRead's
      default) -- a live GST_DEBUG_FILE has no read-sharing on the
      WRITER's side, so FileShare.Read alone throws "being used by another
      process" (measured directly against a file held open for write by a
      separate process; Copy-Item on the identical file succeeds, because
      it goes through a different Win32 CopyFile path that tolerates this
      share mode). When truncation IS needed via the "already over the
      bound at open time" path, the bound is enforced on the READ LOOP
      itself -- exactly -MaxBytes bytes are read and written, counted down
      per chunk, regardless of how large the source grows during the copy.

      Round-4 review finding 3 (still in force): when truncating via that
      same "already over the bound at open time" path, the OUTPUT FILE
      (banner + content), not just the content, is bounded to AT MOST
      -MaxBytes total. The banner's length is computed FIRST and
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
      Where to write an UNTRUNCATED copy (source never exceeded -MaxBytes
      for the whole duration of this copy) -- a plain, verbatim copy, no
      banner, no rename. Also used as a TEMPORARY scratch file when the
      source turns out to grow past the bound mid-copy (round-6 finding
      1) -- deleted once the truncated conversion below completes.

      .PARAMETER DestPathTruncated
      Where to write a TRUNCATED copy -- either because the source already
      exceeded -MaxBytes when this function opened it, or because it grew
      past -MaxBytes while this copy was running. Only one of
      -DestPathWhole/-DestPathTruncated is ever left behind when this
      function returns; which one is reported back in the returned
      object's .dest_path.

      .PARAMETER MaxBytes
      The bound (200 MB in production, or a smaller per-run-cap-derived
      residual -- see In-Sandbox-Soak.ps1) on the TOTAL output file
      (banner + content, whichever path is taken). Must be at least 4096
      bytes.

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

        if ($currentLength -gt $MaxBytes) {
            # Already over the bound at open time -- the ORIGINAL
            # truncated path (round-3/round-4/round-5 fixes, all still in
            # force). Seek straight to the correct tail-start position and
            # stream a bounded, bannered copy.
            $banner = "# sandbox-lab TRUNCATED: kept at most the LAST $(Get-ByteSizeLabel -Bytes $MaxBytes) of this file (it was $(Get-ByteSizeLabel -Bytes $currentLength) when listed for copy -- it may have grown further since); earlier content was dropped, not the whole file.`r`n"
            $bannerBytes = [System.Text.Encoding]::ASCII.GetBytes($banner)
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
        }

        # Round-6 review finding 1: TENTATIVELY under the bound at open
        # time -- but this copy can take a while, and the source may keep
        # growing for its entire duration. Stream with a COUNTED loop
        # bounded to -MaxBytes (never "read to EOF, however far away that
        # turns out to be"), then decide which outcome actually happened.
        $destStream = [System.IO.File]::Create($DestPathWhole)
        $totalWritten = [int64]0
        $hitBoundWithoutEof = $false
        try {
            $bufferSize = [Math]::Min([int64]1MB, [Math]::Max([int64]1, $MaxBytes))
            $buffer = New-Object byte[] ([int]$bufferSize)
            $remaining = $MaxBytes
            # Round-6 review finding 1's own regression test exposed a
            # second, subtler half of this same bug: a plain
            # zero-bytes-read-means-EOF loop gives up the INSTANT it
            # catches up to whatever the writer has produced SO FAR, even
            # though the writer is still actively appending -- for a local
            # file, Read() returning 0 is not "closed"/"error", it is
            # simply "nothing past the current position RIGHT NOW", and a
            # live GStreamer worker's own write cadence (buffered flushes,
            # not a continuous byte stream) means this reader can easily
            # win that race and wrongly conclude "done" while there is
            # more still coming. A short, BOUNDED grace window on a
            # zero-byte read (wall-clock deadline, not a fixed retry
            # count -- more forgiving of a loaded/slow box, where a fixed
            # small number of fixed-length sleeps could still run out
            # before a genuinely-still-writing source produces its next
            # chunk) gives a still-writing source a fair chance to catch
            # up before this loop commits to "that was a genuine end of
            # file". Bounded to 500 ms per gap (reset the instant real
            # data resumes) -- trivial next to this function's real
            # calling cadence (a checkpoint every ~3 minutes), so this can
            # never turn into the kind of unbounded wait the -MaxBytes cap
            # itself exists to prevent.
            $zeroReadGraceDeadline = $null
            $zeroReadGraceMs = 500
            while ($remaining -gt 0) {
                $toRead = [int]([Math]::Min($bufferSize, $remaining))
                $read = $srcStream.Read($buffer, 0, $toRead)
                if ($read -le 0) {
                    if (-not $zeroReadGraceDeadline) { $zeroReadGraceDeadline = (Get-Date).AddMilliseconds($zeroReadGraceMs) }
                    if ((Get-Date) -ge $zeroReadGraceDeadline) { break }
                    Start-Sleep -Milliseconds 20
                    continue
                }
                $zeroReadGraceDeadline = $null
                $destStream.Write($buffer, 0, $read)
                $totalWritten += $read
                $remaining -= $read
            }
            if ($remaining -le 0) {
                # Wrote exactly -MaxBytes bytes without the read loop ever
                # seeing a natural end-of-file. This is ambiguous on its
                # own -- the source could be EXACTLY -MaxBytes bytes long
                # (genuinely whole, coincidentally landing right on the
                # bound) -- so resolve it with one more real read: if
                # there is truly nothing left, this 1-byte probe returns 0
                # (untruncated after all); if it returns data, the source
                # has already grown past what this loop just wrote (or was
                # always longer and this loop simply hadn't reached the
                # end yet), and this copy must be treated as truncated.
                $probe = New-Object byte[] 1
                if ($srcStream.Read($probe, 0, 1) -gt 0) { $hitBoundWithoutEof = $true }
            }
        } finally { $destStream.Dispose() }

        if (-not $hitBoundWithoutEof) {
            return [pscustomobject]@{
                truncated = $false
                dest_path = $DestPathWhole
                bytes_written = $totalWritten
            }
        }

        # The source grew past -MaxBytes while this copy was running.
        # Convert the tentative whole-file scratch copy into a truncated
        # result: a banner (honestly describing this as the FIRST
        # -MaxBytes-worth, not the last -- there was no way to know in
        # advance that a tail-seek would be needed) plus that already-read
        # content, trimmed to fit within -MaxBytes alongside the banner.
        $banner = "# sandbox-lab TRUNCATED: kept the FIRST $(Get-ByteSizeLabel -Bytes $MaxBytes) of this file (it exceeded that bound WHILE this copy was running -- it was under $(Get-ByteSizeLabel -Bytes $MaxBytes) when this copy started, so this is a from-the-start capture, not the file's tail); later content was dropped.`r`n"
        $bannerBytes = [System.Text.Encoding]::ASCII.GetBytes($banner)
        $contentBudget = [Math]::Max(0, $MaxBytes - $bannerBytes.Length)
        $truncStream = [System.IO.File]::Create($DestPathTruncated)
        try {
            $truncStream.Write($bannerBytes, 0, $bannerBytes.Length)
            $wholeReadStream = [System.IO.File]::OpenRead($DestPathWhole)
            try {
                $bufferSize2 = [Math]::Min([int64]1MB, [Math]::Max([int64]1, $contentBudget))
                $buffer2 = New-Object byte[] ([int]$bufferSize2)
                $remaining2 = $contentBudget
                while ($remaining2 -gt 0) {
                    $toRead2 = [int]([Math]::Min($bufferSize2, $remaining2))
                    $read2 = $wholeReadStream.Read($buffer2, 0, $toRead2)
                    if ($read2 -le 0) { break }
                    $truncStream.Write($buffer2, 0, $read2)
                    $remaining2 -= $read2
                }
            } finally { $wholeReadStream.Dispose() }
        } finally { $truncStream.Dispose() }
        Remove-Item -LiteralPath $DestPathWhole -Force -ErrorAction SilentlyContinue
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

      Round-6 review finding 6: In-Sandbox-Soak.ps1 additionally caps a
      SINGLE checkpoint's own total capture (across every candidate file
      that checkpoint copies -- the primary GST_DEBUG_FILE plus any
      rotated/*.gstdebug siblings) at 200 MB, independent of this
      function -- so one checkpoint with several large candidates can
      never drain the WHOLE 400 MB periodic budget by itself. See
      In-Sandbox-Soak.ps1's own gst-debug capture loop for that check;
      this function only ever reasons about the RUN-WIDE periodic/
      non-periodic totals, not any single checkpoint's own share of them.

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
