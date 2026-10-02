# rung.ps1 - READ-ONLY watched acceptance rung for beta.10 (30m / 2h / 4h / 8h ...).
# Every 30 s   : per-channel freshness + newest-segment stream types (watch-live.ps1). A channel is DARK when
#                its playlist is > 20 s old or its newest segment lacks video or audio.
# Every 10 min : verify_beta10_live_hls_media.py (captions decoded from TS, PTS continuity, decodability).
# Every 30 min : capture_emitted_hls_audio_proof.py 240 s continuous loudness (-16 +/- 1 LUFS).
# Verdict      : PASS only if (a) no channel was DARK for more than one consecutive 30 s sample,
#                (b) every verifier run has timestamp_continuity and freshness PASS on all three
#                    channels, and no caption outage (see rung_check.py, U48): a quiet caption channel
#                    is printed as OK ... c:CAPTION_QUIET(<why>) -- listed with its numbers, not failed,
#                (c) every loudness run is PASS, and (d) the service pid never changed.
#                Anything else is FAIL. Rollover/restart/stall log lines are copied into the evidence folder.
# Usage: rung.ps1 -Name 30m -Minutes 30
param([Parameter(Mandatory)] [string]$Name, [Parameter(Mandatory)] [int]$Minutes)
$ErrorActionPreference = 'Continue'
$Ov = Split-Path $PSScriptRoot -Parent
$Wt = 'C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds'
$Py = "$Wt\.venv\Scripts\python.exe"
$Hls = 'C:\ProgramData\CivicCast\data\egress\live-hls'
$Log = 'C:\ProgramData\CivicCast\logs\control_plane-app.log'
$env:PATH = "C:\Users\scott\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-essentials_build\bin;$env:PATH"
$Dir = Join-Path $Ov "evidence\rung-$Name-$(Get-Date -Format yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Force $Dir | Out-Null
$samples = Join-Path $Dir 'samples.txt'
function Note($m) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Add-Content (Join-Path $Dir 'rung.log') $line; $line }
$start = Get-Date; $end = $start.AddMinutes($Minutes)
$pid0 = (Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'").ProcessId
$logStart = (Get-Item $Log).Length
Note "RUNG $Name START ${Minutes}m service pid $pid0 evidence $Dir"
# U50: keep finished segments so the verifier's 60 s caption window can be filled. The live-HLS
# directory holds only ~7 live segments (~14 s) beside fossils from earlier runs, so the window
# was 10 s on paper. The keeper plain-copies finished segments into $KeepDir and self-exits at
# rung end + 5 min; it never opens playlist.m3u8 and never holds a handle on a live segment.
$KeepDir = Join-Path $env:TEMP 'cc-caption-keep'
$keepUntil = $end.AddMinutes(5).ToString('yyyy-MM-ddTHH:mm:ss')
$keepProc = Start-Process -FilePath $Py -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $Dir 'segment_keeper.txt') `
    -RedirectStandardError (Join-Path $Dir 'segment_keeper.err.txt') `
    -ArgumentList @("`"$(Join-Path $PSScriptRoot 'segment_keeper.py')`"", '--hls', "`"$Hls`"", '--out', "`"$KeepDir`"", '--until', $keepUntil)
