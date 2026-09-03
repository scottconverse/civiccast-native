# DIRECTIVE 6 — soak72-9573d4a: unattended install via the poll task (autorun hook)

Trigger: START NOW

Ack (soak/ACK-6.md), then, in an ELEVATED PowerShell 5.1:

## 1. Add the autorun hook to the poll task (one time; survives app close and reboot)
Append this to the END of `C:\CivicCastSoak\bin\poll-directives.ps1`:
```
# --- autorun hook (DIRECTIVE-6): run any new soak/autorun/AUTORUN-*.ps1 from the directives branch, once each ---
$ranDir="$root\state\autorun-done"; New-Item -Force -ItemType Directory $ranDir | Out-Null
Get-ChildItem "$d\soak\autorun" -Filter 'AUTORUN-*.ps1' -ErrorAction SilentlyContinue | Sort-Object Name | ForEach-Object {
  $mark = Join-Path $ranDir ($_.Name + '.done')
  if (-not (Test-Path $mark)) { Set-Content $mark -Value $stamp; & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $_.FullName *> "$root\reports\$($_.BaseName)-$stamp.log" }
}
```
Then run the poll task once by hand: `Start-ScheduledTask -TaskName CivicCastSoak-Poll`. It will execute
`soak/autorun/AUTORUN-6.ps1` from the directives branch: verify the kit against SHA256SUMS.txt (re-fetching only
bad files with per-file curl), run the SILENT install (`/S /D=C:\CivicCastHostStore\install`), wait for `/health`,
and commit `soak/AUTORUN-6-<stamp>.md` with the installer exit code, the log tail and the health JSON to your branch.
That may take 30-40 minutes; do not interrupt it.

## 2. Then
When the station reports `status: healthy`, continue with DIRECTIVE-1 sections 4-11 (three channels with the
sample videos, program cycling, heartbeats are already running, 4-hour reports, 24 h checkpoint, 48 h end).
Never wait for a human. From now on the coordinator can also ship fixes as `soak/autorun/AUTORUN-<n>.ps1`; the
poll task runs each one exactly once and logs to `C:\CivicCastSoak\reports\`.
