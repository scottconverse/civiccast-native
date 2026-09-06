# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# HostLiveness.ps1 -- dot-sourceable host-side liveness classification for
# the sandbox soak lane (sandbox-lab/Run-SandboxSoak.ps1). Extracted into
# its own file, exactly like SoakVerdict.ps1, so it can be unit-tested with
# synthetic (now, launch_utc, mtimes) tuples (Test-HostLiveness.ps1) without
# ever launching a sandbox.
#
# THE BUG THIS EXISTS FOR (run 3, head 406fe80): PowerShell variable names
# are CASE-INSENSITIVE. Run-SandboxSoak.ps1's wait loop declared the -Minutes
# threshold PARAMETER as `$QuietMinutes` and then, a few lines later, the
# LOCAL elapsed-time computation as `$quietMinutes` -- to PowerShell these
# are literally the same variable (this project has hit this exact class of
# bug before: Run-GateA.ps1's own header comment on `$sourceSha` /
# -SourceSha). The very first loop iteration computed an elapsed time of
# ~0 minutes (the guest had JUST launched) and that assignment clobbered
# the 15-minute threshold down to ~0 -- so the very next comparison
# (`$quietMinutes -ge $QuietMinutes`, now comparing ~0 against itself)
# fired immediately, ~40s after launch, well before the guest had even
# booted (Windows Sandbox measured at 30-60s boot time before its
# LogonCommand script starts, let alone before that script's first
# soak-log.txt write). This is also why the printed reason said
# ">= 0 minute(s)" instead of ">= 15 minute(s))" -- the threshold value
# itself was already destroyed by the time the message was built.
#
# Every function below takes ONLY distinctly-named parameters, on separate
# lines from any local variable of a similar name, specifically to make
# this class of bug visible in a diff rather than hidden by casing.
#
# SECOND, related bug: absence was never distinguished from staleness.
# "No file exists yet" was folded into the same generic quiet-bound as "a
# file exists but stopped advancing" via `Get-MainThreadLivenessUtc`
# returning $null and the caller treating a stale `$lastMainThreadProgressUtc`
# (seeded to launch time) as equivalent to 15 minutes of silence from a
# process that HAD been writing and stopped. A guest that has not booted
# yet (no files can exist) is not the same condition as a guest that booted,
# ran for a while, and then stopped -- the first is normal for the first
# few minutes, the second never is. Get-SandboxLivenessVerdict below treats
# them as two different states with two different bounds.

function Get-SandboxLivenessVerdict {
    <#
      .SYNOPSIS
      Classify the current liveness state of an in-progress sandbox soak
      run from the host side, given only timestamps -- no file I/O, no
      process calls, so it is fully unit-testable with synthetic data.

      .PARAMETER NowUtc
      The current UTC instant this check is being evaluated at.

      .PARAMETER LaunchUtc
      UTC instant WindowsSandbox.exe was launched for this run.

      .PARAMETER MainThreadNewestUtc
      Newest LastWriteTimeUtc among soak-log.txt / summary.json / the
      phase-marker files, or $null if NONE of them exist yet (the guest
      has not booted / the LogonCommand script has not run far enough to
      write its first line).

      .PARAMETER HeartbeatNewestUtc
      LastWriteTimeUtc of _SHIPPER-HEARTBEAT.txt, or $null if it does not
      exist yet. Used ONLY to classify a main-thread stall as a genuine
      guest hang (heartbeat still fresh -- the shipper, a separate process,
      is still alive and ticking) vs. a broken evidence channel (heartbeat
      also stale/missing -- classify as harness error, not a product state).

      .PARAMETER BootBoundMinutes
      Minutes from LaunchUtc within which AT LEAST ONE main-thread file
      must exist. Windows Sandbox itself measured 30-60s to boot before its
      LogonCommand script even starts; this bound must clear that
      comfortably. Default 5.

      .PARAMETER QuietMinutes
      Minutes of no NEW main-thread mtime, once at least one main-thread
      file exists, before this is classified as a stall or a quiet-share
      (never before the first file exists -- see BootBoundMinutes above).
      Default 15.

      .OUTPUTS
      [pscustomobject] @{ verdict; reason }
      verdict is one of:
        'alive'                -- no bound exceeded; keep waiting.
        'guest-never-started'  -- no main-thread file within BootBoundMinutes
                                   of launch. HARNESS_ERROR, never a stall.
        'stall'                -- main-thread mtime stale >= QuietMinutes,
                                   but the shipper heartbeat is still fresh.
                                   A genuine stuck-guest condition.
        'quiet-share'           -- main-thread mtime stale >= QuietMinutes
                                   AND the heartbeat is also stale/missing.
                                   HARNESS_ERROR -- channel or guest wedged,
                                   not a diagnosable product state.
    #>
    param(
        [Parameter(Mandatory = $true)] [datetime]$NowUtc,
        [Parameter(Mandatory = $true)] [datetime]$LaunchUtc,
        [datetime]$MainThreadNewestUtc,
        [datetime]$HeartbeatNewestUtc,
        [int]$BootBoundMinutes = 5,
        [int]$QuietMinutes = 15
    )

    if (-not $MainThreadNewestUtc) {
        $sinceLaunchMinutes = ($NowUtc - $LaunchUtc).TotalMinutes
        if ($sinceLaunchMinutes -ge $BootBoundMinutes) {
            return [pscustomobject]@{
                verdict = 'guest-never-started'
                reason = "no soak-log.txt/summary.json/phase-marker exists $([Math]::Round($sinceLaunchMinutes, 1)) minute(s) after launch (boot bound ${BootBoundMinutes}m) -- the guest never started, or never got far enough to write its first line"
            }
        }
        return [pscustomobject]@{
            verdict = 'alive'
            reason = "no main-thread file yet, but only $([Math]::Round($sinceLaunchMinutes, 1)) minute(s) since launch (boot bound ${BootBoundMinutes}m not yet reached) -- normal"
        }
    }

    $mainThreadStaleMinutes = ($NowUtc - $MainThreadNewestUtc).TotalMinutes
    if ($mainThreadStaleMinutes -lt $QuietMinutes) {
        return [pscustomobject]@{
            verdict = 'alive'
            reason = "main-thread mtime is $([Math]::Round($mainThreadStaleMinutes, 1)) minute(s) old, under the ${QuietMinutes}m quiet bound"
        }
    }

    if ($HeartbeatNewestUtc) {
        $heartbeatStaleMinutes = ($NowUtc - $HeartbeatNewestUtc).TotalMinutes
        if ($heartbeatStaleMinutes -lt $QuietMinutes) {
            return [pscustomobject]@{
                verdict = 'stall'
                reason = "main-thread mtime stale for $([Math]::Round($mainThreadStaleMinutes, 1)) minute(s) (>= ${QuietMinutes}m), but the shipper heartbeat is only $([Math]::Round($heartbeatStaleMinutes, 1)) minute(s) old -- the guest script itself appears stuck"
            }
        }
    }

    return [pscustomobject]@{
        verdict = 'quiet-share'
        reason = "main-thread mtime stale for $([Math]::Round($mainThreadStaleMinutes, 1)) minute(s) (>= ${QuietMinutes}m), AND the shipper heartbeat is also stale or missing -- the guest-to-host mapped-folder channel (or the guest itself) is wedged, not a diagnosable product state"
    }
}
