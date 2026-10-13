$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$install='C:\Program Files\CivicCast (Native)'
$pd='C:\ProgramData\CivicCast'
$scratch='C:\CivicCastScratch'
$evidence='C:\CivicCastEvidence\result.json'
Start-Transcript -Path 'C:\CivicCastEvidence\transcript-api.log' -Force | Out-Null
function Set-Phase([string]$Name) {$script:phase=$Name;([DateTime]::UtcNow.ToString('o')+' phase='+$Name) | Add-Content 'C:\CivicCastEvidence\progress.log'}
$previous=Get-Content $evidence -Raw | ConvertFrom-Json
$r=[ordered]@{}
foreach($property in $previous.PSObject.Properties){$r[$property.Name]=$property.Value}
$r.phases=[ordered]@{}
foreach($property in $previous.phases.PSObject.Properties){$r.phases[$property.Name]=$property.Value}
foreach($key in @('failedPhase','error','errorDetail','finishedUtc')){$r.Remove($key)}
$r.apiResumedUtc=[DateTime]::UtcNow.ToString('o')
try {
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
  $login = Invoke-RestMethod 'http://127.0.0.1:8000/api/setup/login' -Method Post -ContentType 'application/json' -Body '{"admin_username":"sandbox-admin","admin_password":"sandbox-only-password-long-enough"}' -TimeoutSec 15
  $headers = @{Authorization=('Bearer ' + $login.operator_console_token)}
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







