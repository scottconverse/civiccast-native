# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
$ErrorActionPreference='Stop';Import-Module (Join-Path $PSScriptRoot 'ProbeContracts.psm1') -Force
$tmp=Join-Path ([IO.Path]::GetTempPath()) ('cc-filler-probe-'+[guid]::NewGuid().ToString('N'));New-Item -ItemType Directory $tmp|Out-Null
try{
  $zero=Join-Path $tmp 'zero.json';'{"ts":{"packets":{"total":0,"invalid-syncs":0,"transport-errors":0}},"pids":[{"packets":{"total":0,"discontinuities":0}}]}'|Set-Content $zero
  if((Read-TsVerdict $zero).verdict -ne 'fail-zero-packets'){throw 'zero packets accepted'}
  $clean=Join-Path $tmp 'clean.json';'{"ts":{"packets":{"total":42,"invalid-syncs":0,"transport-errors":0}},"pids":[{"packets":{"total":42,"discontinuities":0}}]}'|Set-Content $clean
  if((Read-TsVerdict $clean).verdict -ne 'pass'){throw 'clean TS rejected'}
  $errors=Join-Path $tmp 'errors.json';'{"ts":{"packets":{"total":42,"invalid-syncs":0,"transport-errors":1}},"pids":[{"packets":{"total":42,"discontinuities":0}}]}'|Set-Content $errors
  if((Read-TsVerdict $errors).verdict -ne 'fail-stream-errors'){throw 'TS errors accepted'}
  $bad=Join-Path $tmp 'bad.json';'{'|Set-Content $bad;if((Read-TsVerdict $bad).verdict -ne 'fail-unparsable-report'){throw 'malformed report accepted'}
  $nullCounter=Join-Path $tmp 'null-counter.json';'{"ts":{"packets":{"total":42,"invalid-syncs":null,"transport-errors":0}},"pids":[{"packets":{"total":42,"discontinuities":0}}]}'|Set-Content $nullCounter
  if((Read-TsVerdict $nullCounter).verdict -ne 'fail-invalid-invalid-syncs'){throw 'null counter accepted'}
  $missingPids=Join-Path $tmp 'missing-pids.json';'{"ts":{"packets":{"total":42,"invalid-syncs":0,"transport-errors":0}}}'|Set-Content $missingPids
  if((Read-TsVerdict $missingPids).verdict -ne 'fail-missing-pids'){throw 'missing pids accepted'}
  $emptyPids=Join-Path $tmp 'empty-pids.json';'{"ts":{"packets":{"total":42,"invalid-syncs":0,"transport-errors":0}},"pids":[]}'|Set-Content $emptyPids
  if((Read-TsVerdict $emptyPids).verdict -ne 'fail-missing-pids'){throw 'empty pids accepted'}
  $nonNumeric=Join-Path $tmp 'nonnumeric.json';'{"ts":{"packets":{"total":"many","invalid-syncs":0,"transport-errors":0}},"pids":[{"packets":{"total":42,"discontinuities":0}}]}'|Set-Content $nonNumeric
  if((Read-TsVerdict $nonNumeric).verdict -ne 'fail-invalid-total'){throw 'nonnumeric total accepted'}
  try{Assert-StablePid ([pscustomobject]@{pid=12}) 11;throw 'pid change accepted'}catch{if($_.Exception.Message -eq 'pid change accepted'){throw}}
  try{Assert-ExpectedVersion ([pscustomobject]@{version='wrong'}) '1.0.0-beta.5';throw 'version mismatch accepted'}catch{if($_.Exception.Message -eq 'version mismatch accepted'){throw}}
  $b=New-ScheduleBody asset-a test-channel ([datetime]'2026-09-08T12:00:00Z') 30 probe
  if($b.asset_id-ne'asset-a'-or$b.channel_id-ne'test-channel'-or$b.mode-ne'premiere'-or$b.duration_seconds-ne30-or$b.scheduled_at-ne'2026-09-08T12:00:00.0000000Z'){throw 'schedule request shape drift'}
  $c=New-CommitBody test-channel occ-1 item-1;if($c.channel_id-ne'test-channel'-or$c.occurrence_id-ne'occ-1'-or$c.schedule_item_id-ne'item-1'){throw 'commit request shape drift'}
  $n=New-BulletinBody run-1 13;if($n.title-ne'Probe slide 13'-or$n.target_zone_kind-ne'primary'){throw 'bulletin request shape drift'}
  $a=New-BulletinApprovalBody run-1;if($a.state-ne'accepted'-or$a.approved_by_operator-ne'run-1'){throw 'approval request shape drift'}
  $assets=@([pscustomobject]@{asset_id='a';title='Mission A';state='validated';manifest_url='/media/a.m3u8';published_at='2026-09-08T12:00:00Z'},[pscustomobject]@{asset_id='b';title='Draft';state='validated';manifest_url=$null;published_at=$null})
  if((Select-ApprovedAsset $assets 'Mission A').asset_id-ne'a'){throw 'approved asset selection drift'}
  try{Select-ApprovedAsset $assets 'Draft';throw 'unapproved asset accepted'}catch{if($_.Exception.Message-eq'unapproved asset accepted'){throw}}
  try{Select-ApprovedAsset @($assets[0],$assets[0]) 'Mission A';throw 'duplicate title accepted'}catch{if($_.Exception.Message-eq'duplicate title accepted'){throw}}
  $cfg=New-ProbeChannelConfigBody filler-probe 19091
  if($cfg.channel_id-ne'filler-probe'-or-not$cfg.enabled-or-not$cfg.auto_start-or$cfg.fill_policy-ne'bulletins'-or$cfg.sinks.Count-ne1-or$cfg.sinks[0].uri-ne'udp://127.0.0.1:19091'){throw 'probe channel config shape drift'}
  $sha='0123456789012345678901234567890123456789';$hash='a'*64
  $identity=[pscustomobject]@{schema='civiccast-native-tester-run-identity-v3';mission='beta5-sep8-012345678901';candidate_source_sha=$sha;expected_version='1.0.0-beta.5';installed_version='1.0.0-beta.5';expected_manifest_sha256=$hash;actual_manifest_sha256=$hash;expected_installer_sha256=$hash;actual_installer_sha256=$hash;native_app_payload_source_sha=$sha;expected_runtime_file_sha256=[pscustomobject]@{'pythonservice.exe'=$hash};actual_runtime_file_sha256=[pscustomobject]@{'pythonservice.exe'=$hash};approved_assets=@([pscustomobject]@{asset_id='a';duration_seconds=10;title='A'},[pscustomobject]@{asset_id='b';duration_seconds=10;title='B'})}
  $final=[pscustomobject]@{schema='civiccast-native-beta5-media-verdict-v3';mission=$identity.mission;candidate_source_sha=$sha;verdict='PASS';reason='';completed_utc='2026-09-08T12:00:00Z'}
  Assert-TesterEvidence $identity $final $sha '1.0.0-beta.5'
  $badFinal=$final.PSObject.Copy();$badFinal.verdict='FAIL';try{Assert-TesterEvidence $identity $badFinal $sha '1.0.0-beta.5';throw 'failed soak accepted'}catch{if($_.Exception.Message-eq'failed soak accepted'){throw}}
  $calls=@();$invoker={param($Method,$Path,$Body)$script:calls+=@("$Method $Path");if($Method-eq'Post'){throw 'stop failed'}}
  $cleanup=@(Invoke-ProbeCleanup $true filler-probe 19091 $invoker)
  if($calls.Count-ne2-or$calls[0]-notmatch'commands$'-or$calls[1]-notmatch'config$'-or$cleanup.Count-ne1){throw 'cleanup did not attempt both stop and disable after stop failure'}
  'ProbeContracts tests PASS'
}finally{Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue}
