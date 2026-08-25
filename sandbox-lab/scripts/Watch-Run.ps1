$ErrorActionPreference = "SilentlyContinue"
$out = "C:\Users\scott\Desktop\Code\sandbox-lab\output"
$status = Join-Path $out "WATCH-STATUS.txt"
$t35 = Join-Path $out "T3T5-RESULT.txt"
$lastStep = ""
$lastChange = Get-Date
$maxMinutes = 360   # hard cap: install(~50) + 4h soak + margin
$deadline = (Get-Date).AddMinutes($maxMinutes)

while ((Get-Date) -lt $deadline) {
    $now = (Get-Date).ToString('HH:mm:ss')
    $vm = (Get-Process vmmemWindowsSandbox -ErrorAction SilentlyContinue | Measure-Object).Count
    # newest artifact + step
    $newest = Get-ChildItem $out -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $step = ""
    $summ = Join-Path $out "in-sandbox-summary.json"
    if (Test-Path $summ) { try { $step = (Get-Content $summ -Raw | ConvertFrom-Json).last_step } catch {} }
    $t35tail = ""
    if (Test-Path $t35) { $t35tail = (Get-Content $t35 -Tail 3) -join ' | ' }
    if ($step -ne $lastStep -and $step) { $lastStep = $step; $lastChange = Get-Date }
    $stalledMin = [int]((Get-Date) - $lastChange).TotalMinutes
    $line = "[$now] vm=$vm step='$step' stalled=${stalledMin}m newest='$($newest.Name)'@$($newest.LastWriteTime.ToString('HH:mm')) t35='$t35tail'"
    $line | Set-Content -Path $status -Encoding UTF8

    # done?
    if (Test-Path $t35) {
        $c = Get-Content $t35 -Raw
        if ($c -match 'T5_RESULT=') { "DONE $now`n$c" | Set-Content -Path $status -Encoding UTF8; break }
    }
    # VM vanished before T5 done = collapse
    if ($vm -eq 0 -and (Test-Path $summ)) {
        Start-Sleep -Seconds 15
        $vm2 = (Get-Process vmmemWindowsSandbox -ErrorAction SilentlyContinue | Measure-Object).Count
        if ($vm2 -eq 0) { "VM_GONE $now (before T5_RESULT) -- possible collapse`n$t35tail" | Set-Content -Path $status -Encoding UTF8; break }
    }
    Start-Sleep -Seconds 600
}
