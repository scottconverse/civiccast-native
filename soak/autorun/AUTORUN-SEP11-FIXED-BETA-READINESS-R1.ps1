# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$DryRun)
$ErrorActionPreference = 'Stop'
$expectedHost = 'DESKTOP-VBMA6O5'
$candidate = '39e7ec3cbb4ccbeb3009ff3257dfc314010151f3'
if ($DryRun) {
    [ordered]@{order='SEP11-FIXED-BETA-READINESS-R1';target=$expectedHost;candidate=$candidate;station_changes=$false;secret_contents_read=$false} | ConvertTo-Json
    exit 0
}
if ($env:COMPUTERNAME -ine $expectedHost) { throw 'This readiness order targets DESKTOP-VBMA6O5 only.' }
$root = 'C:\CivicCastSoak'
$report = [ordered]@{order='SEP11-FIXED-BETA-READINESS-R1';hostname=$env:COMPUTERNAME;utc=[DateTime]::UtcNow.ToString('o');candidate_source_sha=$candidate;station_changes=$false}
$os = Get-CimInstance Win32_OperatingSystem
$system = Get-CimInstance Win32_ComputerSystem
$report.os = [ordered]@{caption=$os.Caption;version=$os.Version;build=$os.BuildNumber;total_ram_gb=[math]::Round($system.TotalPhysicalMemory/1GB,1);free_ram_mb=[math]::Round($os.FreePhysicalMemory/1KB);logical_processors=$system.NumberOfLogicalProcessors}
$report.cpu = @(Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors)
$report.disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Select-Object DeviceID,@{n='free_gb';e={[math]::Round($_.FreeSpace/1GB,1)}})
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$report.administrator = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$report.ipv4 = @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254*'} | Select-Object IPAddress,InterfaceAlias)
$report.tasks = @(Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object {$_.TaskName -like 'CivicCastSoak-*' -or $_.TaskName -like 'CivicCast-Beta5-*' -or $_.TaskName -match 'GateA|BetaReleaseRunner'} | ForEach-Object {
    $task = $_
    $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath
    [pscustomobject]@{name=$task.TaskName;state=$task.State.ToString();last_run=$info.LastRunTime;last_result=$info.LastTaskResult;executables=@($task.Actions.Execute)}
})
$report.poll_tail = @(Get-Content -LiteralPath (Join-Path $root 'reports\poll.log') -Tail 12 -ErrorAction SilentlyContinue | Where-Object {$_ -match 'current=|EXECUTING |FINISHED |FETCH FAILED|suppressed'})
$report.done_orders = @(Get-ChildItem -LiteralPath (Join-Path $root 'state\autorun-done') -File -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
$report.soak_started = Test-Path -LiteralPath (Join-Path $root 'state\soak-started')
$report.token_file_present = Test-Path -LiteralPath (Join-Path $root 'state\token')
$report.tools = @('git','gh','python','uv','tsp','ssh','WindowsSandbox') | ForEach-Object {
    $tool = Get-Command $_ -ErrorAction SilentlyContinue | Select-Object -First 1
    [pscustomobject]@{name=$_;path=$(if($tool){$tool.Source}else{$null})}
}
$report.services = @(Get-CimInstance Win32_Service | Where-Object {$_.Name -match 'CivicCast|^sshd$|actions.runner'} | Select-Object Name,State,StartMode)
$report.installed_version = $(try {Get-ItemPropertyValue -LiteralPath 'HKLM:\Software\CivicCast\Native' -Name InstalledVersion -ErrorAction Stop} catch {$null})
$report.health = $(try {Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 5 | Select-Object status,version,schema,schema_db_revision,schema_expected_head,mode} catch {@{status='unreachable';error_type=$_.Exception.GetType().Name}})
$report.kit_locations = @('C:\CivicCastTester','C:\CivicCastSoak','C:\CivicCastSoak\kits','C:\CivicCastSoak\missions','C:\CivicCastSoak\bin','C:\ProgramData\CivicCast') | ForEach-Object {
    [pscustomobject]@{path=$_;exists=(Test-Path -LiteralPath $_);children=@(Get-ChildItem -LiteralPath $_ -ErrorAction SilentlyContinue | Select-Object -First 25 -ExpandProperty Name)}
}
$report.bin_scripts = @(Get-ChildItem -LiteralPath (Join-Path $root 'bin') -Filter '*.ps1' -File -ErrorAction SilentlyContinue | ForEach-Object {[pscustomobject]@{name=$_.Name;sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash}})
$report.sandbox = $(try {(Get-WindowsOptionalFeature -Online -FeatureName Containers-DisposableClientVM -ErrorAction Stop).State.ToString()} catch {'unavailable-or-not-elevated'})
Write-Output 'FIXED_BETA_READINESS_JSON_BEGIN'
$report | ConvertTo-Json -Depth 7
Write-Output 'FIXED_BETA_READINESS_JSON_END'
