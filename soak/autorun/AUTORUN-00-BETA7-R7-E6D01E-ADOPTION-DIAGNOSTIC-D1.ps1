# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param([switch]$SelfTest)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

$expectedHost='DESKTOP-VBMA6O5'
$expectedMission='BETA7-3E117FF1-OFF4H-R7-E6D01E'
$missionRoot='C:\CivicCastSoak\missions\beta7-3e117ff1-off4h-r7-e6d01e'
$upgradeResult=Join-Path $missionRoot 'upgrade-result.json'

function Convert-R7UpgradeResultJson {
    param([Parameter(Mandatory)][string]$Raw)
    if([Text.Encoding]::UTF8.GetByteCount($Raw) -gt 262144){throw 'R7 upgrade result exceeds the 256 KiB diagnostic bound.'}
    try{return $Raw|ConvertFrom-Json}catch{throw 'R7 upgrade result is not valid JSON.'}
}

function Get-R7AdoptionFailureReport {
    param([Parameter(Mandatory)][string]$Path)
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)){
        return [ordered]@{status='MISSING';path=$Path;sha256=$null;length=$null;report=$null}
    }
    $item=Get-Item -LiteralPath $Path
    $raw=Get-Content -LiteralPath $Path -Raw
    $parsed=Convert-R7UpgradeResultJson -Raw $raw
    return [ordered]@{
        status='COLLECTED'
        path=$Path
        sha256=(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
        length=[long]$item.Length
        report=$parsed
    }
}

if($SelfTest){
    if($expectedHost -cne 'DESKTOP-VBMA6O5' -or $expectedMission -cne 'BETA7-3E117FF1-OFF4H-R7-E6D01E' -or $missionRoot -cne 'C:\CivicCastSoak\missions\beta7-3e117ff1-off4h-r7-e6d01e'){
        throw 'Diagnostic identity is not bound to the failed R7 mission.'
    }
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($PSCommandPath,[ref]$tokens,[ref]$errors)
    if(@($errors).Count){throw 'R7 adoption diagnostic has parse errors.'}
    $text=Get-Content -LiteralPath $PSCommandPath -Raw
    foreach($required in @($expectedHost,$expectedMission,$missionRoot,'upgrade-result.json','station_changes=$false')){
        if($text.IndexOf($required,[StringComparison]::Ordinal) -lt 0){throw "Diagnostic lost required binding: $required"}
    }
    foreach($token in @('$entryLimit=64','Select-Object -First $entryLimit','mission_entries_truncated=($entryTotal -gt $entryLimit)','UTF8.GetByteCount($json) -gt 393216')){
        if([regex]::Matches($text,[regex]::Escape($token)).Count -ne 2){throw "Diagnostic lost its live output bound: $token"}
    }
    $allowedCommands=@('ConvertFrom-Json','ConvertTo-Json','Convert-R7UpgradeResultJson','ForEach-Object','Get-ChildItem','Get-Content','Get-FileHash','Get-Item','Get-R7AdoptionFailureReport','Join-Path','Select-Object','Set-StrictMode','Sort-Object','Test-Path','Where-Object','Write-Output')
    $commands=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.CommandAst]},$true)|ForEach-Object{$_.GetCommandName()}|Where-Object{$_})
    $unknownCommands=@($commands|Where-Object{$allowedCommands -cnotcontains $_}|Select-Object -Unique)
    if($unknownCommands.Count){throw "Diagnostic contains a command outside its read-only allowlist: $($unknownCommands -join ', ')"}
    $allowedTypes=@('datetime','long','Management.Automation.Language.CommandAst','Management.Automation.Language.Parser','Management.Automation.Language.TypeExpressionAst','Parameter','regex','string','StringComparison','Text.Encoding')
    $types=@($ast.FindAll({param($node)$node -is [Management.Automation.Language.TypeExpressionAst]},$true)|ForEach-Object{$_.TypeName.FullName}|Where-Object{$_}|Select-Object -Unique)
    $unknownTypes=@($types|Where-Object{$allowedTypes -cnotcontains $_})
    if($unknownTypes.Count){throw "Diagnostic contains a type outside its read-only allowlist: $($unknownTypes -join ', ')"}
    $result=Convert-R7UpgradeResultJson -Raw '{"status":"FAIL","error":"fixture"}'
    if([string]$result.status -cne 'FAIL' -or [string]$result.error -cne 'fixture'){throw 'Diagnostic JSON fixture did not round-trip exactly.'}
    $missing=Get-R7AdoptionFailureReport -Path ($PSCommandPath+'.missing')
    if($missing.status -cne 'MISSING' -or $null -ne $missing.report){throw 'Diagnostic missing-file fixture did not fail closed.'}
    [pscustomobject]@{verdict='PASS';runtime=$PSVersionTable.PSEdition;version=$PSVersionTable.PSVersion.ToString();station_changes=$false;network_calls=0;task_changes=0}|ConvertTo-Json -Compress
    return
}

if($env:COMPUTERNAME -ine $expectedHost){throw "This diagnostic targets $expectedHost only."}
$collected=Get-R7AdoptionFailureReport -Path $upgradeResult
$entries=@()
$entryTotal=0
$entryLimit=64
if(Test-Path -LiteralPath $missionRoot -PathType Container){
    $allEntries=@(Get-ChildItem -LiteralPath $missionRoot -Force|Sort-Object Name)
    $entryTotal=$allEntries.Count
    $entries=@($allEntries|Select-Object -First $entryLimit|ForEach-Object{[ordered]@{name=$_.Name;kind=if($_.PSIsContainer){'directory'}else{'file'};length=if($_.PSIsContainer){$null}else{[long]$_.Length};last_write_utc=$_.LastWriteTimeUtc.ToString('o')}})
}
$output=[ordered]@{
    schema='civiccast-beta7-r7-adoption-diagnostic-v1'
    expected_host=$expectedHost
    hostname=[string]$env:COMPUTERNAME
    mission_nonce=$expectedMission
    captured_utc=[datetime]::UtcNow.ToString('o')
    station_changes=$false
    network_calls=0
    task_changes=0
    mission_root_exists=(Test-Path -LiteralPath $missionRoot -PathType Container)
    mission_entry_total=$entryTotal
    mission_entry_limit=$entryLimit
    mission_entries_truncated=($entryTotal -gt $entryLimit)
    mission_entries=$entries
    upgrade_result=$collected
}
$json=$output|ConvertTo-Json -Depth 16 -Compress
if([Text.Encoding]::UTF8.GetByteCount($json) -gt 393216){throw 'Final R7 adoption diagnostic exceeds the 384 KiB output bound.'}
Write-Output 'BETA7_R7_ADOPTION_DIAGNOSTIC_JSON_BEGIN'
Write-Output $json
Write-Output 'BETA7_R7_ADOPTION_DIAGNOSTIC_JSON_END'
