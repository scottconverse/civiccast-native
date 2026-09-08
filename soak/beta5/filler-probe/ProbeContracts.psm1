# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
function Read-TsVerdict {
    param([Parameter(Mandatory=$true)][string]$Path,[int]$ExitCode=0)
    $r=[ordered]@{verdict='fail-no-report';packets_total=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null}
    if($ExitCode -ne 0){$r.verdict="fail-exit-$ExitCode";return $r}
    if(-not(Test-Path -LiteralPath $Path)){return $r}
    try{$j=Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json -ErrorAction Stop}catch{$r.verdict='fail-unparsable-report';return $r}
    if(-not $j.ts -or -not $j.ts.packets){$r.verdict='fail-no-ts-packets-node';return $r}
    $names=@($j.ts.packets.PSObject.Properties.Name)
    foreach($required in 'total','invalid-syncs','transport-errors'){
        if($names -notcontains $required){$r.verdict="fail-missing-$required";return $r}
        $raw="$($j.ts.packets.$required)";if($raw -notmatch '^\d+$'){$r.verdict="fail-invalid-$required";return $r}
    }
    try{$total=[int64]$j.ts.packets.total;$invalid=[int64]$j.ts.packets.'invalid-syncs';$transport=[int64]$j.ts.packets.'transport-errors'}catch{$r.verdict='fail-counter-out-of-range';return $r}
    $pids=@(@($j.pids)|Where-Object{$null -ne $_});if($pids.Count -lt 1){$r.verdict='fail-missing-pids';return $r}
    $disc=0;foreach($p in $pids){
        if(-not $p.packets){$r.verdict='fail-missing-pid-packets';return $r};$pn=@($p.packets.PSObject.Properties.Name)
        foreach($required in 'total','discontinuities'){if($pn -notcontains $required){$r.verdict="fail-missing-pid-$required";return $r};$raw="$($p.packets.$required)";if($raw -notmatch '^\d+$'){$r.verdict="fail-invalid-pid-$required";return $r}}
        try{$disc += [int64]$p.packets.discontinuities}catch{$r.verdict='fail-pid-counter-out-of-range';return $r}
    }
    $r.packets_total=$total;$r.invalid_syncs=$invalid;$r.transport_errors=$transport;$r.discontinuities=$disc
    if($total -le 0){$r.verdict='fail-zero-packets'}elseif($r.invalid_syncs -eq 0 -and $r.transport_errors -eq 0 -and $disc -eq 0){$r.verdict='pass'}else{$r.verdict='fail-stream-errors'}
    return $r
}
function Assert-ExpectedVersion { param($Response,[string]$Expected) if("$($Response.version)" -ne $Expected){throw "installed version mismatch: actual=$($Response.version) expected=$Expected"} }
function Assert-StablePid { param($State,[int64]$ExpectedPid) if($null -eq $State.pid -or [int64]$State.pid -ne $ExpectedPid){throw "GStreamer PID changed: initial=$ExpectedPid current=$($State.pid)"} }
function New-ScheduleBody { param([string]$AssetId,[string]$ChannelId,[datetime]$When,[int]$Duration,[string]$Notes) [ordered]@{asset_id=$AssetId;channel_id=$ChannelId;mode='premiere';scheduled_at=$When.ToUniversalTime().ToString('o');duration_seconds=$Duration;notes=$Notes} }
function New-CommitBody { param([string]$ChannelId,[string]$OccurrenceId,[string]$ScheduleItemId) [ordered]@{channel_id=$ChannelId;occurrence_id=$OccurrenceId;schedule_item_id=$ScheduleItemId} }
function New-BulletinBody { param([string]$RunId,[int]$Index) [ordered]@{organization='CivicCast Test';submitter_label=$RunId;title=("Probe slide {0:D2}" -f $Index);message=("Installed-runtime rotation marker {0:D2} of 13" -f $Index);target_zone_kind='primary'} }
function New-BulletinApprovalBody { param([string]$RunId) [ordered]@{state='accepted';approved_by_operator=$RunId} }
function Select-ApprovedAsset {
    param([Parameter(Mandatory=$true)][object[]]$Assets,[Parameter(Mandatory=$true)][string]$Title)
    $matches=@($Assets|Where-Object{"$($_.title)" -ceq $Title -and "$($_.state)" -in @('validated','recorded') -and -not [string]::IsNullOrWhiteSpace("$($_.manifest_url)") -and $null -ne $_.published_at})
    if($matches.Count -ne 1){throw "expected exactly one published packaged asset titled '$Title'; found $($matches.Count)"}
    return $matches[0]
}
function New-ProbeChannelConfigBody {
    param([Parameter(Mandatory=$true)][string]$ChannelId,[Parameter(Mandatory=$true)][int]$UdpPort,[bool]$Enabled=$true)
    [ordered]@{channel_id=$ChannelId;enabled=$Enabled;auto_start=$true;allow_software_fallback=$true;fill_policy='bulletins';sinks=@([ordered]@{kind='udp-ts';label='Filler probe loopback';uri="udp://127.0.0.1:$UdpPort"});slate_message='CivicCast installed-runtime filler acceptance probe'}
}
function Assert-TesterEvidence {
    param([Parameter(Mandatory=$true)]$Identity,[Parameter(Mandatory=$true)]$FinalVerdict,[Parameter(Mandatory=$true)][string]$ExpectedSha,[Parameter(Mandatory=$true)][string]$ExpectedVersion)
    if("$($Identity.schema)" -ne 'civiccast-native-tester-run-identity-v3'){throw 'unexpected run identity schema'}
    if("$($FinalVerdict.schema)" -ne 'civiccast-native-beta5-media-verdict-v3'){throw 'unexpected final verdict schema'}
    if("$($FinalVerdict.verdict)" -ne 'PASS'){throw "normal three-channel soak is not PASS: $($FinalVerdict.verdict)"}
    if("$($Identity.candidate_source_sha)" -ne $ExpectedSha -or "$($FinalVerdict.candidate_source_sha)" -ne $ExpectedSha){throw 'candidate source SHA mismatch'}
    if("$($FinalVerdict.mission)" -ne "$($Identity.mission)"){throw 'final verdict mission does not match run identity'}
    if("$($Identity.expected_version)" -ne $ExpectedVersion -or "$($Identity.installed_version)" -ne $ExpectedVersion){throw 'installed version does not match expected version'}
    foreach($pair in @(@('manifest',$Identity.expected_manifest_sha256,$Identity.actual_manifest_sha256),@('installer',$Identity.expected_installer_sha256,$Identity.actual_installer_sha256))){if("$($pair[1])" -notmatch '^[0-9a-fA-F]{64}$' -or "$($pair[2])" -ne "$($pair[1])"){throw "$($pair[0]) hash receipt mismatch"}}
    if("$($Identity.native_app_payload_source_sha)" -ne $ExpectedSha){throw 'installed native payload source SHA mismatch'}
    $expected=$Identity.expected_runtime_file_sha256;$actual=$Identity.actual_runtime_file_sha256
    if($null-eq$expected-or$null-eq$actual){throw 'runtime file hash receipts are missing'}
    $names=@($expected.PSObject.Properties.Name);if($names.Count-lt1){throw 'runtime file hash receipt is empty'}
    foreach($name in $names){$e="$($expected.$name)";$p=$actual.PSObject.Properties[$name];if($e-notmatch'^[0-9a-fA-F]{64}$'-or$null-eq$p-or"$($p.Value)"-ne$e){throw "runtime file hash mismatch: $name"}}
    if(@($Identity.approved_assets).Count-ne2){throw 'run identity must contain exactly two approved assets'}
}
function Invoke-ProbeCleanup {
    param([bool]$Created,[Parameter(Mandatory=$true)][string]$ChannelId,[Parameter(Mandatory=$true)][int]$UdpPort,[Parameter(Mandatory=$true)][scriptblock]$ApiInvoker)
    if(-not$Created){return @()};$errors=@()
    try{&$ApiInvoker Post "/api/staff/egress/channels/$ChannelId/commands" ([ordered]@{action='stop'})|Out-Null}catch{$errors+="stop: $($_.Exception.Message)"}
    try{&$ApiInvoker Put "/api/staff/egress/channels/$ChannelId/config" (New-ProbeChannelConfigBody $ChannelId $UdpPort $false)|Out-Null}catch{$errors+="disable: $($_.Exception.Message)"}
    return $errors
}
Export-ModuleMember -Function Read-TsVerdict,Assert-ExpectedVersion,Assert-StablePid,New-ScheduleBody,New-CommitBody,New-BulletinBody,New-BulletinApprovalBody,Select-ApprovedAsset,New-ProbeChannelConfigBody,Assert-TesterEvidence,Invoke-ProbeCleanup
