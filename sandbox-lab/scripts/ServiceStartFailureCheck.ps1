# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# ServiceStartFailureCheck.ps1 -- Test-ServiceStartFailureIsProductCrash,
# extracted from In-Sandbox-Soak.ps1 (round-14 finding 8) into its own
# dot-sourceable file, matching this project's established pattern
# (RestartClassifier.ps1/SoakVerdict.ps1/HostLiveness.ps1/
# DaemonLogPatterns.ps1) so it is unit-testable (Test-ServiceStartFailure.ps1)
# with synthetic Get-Service/Get-WinEvent results instead of the live
# System event log. Both In-Sandbox-Soak.ps1 (the real driver) and
# Test-ServiceStartFailure.ps1 dot-source this SAME file.

# WS5-owner-approved DISPLAY_NAME constant, duplicated from
# civiccast/native/supervisor/config.py:38 (PowerShell reads no Python at
# runtime, so this string cannot be imported -- it must be kept in sync by
# hand). Round-follow-up-C finding: this used to be a bare literal inside
# the function body with a comment telling readers to "re-verify against
# HEAD before trusting this constant blindly" -- a comment is not a gate,
# so drift between the two files could go unnoticed indefinitely. Hoisted
# to a script-scope constant so Test-ServiceStartFailure.ps1 can read
# config.py's own DISPLAY_NAME literal (via regex, no Python interpreter
# required) and assert equality against THIS value -- a rename in either
# file without the other now fails the lane's unit tests instead of
# silently reintroducing round-14 finding 1's exact bug class.
$script:ServiceStartFailureWellKnownDisplayName = 'CivicCast Native Supervisor'