Note "segment_keeper pid $($keepProc.Id) out $KeepDir until $keepUntil" | Out-Null
$failures = New-Object System.Collections.Generic.List[string]
$darkStreak = @{ public = 0; government = 0; education = 0 }
$nextVerify = $start; $nextLoud = $start.AddMinutes(2); $verifyN = 0; $loudN = 0; $loudProc = $null; $loudOut = $null
while ((Get-Date) -lt $end) {
    $status = & (Join-Path $PSScriptRoot 'watch-live.ps1') -Segments 1
    $status | Add-Content $samples
    $svcPid = (Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'").ProcessId
    if ($svcPid -ne $pid0) { $failures.Add("service pid changed $pid0 -> $svcPid at $(Get-Date -Format HH:mm:ss)"); $pid0 = $svcPid }
    foreach ($c in 'public', 'government', 'education') {
        $row = $status | Where-Object { $_ -match "^$c\s" }
        if ($row -match '\sok\s') { $darkStreak[$c] = 0 } else {
            $darkStreak[$c]++
            if ($darkStreak[$c] -eq 2) { $failures.Add("$c DARK for 2 consecutive samples at $(Get-Date -Format HH:mm:ss): $row"); Note "FAIL-EVENT $c dark: $row" | Out-Null }
        }
    }
    if ((Get-Date) -ge $nextVerify) {
        $verifyN++; $out = Join-Path $Dir ("verify-{0:D2}.json" -f $verifyN)
        # U50: --caption-keep-dir points the 60 s caption window at the keeper's copies. The verifier
        # uses it only while its heartbeat is fresh; otherwise it falls back to the live directory
        # and says so in the evidence (source: live).
        & $Py "$Wt\scripts\verify_beta10_live_hls_media.py" --hls-root $Hls --out $out --caption-keep-dir $KeepDir *> (Join-Path $Dir ("verify-{0:D2}.txt" -f $verifyN))
        # U59 proposal: keep the ASR's own output beside each verify, so a caption result can be re-judged
        # after the live active.vtt has moved on (it holds only the current ASR session). Plain copy.
        foreach ($ch in 'public', 'government', 'education') {
            $vtt = "C:\ProgramData\CivicCast\data\egress\$ch\captions\active.vtt"
            if (Test-Path -LiteralPath $vtt) {
                Copy-Item -LiteralPath $vtt -Destination (Join-Path $Dir ("verify-{0:D2}-{1}-active.vtt" -f $verifyN, $ch)) -ErrorAction SilentlyContinue
            }
        }
        $chk = & $Py (Join-Path $PSScriptRoot 'rung_check.py') verify $out
        Note "verify #$verifyN $chk" | Out-Null
        # '^OK', not -eq 'OK': since U48 a clean line can carry trailing CAPTION_QUIET(<why>) notes,
        # which are listed for the log and are not failures.
        if ($chk -notmatch '^OK') { $failures.Add("verify #$verifyN $chk") }
        $nextVerify = (Get-Date).AddMinutes(10)
    }
    # Loudness runs in the BACKGROUND (~12 min for 3 x 240 s) so the 30 s dark sampling and 10-min verify keep running.
    if ($loudProc -and $loudProc.HasExited) {
        $chk = & $Py (Join-Path $PSScriptRoot 'rung_check.py') loudness $loudOut
        Note "loudness #$loudN $chk" | Out-Null
        if ($chk -notmatch '^PASS') { $failures.Add("loudness #$loudN $chk") }
        $loudProc = $null
    }
    if (-not $loudProc -and (Get-Date) -ge $nextLoud -and (Get-Date).AddMinutes(15) -lt $end) {
        $loudN++; $loudOut = Join-Path $Dir ("loudness-{0:D2}.json" -f $loudN)
        $loudProc = Start-Process -FilePath $Py -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $Dir ("loudness-{0:D2}.txt" -f $loudN)) -RedirectStandardError (Join-Path $Dir ("loudness-{0:D2}.err.txt" -f $loudN)) -ArgumentList @("`"$Wt\scripts\capture_emitted_hls_audio_proof.py`"", '--hls-root', "`"$Hls`"", '--out', "`"$loudOut`"", '--duration-seconds', '240', '--scratch-dir', "`"$env:TEMP\cc-rung-loud`"")
        $nextLoud = (Get-Date).AddMinutes(30)
    }
    Start-Sleep 30
}
if ($loudProc) { $loudProc.WaitForExit(900000) | Out-Null; $chk = & $Py (Join-Path $PSScriptRoot 'rung_check.py') loudness $loudOut; Note "loudness #$loudN $chk" | Out-Null; if ($chk -notmatch '^PASS') { $failures.Add("loudness #$loudN $chk") } }
# U50: the keeper self-exits at rung end + 5 min; stop it now so a long-lived rung tree does not
# leave a copier behind. Matched by command line, not by the pid Start-Process handed back: on this
# machine $Py is a venv shim that re-execs the real interpreter, so the launcher pid is not the
# keeper's own (observed: launcher 29804, heartbeat pid 31676).
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*segment_keeper.py*' -and $_.CommandLine -like "*$KeepDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Note "segment_keeper stopped (rung end)" | Out-Null
# Copy the rung's egress events.
$fs = [IO.File]::Open($Log, 'Open', 'Read', 'ReadWrite'); $fs.Seek($logStart, 'Begin') | Out-Null
$text = (New-Object IO.StreamReader($fs)).ReadToEnd(); $fs.Dispose()
($text -split "`r?`n") | Where-Object { $_ -cmatch 'issued a seamless plan rollover|content-reload accepted|preparation for .* took|worker exited|past due|Channel automation pass for|relay child|HLS relay up| ERROR civiccast|reconcil|Caption tap overload' } | Set-Content (Join-Path $Dir 'events.log')
Get-ChildItem C:\ProgramData\CivicCast\data\egress\*\reload-status.json | ForEach-Object { "$($_.Directory.Name) $($_.LastWriteTime.ToString('o')) $(Get-Content $_.FullName -Raw)" } | Set-Content (Join-Path $Dir 'reload-status-end.txt')
# Captions THROUGHOUT: the per-sample verifier cannot see a caption pause between samples (U10), so any
# caption-tap overload pause inside the rung window is a failure in its own right.
$pauses = @(($text -split "`r?`n") | Where-Object { $_ -cmatch 'Caption tap overload for channel .* PAUSED' })
foreach ($p in $pauses) { $failures.Add("caption pause: $($p.Substring(0, [Math]::Min(160, $p.Length)))") }
Note "caption pauses in window: $($pauses.Count)" | Out-Null
$verdict = if ($failures.Count -eq 0 -and $verifyN -gt 0) { 'PASS' } else { 'FAIL' }
$failures | Set-Content (Join-Path $Dir 'failures.txt')
Note "RUNG $Name END verdict $verdict verifies $verifyN loudness $loudN failures $($failures.Count)"
$verdict | Set-Content (Join-Path $Dir 'VERDICT.txt')
