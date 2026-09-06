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
#     was written against; captured here anyway in case a future build
#     folds it into the same stream or a different code path emits an
#     equivalent stdout line -- this parser is a pure line-matcher and does
#     not care which file the caller actually reads it from). This regex
#     alone is NOT the production path for worker_stall_count -- see the
#     WORKER_RESULT rule directly below, which is.
#   - "WORKER_RESULT {'error': ('stall', 'output stalled'), ...}" (round-2
#     finding 1, HIGH: worker.py:576 (and :574 on the preroll-timeout exit
#     path) prints this line to STDOUT at
#     process exit on every path this parser's own callers have traced --
#     engine.py's own `run_forever`/`run` return value, echoed verbatim via
#     Python dict repr. NOT actually unconditional, though (round-follow-up-
#     B finding 2b, downgrading the earlier "always" claim -- see this
#     file's own header note further down for the os._exit(70) blind spot
#     this leaves and how worker_stall_stderr_count covers it). This is the
#     ACTUAL production signal for a stall when it DOES print:
#     Update-WorkerStdoutCounters (In-Sandbox-Soak.ps1) only ever opens
#     gst-worker.stdout.log, never gst-worker.stderr.log (strategy.py:879-880
#     routes the `^CTRL stall:` line above to the STDERR file specifically),
#     so the stderr-only regex above was structurally dead code against
#     THIS parser's stdout-only reads -- until Update-WorkerStderrCounters
#     (In-Sandbox-Soak.ps1, round-follow-up-B) started feeding this same
#     regex stderr lines via ConvertFrom-WorkerStderrLines below, closing
#     the os._exit(70) blind spot documented above: engine.py's stall
#     watchdog prints "CTRL stall: ..." to stderr BEFORE teardown even
#     starts, so it survives a hung-teardown exit that eats the STDOUT
#     WORKER_RESULT receipt. Anchored on the `'error': ('stall'`
#     sub-tuple specifically (not a bare "stall" substring): engine.py's
#     other `self._error = (...)` assignments use different tuple heads
#     (`"caption-gap"`, a raw string, or a GstMessage error object -- engine.py
#     lines 588/776/1057), so this never over-matches a different failure
#     reason. Residual, intentionally-accepted risk: if a future build ever
#     ALSO routes the `^CTRL stall:` line to stdout, a single real stall
#     would then match both this rule and the one above in the same read
#     and double-count -- not addressed here, since it isn't the checkout's
#     current behavior; re-check both rules together if that line's
#     destination ever changes.
#
# A real captured sample (soak-bcb3ebe-20260906-113951Z, government
# channel) contains lines this must NOT match -- "CTRL reload: new leg
# stream held at its first buffer (...)" (a distinct, non-terminal
# reload-progress line) -- exercised directly in Test-WorkerStdoutParser.ps1
# as a negative case, alongside synthetic WORKER_RESULT lines carrying a
# non-stall/no error to prove those are excluded too.

# Anchored on the line's own start (^) since these are single-purpose
# stdout lines with no surrounding log-line envelope (no timestamp/logger
# prefix the way the daemon's app log has) -- confirmed directly against
# the real captured sample above.
$script:WorkerReloadCommittedRegex = [regex]'^CTRL reload committed(?:\s*\(elements=(?<elements>\d+)\))?\s*$'
$script:WorkerReloadAbortedRegex = [regex]'^CTRL reload aborted:\s*(?<reason>.*)$'
$script:WorkerStallRegex = [regex]'^CTRL stall:\s*(?<detail>.*)$'
# Round-2 finding 1: the production-path stall signal -- see this file's
# own header comment above for why the stderr-only regex just above is not
# enough on its own. `.*?` (lazy) between WORKER_RESULT and the error tuple
# so this stays a simple substring test regardless of what else the dict
# repr carries either side of it (`swaps=`, `teardown_clean=`, key order).
$script:WorkerResultStallRegex = [regex]"^WORKER_RESULT\s.*?'error':\s*\('stall'"

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
        if ($script:WorkerResultStallRegex.IsMatch($line)) {
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

function ConvertFrom-WorkerStderrLines {
    <#
      .SYNOPSIS
      Round-follow-up-B finding 2b: the stderr-side counterpart to
      ConvertFrom-WorkerStdoutLines above. Pure line-matcher: given an
      array of already-split gst-worker.stderr.log lines, counts how many
      match $script:WorkerStallRegex ("^CTRL stall: ...", strategy.py:879-
      880's actual destination for that line). This is the ONLY thing this
      function looks for -- gst-worker.stderr.log carries no reload-
      committed/aborted lines of its own, so there is nothing else worth
      counting here.

      Exists because worker.py's own WORKER_RESULT stdout receipt (see
      $WorkerResultStallRegex's header comment above) is NOT written when
      engine.py's `stop(force_exit_on_hang=True)` teardown backstop itself
      hangs -- `os._exit(70)` fires before `print(f"WORKER_RESULT
      {result}")` ever runs. The stderr stall line, by contrast, is printed
      by the stall watchdog BEFORE teardown is even attempted, so it is
      present for every real stall regardless of how teardown then goes.
      Called by Update-WorkerStderrCounters (In-Sandbox-Soak.ps1) using the
      SAME incremental-byte-offset, rotation-safe read pattern as
      Update-WorkerStdoutCounters, against gst-worker.stderr.log instead of
      gst-worker.stdout.log.

      .OUTPUTS
      [pscustomobject] @{ worker_stall_stderr_count = int }
    #>
    param([string[]]$Lines = @())

    $workerStallStderrCount = 0
    foreach ($line in @($Lines)) {
        if ([string]::IsNullOrEmpty($line)) { continue }
        if ($script:WorkerStallRegex.IsMatch($line)) {
            $workerStallStderrCount++
        }
    }

    return [pscustomobject]@{
        worker_stall_stderr_count = $workerStallStderrCount
    }
}
