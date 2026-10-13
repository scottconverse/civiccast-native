'guest-resume ' + [DateTime]::UtcNow.ToString('o') | Add-Content 'C:\CivicCastEvidence\progress.log'
Start-Transcript -Path 'C:\CivicCastEvidence\transcript-resume.log' -Force | Out-Null
function Set-Phase([string]$Name) {
  $script:phase = $Name
  ([DateTime]::UtcNow.ToString('o') + ' phase=' + $Name) | Add-Content 'C:\CivicCastEvidence\progress.log'
}
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$install = 'C:\Program Files\CivicCast (Native)'
$python = Join-Path $install 'runtime\python.exe'
$pd = 'C:\ProgramData\CivicCast'
$scratch = 'C:\CivicCastScratch'
$evidence = 'C:\CivicCastEvidence\result.json'
Set-Phase 'preflight'
$r = [ordered]@{ startedUtc=[DateTime]::UtcNow.ToString('o'); phases=[ordered]@{} }
New-Item -ItemType Directory -Path $scratch -Force | Out-Null
try {
  $id = [Security.Principal.WindowsIdentity]::GetCurrent()
  $r.logonIdentity = $id.Name
  $r.adminToken = ([Security.Principal.WindowsPrincipal]::new($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  $r.memoryMiB = [math]::Round((Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize / 1024)
  if (-not $r.adminToken) { throw 'Sandbox logon token is not elevated; no SCM mutation attempted.' }
  $seed = Get-Content "$scratch\seed-result.json" -Raw | ConvertFrom-Json
  $r.legacyStateSha256 = $seed.stateSha256
  $r.legacyFixtureSha256 = $seed.fixtureSha256
  $r.serviceBeforeMigration = (Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'").StartName
  $r.phases.fixture = 'existing same-guest PostgreSQL schema current; original LocalSystem seed retained without reseeding'
  $taskPrincipal = New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
  Set-Phase 'migrate-identity'
$ErrorActionPreference='Continue'
  & $python '-m' 'civiccast.native.install_service_identity' '--install-root' $install *> "$scratch\identity.log"
$ErrorActionPreference='Stop'
  if ($LASTEXITCODE -ne 0) { throw "SCM service identity migration failed ($LASTEXITCODE)." }
  $svc = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'"
  $r.serviceAfterMigration=$svc.StartName; $r.stateAfterMigration=$svc.State
  $r.migrationReceipt=Test-Path "$pd\profile\identity-migration.complete"
  $state="$pd\profile\CivicCast\station-state.json"; $fixture="$pd\profile\CivicCast\migration-fixture.txt"
  $r.migratedStateSha256=if(Test-Path $state){(Get-FileHash $state -Algorithm SHA256).Hash.ToLowerInvariant()}else{$null}
  $r.migratedFixtureSha256=if(Test-Path $fixture){(Get-FileHash $fixture -Algorithm SHA256).Hash.ToLowerInvariant()}else{$null}
  $sidText=(& sc.exe showsid CivicCastSupervisor 2>&1 | Out-String)
  $sidMatch=[regex]::Match($sidText,'S-1-5-80-(?:\d+-){4}\d+')
  $sid=if($sidMatch.Success){$sidMatch.Value}else{$null}; $r.serviceSid=$sid
  if(-not $sid){throw 'Could not resolve the registered service SID.'}
  $vault="$pd\credentials\station-vault.dpapi"; $r.vaultExists=Test-Path $vault
  $vaultSids=if($r.vaultExists){@((Get-Acl $vault).Access | ForEach-Object { try{$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value}catch{$_.IdentityReference.Value} })}else{@()}
  $r.serviceSidOnVaultAcl=$vaultSids -contains $sid
  foreach($name in @('provision','upgrade')){
    $protectedPath=Join-Path $pd $name
    $protectedAcl=Get-Acl $protectedPath
    $protectedSids=@($protectedAcl.Access | ForEach-Object { try{$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value}catch{$_.IdentityReference.Value} })
    $r[$name + 'AclProtected']=[bool]$protectedAcl.AreAccessRulesProtected
    $r[$name + 'HasServiceSid']=$protectedSids -contains $sid
  }
  if(-not $r.provisionAclProtected -or $r.provisionHasServiceSid -or -not $r.upgradeAclProtected -or $r.upgradeHasServiceSid){throw 'Protected provisioning/upgrade ACL acquired service access or inheritance.'}
  $r.phases.protectedAcl='provision and upgrade state roots remain protected and exclude the service SID'
  if (-not $r.migrationReceipt -or $r.legacyStateSha256 -ne $r.migratedStateSha256 -or $r.legacyFixtureSha256 -ne $r.migratedFixtureSha256) { throw 'Migration receipt or byte-for-byte profile comparison failed.' }
  $r.phases.profile='migration receipt exists and source/destination profile hashes match'
  Set-Phase 'verify-secret'
  $task='CcVault-' + [Guid]::NewGuid().ToString('N')
  Register-ScheduledTask $task -Action (New-ScheduledTaskAction -Execute $python -Argument '-I C:\CivicCastScripts\VerifyVault.py') -Principal $taskPrincipal -Force | Out-Null
  Start-ScheduledTask $task
  $vaultFile="$scratch\vault-result.json"; $until=[DateTime]::UtcNow.AddSeconds(30)
  while(-not(Test-Path $vaultFile) -and [DateTime]::UtcNow -lt $until){Start-Sleep -Milliseconds 250}
  Unregister-ScheduledTask $task -Confirm:$false -ErrorAction SilentlyContinue
  if(-not(Test-Path $vaultFile)){throw 'LocalSystem migrated-vault verification timed out.'}
  $r.credentialPreserved=[bool]((Get-Content $vaultFile -Raw | ConvertFrom-Json).credentialPreserved)
  if(-not $r.credentialPreserved){throw 'Synthetic secret missing from encrypted migrated vault.'}
  $r.phases.credential='LocalSystem decrypted the migrated vault and matched the synthetic secret'
  Set-Phase 'restricted-start-api'
  Start-Service CivicCastSupervisor
  $until=[DateTime]::UtcNow.AddSeconds(210); $health=$null; $stateName='Unknown'
  while([DateTime]::UtcNow -lt $until){
    $stateName=(Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'").State
    if($stateName -eq 'Stopped'){break}
    try{$health=Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 3;if($health){break}}catch{}
    Start-Sleep -Seconds 2
  }
  $r.serviceStateAfterStart=$stateName; $r.serviceStartName=(Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'").StartName
  $r.apiHealthHttp=if($health){200}else{$null}; $r.apiMode=if($health -and $health.mode){[string]$health.mode}else{$null}
  if(-not $health){$log="$pd\logs\supervisor.log";$r.supervisorLogTail=if(Test-Path $log){(Get-Content $log -Tail 20)-join [Environment]::NewLine}else{''};throw 'Restricted SCM service did not serve /health within 210 seconds.'}
  $r.phases.api='restricted-account SCM service served actual loopback /health'
  $r.apiHealth = $health
  $serviceRunning = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'"
  $r.serviceProcessId = $serviceRunning.ProcessId
  $serviceProcess = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $serviceRunning.ProcessId)
  $r.serviceProcessOwner = Invoke-CimMethod -InputObject $serviceProcess -MethodName GetOwner | Select-Object Domain,User,ReturnValue
  Set-Phase 'restricted-backup-credential-export'
  $login = Invoke-RestMethod 'http://127.0.0.1:8000/api/staff/auth/login' -Method Post -ContentType 'application/json' -Body '{"username":"sandbox-admin","password":"sandbox-only-password-long-enough"}' -TimeoutSec 15
  $headers = @{Authorization=('Bearer ' + $login.access_token)}
  $backup = Invoke-RestMethod 'http://127.0.0.1:8000/api/staff/backups/create' -Method Post -ContentType 'application/json' -Headers $headers -Body '{"passphrase":"sandbox-only-recovery-passphrase"}' -TimeoutSec 60
  $verifyBody = @{backup_id=$backup.backup_id;passphrase='sandbox-only-recovery-passphrase'} | ConvertTo-Json
  $verifiedBackup = Invoke-RestMethod 'http://127.0.0.1:8000/api/staff/backups/verify' -Method Post -ContentType 'application/json' -Headers $headers -Body $verifyBody -TimeoutSec 60
  $r.restrictedBackupVerified = [bool]$verifiedBackup.valid
  $r.restrictedBackupDatabaseEngine = $verifiedBackup.database_engine
  if (-not $r.restrictedBackupVerified) {throw 'Restricted API backup did not verify.'}
  $r.phases.restrictedCredentials = 'real restricted-account API exported vault credentials into encrypted PostgreSQL backup and verified it'
  Stop-Service CivicCastSupervisor -Force -ErrorAction SilentlyContinue
  $until=[DateTime]::UtcNow.AddSeconds(40); do{Start-Sleep -Milliseconds 500;$stateName=(Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'").State}while($stateName -ne 'Stopped' -and [DateTime]::UtcNow -lt $until)
  $r.serviceStopped=($stateName -eq 'Stopped'); $r.phases.cleanup='bounded guest service stop requested'
} catch {
  $r.failedPhase=$phase; $r.error=$_.Exception.Message; $r.errorDetail=($_ | Out-String)
  try{Stop-Service CivicCastSupervisor -Force -ErrorAction SilentlyContinue}catch{}
} finally {
  $r.finishedUtc=[DateTime]::UtcNow.ToString('o')
  Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
  try{$r | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $evidence -Encoding UTF8}catch{}
  if(Test-Path "$pd\logs"){Get-ChildItem "$pd\logs" -Filter '*.log' | ForEach-Object {Copy-Item $_.FullName 'C:\CivicCastEvidence' -Force -ErrorAction SilentlyContinue}}
  if(Test-Path $scratch){Get-ChildItem $scratch -Filter '*.log' | ForEach-Object {Copy-Item $_.FullName 'C:\CivicCastEvidence' -Force -ErrorAction SilentlyContinue}}
}






