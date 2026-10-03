$ErrorActionPreference='Continue'
$out='C:\Diag\out'
New-Item -ItemType Directory -Force "$out\tmp" | Out-Null
'started ' + (Get-Date -Format o) | Set-Content "$out\00-started.txt"
$root='C:\CivicCastHostStore\install'
$vc=Start-Process -FilePath "$root\vc_redist.x64.exe" -ArgumentList '/install','/quiet','/norestart' -PassThru -Wait
('vcredist exit={0} at {1}' -f $vc.ExitCode,(Get-Date -Format o)) | Set-Content "$out\00b-vcredist.txt"
Start-Job -Name sampler -ScriptBlock {
  while($true){
    $os=Get-CimInstance Win32_OperatingSystem
    $line='{0} freeMB={1}' -f (Get-Date -Format o),[int]($os.FreePhysicalMemory/1024)
    $top=Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 4 | ForEach-Object { '{0}:{1}MB' -f $_.Name,[int]($_.WorkingSet64/1MB) }
    ($line + ' | ' + ($top -join ' ')) | Add-Content 'C:\Diag\out\samples.txt'
    Start-Sleep 5 } } | Out-Null
function Run-Phase($name,$vulkan,$port,$models){
  $log="$out\$name.log"; $stamp={ Get-Date -Format 'HH:mm:ss.fff' }
  "[$(& $stamp)] phase $name begin (OLLAMA_VULKAN=$vulkan)" | Add-Content $log
  $env:OLLAMA_HOST="127.0.0.1:$port"; $env:OLLAMA_MODELS="$root\models\ollama"; $env:OLLAMA_NO_CLOUD='1'; $env:OLLAMA_KEEP_ALIVE='0'
  $env:OLLAMA_MAX_LOADED_MODELS='1'; $env:OLLAMA_NUM_PARALLEL='1'; $env:NO_PROXY='127.0.0.1,localhost'
  if($vulkan -ne 'default'){ $env:OLLAMA_VULKAN=$vulkan } else { Remove-Item Env:OLLAMA_VULKAN -ErrorAction SilentlyContinue }
  $srv=Start-Process -FilePath "$root\dependencies\ollama\ollama.exe" -ArgumentList 'serve' -WorkingDirectory "$root\dependencies\ollama" -WindowStyle Hidden -PassThru -RedirectStandardOutput "$out\$name.srv.out.txt" -RedirectStandardError "$out\$name.srv.err.txt"
  $t0=Get-Date; $ready=$false
  while(((Get-Date)-$t0).TotalSeconds -lt 600){
    try{ $r=Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/version" -UseBasicParsing -TimeoutSec 5; "[$(& $stamp)] READY after $([int]((Get-Date)-$t0).TotalSeconds)s: $($r.Content)" | Add-Content $log; $ready=$true; break }catch{ Start-Sleep 2 }
  }
  if(-not $ready){ "[$(& $stamp)] NOT READY after 600s" | Add-Content $log }
  if($ready -and $models){
    foreach($m in @(@('gemma4:12b','Reply with exactly CIVICCAST_OK and nothing else.'),@('gemma4:e4b','Reply with exactly CIVICCAST_FALLBACK_OK and nothing else.'),@('translategemma:4b','Translate into Spanish. Return only the translation: The council meeting is open.'))){
      $body=@{model=$m[0];prompt=$m[1];stream=$false;think=$false;keep_alive=0;options=@{temperature=0;num_predict=64}} | ConvertTo-Json -Depth 5
      $t1=Get-Date
      try{ $r=Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/generate" -Method Post -Body $body -ContentType 'application/json' -UseBasicParsing -TimeoutSec 900
           $j=$r.Content | ConvertFrom-Json
           "[$(& $stamp)] $($m[0]) OK in $([int]((Get-Date)-$t1).TotalSeconds)s: response='$($j.response)' load_s=$([math]::Round($j.load_duration/1e9,1)) eval_s=$([math]::Round($j.eval_duration/1e9,1))" | Add-Content $log
      }catch{ "[$(& $stamp)] $($m[0]) FAILED after $([int]((Get-Date)-$t1).TotalSeconds)s: $($_.Exception.Message)" | Add-Content $log }
    }
  }
  try{ Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue; & taskkill.exe /F /T /PID $srv.Id 2>&1 | Out-Null }catch{}
  Start-Sleep 5
}
Run-Phase 'phaseA-default' 'default' 49901 $true
Run-Phase 'phaseB-vulkan0' '0' 49902 $false
Get-Job | Stop-Job -ErrorAction SilentlyContinue
cmd /c "wevtutil qe Application /c:60 /rd:true /f:text > `"$out\events-application.txt`" 2>&1"
'done ' + (Get-Date -Format o) | Set-Content "$out\99-DONE.txt"
Start-Sleep 5
shutdown /s /t 0
