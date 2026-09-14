# Verify every executable R9 harness file before and after stable-bin copying.
[CmdletBinding()]
param([string]$PackageRoot=$PSScriptRoot,[string]$IdentityPath)
$ErrorActionPreference='Stop'
if(-not $IdentityPath){$IdentityPath=Join-Path $PackageRoot 'run-identity.json'}
$manifestPath=Join-Path $PackageRoot 'harness-manifest.json'
if(-not(Test-Path -LiteralPath $manifestPath -PathType Leaf)){throw 'R9 harness manifest is absent.'}
if(-not(Test-Path -LiteralPath $IdentityPath -PathType Leaf)){throw 'R9 run identity is absent.'}
$identity=Get-Content -LiteralPath $IdentityPath -Raw|ConvertFrom-Json
$manifestHash=(Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
if("$($identity.expected_harness_manifest_sha256)" -cne $manifestHash){throw 'R9 harness manifest hash does not match run identity.'}
$manifest=Get-Content -LiteralPath $manifestPath -Raw|ConvertFrom-Json
if("$($manifest.schema)" -cne 'civiccast-beta7-harness-manifest-v1'){throw 'Unexpected R9 harness manifest schema.'}
$expected=@('Assert-Beta7CandidateBinding.ps1','BETA7-MISSION.md','Beta7Tester.Common.ps1','Beta7TransportProbeR9.ps1','Invoke-Beta7TesterUpgrade.ps1','Run-Beta7PhysicalOFF4HJob.ps1','Run-BetaExistingTesterSoakR9.ps1','Start-Beta7PhysicalOFF4HJob.ps1','Test-Beta7HarnessPackage.ps1','Test-Beta7R9Harness.ps1','TSDuckReportClassifierR9.ps1')
$entries=@($manifest.files)
if($entries.Count -ne $expected.Count -or (@($entries.path|Sort-Object)-join "`0") -cne (($expected|Sort-Object)-join "`0")){throw 'R9 harness manifest file set is incomplete or contains extras.'}
$result=[ordered]@{}
foreach($entry in $entries){
    if("$($entry.sha256)" -notmatch '^[0-9a-f]{64}$'){throw "Invalid R9 harness hash for $($entry.path)."}
    $path=Join-Path $PackageRoot ([string]$entry.path)
    if(-not(Test-Path -LiteralPath $path -PathType Leaf)){throw "R9 harness file is absent: $($entry.path)"}
    $actual=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if($actual -cne "$($entry.sha256)"){throw "R9 harness file hash mismatch: $($entry.path)"}
    $result[[string]$entry.path]=$actual
}
[pscustomobject]@{manifest_sha256=$manifestHash;file_sha256=$result}
