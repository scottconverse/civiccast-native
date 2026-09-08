# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
function Read-TsVerdict {
    param([Parameter(Mandatory=$true)][string]$Path,[int]$ExitCode=0)
    $r=[ordered]@{verdict='fail-no-report';packets_total=$null;invalid_syncs=$null;transport_errors=$null;discontinuities=$null}
    if($ExitCode-ne0){$r.verdict="fail-exit-$ExitCode";return $r}
    if(-not(Test-Path -LiteralPath $Path)){return $r}
    try{$j=Get-Content -LiteralPath $Path -Raw|ConvertFrom-Json -ErrorAction Stop}catch{$r.verdict='fail-unparsable-report';return $r}
    if(-not $j.ts -or -not $j.ts.packets){$r.verdict='fail-no-ts-packets-node';return $r}
    $names=@($j.ts.packets.PSObject.Properties.Name)
    foreach($required in 'total','invalid-syncs','transport-errors'){
        if($names-notcontains$required){$r.verdict="fail-missing-$required";return $r}
        $raw="$($j.ts.packets.$required)";if($raw-notmatch'^\d+$'){$r.verdict="fail-invalid-$required";return $r}
    }
    $total=[int64]$j.ts.packets.total;$invalid=[int64]$j.ts.packets.'invalid-syncs';$transport=[int64]$j.ts.packets.'transport-errors'
    $pids=@(@($j.pids)|Where-Object{$null-ne$_});if($pids.Count-lt1){$r.verdict='fail-missing-pids';return $r}
    $disc=0;foreach($p in $pids){
        if(-not $p.packets){$r.verdict='fail-missing-pid-packets';return $r};$pn=@($p.packets.PSObject.Properties.Name)
        foreach($required in 'total','discontinuities'){if($pn-notcontains$required){$r.verdict="fail-missing-pid-$required";return $r};$raw="$($p.packets.$required)";if($raw-notmatch'^\d+$'){$r.verdict="fail-invalid-pid-$required";return $r}}
        $disc+=[int64]$p.packets.discontinuities
    }
    $r.packets_total=$total;$r.invalid_syncs=$invalid;$r.transport_errors=$transport;$r.discontinuities=$disc
    if($total-le0){$r.verdict='fail-zero-packets'}elseif($r.invalid_syncs-eq0-and$r.transport_errors-eq0-and$disc-eq0){$r.verdict='pass'}else{$r.verdict='fail-stream-errors'}
    return $r
}
function Assert-ExpectedVersion { param($Response,[string]$Expected) if("$($Response.version)"-ne$Expected){throw "installed version mismatch: actual=$($Response.version) expected=$Expected"} }
function Assert-StablePid { param($State,[int64]$ExpectedPid) if($null-eq$State.pid-or[int64]$State.pid-ne$ExpectedPid){throw "GStreamer PID changed: initial=$ExpectedPid current=$($State.pid)"} }
function New-ScheduleBody { param([string]$AssetId,[string]$ChannelId,[datetime]$When,[int]$Duration,[string]$Notes) [ordered]@{asset_id=$AssetId;channel_id=$ChannelId;mode='premiere';scheduled_at=$When.ToUniversalTime().ToString('o');duration_seconds=$Duration;notes=$Notes} }
function New-CommitBody { param([string]$ChannelId,[string]$OccurrenceId,[string]$ScheduleItemId) [ordered]@{channel_id=$ChannelId;occurrence_id=$OccurrenceId;schedule_item_id=$ScheduleItemId} }
function New-BulletinBody { param([string]$RunId,[int]$Index) [ordered]@{organization='CivicCast Test';submitter_label=$RunId;title=("Probe slide {0:D2}"-f$Index);message=("Installed-runtime rotation marker {0:D2} of 13"-f$Index);target_zone_kind='primary'} }
function New-BulletinApprovalBody { param([string]$RunId) [ordered]@{state='accepted';approved_by_operator=$RunId} }
Export-ModuleMember -Function Read-TsVerdict,Assert-ExpectedVersion,Assert-StablePid,New-ScheduleBody,New-CommitBody,New-BulletinBody,New-BulletinApprovalBody
