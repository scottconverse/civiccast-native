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
      "<name>.tail200mb" filename for the same reason.

      .PARAMETER SourcePath
      The live GST_DEBUG_FILE (or a rotated/*.gstdebug sibling) to read
      from. May still be open for write by another process.

      .PARAMETER DestPath
      Where to write the (bannered, bounded) copy. Overwritten if it
      already exists.

      .PARAMETER MaxBytes
      The bound (200 MB in production). If the source is currently
      shorter than this, the whole source is copied (startPos clamps to
      0) -- this function is only ever called by a caller that already
      confirmed the source exceeds the bound, but it is safe standalone
      either way.
    #>
    param([string]$SourcePath, [string]$DestPath, [long]$MaxBytes)
    $srcStream = [System.IO.File]::Open($SourcePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $currentLength = $srcStream.Length
        $startPos = [Math]::Max(0, $currentLength - $MaxBytes)
        $null = $srcStream.Seek($startPos, [System.IO.SeekOrigin]::Begin)
        $destStream = [System.IO.File]::Create($DestPath)
        try {
            $banner = "# sandbox-lab TRUNCATED: kept at most the LAST $([math]::Round($MaxBytes / 1MB, 0)) MB of this file (it was $([math]::Round($currentLength / 1MB, 1)) MB when listed for copy -- it may have grown further since); earlier content was dropped, not the whole file.`r`n"
            $bannerBytes = [System.Text.Encoding]::ASCII.GetBytes($banner)
            $destStream.Write($bannerBytes, 0, $bannerBytes.Length)

            $bufferSize = [Math]::Min([int64]1MB, $MaxBytes)
            if ($bufferSize -le 0) { $bufferSize = 64KB }
            $buffer = New-Object byte[] ([int]$bufferSize)
            $remaining = $MaxBytes
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
