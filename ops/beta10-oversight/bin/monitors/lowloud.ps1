param([string]$Src, [int]$From, [int]$To, [int]$Step = 240)
$ff = 'C:\Program Files\CivicCast (Native)\dependencies\ffmpeg\bin\ffmpeg.exe'
$tmp = Join-Path $env:TEMP 'lowloud.txt'
for ($a = $From; $a -lt $To; $a += $Step) {
    $p = Start-Process -FilePath $ff -ArgumentList @('-hide_banner','-nostats','-ss',"$a",'-t',"$Step",'-i',"`"$Src`"",'-vn','-af','ebur128=framelog=quiet','-f','null','-') -RedirectStandardError $tmp -NoNewWindow -PassThru
    try { $p.PriorityClass = 'Idle' } catch {}
    $p.WaitForExit()
    $i = (Select-String -Path $tmp -Pattern '^\s+I:\s+(-?[\d.]+) LUFS' | Select-Object -Last 1).Matches.Groups[1].Value
    "$a $i"
}
