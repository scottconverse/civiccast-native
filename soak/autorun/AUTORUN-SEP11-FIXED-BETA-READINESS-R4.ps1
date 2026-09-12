# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$SelfTest)
$ErrorActionPreference = 'Stop'
function Convert-ReadinessJson($Report) {
    $json = $Report | ConvertTo-Json -Depth 5 -Compress
    if ($json.Length -gt 65536) { throw 'Readiness report unexpectedly exceeds 64 KiB.' }
    return $json
}
if ($SelfTest) {
    # Get-Content strings carry provider metadata in Windows PowerShell 5.1.
    # Materialize fresh strings instead of serializing those extended objects.
    $fixture = @(Get-Content -LiteralPath $PSCommandPath -TotalCount 3 | ForEach-Object { [string]::Concat('', [string]$_) })
    $json = Convert-ReadinessJson @{lines=$fixture;tasks=@(@{name='test';state='Ready'})}
    if ($json -match 'PSProvider|PSDrive|PSPath|ImplementingType') { throw 'Provider metadata leaked into JSON.' }
    $roundTrip = $json | ConvertFrom-Json
    if ($roundTrip.lines.Count -ne 3 -or $roundTrip.tasks[0].state -ne 'Ready') { throw 'Scalar report round trip failed.' }
    Write-Output 'PASS: PS5.1 decorated-content serialization is bounded and round-trips.'
    exit 0
}
if ($env:COMPUTERNAME -ine 'DESKTOP-VBMA6O5') { throw 'This order targets DESKTOP-VBMA6O5 only.' }
$root = 'C:\CivicCastSoak'
$report = [ordered]@{
    order='SEP11-FIXED-BETA-READINESS-R4'; hostname=[string]$env:COMPUTERNAME
    utc=[datetime]::UtcNow.ToString('o'); station_changes=$false
    candidate_source_sha='39e7ec3cbb4ccbeb3009ff3257dfc314010151f3'
    errors=@()
}
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $report.free_ram_mb = [math]::Round([double]$os.FreePhysicalMemory / 1024)
    $disk = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"
    $report.free_disk_gb = [math]::Round([double]$disk.FreeSpace / 1GB, 1)
} catch { $report.errors += 'system:' + $_.Exception.GetType().Name }
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
$report.administrator = [bool]$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$report.token_file_present = [bool](Test-Path -LiteralPath "$root\state\token" -PathType Leaf)
$report.legacy_soak_started = [bool](Test-Path -LiteralPath "$root\state\soak-started")
$report.install_root_present = [bool](Test-Path -LiteralPath 'C:\CivicCastHostStore\install' -PathType Container)
$report.tasks = @()
try {
    foreach ($task in @(Get-ScheduledTask | Where-Object { $_.TaskName -like 'CivicCastSoak-*' -or $_.TaskName -like 'CivicCast-Beta5-*' })) {
        $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath
        $report.tasks += @{name=[string]$task.TaskName;state=[string]$task.State;enabled=[bool]$task.Settings.Enabled;last_result=[long]$info.LastTaskResult}
    }
} catch { $report.errors += 'tasks:' + $_.Exception.GetType().Name }
$report.services = @()
foreach ($service in @(Get-Service -Name '*CivicCast*' -ErrorAction SilentlyContinue)) {
    $report.services += @{name=[string]$service.Name;state=[string]$service.Status}
}
$report.tools = @()
foreach ($name in @('git','curl','tar','tsp')) {
    $command = Get-Command "$name.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
    $report.tools += @{name=$name;path=$(if ($command) {[string]$command.Source} else {''})}
}
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 5
    $report.health = @{status=[string]$health.status;version=[string]$health.version;schema=[string]$health.schema}
} catch { $report.errors += 'health:' + $_.Exception.GetType().Name }
try {
    $response = Invoke-WebRequest 'http://192.168.0.135:8766/SHA256SUMS.txt' -UseBasicParsing -TimeoutSec 10
    $report.lan_manifest = @{http_status=[int]$response.StatusCode;characters=([string]$response.Content).Length}
} catch { $report.errors += 'lan_manifest:' + $_.Exception.GetType().Name }
$report.poll_tail = @(Get-Content -LiteralPath "$root\reports\poll.log" -Tail 6 -ErrorAction SilentlyContinue | ForEach-Object { [string]::Concat('', [string]$_) })
Write-Output 'FIXED_BETA_READINESS_R4_JSON_BEGIN'
Write-Output (Convert-ReadinessJson $report)
Write-Output 'FIXED_BETA_READINESS_R4_JSON_END'
