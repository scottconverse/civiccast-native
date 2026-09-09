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

      Round-7 review finding 4: rounding is explicitly
      [MidpointRounding]::AwayFromZero (never .NET's own default,
      ToEven/"banker's rounding", which would round some exact .5 KB/MB
      boundaries DOWN instead of up) -- pinned by
      Test-GstDebugTail.ps1's own byte-size-label table, including the
      1048575-byte (1 MB minus 1 byte) boundary case.

      .OUTPUTS
      [string] -- e.g. "200MB", "512KB". No space (filename-safe).
    #>
    param([long]$Bytes)
    if ($Bytes -ge 1MB) { return "$([Math]::Round($Bytes / 1MB, 0, [MidpointRounding]::AwayFromZero))MB" }
    return "$([Math]::Round($Bytes / 1KB, 0, [MidpointRounding]::AwayFromZero))KB"
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

      Round-7 review finding 1 (HIGH) REPLACED round-6's own fix for the
      "source still growing during this copy" problem, which added a
      counted read loop PLUS a 500 ms wall-clock grace window on every
      zero-byte read (to tolerate a live writer's own buffered-flush
      cadence). That grace window RESET on every successful read, so a
      source trickling in at even 1 byte per 200 ms could keep a single
      Copy-GstDebugTail call open indefinitely -- and because
      Copy-StationLogs (and therefore this function) runs SYNCHRONOUSLY
      inside In-Sandbox-Soak.ps1's own poll loop, a copy that never
      returns starves the host's 6-minute rollup-stall bound into firing
      a FALSE STALL on an otherwise healthy run.

      THE FIX: no more grace window, no more "wait and see if more data
      shows up" at all. This function now takes a single, one-time
      SNAPSHOT of the source's length the moment it opens the file
      (`$srcStream.Length`, read exactly once) and commits to that
      snapshot for the whole call: it copies exactly
      `min(snapshot length, -MaxBytes)` bytes, starting at
      `max(0, snapshot length - MaxBytes)`, and nothing written to the
      source AFTER that snapshot is captured by this call at all --
      stated here plainly, since it is the contract every caller and
      every test now relies on. A source that keeps growing after the
      snapshot cannot make this function copy any more than -MaxBytes,
      and cannot make it run any longer than reading that fixed, known
      amount takes -- there is no more open-ended "is there more coming"
      question for this function to answer at all. The NEXT checkpoint
      (a fresh call, a fresh snapshot) picks up whatever grew in the
      meantime, exactly the same way every OTHER piece of evidence this
      lane captures is a point-in-time snapshot, not a live tail.

      A SEPARATE, purely defensive -WholeCopyDeadlineSeconds bounds the
      read loop's own wall-clock duration (default 30 s -- generous for
      even a 200 MB read against a healthy local disk, trivial next to
      the 6-minute rollup-stall bound this exists to protect): if the
      loop has not finished copying the snapshot-determined amount by
      that deadline (a slow/contended disk, not a growing source -- the
      snapshot already fixed how much there is to read), it stops where
      it is and the result is marked BOTH .truncated and .partial, with
      the destination renamed to "<name>.partial" so an incomplete
      capture is never mistaken for a complete one at its otherwise-
      legitimate filename (round-7 finding 7's own "never leave an
      unbannered partial at the legitimate name" principle, applied here
      too). This deadline is a safety net for a genuinely slow disk, not
      a mechanism this lane's own tests need to routinely exercise -- the
      snapshot rule alone is what makes an ordinary copy (of either kind)
      finish in the time a plain sequential read of a bounded, already-
      known amount of data actually takes: a static/no-growth copy costs
      0 ms of extra waiting (round-7 finding 2), never the 500 ms this
      function's OWN round-6 iteration used to spend even when nothing
      was wrong at all.

      Round-3 review findings 1-2 (still in force): opens with
      FileShare.ReadWrite, not FileShare.Read ([System.IO.File]::OpenRead's
      default) -- a live GST_DEBUG_FILE has no read-sharing on the
      WRITER's side, so FileShare.Read alone throws "being used by another
      process" (measured directly against a file held open for write by a
      separate process; Copy-Item on the identical file succeeds, because
      it goes through a different Win32 CopyFile path that tolerates this
      share mode).

      Round-4 review finding 3 (still in force): when truncating, the
      OUTPUT FILE (banner + content), not just the content, is bounded to
      AT MOST -MaxBytes total. The banner's length is computed FIRST and
      subtracted from the content budget before the read position is even
      chosen, so the retained content still ends at the snapshot's own
      true end-of-file.

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
      Where to write an UNTRUNCATED copy (the snapshot length was already
      <= -MaxBytes) -- a plain, verbatim copy, no banner, no rename
      (unless the wall-clock deadline fires mid-copy, in which case it is
      renamed to "<DestPathWhole>.partial" instead).

      .PARAMETER DestPathTruncated
      Where to write a TRUNCATED copy (the snapshot length exceeded
      -MaxBytes). Only one of -DestPathWhole/-DestPathTruncated is ever
      left behind when this function returns; which one (or its
      ".partial"-suffixed form) is reported back in the returned object's
      .dest_path.

      .PARAMETER MaxBytes
      The bound (200 MB in production, or a smaller per-run-cap-derived
      residual -- see In-Sandbox-Soak.ps1) on the TOTAL output file
      (banner + content, when truncated). Must be at least 4096 bytes.

      .PARAMETER WholeCopyDeadlineSeconds
      Wall-clock ceiling on the read loop itself, default 30. Purely
      defensive (a slow/contended disk) -- the snapshot rule already
      bounds how much there is to read; this bounds how long reading it
      is allowed to take.

      .OUTPUTS
      [pscustomobject] @{ truncated; partial; dest_path; bytes_written }
    #>
    param(
        [string]$SourcePath,
        [string]$DestPathWhole,
        [string]$DestPathTruncated,
        [ValidateRange(4096, [long]::MaxValue)]
        [long]$MaxBytes,
        [int]$WholeCopyDeadlineSeconds = 30
    )
    $srcStream = [System.IO.File]::Open($SourcePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        # Round-7 review finding 1: ONE-TIME SNAPSHOT. Never re-queried.
        # Anything the source gains after this line is simply not part of
        # this call's world -- see this function's own header for why that
        # is the deliberate contract, not an oversight.
        $snapshotLength = $srcStream.Length
        $truncated = ($snapshotLength -gt $MaxBytes)

        if ($truncated) {
            $banner = "# sandbox-lab TRUNCATED: kept at most the LAST $(Get-ByteSizeLabel -Bytes $MaxBytes) of this file (it was $(Get-ByteSizeLabel -Bytes $snapshotLength) at the moment this copy started; anything written after that snapshot was not captured -- see the next checkpoint for that).`r`n"
            $bannerBytes = [System.Text.Encoding]::ASCII.GetBytes($banner)
            $contentBudget = [Math]::Max(0, $MaxBytes - $bannerBytes.Length)
            $startPos = [Math]::Max(0, $snapshotLength - $contentBudget)
            $destPath = $DestPathTruncated
        } else {
            $bannerBytes = [byte[]]@()
            $contentBudget = $snapshotLength
            $startPos = 0
            $destPath = $DestPathWhole
        }
        $null = $srcStream.Seek($startPos, [System.IO.SeekOrigin]::Begin)

        $destStream = [System.IO.File]::Create($destPath)
        $partial = $false
        try {
            if ($truncated) { $destStream.Write($bannerBytes, 0, $bannerBytes.Length) }
            $bufferSize = [Math]::Min([int64]1MB, [Math]::Max([int64]1, $contentBudget))
            $buffer = New-Object byte[] ([int]$bufferSize)
            $remaining = $contentBudget
            # Round-7 finding 1's purely defensive wall-clock ceiling --
            # see this function's own header. Not a growth-detection
            # mechanism (the snapshot already settled that question); only
            # a genuinely slow/contended disk should ever trip this.
            $deadline = (Get-Date).AddSeconds($WholeCopyDeadlineSeconds)
            while ($remaining -gt 0) {
                if ((Get-Date) -ge $deadline) { $partial = $true; break }
                $toRead = [int]([Math]::Min($bufferSize, $remaining))
                $read = $srcStream.Read($buffer, 0, $toRead)
                if ($read -le 0) { break }
                $destStream.Write($buffer, 0, $read)
                $remaining -= $read
            }
        } finally { $destStream.Dispose() }

        $finalPath = $destPath
        if ($partial) {
            # Round-7 finding 7's principle applied here too: an
            # incomplete capture must never sit at the same filename a
            # complete one would use. Best-effort rename; if it fails for
            # some reason, the file stays at its original (still
            # accurate-to-what-was-written, just unrenamed) path and
            # .partial in the returned object still tells the caller the
            # truth.
            $partialPath = "$destPath.partial"
            try {
                Move-Item -LiteralPath $destPath -Destination $partialPath -Force -ErrorAction Stop
                $finalPath = $partialPath
            } catch {
                # Left at $destPath -- .partial=$true in the result is
                # still authoritative regardless of whether the rename
                # itself succeeded.
            }
        }
        return [pscustomobject]@{
            truncated = ($truncated -or $partial)
            partial = $partial
            dest_path = $finalPath
            bytes_written = (Get-Item -LiteralPath $finalPath).Length
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