# Round-11 finding 5 (MEDIUM) / round-12 findings 4-5: neither a
# Start-Service THROW nor a Start-Service SUCCESS followed by the service
# never reaching Running is automatically a harness/setup problem -- if
# the SCM actually launched the service binary and it exited/crashed, that
# is a real product defect (FAIL), never something this harness caused.
# Only a case where the SCM itself refused to even attempt the launch
# (access denied, the service marked for deletion, a missing/failed
# dependency), or genuinely never got the process running at all, is a
# harness/setup condition (HARNESS_ERROR). Round-12 finding 4: this check
# now runs on BOTH branches (a throw, AND a success-then-dies-before-
# Running) -- the round-11 version only ran it on the throw branch, so a
# service that accepted Start-Service and then crashed before settling
# into Running unconditionally read as HARNESS_ERROR with no event-log
# check at all.
function Test-ServiceStartFailureIsProductCrash {
    <#
      .SYNOPSIS
      Round-14 finding 1 (BLOCKER): Service Control Manager events record
      the service's DISPLAY name in their structured properties, never its
      short service NAME -- measured directly: filtering on
      Properties[0].Value -eq 'CivicCastSupervisor' matched 0 of 1006 real
      SCM events for this service; its actual display name is what
      appears. Resolved at runtime via `(Get-Service -Name
      CivicCastSupervisor).DisplayName` rather than hardcoding it, since
      the installer/manifest could rename it without this script's own
      knowledge going stale.

      Round-14 finding 3 (HIGH): the structured property holding the
      service (display) name is not always at the same index -- 7009's
      own layout is [timeout_ms, service_name], i.e. Properties[1], while
      7034/7031/7024/7000 carry it at Properties[0]. Rather than hardcode
      a different index per event ID, every property on the event is
      checked for a match, whichever index it lands in.

      Round-14 finding 2 (HIGH): evaluates ALL matching events since
      $SinceUtc, not just the newest -- Get-WinEvent returns newest first,
      so a 7000/7009 logged AFTER a genuine 7034/7031/7024 crash would
      otherwise mask it. ANY crash-ID event anywhere in the matched set is
      FAIL; only when NONE of them are a crash ID does this fall through
      to the 7000/7009 HARNESS_ERROR default.

      Round-14 finding 4 (MEDIUM): the previous "promote 7000/7009 to a
      product crash if the message text contains a launched-and-failed
      phrase" branch is DELETED -- measured: those phrases do not occur in
      real 7000/7009 message text. 7000 (service failed to start) / 7009
      (timeout waiting for the service to report itself started) now mean
      HARNESS_ERROR, unconditionally, whenever no crash-ID event
      (7034/7031/7024) is ALSO present in the same evaluated set.

      Evidence checked, in order: (1) the System event log for Service
      Control Manager events naming this service's DISPLAY name (resolved
      at runtime, matched against ANY property on the event), with
      TimeCreated at or after $SinceUtc (round-12 finding 5: the actual
      moment THIS SCRIPT attempted Start-Service, not a fixed window that
      could span an unrelated prior crash). Any 7034 (terminated
      unexpectedly) / 7031 (crashed, scheduled for restart) / 7024
      (terminated with a specific service-defined exit code) event means
      the SCM DID launch the process and it died: a real product crash,
      FAIL. Otherwise, any 7000/7009 event means the SCM itself could not
      get the process running: HARNESS_ERROR. (2) the exception text
      itself for the SCM's own refusal phrasing ("access is denied",
      "marked for deletion", "dependency"). Neither a positive crash-event
      match NOR a clear SCM-refusal phrase found defaults to HARNESS_ERROR
      (the conservative default when evidence is ambiguous -- never guess
      FAIL without a positive product-crash signal).

      .PARAMETER SinceUtc
      UTC instant of this script's own Start-Service attempt -- the event
      log is queried with StartTime at or after this, never a fixed
      window (round-12 finding 5).
    #>
    param([string]$ExceptionText, [datetime]$SinceUtc)
    # Followup finding 3 (round 14 addendum): the well-known display name
    # the installer ships (config.py's own DISPLAY_NAME constant -- see the
    # script-scope $script:ServiceStartFailureWellKnownDisplayName defined
    # above, and Test-ServiceStartFailure.ps1's drift-guard scenario), used
    # ONLY as a fallback when Get-Service itself throws (service
    # uninstalled/renamed concurrently, or -- exactly the scenario this
    # whole function exists for -- the service never even registered
    # because the SCM refused the launch). Skipping the event-log check
    # entirely in that case (the round-14 behavior) meant a genuine crash
    # could go undetected purely because Get-Service happened to fail at
    # the wrong moment, silently defaulting to HARNESS_ERROR with no
    # attempt to look.
    $wellKnownDisplayName = $script:ServiceStartFailureWellKnownDisplayName
    try {
        $displayName = $null
        try {
            $displayName = (Get-Service -Name 'CivicCastSupervisor' -ErrorAction Stop).DisplayName
        } catch {
            # Get-Service itself can fail -- NOT itself evidence of
            # anything, but the event-log check must still be attempted
            # against the well-known constant name rather than skipped.
            $displayName = $wellKnownDisplayName
        }
        if ($displayName) {
            $scmEvents = @(Get-WinEvent -FilterHashtable @{ LogName = 'System'; ProviderName = 'Service Control Manager'; Id = 7034, 7031, 7024, 7000, 7009; StartTime = $SinceUtc.ToLocalTime() } -ErrorAction SilentlyContinue |
                Where-Object {
                    $isMatch = $false
                    foreach ($p in $_.Properties) { if ("$($p.Value)" -eq $displayName) { $isMatch = $true; break } }
                    $isMatch
                })
            # Round-14 finding 2: check ALL matched events for a crash ID
            # -- Get-WinEvent returns newest first, so only inspecting
            # $scmEvents[0] could see a later, unrelated 7000/7009 and
            # miss an earlier real 7034/7031/7024 crash in the same set.
            $crashEvents = @($scmEvents | Where-Object { $_.Id -in 7034, 7031, 7024 })
            if ($crashEvents.Count -gt 0) {
                $ev = $crashEvents[0]
                return [pscustomobject]@{ IsProductCrash = $true; Reason = "System event log: Service Control Manager logged event ID $($ev.Id) for service '$displayName' at $($ev.TimeCreated.ToString('o')), at/after this script's own Start-Service attempt ($($SinceUtc.ToString('o')))" }
            }
            $noStartEvents = @($scmEvents | Where-Object { $_.Id -in 7000, 7009 })
            if ($noStartEvents.Count -gt 0) {
                $ev = $noStartEvents[0]
                return [pscustomobject]@{ IsProductCrash = $false; Reason = "System event log: Service Control Manager logged event ID $($ev.Id) for service '$displayName' at $($ev.TimeCreated.ToString('o')) -- the SCM itself could not get the process running (or never heard back in time)" }
            }
        }
    } catch {
        # Get-WinEvent itself can fail (channel not present, permissions) --
        # that is NOT evidence of anything; fall through to the exception-
        # text check below.
    }
    if ("$ExceptionText" -match 'access is denied|marked for deletion|dependen') {
        return [pscustomobject]@{ IsProductCrash = $false; Reason = "Start-Service exception text indicates the SCM itself refused the launch: $ExceptionText" }
    }
    return [pscustomobject]@{ IsProductCrash = $false; Reason = "no SCM crash/no-start event (7034/7031/7024/7000/7009, matched against the service's own display name) for CivicCastSupervisor at/after this script's Start-Service attempt ($($SinceUtc.ToString('o'))), and the exception text (if any) does not match a known SCM-refusal phrase -- defaulting to HARNESS_ERROR (ambiguous evidence, not a confirmed product crash)$(if ($ExceptionText) { ": $ExceptionText" })" }
}
