'guest-entry ' + [DateTime]::UtcNow.ToString('o') | Set-Content 'C:\CivicCastEvidence\progress.log'
Start-Transcript -Path 'C:\CivicCastEvidence\transcript.log' -Force | Out-Null
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
  Set-Phase 'stage'
  New-Item -ItemType Directory -Path $install -Force | Out-Null
  $copy = @('/E','/COPY:DAT','/DCOPY:DAT','/XJ','/R:1','/W:1','/NFL','/NDL','/NJH','/NJS','/NP')
  & robocopy.exe 'C:\CivicCastHostRuntime' "$install\runtime" @copy | Out-Null
  if ($LASTEXITCODE -gt 7) { throw "Runtime copy failed ($LASTEXITCODE)." }
  New-Item -ItemType Directory -Path "$install\packs\native-server-binaries" -Force | Out-Null
  & robocopy.exe 'C:\CivicCastPostgres' "$install\packs\native-server-binaries\payload" @copy | Out-Null
  if ($LASTEXITCODE -gt 7) { throw "PostgreSQL payload copy failed ($LASTEXITCODE)." }
  $target = "$install\runtime\Lib\site-packages\civiccast"
  New-Item -ItemType Directory -Path $target -Force | Out-Null
  $overlay = @('/E','/COPY:DAT','/DCOPY:DAT','/XJ','/R:1','/W:1','/NFL','/NDL','/NJH','/NJS','/NP','/XD','node_modules','target','dist','__pycache__','.pytest_cache','.mypy_cache','.ruff_cache','/XF','*.pyc')
  & robocopy.exe 'C:\CivicCastSource' $target @overlay | Out-Null
  if ($LASTEXITCODE -gt 7) { throw "Python source overlay failed ($LASTEXITCODE)." }
  $r.phases.stage = 'installed runtime plus current Python source and extracted PostgreSQL payload staged locally'
  Set-Phase 'stage-vc-runtime'
  $vcHashes = [ordered]@{}
  foreach ($dll in @('vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll')) {
    $sourceDll = Join-Path 'C:\CivicCastScripts' $dll
    Copy-Item -LiteralPath $sourceDll -Destination "$install\packs\native-server-binaries\payload\bin" -Force
    $vcHashes[$dll] = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash.ToLowerInvariant()
  }
  $r.vcRuntimeSha256 = $vcHashes
  $r.phases.vcRuntime = 'host System32 VC runtime DLL copies staged app-locally only in disposable PostgreSQL bin; MSI omitted'
  Set-Phase 'postgres-fixture'
  $bin = "$install\packs\native-server-binaries\payload\bin"
  $pg = "$pd\data\pgdata"
  New-Item -ItemType Directory -Path "$pd\data" -Force | Out-Null
  & "$bin\initdb.exe" '-D' $pg '-U' 'postgres' '--auth=trust' '--encoding=UTF8' *> "$scratch\initdb.log"
  if ($LASTEXITCODE -ne 0) { throw "Packaged PostgreSQL initdb failed ($LASTEXITCODE)." }
  Add-Content "$pg\postgresql.conf" ([Environment]::NewLine + "listen_addresses = '127.0.0.1'" + [Environment]::NewLine + 'port = 55439' + [Environment]::NewLine)
  & "$bin\pg_ctl.exe" 'start' '-D' $pg '-w' '-t' '20' '-o' '-p 55439 -h 127.0.0.1' *> "$scratch\pg-start.log"
  if ($LASTEXITCODE -ne 0) { throw "Packaged PostgreSQL start failed ($LASTEXITCODE)." }
  & "$bin\createdb.exe" '-h' '127.0.0.1' '-p' '55439' '-U' 'postgres' 'civiccast' *> "$scratch\createdb.log"
  if ($LASTEXITCODE -ne 0) { throw "PostgreSQL test database creation failed ($LASTEXITCODE)." }
  & "$bin\pg_ctl.exe" 'stop' '-D' $pg '-m' 'fast' '-w' *> "$scratch\pg-stop.log"
  if ($LASTEXITCODE -ne 0) { throw "PostgreSQL fixture stop failed ($LASTEXITCODE)." }
  $r.phases.postgres = 'actual packaged PostgreSQL cluster initialized and stopped cleanly'
  Set-Phase 'register-local-system'
  & $python '-m' 'civiccast.native.supervisor.service_host' '--startup' 'auto' 'install' *> "$scratch\register.log"
  if ($LASTEXITCODE -ne 0) { throw "SCM registration failed ($LASTEXITCODE)." }
  $svcKey = 'HKLM:\SYSTEM\CurrentControlSet\Services\CivicCastSupervisor'
  $profile = "$env:WINDIR\System32\config\systemprofile"
  New-ItemProperty $svcKey Environment -PropertyType MultiString -Value @("LOCALAPPDATA=$env:WINDIR\System32\config\systemprofile\AppData\Local","USERPROFILE=$profile") -Force | Out-Null
  $dbKey = 'HKLM:\SOFTWARE\CivicCast\Native'
  New-Item $dbKey -Force | Out-Null
  New-ItemProperty $dbKey DatabaseUrl -PropertyType String -Value 'postgresql://postgres@127.0.0.1:55439/civiccast' -Force | Out-Null
  $r.serviceBeforeMigration = (Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'").StartName
  $taskPrincipal = New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
  Set-Phase 'seed-local-system'
  $task = 'CcSeed-' + [Guid]::NewGuid().ToString('N')
  Register-ScheduledTask $task -Action (New-ScheduledTaskAction -Execute $python -Argument '-I C:\CivicCastScripts\SeedLegacy.py') -Principal $taskPrincipal -Force | Out-Null
  Start-ScheduledTask $task
  $seedFile = "$scratch\seed-result.json"; $until = [DateTime]::UtcNow.AddSeconds(30)
  while (-not (Test-Path $seedFile) -and [DateTime]::UtcNow -lt $until) { Start-Sleep -Milliseconds 250 }
  Unregister-ScheduledTask $task -Confirm:$false -ErrorAction SilentlyContinue
  if (-not (Test-Path $seedFile)) { throw 'LocalSystem legacy-profile seed task timed out.' }
  $seed = Get-Content $seedFile -Raw | ConvertFrom-Json
  if (-not $seed.ok) { throw 'Synthetic LocalSystem state/credential seeding failed.' }
  $r.legacyStateSha256=$seed.stateSha256; $r.legacyFixtureSha256=$seed.fixtureSha256
  $r.phases.seed='synthetic first-admin state and allow-listed credential created under LocalSystem'
  Set-Phase 'migrate-identity'
  & $python '-m' 'civiccast.native.install_service_identity' '--install-root' $install *> "$scratch\identity.log"
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
  if(Test-Path $scratch){Get-ChildItem $scratch -Filter '*.log' | ForEach-Object {Copy-Item $_.FullName 'C:\CivicCastEvidence' -Force -ErrorAction SilentlyContinue}}
}


