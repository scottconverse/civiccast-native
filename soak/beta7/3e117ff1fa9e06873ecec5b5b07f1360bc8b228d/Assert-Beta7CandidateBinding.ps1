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
if([string]$id.mission_nonce -cne 'BETA7-3E117FF1-OFF8H-R3-A91E4C'){throw 'Mission nonce mismatch.'}
if([string]$id.task_name -cne 'CivicCast-Beta7-3e117ff1-OFF8H-R3-A91E4C'){throw 'Scheduled-task identity mismatch.'}
if([string]$id.evidence_relative_root -cne 'soak/beta7-3e117ff1fa9e06873ecec5b5b07f1360bc8b228d/physical-soak-off8h-r3-a91e4c'){throw 'Evidence-root identity mismatch.'}
if([int]$id.minutes_per_phase -ne 480 -or [int]$id.planned_seconds -ne 28800){throw 'Mission is not bound to one eight-hour captions-OFF phase.'}
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
