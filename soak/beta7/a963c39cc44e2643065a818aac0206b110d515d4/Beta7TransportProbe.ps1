# SPDX-License-Identifier: Apache-2.0
# Asynchronous, process-owned TSDuck transport probe for fixed beta tester work.
. (Join-Path $PSScriptRoot 'TSDuckReportClassifier.ps1')
function Get-Beta7TransportGrade {
    param([Parameter(Mandatory)]$Json, [Parameter(Mandatory)][string]$Label, [Parameter(Mandatory)][int]$Port, [int]$ExitCode = 0)
    $packets = $null; $invalid = $null; $transport = $null; $discontinuities = $null
    try {
        if ([int]$ExitCode -ne 0) { throw "tsp exit code $ExitCode" }
        $metrics = Get-TSDuckReportMetrics $Json
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
    param([Parameter(Mandatory)][string]$TspExe,[Parameter(Mandatory)][ValidateRange(1,65535)][int]$Port,[Parameter(Mandatory)][string]$OutputDirectory,[Parameter(Mandatory)][string]$Label)
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
    $args = @('-I','ip',([string]$Port),'--buffer-size','16777216','-P','until','--seconds','30','-P','analyze','--json','--output-file',$quotedReport,'-O','drop')
    $process = Start-Process -FilePath $exe -ArgumentList $args -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $null = $process.Handle
    $started = [datetime]::UtcNow
    return [pscustomobject]@{Process=$process;StartedUtc=$started;DeadlineUtc=$started.AddSeconds(60);Port=$Port;Label=$Label;ReportPath=$report;StdoutPath=$stdout;StderrPath=$stderr}
}

function Complete-Beta7TransportProbe {
    param([Parameter(Mandatory)]$Probe)
    $process = $Probe.Process
    $process.Refresh()
    if (-not $process.HasExited) {
        if ([datetime]::UtcNow -lt ([datetime]$Probe.DeadlineUtc)) { return $null }
        try { $process.Kill(); $null = $process.WaitForExit(5000) } catch { }
        return [pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='probe deadline exceeded';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null;exit_code=$null}
    }
    $process.Refresh()
    if ($null -eq $process.ExitCode) { return [pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='tsp exit code unavailable';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null;exit_code=$null} }
    $exitCode = [int]$process.ExitCode
    if ($exitCode -ne 0) { return [pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason="tsp exit code $exitCode";packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null;exit_code=$exitCode} }
    if (-not (Test-Path -LiteralPath $Probe.ReportPath -PathType Leaf)) { return [pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='missing report';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null;exit_code=$exitCode} }
    $item = Get-Item -LiteralPath $Probe.ReportPath
    if ($item.Length -le 0) { return [pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='empty report';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null;exit_code=$exitCode} }
    try { $json = Get-Content -LiteralPath $Probe.ReportPath -Raw | ConvertFrom-Json } catch { return [pscustomobject]@{label=$Probe.Label;port=[int]$Probe.Port;verdict='FAIL';reason='malformed report';packets=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null;exit_code=$exitCode} }
    return Get-Beta7TransportGrade -Json $json -Label $Probe.Label -Port ([int]$Probe.Port) -ExitCode $exitCode
}

function Stop-Beta7TransportProbe {
    param([Parameter(Mandatory)]$Probe)
    $process = $Probe.Process
    $process.Refresh()
    if (-not $process.HasExited) { $process.Kill(); $null = $process.WaitForExit(5000) }
}
