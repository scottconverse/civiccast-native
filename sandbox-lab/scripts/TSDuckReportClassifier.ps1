# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
<# Pure parser for the JSON emitted by tsp -P analyze --json. #>

function Get-TSDuckRequiredInteger {
    param([Parameter(Mandatory)] $Object, [Parameter(Mandatory)][string] $Name)
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value -or "$($property.Value)" -notmatch '^\d+$') {
        throw "TSDuck report field is missing or malformed: $Name."
    }
    return [int64] $property.Value
}

function Get-TSDuckReportMetrics {
    param([Parameter(Mandatory)] $Report)
    if ($null -eq $Report.ts -or $null -eq $Report.ts.packets) {
        throw 'TSDuck report has no ts.packets section.'
    }
    $packets = $Report.ts.packets
    $pidRows = @($Report.pids)
    if ($pidRows.Count -eq 0) { throw 'TSDuck report has no PID rows.' }
    $discontinuities = [int64] 0
    foreach ($pidRow in $pidRows) {
        if ($null -eq $pidRow.packets) { throw 'TSDuck PID row has no packets section.' }
        $discontinuities += Get-TSDuckRequiredInteger -Object $pidRow.packets -Name 'discontinuities'
    }
    return [ordered]@{
        packets_total = Get-TSDuckRequiredInteger -Object $packets -Name 'total'
        invalid_syncs = Get-TSDuckRequiredInteger -Object $packets -Name 'invalid-syncs'
        transport_errors = Get-TSDuckRequiredInteger -Object $packets -Name 'transport-errors'
        # TSDuck's current JSON has no ts-level/PCR-only discontinuity counter.
        pid_discontinuities = $discontinuities
    }
}

function Get-TSDuckMetricsVerdict {
    param([Parameter(Mandatory)] $Metrics)
    if ([int64] $Metrics.packets_total -le 0) { return 'fail-zero-packets' }
    if ([int64] $Metrics.invalid_syncs -ne 0 -or
        [int64] $Metrics.transport_errors -ne 0 -or
        [int64] $Metrics.pid_discontinuities -ne 0) {
        return 'fail-stream-errors'
    }
    return 'pass'
}
