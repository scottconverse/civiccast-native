# Candidate-specific release identity guard. It must pass before any tester mutation.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$IdentityPath)
$ErrorActionPreference='Stop'
$raw=Get-Content -LiteralPath $IdentityPath -Raw
$placeholders=@([regex]::Matches($raw,'__[A-Z0-9_]+__') | ForEach-Object {$_.Value} | Sort-Object -Unique)
if($placeholders.Count){throw "Finalized candidate identity contains unresolved placeholders: $($placeholders -join ', ')"}
. (Join-Path $PSScriptRoot 'Beta7Tester.Common.ps1')
$id=Get-Beta5Identity $IdentityPath
$sha='3e117ff1fa9e06873ecec5b5b07f1360bc8b228d'
$manifest='2af18a8f5bea094cdf7af248eae04be58501e8a390a3099450500819e38d8eb8'
$installer='07fc5259514a3e98164869efbbd9c5bdfb7d83dfe6a96c61d15795c6ace77a97'
foreach($field in @('candidate_source_sha','build_source_sha','gate_a_source_sha')){
    if([string]$id.$field -cne $sha){throw "Exact-candidate field $field does not equal $sha."}
}
if([string]$id.build_run_id -cne '34762831824' -or [string]$id.build_conclusion -cne 'success'){throw 'Build identity is not exact successful run 34762831824.'}
if([string]$id.expected_manifest_sha256 -cne $manifest){throw 'Whole-kit manifest hash is not the verified 3e117ff1 manifest.'}
if([string]$id.expected_installer_sha256 -cne $installer){throw 'Installer hash is not the verified 3e117ff1 installer.'}
if([string]$id.expected_version -cne '1.0.0-beta.7'){throw 'Version is not exactly 1.0.0-beta.7.'}
if([string]$id.expected_authenticode_status -cne 'Valid' -or [string]$id.expected_installer_signer -cne 'Scott Converse'){throw 'Expected installer trust identity is not exact.'}
if([string]$id.gate_a_run_id -cne '34772707033' -or [string]$id.gate_a_verdict -cne 'PASS'){throw 'Gate A identity is not exact successful run 34772707033.'}
if([string]$id.mission_nonce -cne 'BETA7-3E117FF1-OFF4H-R7-E6D01E'){throw 'Mission nonce mismatch.'}
if([string]$id.task_name -cne 'CivicCast-Beta7-3e117ff1-OFF4H-R7-E6D01E'){throw 'Scheduled-task identity mismatch.'}
if([string]$id.evidence_relative_root -cne 'soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off4h-r7-e6d01e'){throw 'Evidence-root identity mismatch.'}
if([int]$id.minutes_per_phase -ne 240 -or [int]$id.planned_seconds -ne 14400){throw 'Mission is not bound to one four-hour captions-OFF phase.'}
$topology=@($id.expected_elements_per_phase.OFF.PSObject.Properties)
if($topology.Count -ne 3 -or @($topology|Where-Object{@($_.Value).Count -ne 1 -or [int]@($_.Value)[0] -ne 146}).Count){throw 'Physical topology must require exactly elements=146 on all three channels.'}
if("$($id.topology_provenance.evidence_path)" -cne 'docs/evidence/soak-2026-09-09-beta5/blackwell-evidence.zip' -or "$($id.topology_provenance.evidence_sha256)" -cne '685a20a351d4569d8b16aebc0b75718d1cdd7e977aa35d415fdb5842ea319bae' -or -not[bool]$id.topology_provenance.current_candidate_must_reestablish_before_measurement){throw 'Topology provenance is not bound to the preserved historical Blackwell baseline and current-run reestablishment.'}
$failed=@($id.topology_provenance.known_failed_elements|ForEach-Object{[int]$_}|Sort-Object -Unique)
if(($failed -join ',') -cne '33,56,74'){throw 'Known failed topology counts must be exactly 33, 56, and 74.'}
if("$($id.expected_harness_manifest_sha256)" -notmatch '^[0-9a-f]{64}$' -or "$($id.expected_harness_manifest_sha256)" -ceq ('0' * 64) -or "$($id.harness_source_commit)" -notmatch '^[0-9a-f]{40}$' -or "$($id.harness_source_commit)" -ceq ('0' * 40)){throw 'Harness manifest/source provenance is absent, zero, or invalid.'}
if("$($id.r5_invalidation_receipt_sha256)" -notmatch '^[0-9a-f]{64}$' -or "$($id.r5_invalidation_receipt_sha256)" -ceq ('0' * 64) -or "$($id.r5_invalidation_remote_commit)" -notmatch '^[0-9a-f]{40}$' -or "$($id.r5_invalidation_remote_commit)" -ceq ('0' * 40)){throw 'R5 invalidation receipt provenance is absent, zero, or invalid.'}
$expectedGateEvidence=[ordered]@{
    clean_install=@{verdict='f09fc526aa40de18e5bdff1d444fa49184396f3e994542307e597bf3e2f6cd65';digest='b8f22c2468abcbe74823f3814c213c009d19c1cbe01b6a5cba676cf151bf0706';id='10324325038'}
    cross_version_upgrade=@{verdict='3163c5b7e836bdd235593e215a3ed8beafe271ae5e73705965843dae93d3f06e';digest='a750390c3feecc100600b5932f964dc4027f6175d1e99a2b6360c2ff3e8475c3';id='10325385103'}
    download_only=@{verdict='1dbca663def8bdee613eaf2d0429a4488dbc4fe5bd1c881d1510544315a08052';digest='f78d1a67813ed117d11776af08a6fedd4ba6d2a9a77c84ca634cc0bcd97b1e25';id='10325128671'}
}
foreach($field in @('gate_a_verdict_artifact_sha256','gate_a_artifact_digest_sha256','gate_a_artifact_id')){
    $properties=@($id.$field.PSObject.Properties)
    if($properties.Count -ne 3 -or @($properties.Name | Where-Object {$_ -notin @($expectedGateEvidence.Keys)}).Count){throw "Gate A identity field $field must contain exactly the three expected lanes."}
}
foreach($lane in $expectedGateEvidence.Keys){
    $expected=$expectedGateEvidence[$lane]
    if([string]$id.gate_a_verdict_artifact_sha256.$lane -cne $expected.verdict){throw "Gate A inner verdict hash is not exact for $lane."}
    if([string]$id.gate_a_artifact_digest_sha256.$lane -cne $expected.digest){throw "Gate A artifact digest is not exact for $lane."}
    if([string]$id.gate_a_artifact_id.$lane -cne $expected.id){throw "Gate A artifact ID is not exact for $lane."}
}
return $id
