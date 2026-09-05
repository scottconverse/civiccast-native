# AUTORUN-9i (soak8-e1acfe6) -- read-only: what is burning CPU in the control plane?
# Hypothesis: caption/summary/transcription jobs for the uploaded clips (in-process, CPU).
# Captures: control-plane log lines about captions/whisper/summary/ollama/jobs (counts + last 60),
# ollama/ffmpeg processes, asset + caption job states from the API, and a second CPU sample.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$base  = 'http://127.0.0.1:8000'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9i control-plane CPU attribution", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
$log = 'C:\ProgramData\CivicCast\logs\control_plane-app.log'
$lines = @(Get-Content $log -ErrorAction SilentlyContinue)
$out += "log lines: $($lines.Count)"
$pats = [ordered]@{ caption='caption'; whisper='whisper'; transcri='transcri'; summary='summar'; ollama='ollama'; job='job'; package='packag'; conform='conform'; ffmpeg='ffmpeg'; media_integrity='media_integrity|media-integrity'; traceback='Traceback'; exception='Error:|Exception' }
$out += "## counts (whole log, case-insensitive)"
$out += '```'
foreach ($k in $pats.Keys) { $out += "$k = $(@($lines | Where-Object { $_ -match $pats[$k] }).Count)" }
$out += '```'
foreach ($k in 'caption','whisper','summary','ollama','traceback','exception') {
  $hits = @($lines | Where-Object { $_ -match $pats[$k] } | Select-Object -Last 25)
  $out += "## $k (last 25)"
  $out += '```'
  $out += ($hits | ForEach-Object { $_.Substring(0, [Math]::Min(240, $_.Length)) })
  $out += '```'
}
$out += "## other logs in C:\ProgramData\CivicCast\logs"
$out += '```'
$out += (Get-ChildItem 'C:\ProgramData\CivicCast\logs' -File -ErrorAction SilentlyContinue | ForEach-Object { "$($_.Name) $($_.Length) bytes $($_.LastWriteTimeUtc.ToString('o'))" })
$out += '```'
$out += "## all processes over 5% CPU right now (10 s sample)"
$s0 = @{}; Get-Process -ErrorAction SilentlyContinue | ForEach-Object { $s0[$_.Id] = $_.CPU }
Start-Sleep -Seconds 10
$out += '```'
$out += (Get-Process -ErrorAction SilentlyContinue | ForEach-Object { $d = $_.CPU - ($s0[$_.Id]); if ($d -gt 0.5) { "$($_.ProcessName) pid=$($_.Id) cpu_pct=$([math]::Round($d/10*100)) rss_mb=$([math]::Round($_.WorkingSet64/1MB)) threads=$($_.Threads.Count)" } })
$out += '```'
$tokenFile = "$root\state\token"
if (Test-Path $tokenFile) {
  $hdr = @{ Authorization = "Bearer $((Get-Content $tokenFile -Raw).Trim())" }
  $out += "## API: assets, caption jobs, summary jobs, health"
  $out += '```'
  foreach ($path in '/api/staff/assets?limit=10', '/api/staff/captions/review-items?limit=5', '/api/staff/summaries/jobs?limit=5', '/api/health') {
    try { $r = Invoke-WebRequest -Uri ($base + $path) -Headers $hdr -TimeoutSec 20 -UseBasicParsing; $out += "GET $path -> $([int]$r.StatusCode) $($r.Content.Substring(0,[Math]::Min(1200,$r.Content.Length)))" } catch { $out += "GET $path -> $($_.Exception.Message)" }
  }
  $out += '```'
}
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9i-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9i-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9i control-plane cpu attribution $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
