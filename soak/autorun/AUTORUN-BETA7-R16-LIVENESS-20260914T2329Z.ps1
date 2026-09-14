$ErrorActionPreference = "Stop"

$taskName = "CivicCast-Beta7-3e117ff1-OFF8H-R16-7B9E52"
$mission = "BETA7-3E117FF1-OFF8H-R16-7B9E52"
$jobRoot = "C:\CivicCastSoak\repo\soak\beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d\physical-soak-off8h-r16-7b9e52"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
$taskInfo = if ($null -ne $task) {
    Get-ScheduledTaskInfo -TaskName $taskName
}
else {
    $null
}

$missionProcesses = @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $null -ne $_.CommandLine -and
            ($_.CommandLine -like "*$mission*" -or $_.CommandLine -like "*$taskName*")
        } |
        Select-Object ProcessId, ParentProcessId, Name, CreationDate, CommandLine
)

$pythonProcesses = @(
    Get-Process -Name python, pythonservice -ErrorAction SilentlyContinue |
        Select-Object Id, ProcessName, StartTime, CPU, WorkingSet64
)

$jobPath = Join-Path $jobRoot "job.json"
$completionPath = Join-Path $jobRoot "COMPLETION.json"
$verdictPath = Join-Path $jobRoot "VERDICT.md"
$evidencePath = Join-Path $jobRoot "evidence.zip"
$job = if (Test-Path -LiteralPath $jobPath) {
    Get-Content -LiteralPath $jobPath -Raw | ConvertFrom-Json
}
else {
    $null
}

$result = [ordered]@{
    schema = "civiccast-beta7-r16-liveness-v1"
    checked_utc = (Get-Date).ToUniversalTime().ToString("o")
    hostname = $env:COMPUTERNAME
    mission_nonce = $mission
    scheduled_task = if ($null -ne $task) {
        [ordered]@{
            exists = $true
            state = [string]$task.State
            enabled = [bool]$task.Settings.Enabled
            last_run_time = $taskInfo.LastRunTime.ToUniversalTime().ToString("o")
            last_task_result = $taskInfo.LastTaskResult
            next_run_time = if ($taskInfo.NextRunTime -gt [datetime]::MinValue) {
                $taskInfo.NextRunTime.ToUniversalTime().ToString("o")
            }
            else {
                $null
            }
        }
    }
    else {
        [ordered]@{ exists = $false }
    }
    mission_processes = $missionProcesses
    python_processes = $pythonProcesses
    job_receipt_exists = Test-Path -LiteralPath $jobPath
    job_state = if ($null -ne $job) { $job.job_state } else { $null }
    measured_phase_begin_utc = if ($null -ne $job) { $job.measured_phase_begin_utc } else { $null }
    measured_phase_planned_end_utc = if ($null -ne $job) { $job.measured_phase_planned_end_utc } else { $null }
    completion_exists = Test-Path -LiteralPath $completionPath
    verdict_exists = Test-Path -LiteralPath $verdictPath
    evidence_exists = Test-Path -LiteralPath $evidencePath
}

$result | ConvertTo-Json -Depth 8
