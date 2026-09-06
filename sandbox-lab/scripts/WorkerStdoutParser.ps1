# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# WorkerStdoutParser.ps1 -- dot-sourceable parsing of the per-channel
# GStreamer worker's own stdout log
# (<egress_work_dir>\<channel>\logs\gst-worker.stdout.log), extracted into
# its own file (matching SoakVerdict.ps1/RestartClassifier.ps1/
# HostLiveness.ps1's own pattern) so the line-matching logic is
# unit-testable (Test-WorkerStdoutParser.ps1) with verbatim captured lines,
# with no live sandbox, station, or worker process required.
#
# Lines this looks for (civiccast/egress/gst/engine.py, main bcb3ebe --
# re-verify against HEAD before trusting these citations blindly):
#   - "CTRL reload committed (elements=<N>)"                 (engine.py:1829,
#     plain `print(...)`, i.e. stdout)
#   - "CTRL reload aborted: <reason>"                        (engine.py:1038
#     and :1847, both plain `print(...)`, i.e. stdout)
#   - "CTRL stall: no output for <N>s - quitting for daemon restart"
#     (engine.py:1125 -- printed to STDERR, not stdout, in the checkout this
#     was written against; captured here anyway on the coordinator's
#     explicit instruction to parse gst-worker.stdout.log for it, in case a
#     future build folds it into the same stream or a different code path
#     emits an equivalent stdout line -- this parser is a pure line-matcher
#     and does not care which file the caller actually reads it from).
#
# A real captured sample (soak-bcb3ebe-20260906-113951Z, government
# channel) contains lines this must NOT match -- "CTRL reload: new leg
# stream held at its first buffer (...)" (a distinct, non-terminal
# reload-progress line) and "WORKER_RESULT {...}" (the worker's own
# structured exit summary) -- both exercised directly in
# Test-WorkerStdoutParser.ps1 as negative cases.

# Anchored on the line's own start (^) since these are single-purpose
# stdout lines with no surrounding log-line envelope (no timestamp/logger
# prefix the way the daemon's app log has) -- confirmed directly against
# the real captured sample above.
$script:WorkerReloadCommittedRegex = [regex]'^CTRL reload committed(?:\s*\(elements=(?<elements>\d+)\))?\s*$'
$script:WorkerReloadAbortedRegex = [regex]'^CTRL reload aborted:\s*(?<reason>.*)$'
$script:WorkerStallRegex = [regex]'^CTRL stall:\s*(?<detail>.*)$'

function ConvertFrom-WorkerStdoutLines {
    <#
      .SYNOPSIS
      Pure line-matcher: given an array of already-split text lines (no
      trailing newlines), returns the counts/reasons this soak lane records
      per channel. Never touches a file itself -- the incremental
      byte-offset read (rotation-safe, matching Update-DaemonLogRing's own
      pattern) lives in In-Sandbox-Soak.ps1's Update-WorkerStdoutCounters,
      which calls this function once per read with only the newly-appended
      lines.

      .OUTPUTS
      [pscustomobject] @{
        reload_committed_count = int
        reload_aborted_count   = int
        reload_aborted_reasons = string[]   (one entry per aborted line, in order)
        worker_stall_count     = int
      }
    #>
    param([string[]]$Lines = @())

    $reloadCommittedCount = 0
    $reloadAbortedCount = 0
    $reloadAbortedReasons = @()
    $workerStallCount = 0

    foreach ($line in @($Lines)) {
        if ([string]::IsNullOrEmpty($line)) { continue }
        if ($script:WorkerReloadCommittedRegex.IsMatch($line)) {
            $reloadCommittedCount++
            continue
        }
        $abortMatch = $script:WorkerReloadAbortedRegex.Match($line)
        if ($abortMatch.Success) {
            $reloadAbortedCount++
            $reloadAbortedReasons += $abortMatch.Groups['reason'].Value
            continue
        }
        if ($script:WorkerStallRegex.IsMatch($line)) {
            $workerStallCount++
            continue
        }
    }

    return [pscustomobject]@{
        reload_committed_count = $reloadCommittedCount
        reload_aborted_count   = $reloadAbortedCount
        reload_aborted_reasons = @($reloadAbortedReasons)
        worker_stall_count     = $workerStallCount
    }
}
