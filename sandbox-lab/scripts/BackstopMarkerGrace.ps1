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
# THE BUG THIS EXISTS FOR (round-follow-up-B review, addressed here):
# In-Sandbox-Soak.ps1's harness-error path
# (Write-HarnessErrorVerdictAndExit, reachable from five call sites --
# In-Sandbox-Soak.ps1:1031,1262,1298,1587,1626 -- that fire after
# PHASE-HEALTHY) writes, in this exact order, all before the guest exits:
#   1. SOAK-START.json, explicitly marked
#      `harness_error_before_soak_start: true` (In-Sandbox-Soak.ps1:400) --
#      a backstop so downstream tooling always finds a SOAK-START.json,
#      even on a run that failed before the real soak clock started;
#   2. VERDICT.json / VERDICT.txt (In-Sandbox-Soak.ps1:416-417);
#   3. Invoke-FinalFlush (In-Sandbox-Soak.ps1:419), which forces one last
#      robocopy mirror of $LocalDir -> $ShipDir.
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
