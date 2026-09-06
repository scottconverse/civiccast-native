# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Test-WorkerStdoutParser.ps1 -- pytest-free PowerShell unit checks for
# ConvertFrom-WorkerStdoutLines (WorkerStdoutParser.ps1), fed verbatim
# lines captured from a real soak run's gst-worker.stdout.log
# (soak-bcb3ebe-20260906-113951Z, government channel) plus synthetic lines
# for the two patterns that sample happened not to contain. No sandbox, no
# live worker process, no filesystem incremental-read required (that part,
# Update-WorkerStdoutCounters, is a thin file-I/O wrapper around this pure
# function -- see In-Sandbox-Soak.ps1). Exits non-zero on any mismatch.
#
# Run: pwsh -File sandbox-lab/scripts/Test-WorkerStdoutParser.ps1

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'WorkerStdoutParser.ps1')

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

# ---------------------------------------------------------------- scenario 1
# Verbatim lines from
# C:\Users\scott\Desktop\Code\cc-sbsoak-run\sandbox-lab\soak-output\
#   soak-bcb3ebe-20260906-113951Z\logs\final\egress-per-channel\
#   government\logs\gst-worker.stdout.log
# (the file's full 6 lines, including its trailing blank line -- the real
# file this lane reads). Contains one "CTRL reload aborted: ..." line, two
# non-matching "CTRL reload: new leg stream held..." progress lines (a
# real line this parser must NOT match), two "WORKER_RESULT {...}" lines
# (also must not match), and a trailing blank line (must not throw/count).
$sample1Lines = @(
    "WORKER_RESULT {'error': ('stall', 'output stalled'), 'teardown_clean': True}"
    "CTRL reload: new leg stream held at its first buffer (1 stream(s) still to preroll)"
    "CTRL reload: new leg stream held at its first buffer (0 stream(s) still to preroll)"
    "WORKER_RESULT {'error': ('stall', 'output stalled'), 'teardown_clean': True}"
    "CTRL reload aborted: new program errored before commit: gst-stream-error-quark: GStreamer encountered a general stream error. (1)"
    ""
)
$r1 = ConvertFrom-WorkerStdoutLines -Lines $sample1Lines
Assert-Equal 'scenario1 (real sample) reload_committed_count' 0 $r1.reload_committed_count
Assert-Equal 'scenario1 (real sample) reload_aborted_count' 1 $r1.reload_aborted_count
Assert-Equal 'scenario1 (real sample) reload_aborted_reasons[0]' 'new program errored before commit: gst-stream-error-quark: GStreamer encountered a general stream error. (1)' $r1.reload_aborted_reasons[0]
Assert-Equal 'scenario1 (real sample) worker_stall_count' 0 $r1.worker_stall_count

# ---------------------------------------------------------------- scenario 2
# Synthetic "CTRL reload committed (elements=N)" -- engine.py:1829's exact
# format -- the real sample above never happened to log a successful
# commit, so this is exercised directly.
$r2 = ConvertFrom-WorkerStdoutLines -Lines @('CTRL reload committed (elements=42)')
Assert-Equal 'scenario2 (reload committed) reload_committed_count' 1 $r2.reload_committed_count
Assert-Equal 'scenario2 (reload committed) reload_aborted_count' 0 $r2.reload_aborted_count
Assert-Equal 'scenario2 (reload committed) worker_stall_count' 0 $r2.worker_stall_count

# ---------------------------------------------------------------- scenario 3
# Synthetic "CTRL stall: ..." -- engine.py:1125's exact format (printed to
# stderr in the checkout this was written against, per this parser's own
# file header -- but the parser itself is a pure line-matcher, agnostic to
# which stream it was read from).
$r3 = ConvertFrom-WorkerStdoutLines -Lines @('CTRL stall: no output for 10s - quitting for daemon restart')
Assert-Equal 'scenario3 (stall) worker_stall_count' 1 $r3.worker_stall_count
Assert-Equal 'scenario3 (stall) reload_committed_count' 0 $r3.reload_committed_count
Assert-Equal 'scenario3 (stall) reload_aborted_count' 0 $r3.reload_aborted_count

# ---------------------------------------------------------------- scenario 4
# Multiple aborts with DIFFERENT reasons in one read -- reasons must
# accumulate in order, count must match the array length.
$r4 = ConvertFrom-WorkerStdoutLines -Lines @(
    'CTRL reload aborted: new program errored before commit: boom'
    'CTRL reload committed (elements=7)'
    'CTRL reload aborted: new program produced no buffer within 5s; reverting'
)
Assert-Equal 'scenario4 (mixed) reload_aborted_count' 2 $r4.reload_aborted_count
Assert-Equal 'scenario4 (mixed) reload_committed_count' 1 $r4.reload_committed_count
Assert-Equal 'scenario4 (mixed) reasons.Count' 2 $r4.reload_aborted_reasons.Count
Assert-Equal 'scenario4 (mixed) reasons[0]' 'new program errored before commit: boom' $r4.reload_aborted_reasons[0]
Assert-Equal 'scenario4 (mixed) reasons[1]' 'new program produced no buffer within 5s; reverting' $r4.reload_aborted_reasons[1]

# ---------------------------------------------------------------- scenario 5
# Empty/no lines at all -- must return zeroed counts, never throw.
$r5 = ConvertFrom-WorkerStdoutLines -Lines @()
Assert-Equal 'scenario5 (empty) reload_committed_count' 0 $r5.reload_committed_count
Assert-Equal 'scenario5 (empty) reload_aborted_count' 0 $r5.reload_aborted_count
Assert-Equal 'scenario5 (empty) worker_stall_count' 0 $r5.worker_stall_count
Assert-Equal 'scenario5 (empty) reasons.Count' 0 $r5.reload_aborted_reasons.Count

# ---------------------------------------------------------------- scenario 6
# "CTRL reload committed" with NO "(elements=N)" suffix -- the regex's
# element-count group is optional; the bare line must still match.
$r6 = ConvertFrom-WorkerStdoutLines -Lines @('CTRL reload committed')
Assert-Equal 'scenario6 (bare committed, no elements=) reload_committed_count' 1 $r6.reload_committed_count

Write-Host ""
Write-Host "WorkerStdoutParser unit checks: $($script:total - $script:failures)/$($script:total) passed" -ForegroundColor $(if ($script:failures -eq 0) { 'Green' } else { 'Red' })
if ($script:failures -gt 0) { exit 1 }
exit 0
