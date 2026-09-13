# SPDX-License-Identifier: Apache-2.0
# Asynchronous, process-owned TSDuck transport probe for fixed beta tester work.
. (Join-Path $PSScriptRoot 'TSDuckReportClassifierR6.ps1')
function Get-Beta7TransportGrade {
    param([Parameter(Mandatory)]$Json, [Parameter(Mandatory)][string]$Label, [Parameter(Mandatory)][int]$Port, [int]$ExitCode = 0)
    $packets = $null; $invalid = $null; $transport = $null; $discontinuities = $null
    try {
        if ([int]$ExitCode -ne 0) { throw "tsp exit code $ExitCode" }
        $metrics = Get-TSDuckR6ReportMetrics $Json
        $packets = [int64]$metrics.packets_total
        $invalid = [int64]$metrics.invalid_syncs
        $transport = [int64]$metrics.transport_errors
        $discontinuities = [int64]$metrics.pid_discontinuities
        if ($packets -le 0) { throw 'zero packets' }
        if ($invalid -ne 0 -or $transport -ne 0 -or $discontinuities -ne 0) { throw 'stream errors present' }
        return [pscustomobject]@{label=$Label;port=$Port;verdict='PASS';reason='clean transport counters';packets=$packets;invalid_syncs=$invalid;transport_errors=$transport;discontinuities=$discontinuities;exit_code=$ExitCode}
    } catch {
        return [pscustomobject]@{label=$Label;port=$Port;verdict='FAIL';reason=[string]$_.Exception.Message;packets=$packets;invalid_syncs=$invalid;transport_errors=$transport;discontinuities=$discontinuities;exit_code=$ExitCode}
    }
}

function Start-Beta7TransportProbe {
    param([Parameter(Mandatory)][string]$TspExe,[Parameter(Mandatory)][ValidateRange(1,65535)][int]$Port,[Parameter(Mandatory)][string]$OutputDirectory,[Parameter(Mandatory)][string]$Label,[ValidateSet(0,5)][int]$WarmupSeconds=5)
    if ($TspExe -notmatch '^[A-Za-z]:\\' -or $OutputDirectory -notmatch '^[A-Za-z]:\\') { throw 'TSDuck executable and output directory must be absolute Windows paths.' }
    $exe = [IO.Path]::GetFullPath($TspExe)
    $out = [IO.Path]::GetFullPath($OutputDirectory)
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "TSDuck executable is absent: $exe" }
    New-Item -ItemType Directory -Force -Path $out | Out-Null
    $safe = ($Label -replace '[^A-Za-z0-9._-]','_')
    if (-not $safe) { throw 'Label must contain at least one usable filename character.' }
    $report = Join-Path $out "tsduck-$safe-report.json"
    $stdout = Join-Path $out "tsduck-$safe.stdout.log"
    $stderr = Join-Path $out "tsduck-$safe.stderr.log"
    $quotedReport = '"' + $report + '"'
    $args = @('--receive-timeout','10000','-I','ip',([string]$Port),'--buffer-size','16777216')
    if($WarmupSeconds -eq 5){$args += @('-P','until','--seconds','35','-P','skip','--seconds','5')}else{$args += @('-P','until','--seconds','30')}
    $args += @('-P','analyze','--json','--output-file',$quotedReport,'-O','drop')
    $process = Start-Process -FilePath $exe -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $null = $process.Handle
    $started = [datetime]::UtcNow
    return [pscustomobject]@{Process=$process;StartedUtc=$started;DeadlineUtc=$started.AddSeconds(60);Port=$Port;Label=$Label;WarmupSeconds=$WarmupSeconds;ReportPath=$report;StdoutPath=$stdout;StderrPath=$stderr}
}

function Add-Beta7TransportLifecycleEvidence {
    param([Parameter(Mandatory)]$Result,[Parameter(Mandatory)]$Probe,$ExitCode=$null)
    $completed=[datetime]::UtcNow
    $Result | Add-Member -NotePropertyName started_utc -NotePropertyValue ([datetime]$Probe.StartedUtc).ToString('o') -Force
    $Result | Add-Member -NotePropertyName deadline_utc -NotePropertyValue ([datetime]$Probe.DeadlineUtc).ToString('o') -Force
    $Result | Add-Member -NotePropertyName completed_utc -NotePropertyValue $completed.ToString('o') -Force
    $Result | Add-Member -NotePropertyName elapsed_seconds -NotePropertyValue ([math]::Round(($completed-([datetime]$Probe.StartedUtc)).TotalSeconds,3)) -Force
    $Result | Add-Member -NotePropertyName report_exists -NotePropertyValue ([bool](Test-Path -LiteralPath $Probe.ReportPath -PathType Leaf)) -Force
    $Result | Add-Member -NotePropertyName exit_code -NotePropertyValue $ExitCode -Force
    $Result | Add-Member -NotePropertyName acquisition_discard_seconds -NotePropertyValue ([int]$Probe.WarmupSeconds) -Force
    $Result | Add-Member -NotePropertyName analyzed_seconds -NotePropertyValue 30 -Force
    return $Result
}

function Complete-Beta7TransportProbe {
    param([Parameter(Mandatory)]$Probe)
    $process = $Probe.Process
    $process.Refresh()
    if (-not $process.HasExited) {
        if ([datetime]::UtcNow -lt ([datetime]$Probe.DeadlineUtc)) { return $null }
        try { $process.Kill(); $null = $process.WaitForExit(5000) } catch { }
        return Add-Beta7TransportLifecycleEvidence ([pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='probe deadline exceeded';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null}) $Probe
    }
    $process.Refresh()
    if ($null -eq $process.ExitCode) { return Add-Beta7TransportLifecycleEvidence ([pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='tsp exit code unavailable';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null}) $Probe }
    $exitCode = [int]$process.ExitCode
    if ($exitCode -ne 0) { return Add-Beta7TransportLifecycleEvidence ([pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason="tsp exit code $exitCode";packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null}) $Probe $exitCode }
    if (-not (Test-Path -LiteralPath $Probe.ReportPath -PathType Leaf)) { return Add-Beta7TransportLifecycleEvidence ([pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='missing report';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null}) $Probe $exitCode }
    $item = Get-Item -LiteralPath $Probe.ReportPath
    if ($item.Length -le 0) { return Add-Beta7TransportLifecycleEvidence ([pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='empty report';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null}) $Probe $exitCode }
    try { $json = Get-Content -LiteralPath $Probe.ReportPath -Raw | ConvertFrom-Json } catch { return Add-Beta7TransportLifecycleEvidence ([pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='malformed report';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null}) $Probe $exitCode }
    $grade=Get-Beta7TransportGrade -Json $json -Label $Probe.Label -Port ([int]$Probe.Port) -ExitCode $exitCode
    return Add-Beta7TransportLifecycleEvidence $grade $Probe $exitCode
}

function Stop-Beta7TransportProbe {
    param([Parameter(Mandatory)]$Probe)
    $process = $Probe.Process
    $process.Refresh()
    if (-not $process.HasExited) { $process.Kill(); $null = $process.WaitForExit(5000) }
}
