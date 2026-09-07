# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# BackstopMarkerGrace.ps1 -- dot-sourceable host-side decision logic for
# Run-SandboxSoak.ps1's harness-error backstop-marker handling, extracted
# into its own file (matching this project's established pattern --
# HostLiveness.ps1/SoakVerdict.ps1/RestartClassifier.ps1/
# ServiceStartFailureCheck.ps1) so it is unit-testable
# (Test-BackstopMarkerGrace.ps1) with a fake Test-Path/clock instead of a
# real sandbox and a real 45-second wait.
#
# THE BUG THIS EXISTS FOR (round-follow-up-B review, addressed here;
# round-4 review finding 5 replaced this header's stale line-number
# citations with function names -- call-site line numbers drift every
# time a new one is added upstream of an existing one, which is exactly
# what happened here: this header used to cite "five call sites" by exact
# line number, and sandbox-lab lane follow-up D alone added six more,
# without ever touching this file -- `grep -n
# 'Write-HarnessErrorVerdictAndExit -Reason'
# sandbox-lab/scripts/In-Sandbox-Soak.ps1` is the only durable way to
# enumerate them; this header names the FUNCTION, never a line number):
#
# In-Sandbox-Soak.ps1's harness-error path (Write-HarnessErrorVerdictAndExit
# -- grep that function name to enumerate its current call sites directly,
# rather than trusting any number written here) writes, in this exact
# order, all before the guest exits:
#   1. SOAK-START.json (via that same function's own Write-PhaseMarker
#      call), explicitly marked `harness_error_before_soak_start: true` --
#      a backstop so downstream tooling always finds a SOAK-START.json,
#      even on a run that failed before the real soak clock started;
#   2. VERDICT.json / VERDICT.txt (via Save-Json / Set-Content, right
#      after the backstop marker, in the same function);
#   3. Invoke-FinalFlush, which forces one last robocopy mirror of
#      $LocalDir -> $ShipDir.
# All three ride the SAME persistent shipper process's fixed ~15s tick
# (its own $IntervalSeconds default -- see In-Sandbox-Soak.ps1's shipper
# script). A single robocopy tick can, in principle, land a partial mirror
# -- and "SOAK-START.json" sorts alphabetically before "VERDICT.txt", so a
# tick that catches the guest mid-write-sequence can ship the marker
# without yet shipping the verdict. Run-SandboxSoak.ps1's own wait loop
# checks Test-Path $verdictTxtPath FIRST every iteration (so it usually
# wins the race), but when it does not, the pre-fix code killed the VM the
# instant it saw the backstop marker -- before VERDICT.txt had a chance to
# ship on that same tick or the very next one -- leaving the operator with
# only HOST-QUIET-SHARE.txt pointing at a VERDICT.txt that in fact already
# existed in the guest and would have shipped moments later.
#
# Round-4 review finding 4: this grace window originally covered ONLY the
# awaiting-soak-start phase (the one place Run-SandboxSoak.ps1 inspects
# SOAK-START.json's own content). Sandbox-lab lane follow-up D added
# Write-HarnessErrorVerdictAndExit call sites that fire BEFORE either
# PHASE-INSTALL-DONE.json or PHASE-HEALTHY.json is ever written (an
# unparsable -WorkerEnv value, a missing installer, a failed registry
# write/verify) -- so the SAME shipper-tick race is reachable from
# Run-SandboxSoak.ps1's 'installing' and 'awaiting-health' phases too.
# Wait-ForVerdictWithGrace (below in THIS file, a thin wrapper around
# Wait-ForVerdictAfterBackstopMarker just above it -- called by
# Run-SandboxSoak.ps1, not defined there) is now the ONE place all three
# phases call this grace wait from.
#
# THE FIX: on seeing the backstop marker, do NOT kill immediately. Give
# VERDICT.txt a bounded grace window (default 45s = 3 shipper ticks at the
# shipper's own ~15s interval, polled every 5s) to show up before falling
# back to the quiet-share exit. If it arrives during the grace window,
# take the normal verdict path -- the run's own VERDICT.txt/.json already
# correctly reports HARNESS_ERROR with the real reason; this grace window
# only prevents the HOST from discarding that already-shipped truth.

