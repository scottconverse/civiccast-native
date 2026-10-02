# trial-events.ps1 - READ-ONLY. Prints NEW rollover/stall/exit log lines since the last call (state in
# bin\.trial-events.state), then prints a PROBLEM line if any channel is stale / audio-only / missing.
# Case-SENSITIVE matching (last_error= would match a case-insensitive 'ERROR').
$Log = 'C:\ProgramData\CivicCast\logs\control_plane-app.log'
$State = Join-Path $PSScriptRoot '.trial-events.state'
$pattern = 'issued a seamless plan rollover|content-reload accepted|preparation for .* took|worker exited|past due|Channel automation pass for .* (has run|finished)|relay child|HLS relay up| ERROR civiccast\.egress|settled|discarded|FALLBACK_SLATE'
$len = (Get-Item $Log).Length
$from = 0L
if (Test-Path $State) { $from = [int64](Get-Content $State) }
if ($from -gt $len) { $from = 0L }   # log rotated
if ($from -lt $len) {
    $fs = [IO.File]::Open($Log, 'Open', 'Read', 'ReadWrite')
    try {
        $fs.Seek($from, 'Begin') | Out-Null
        $sr = New-Object IO.StreamReader($fs)
        $text = $sr.ReadToEnd()
    } finally { $fs.Dispose() }
    foreach ($line in ($text -split "`r?`n")) {
        if ($line -cmatch $pattern -and $line -cnotmatch 'phase_timing|egress state -> (FALLBACK_SLATE|ON_AIR) \(') { $line.Substring(0, [Math]::Min(220, $line.Length)) }
    }
}
Set-Content $State $len
$status = & (Join-Path $PSScriptRoot 'watch-live.ps1') -Segments 1
$bad = $status | Where-Object { $_ -match 'STALE|NO-VIDEO|NO PLAYLIST|DESYNC' }
if ($bad) { "PROBLEM $(Get-Date -Format HH:mm:ss): " + ($bad -join ' ; ') }
