# Rollback-Candidate.ps1 - run ELEVATED via ClaudeElevatedHelper (RunTrustedPowerShellScript).
# Restores the files saved by Install-Candidate.ps1, deletes files the candidate ADDED, restarts the service.
# Args: -BackupDir <dir written by Install-Candidate.ps1> [-NoRestart]
param(
    [Parameter(Mandatory)] [string]$BackupDir,
    [switch]$NoRestart
)
$ErrorActionPreference = 'Stop'
$Service = 'CivicCastSupervisor'
$m = Get-Content (Join-Path $BackupDir 'manifest.json') -Raw | ConvertFrom-Json
$Pkg = $m.pkg   # recorded by Install-Candidate.ps1 (a dry run records its fake root)
$log = New-Object System.Collections.Generic.List[string]
function Say($x) { $log.Add("$(Get-Date -Format 'HH:mm:ss') $x") }
foreach ($r in $m.replaced) {
    $b = Join-Path $BackupDir $r.path; $dst = Join-Path $Pkg $r.path
    if ((Get-FileHash $b).Hash -ne $r.sha256) { throw "backup copy of $($r.path) does not match its recorded hash" }
    Copy-Item -LiteralPath $b -Destination $dst -Force
    if ((Get-FileHash $dst).Hash -ne $r.sha256) { throw "restore hash mismatch for $($r.path)" }
    Say "restored $($r.path) $($r.sha256)"
}
foreach ($rel in @($m.added)) {
    if (-not $rel) { continue }
    $dst = Join-Path $Pkg $rel
    if (Test-Path $dst) { Remove-Item -LiteralPath $dst -Force; Say "removed added file $rel" }
    $pyc = Join-Path (Split-Path $dst) '__pycache__'
    Get-ChildItem $pyc -Filter ("{0}.*.pyc" -f [IO.Path]::GetFileNameWithoutExtension($dst)) -ErrorAction SilentlyContinue | Remove-Item -Force
}
if (-not $NoRestart) {
    $before = (Get-CimInstance Win32_Service -Filter "Name='$Service'").ProcessId
    Restart-Service -Name $Service -Force
    Start-Sleep 5
    $after = Get-CimInstance Win32_Service -Filter "Name='$Service'"
    Say "service restarted: pid $before -> $($after.ProcessId) state $($after.State)"
}
$log | Set-Content (Join-Path $BackupDir ('rollback-log-{0}.txt' -f (Get-Date -Format 'HHmmss'))) -Encoding utf8
$log
