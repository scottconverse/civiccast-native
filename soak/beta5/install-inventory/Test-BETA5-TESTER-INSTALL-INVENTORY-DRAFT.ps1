Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$env:BETA5_INVENTORY_DRAFT_LIBRARY = '1'
try { . (Join-Path $PSScriptRoot 'BETA5-TESTER-INSTALL-INVENTORY-DRAFT.ps1') } finally { Remove-Item Env:BETA5_INVENTORY_DRAFT_LIBRARY -ErrorAction SilentlyContinue }
function Assert-True($Name, [bool] $Value) { if (-not $Value) { throw "Assertion failed: $Name" } }
function Assert-Throws($Name, [scriptblock] $Action) { try { & $Action; throw "Assertion failed: $Name did not throw" } catch { if ($_.Exception.Message -like 'Assertion failed:*') { throw } } }

$file = [pscustomobject]@{ Length = 12; LastWriteTimeUtc = [datetime]'2026-09-08T00:00:00Z' }
$json = [pscustomobject]@{ schema='civiccast-native-tester-run-identity-v3'; mission='beta5-sep8-be1260bd0630'; candidate_source_sha='be1260bd0630261c571e3adf5aac6a6cbebd9e3a'; installed_version='1.0.0-beta.5'; token='must-not-export' }
$process = [pscustomobject]@{ Name='setup.exe'; Id=41; ParentProcessId=4; StartTimeUtc=[datetime]'2026-09-08T00:00:00Z'; CpuSeconds=1.5; CommandLine='SECRET --token abc' }
$service = [pscustomobject]@{ State='Running'; ProcessId=42; PathName='"C:\CivicCastHostStore\install\runtime\CivicCastSupervisor.exe" --BearerPassword SECRET'; StartTimeUtc=[datetime]'2026-09-08T00:00:00Z' }
$oldHost = $env:COMPUTERNAME; $env:COMPUTERNAME='DESKTOP-VBMA6O5'
try {
  Assert-Throws 'wrong host rejected' { Assert-Beta5InventoryHost 'OTHER-HOST' }
  Assert-Throws 'wrong root rejected' { Assert-Beta5InventoryRoot 'C:\OtherRoot' }
  Assert-True 'quoted executable parser strips arguments' ((Get-Beta5InventoryExecutablePath '"C:\Program Files\CivicCast\supervisor.exe" --BearerPassword SECRET') -eq 'C:\Program Files\CivicCast\supervisor.exe')
  Assert-True 'unquoted executable parser handles spaces through exe suffix' ((Get-Beta5InventoryExecutablePath 'C:\Program Files\CivicCast\supervisor.exe --flag') -eq 'C:\Program Files\CivicCast\supervisor.exe')
  $validLog = [pscustomobject]@{ FullName='C:\CivicCastSoak\reports\AUTORUN-SEP8-BETA5-BE1260-R1-20260908T000000Z.log'; Length=5; LastWriteTimeUtc=[datetime]'2026-09-08T00:00:00Z' }
  $invalidLog = [pscustomobject]@{ FullName='C:\CivicCastSoak\reports\AUTORUN-SEP8-BETA5-BE1260BD0630-20260908T000000Z.log'; Length=9; LastWriteTimeUtc=[datetime]'2026-09-08T01:00:00Z' }
  $outsideLog = [pscustomobject]@{ FullName='C:\Other\AUTORUN-SEP8-BETA5-BE1260-R1-20260908T020000Z.log'; Length=11; LastWriteTimeUtc=[datetime]'2026-09-08T02:00:00Z' }
  $logs = @(Get-Beta5InventoryAutorunLogMetadata 'C:\CivicCastSoak\reports' 'AUTORUN-SEP8-BETA5-BE1260-R1-' { param($d,$p) @($validLog,$invalidLog,$outsideLog) })
  Assert-True 'exact autorun log prefix and timestamp filter' ($logs.Count -eq 1 -and $logs[0].path -eq $validLog.FullName)
  $script:observedLogDirectory = $null
  $script:observedLogPrefix = $null
  $null = @(Get-Beta5InventoryAutorunLogMetadata 'C:\CivicCastSoak\reports' 'AUTORUN-SEP8-BETA5-BE1260-R1-' {
    param($directory, $prefix)
    $script:observedLogDirectory = $directory
    $script:observedLogPrefix = $prefix
    @()
  })
  Assert-True 'log callback receives its directory argument unchanged' ($script:observedLogDirectory -eq 'C:\CivicCastSoak\reports')
  Assert-True 'log callback receives its filename prefix unchanged' ($script:observedLogPrefix -eq 'AUTORUN-SEP8-BETA5-BE1260-R1-')
  $missing = Get-Beta5InventoryJsonSummary 'identity.json' { param($p) [pscustomobject]@{ schema='civiccast-native-tester-run-identity-v3' } }
  Assert-True 'missing expected identity fields are reported' (-not $missing.receipt_matches_expected -and $missing.mismatches -contains 'mission')
  $pendingHash = Get-Beta5InventoryJsonSummary 'identity.json' { param($p) [pscustomobject]@{schema='civiccast-native-tester-run-identity-v3';actual_manifest_sha256=$null;actual_installer_sha256=$null} }
  Assert-True 'pending null hash fields are valid JSON, not completed installation' ($pendingHash.valid_json -and $null -eq $pendingHash.actual_manifest_sha256 -and -not $pendingHash.receipt_matches_expected)
  $nullService = Get-Beta5InventorySnapshot -ActualHostname 'DESKTOP-VBMA6O5' -Root 'C:\CivicCastSoak' -FileReader { param($p) $null } -JsonReader { param($p) $null } -ProcessReader { param($n) @() } -ServiceReader { param($n) $null } -KitReader { param($p) @() } -LogReader { param($d,$p) @() }
  Assert-True 'missing service is represented as null' ($null -eq $nullService.service)
  $snapshot = Get-Beta5InventorySnapshot -ActualHostname 'DESKTOP-VBMA6O5' -Root 'C:\CivicCastSoak' -FileReader { param($p) if ($p -like '*run-identity.json') { $file } elseif ($p -like '*install-progress.log') { $file } else { $null } } -JsonReader { param($p) $json } -ProcessReader { param($n) @($process) } -ServiceReader { param($n) $service } -KitReader { param($p) @([pscustomobject]@{RelativePath='setup.exe';Length=12;LastWriteTimeUtc=[datetime]'2026-09-08T00:00:00Z'}) } -LogReader { param($d,$prefix) @() }
  Assert-True 'snapshot candidate binding' ($snapshot.candidate_source_sha -eq 'be1260bd0630261c571e3adf5aac6a6cbebd9e3a')
  Assert-True 'snapshot has no command line' (-not ($snapshot.processes[0].PSObject.Properties.Name -contains 'CommandLine'))
  Assert-True 'snapshot has no token' (-not (($snapshot.identity | ConvertTo-Json -Depth 8) -match 'must-not-export|token'))
  Assert-True 'snapshot does not include log contents' (-not (($snapshot | ConvertTo-Json -Depth 10) -match 'SECRET|abc'))
  Assert-True 'service executable path retained as metadata' ($snapshot.service.executable_path -like '*CivicCastSupervisor.exe')
  Assert-True 'service arguments are not exported' (-not (($snapshot | ConvertTo-Json -Depth 10) -match 'BearerPassword|SECRET'))
  $sparseService = [pscustomobject]@{ State = 'Stopped' }
  $sparseProcess = [pscustomobject]@{ Name = 'setup.exe'; Id = 77; StartTimeUtc = $null; CpuSeconds = $null }
  $sparseSnapshot = Get-Beta5InventorySnapshot -ActualHostname 'DESKTOP-VBMA6O5' -Root 'C:\CivicCastSoak' -FileReader { param($p) $null } -JsonReader { param($p) $null } -ProcessReader { param($n) @($sparseProcess) } -ServiceReader { param($n) $sparseService } -KitReader { param($p) @() } -LogReader { param($d,$p) @() }
  Assert-True 'sparse service preserves state without requiring process metadata' ($sparseSnapshot.service.state -eq 'Stopped')
  Assert-True 'missing service fields are represented as null' ($null -eq $sparseSnapshot.service.process_id -and $null -eq $sparseSnapshot.service.executable_path -and $null -eq $sparseSnapshot.service.started_utc)
  Assert-True 'missing process parent and start fields are represented as null' ($null -eq $sparseSnapshot.processes[0].parent_process_id -and $null -eq $sparseSnapshot.processes[0].started_utc)
} finally { $env:COMPUTERNAME=$oldHost }
Write-Host 'PASS: inert install inventory host, redaction, and metadata-only tests.'
