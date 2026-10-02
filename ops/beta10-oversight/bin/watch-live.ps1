# watch-live.ps1 - READ-ONLY live check of the three channels. One line per channel:
# playlist age, newest-segment stream types, A/V start offset (audio first PTS - video first PTS) of the
# second-newest segment, active.vtt size, plus service pid.
# Flags: STALE (playlist > 20 s old), NO-VIDEO (newest segment lacks video or audio), DESYNC (|a-v| > 0.5 s).
# Usage: watch-live.ps1 [-Segments 2]
param([int]$Segments = 2)
$fp = 'C:\Users\scott\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg.Essentials_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-essentials_build\bin\ffprobe.exe'
function FirstPts($path, $sel) {
    $raw = & $fp -v error -select_streams $sel -show_entries packet=pts_time -of csv=p=0 -read_intervals '%+#1' $path | Select-Object -First 1
    if ($null -eq $raw) { return $null }   # stream absent from the segment (audio-only / video-only)
    $t = ([string]$raw).Trim(', ')
    if ($t -match '^-?\d+(\.\d+)?$') { [double]$t } else { $null }
}
$svc = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'"
"{0} service {1} pid {2}" -f (Get-Date -Format 'HH:mm:ss'), $svc.State, $svc.ProcessId
foreach ($c in 'public', 'government', 'education') {
    $d = "C:\ProgramData\CivicCast\data\egress\live-hls\$c"
    $pl = Get-Item "$d\playlist.m3u8" -ErrorAction SilentlyContinue
    if (-not $pl) { "{0,-10} NO PLAYLIST" -f $c; continue }
    $all = @(Get-Content $pl.FullName | Where-Object { $_ -match '\.ts$' })
    $segs = $all | Select-Object -Last $Segments
    $types = foreach ($s in $segs) {
        $p = Join-Path $d $s
        if (Test-Path $p) { ((& $fp -v error -show_entries stream=codec_type -of csv=p=0 $p | Where-Object { $_ } | ForEach-Object { $_.Trim(', ') } | Sort-Object -Unique) -join ',') } else { 'gone' }
    }
    $offset = $null
    if ($all.Count -ge 2) {
        $p = Join-Path $d $all[$all.Count - 2]
        if (Test-Path $p) { $v = FirstPts $p 'v'; $a = FirstPts $p 'a'; if ($null -ne $v -and $null -ne $a) { $offset = $a - $v } }
    }
    $vtt = Get-Item "C:\ProgramData\CivicCast\data\egress\$c\captions\active.vtt" -ErrorAction SilentlyContinue
    $age = [int]((Get-Date) - $pl.LastWriteTime).TotalSeconds
    $flag = if ($age -gt 20) { 'STALE' } elseif ($types -notcontains 'audio,video') { 'NO-VIDEO' } elseif ($null -ne $offset -and [Math]::Abs($offset) -gt 0.5) { 'DESYNC' } else { 'ok' }
    $off = if ($null -ne $offset) { '{0:N3}s' -f $offset } else { 'n/a' }
    "{0,-10} {1,-8} age {2,4}s  segs [{3}]  a-v {4}  vtt {5}B" -f $c, $flag, $age, ($types -join ' | '), $off, $vtt.Length
}
