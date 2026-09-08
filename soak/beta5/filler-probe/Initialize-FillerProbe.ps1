# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
[CmdletBinding()]
param(
 [Parameter(Mandatory)][ValidatePattern('^https?://')][string]$ApiBase,
 [Parameter(Mandatory)][ValidatePattern('^[a-z0-9][a-z0-9-]{2,63}$')][string]$ChannelId,
 [Parameter(Mandatory)][string]$BearerToken,
 [Parameter(Mandatory)][ValidatePattern('^[0-9a-fA-F]{40}$')][string]$ExpectedSha,
 [Parameter(Mandatory)][string]$ExpectedVersion,
 [Parameter(Mandatory)][string]$RunIdentityPath,
 [Parameter(Mandatory)][string]$FinalVerdictPath,
 [Parameter(Mandatory)][ValidateRange(1024,65535)][int]$UdpPort,
 [Parameter(Mandatory)][string]$TspExe,
 [switch]$LongBoard,[switch]$Execute
)
$ErrorActionPreference='Stop'
Import-Module (Join-Path $PSScriptRoot 'ProbeContracts.psm1') -Force
$base=$ApiBase.TrimEnd('/');$headers=@{Authorization="Bearer $BearerToken"}
$runId='setup-'+(Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out=Join-Path (Join-Path $PSScriptRoot 'results') $runId
New-Item -ItemType Directory -Force -Path $out|Out-Null
[ordered]@{run_id=$runId;api_base=$base;channel_id=$ChannelId;udp_port=$UdpPort;expected_sha=$ExpectedSha.ToLowerInvariant();expected_version=$ExpectedVersion;run_identity_path=$RunIdentityPath;final_verdict_path=$FinalVerdictPath;long_board=[bool]$LongBoard;execute=[bool]$Execute;token_recorded=$false}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $out 'SETUP-PLAN.json') -Encoding UTF8
if(-not$Execute){Write-Host "PLAN ONLY: $out";exit 0}

function Invoke-Api([string]$Method,[string]$Path,[object]$Body=$null){
 $a=@{Method=$Method;Uri="$base$Path";Headers=$headers;TimeoutSec=30}
 if($null-ne$Body){$a.ContentType='application/json';$a.Body=$Body|ConvertTo-Json -Depth 8}
 Invoke-RestMethod @a
}

$identityPath=(Resolve-Path -LiteralPath $RunIdentityPath).Path
$identity=Get-Content -LiteralPath $identityPath -Raw|ConvertFrom-Json
$verdict=Get-Content -LiteralPath (Resolve-Path -LiteralPath $FinalVerdictPath) -Raw|ConvertFrom-Json
Assert-TesterEvidence $identity $verdict $ExpectedSha.ToLowerInvariant() $ExpectedVersion
Assert-ExpectedVersion (Invoke-RestMethod -Method Get -Uri "$base/api/version" -TimeoutSec 20) $ExpectedVersion
if(@(Invoke-Api Get '/api/staff/egress/channels'|Where-Object{"$($_.channel_id)"-eq$ChannelId}).Count-ne0){throw "refusing to replace existing channel: $ChannelId"}

$assets=@();$offset=0
do{$page=@(Invoke-Api Get "/api/staff/assets?limit=500&offset=$offset");$assets+=$page;$offset+=500}while($page.Count-eq500)
$approved=@()
foreach($r in @($identity.approved_assets)){
 $match=@($assets|Where-Object{"$($_.asset_id)"-eq"$($r.asset_id)"-and"$($_.title)"-ceq"$($r.title)"-and"$($_.state)"-in@('validated','recorded')-and-not[string]::IsNullOrWhiteSpace("$($_.manifest_url)")-and$null-ne$_.published_at-and[int]$_.duration_seconds-eq[int]$r.duration_seconds})
 if($match.Count-ne1){throw "approved asset receipt does not match one playable API asset: $($r.asset_id)"};$approved+=$match[0]
}
if("$($approved[0].asset_id)"-eq"$($approved[1].asset_id)"){throw 'approved asset receipt repeats one asset'}
$programSeconds=[Math]::Min(30,[Math]::Min([int]$approved[0].duration_seconds,[int]$approved[1].duration_seconds))
if($programSeconds-lt5){throw 'approved assets are too short for the finite-program probe'}
[ordered]@{schema_version=1;recorded_at_utc=(Get-Date).ToUniversalTime().ToString('o');mission=$identity.mission;candidate_source_sha=$identity.candidate_source_sha;assets=@($approved|ForEach-Object{[ordered]@{asset_id="$($_.asset_id)";title="$($_.title)";state="$($_.state)";manifest_url="$($_.manifest_url)";published_at=$_.published_at;duration_seconds=$_.duration_seconds;content_hash=$_.content_hash}})}|ConvertTo-Json -Depth 8|Set-Content -LiteralPath (Join-Path $out 'IDENTITY-APPROVED-ASSETS.json') -Encoding UTF8

$created=$false;$acceptanceExit=2;$primaryError=$null;$saved=$null;$state=$null
try{
 $saved=Invoke-Api Put "/api/staff/egress/channels/$ChannelId/config" (New-ProbeChannelConfigBody $ChannelId $UdpPort);$created=$true
 $null=Invoke-Api Post "/api/staff/egress/channels/$ChannelId/commands" ([ordered]@{action='start'})
 $deadline=(Get-Date).ToUniversalTime().AddSeconds(90)
 do{Start-Sleep -Seconds 2;$state=Invoke-Api Get "/api/staff/egress/channels/$ChannelId/state"}while(((Get-Date).ToUniversalTime()-lt$deadline)-and($null-eq$state-or$state.state-notin@('ON_AIR','FALLBACK_SLATE')))
 if($null-eq$state-or$state.state-notin@('ON_AIR','FALLBACK_SLATE')){throw "dedicated channel did not start: $($state.state)"}
 $a=@('-NoProfile','-File',(Join-Path $PSScriptRoot 'Invoke-FillerAcceptance.ps1'),'-ApiBase',$base,'-ChannelId',$ChannelId,'-BearerToken',$BearerToken,'-FirstAssetId',"$($approved[0].asset_id)",'-SecondAssetId',"$($approved[1].asset_id)",'-FirstSourceLabel',"$($approved[0].title)",'-SecondSourceLabel',"$($approved[1].title)",'-ExpectedSha',$ExpectedSha,'-ExpectedVersion',$ExpectedVersion,'-InstallReceiptPath',$identityPath,'-UdpPort',"$UdpPort",'-TspExe',$TspExe,'-LeadSeconds','120','-ProgramSeconds',"$programSeconds",'-Execute')
 if($LongBoard){$a+='-LongBoard'};& powershell.exe @a;$acceptanceExit=$LASTEXITCODE
}catch{$primaryError="$($_.Exception.GetType().Name): $($_.Exception.Message)"}
finally{$cleanupErrors=@(Invoke-ProbeCleanup $created $ChannelId $UdpPort ${function:Invoke-Api})}
[ordered]@{configured_channel=$saved;initial_state=$state;acceptance_exit_code=$acceptanceExit;primary_error=$primaryError;cleanup_errors=$cleanupErrors;retained_channel_disabled=($created-and$cleanupErrors.Count-eq0);asset_evidence=(Join-Path $out 'IDENTITY-APPROVED-ASSETS.json')}|ConvertTo-Json -Depth 10|Set-Content -LiteralPath (Join-Path $out 'SETUP-RESULT.json') -Encoding UTF8
if($null-ne$primaryError-or$cleanupErrors.Count-gt0){exit 2};exit $acceptanceExit
