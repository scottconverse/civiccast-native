# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# CaptionsOffCheck.ps1 -- dot-sourceable pure decision logic for the
# -CaptionsOff verification (PUT /api/staff/station/profile
# {"live_captions_enabled": false}, then GET it back), extracted so it is
# unit-testable (Test-CaptionsOffCheck.ps1) with synthetic
# put_ok/get_ok/read_back_value tuples instead of a live station.
# In-Sandbox-Soak.ps1's own HTTP calls (Invoke-CivicCastApi) stay inline;
# only the "was this actually verified, and should this run refuse to
# proceed" judgment lives here, matching ServiceStartFailureCheck.ps1's own
# extraction pattern.

function Get-CaptionsOffVerification {
    <#
      .SYNOPSIS
      Judge whether a requested captions-off switch was actually confirmed.

      .PARAMETER PutOk
      Whether PUT /api/staff/station/profile returned HTTP 200.

      .PARAMETER GetOk
      Whether the follow-up GET /api/staff/station/profile returned HTTP
      200 with a parseable body.

      .PARAMETER ReadBackValue
      The GET response body's `live_captions_enabled` field (any type --
      $null when the GET failed or the field was absent/non-boolean).

      .OUTPUTS
      [pscustomobject] @{
        captions_enabled    = [bool]   -- what to record as the station's
                                          actual live-caption state; the
                                          read-back value when it is a real
                                          bool, otherwise conservatively
                                          $true (unconfirmed-off is never
                                          reported as off)
        verified            = [bool]   -- $true only when PutOk AND the
                                          read-back is the literal boolean
                                          $false
        should_harness_error = [bool]  -- the operator explicitly asked to
                                          test this flag; a failed PUT or a
                                          read-back that is not false must
                                          never silently ride along as an
                                          unconfirmed premise of a PASS/FAIL
                                          verdict (same principle as the
                                          -SeamlessReload verification this
                                          mirrors)
      }
    #>
    param(
        [bool]$PutOk,
        [bool]$GetOk,
        $ReadBackValue
    )

    $readBackIsFalse = ($GetOk -and ($ReadBackValue -is [bool]) -and ($ReadBackValue -eq $false))
    $verified = ($PutOk -and $readBackIsFalse)
    $capturedBoolReadBack = ($GetOk -and ($ReadBackValue -is [bool]))

    return [pscustomobject]@{
        captions_enabled     = $(if ($capturedBoolReadBack) { [bool]$ReadBackValue } else { $true })
        verified             = $verified
        should_harness_error = (-not $PutOk -or -not $readBackIsFalse)
    }
}