function Wait-ForVerdictAfterBackstopMarker {
    <#
      .SYNOPSIS
      Poll for VERDICT.txt for a bounded grace window after seeing the
      harness-error backstop marker, instead of killing the sandbox the
      instant the marker is seen. Pure decision loop -- all I/O (file
      existence, sleeping) is injected via scriptblocks so this is fully
      unit-testable (Test-BackstopMarkerGrace.ps1) without a real
      filesystem or a real 45-second wait.

      .PARAMETER TestVerdictPathExists
      Scriptblock, called with no arguments, returning $true once
      VERDICT.txt exists. Production passes a closure over the real
      -Path (e.g. `{ Test-Path $verdictTxtPath }`); tests pass a fake
      that flips to $true after a chosen number of calls, to simulate
      the verdict arriving mid-grace.

      .PARAMETER SleepSeconds
      Scriptblock, called with one argument (seconds to sleep) between
      polls. Production passes a real `{ param($s) Start-Sleep -Seconds
      $s }`; tests pass a no-op so the whole suite runs instantly instead
      of burning the real grace window on every run.

      .PARAMETER GraceSeconds
      Total bounded wait before giving up, default 45 (~3 shipper ticks
      at the shipper's own ~15s $IntervalSeconds default -- see this
      file's header).

      .PARAMETER PollIntervalSeconds
      How often to re-check within the grace window, default 5.

      .OUTPUTS
      [pscustomobject] @{ verdict_arrived; polls; waited_seconds }
      verdict_arrived is $true the moment TestVerdictPathExists returns
      $true (checked BEFORE any wait, so a verdict already present costs
      zero grace time); $false if the grace window is exhausted first.
      waited_seconds and polls are exposed purely for logging/assertions,
      never used to make the decision themselves.
    #>
    param(
        [Parameter(Mandatory = $true)] [scriptblock]$TestVerdictPathExists,
        [scriptblock]$SleepSeconds = { param($s) Start-Sleep -Seconds $s },
        [int]$GraceSeconds = 45,
        [int]$PollIntervalSeconds = 5
    )
    $waited = 0
    $polls = 0
    while ($true) {
        $polls++
        if (& $TestVerdictPathExists) {
            return [pscustomobject]@{ verdict_arrived = $true; polls = $polls; waited_seconds = $waited }
        }
        if ($waited -ge $GraceSeconds) {
            return [pscustomobject]@{ verdict_arrived = $false; polls = $polls; waited_seconds = $waited }
        }
        & $SleepSeconds $PollIntervalSeconds
        $waited += $PollIntervalSeconds
    }
}

function Wait-ForVerdictWithGrace {
    <#
      .SYNOPSIS
      Round-4 review finding 4/5: ONE shared wrapper around
      Wait-ForVerdictAfterBackstopMarker (just above) called from all
      three pre-'running' phases in Run-SandboxSoak.ps1's own poll loop
      (installing, awaiting-health, awaiting-soak-start).

      Round-follow-up-C's original finding: SOAK-START.json's harness-
      error backstop marker and VERDICT.txt/.json ride the SAME ~15s
      shipper tick (In-Sandbox-Soak.ps1's shipper script, and
      Write-HarnessErrorVerdictAndExit's own write order -- SOAK-START.json,
      then VERDICT.json/.txt, then Invoke-FinalFlush, all before the guest
      exits) -- a tick that lands mid-write-sequence can ship one marker
      without yet shipping VERDICT.txt, so declaring a stall/quiet-share
      the INSTANT some other marker's absence/presence looks stall-worthy
      can beat an already-written VERDICT.txt to the share by moments.

      Round-4 review finding 4 extends this: sandbox-lab lane follow-up D
      added Write-HarnessErrorVerdictAndExit call sites that fire BEFORE
      either PHASE-INSTALL-DONE.json or PHASE-HEALTHY.json is ever written
      (an unparsable -WorkerEnv value, a missing installer, a failed
      registry write/verify -- all diagnosed before the installer even
      finishes or before the health poll even starts) -- so the SAME race
      is reachable from Run-SandboxSoak.ps1's 'installing' and
      'awaiting-health' phases too, not only 'awaiting-soak-start' (the
      only phase this grace wait originally covered). This function is
      the single place all three now call from.

      Extracted here (rather than left inline in Run-SandboxSoak.ps1,
      which has top-level side-effecting code that runs immediately on
      dot-source and so cannot itself be dot-sourced by a test) so it is
      unit-testable (Test-BackstopMarkerGrace.ps1) with fake
      Test-Path/sleep/log closures, matching this function's own
      Wait-ForVerdictAfterBackstopMarker dependency.

      .PARAMETER VerdictTxtPath
      The real VERDICT.txt path in production; irrelevant when
      -TestVerdictPathExists is overridden for a test (still required,
      since it is threaded through to that closure either way).

      .PARAMETER PhaseDescription
      Human-readable fragment describing WHY this grace wait is being
      entered (e.g. "installer bound exceeded", "SOAK-START.json is the
      harness-error backstop marker") -- folded into the one success
      message logged via -LogSuccess; callers still compose their OWN
      "still not arrived" message themselves, since that differs by
      phase.

      .PARAMETER TestVerdictPathExists
      Scriptblock, called with -VerdictTxtPath as its one argument.
      Production default is a real `Test-Path`; tests pass a fake that
      flips to $true after a chosen number of calls.

      .PARAMETER LogSuccess
      Scriptblock, called with one argument (the message) ONLY when the
      grace wait succeeds. Production passes `{ param($m) Write-Step $m
      }` (Run-SandboxSoak.ps1's own logging convention); tests pass a
      closure that just records what it was called with, or a no-op.

      .PARAMETER SleepSeconds / GraceSeconds / PollIntervalSeconds
      Passed straight through to Wait-ForVerdictAfterBackstopMarker.

      .OUTPUTS
      The [pscustomobject] @{ verdict_arrived; polls; waited_seconds }
      Wait-ForVerdictAfterBackstopMarker itself returns, unchanged --
      callers act on .verdict_arrived and may reuse .waited_seconds in
      their own "still not arrived" message.
    #>
    param(
        [string]$VerdictTxtPath,
        [string]$PhaseDescription,
        [scriptblock]$TestVerdictPathExists = { param($p) Test-Path $p },
        [scriptblock]$LogSuccess = { param($m) Write-Host $m },
        [scriptblock]$SleepSeconds = { param($s) Start-Sleep -Seconds $s },
        [int]$GraceSeconds = 45,
        [int]$PollIntervalSeconds = 5
    )
    # NOTE: the wrapping scriptblock below is invoked FROM INSIDE
    # Wait-ForVerdictAfterBackstopMarker's own function body -- and that
    # function ALSO declares a parameter named -TestVerdictPathExists. A
    # PowerShell scriptblock literal (unless captured via GetNewClosure())
    # resolves its free variables dynamically, up the CALL scope chain at
    # INVOCATION time, not lexically at definition time -- so a scriptblock
    # here that referenced `$TestVerdictPathExists` directly would resolve
    # to Wait-ForVerdictAfterBackstopMarker's OWN same-named parameter
    # (which, by the time the scriptblock runs, IS that very scriptblock)
    # and recurse into itself infinitely (confirmed directly: "The script
    # failed due to call depth overflow" the first time this was written
    # without the rename below). Capturing this function's OWN closure
    # into a DIFFERENTLY-named local variable first avoids the collision.
    $injectedTest = $TestVerdictPathExists
    $graceResult = Wait-ForVerdictAfterBackstopMarker `
        -TestVerdictPathExists { & $injectedTest $VerdictTxtPath } `
        -SleepSeconds $SleepSeconds -GraceSeconds $GraceSeconds -PollIntervalSeconds $PollIntervalSeconds
    if ($graceResult.verdict_arrived) {
        & $LogSuccess "$PhaseDescription, but VERDICT.txt arrived after a $($graceResult.waited_seconds)s grace wait ($($graceResult.polls) poll(s)) -- taking the normal verdict path instead of a premature stall/quiet-share exit."
    }
    return $graceResult
}
