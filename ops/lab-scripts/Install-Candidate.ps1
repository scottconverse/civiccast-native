# Install-Candidate.ps1 - run ELEVATED via ClaudeElevatedHelper (RunTrustedPowerShellScript).
# Installs a staged candidate over the installed CivicCast egress files with a verified backup, then
# restarts the service. Refuses if the installed files are not the exact expected base.
# Args: -StageDir <...\staging\U05> -BackupDir <new empty dir> [-NoRestart]
param(
    [Parameter(Mandatory)] [string]$StageDir,
    [Parameter(Mandatory)] [string]$BackupDir,
    [switch]$NoRestart,
    [string]$Pkg = 'C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages'   # override only for dry runs
)
$ErrorActionPreference = 'Stop'
$Service = 'CivicCastSupervisor'
$Cand = Join-Path $StageDir 'candidate'
$BaseSums = Join-Path $StageDir 'installed-base.sha256'
$log = New-Object System.Collections.Generic.List[string]
function Say($m) { $log.Add("$(Get-Date -Format 'HH:mm:ss') $m") }

if (-not (Test-Path $Cand)) { throw "candidate dir missing: $Cand" }
if (-not (Test-Path $BaseSums)) { throw "installed-base.sha256 missing: $BaseSums" }
if ((Test-Path $BackupDir) -and (Get-ChildItem $BackupDir -Force | Select-Object -First 1)) { throw "backup dir not empty: $BackupDir" }
New-Item -ItemType Directory -Force $BackupDir | Out-Null

# 1. Every installed file must match the base the candidate was built from.
#    Lines: "<SHA256>  <relative path under site-packages, e.g. civiccast\egress\automation.py>"
$expected = @{}
foreach ($line in Get-Content $BaseSums) {
    if ($line -match '^\s*([0-9A-Fa-f]{64})\s+\*?(.+?)\s*$') { $expected[$Matches[2].Replace('/','\')] = $Matches[1].ToUpper() }
}
if ($expected.Count -eq 0) { throw 'installed-base.sha256 parsed to zero entries' }
foreach ($rel in $expected.Keys) {
    $p = Join-Path $Pkg $rel
    if (-not (Test-Path $p)) { throw "REFUSING: installed file missing: $p" }
    $h = (Get-FileHash $p -Algorithm SHA256).Hash
    if ($h -ne $expected[$rel]) { throw "REFUSING: installed $rel is $h, expected base $($expected[$rel])" }
}
Say "base verified: $($expected.Count) files"

# 2. Candidate file list (relative to candidate\, must start with civiccast\).
$candFiles = Get-ChildItem $Cand -Recurse -File | ForEach-Object { $_.FullName.Substring($Cand.Length + 1) }
foreach ($rel in $candFiles) { if ($rel -notlike 'civiccast\*') { throw "candidate path outside civiccast\: $rel" } }

# 3. Backup: every installed file the candidate will overwrite; record which candidate files are NEW.
$manifest = [ordered]@{ created = (Get-Date).ToString('o'); pkg = $Pkg; replaced = @(); added = @() }
foreach ($rel in $candFiles) {
    $dst = Join-Path $Pkg $rel
    if (Test-Path $dst) {
        $b = Join-Path $BackupDir $rel
        New-Item -ItemType Directory -Force (Split-Path $b) | Out-Null
        Copy-Item -LiteralPath $dst -Destination $b -Force
        $hb = (Get-FileHash $b).Hash; $ho = (Get-FileHash $dst).Hash
        if ($hb -ne $ho) { throw "backup hash mismatch for $rel" }
        $manifest.replaced += [ordered]@{ path = $rel; sha256 = $ho }
    } else {
        $manifest.added += $rel
    }
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $BackupDir 'manifest.json') -Encoding utf8
Say "backup done: $($manifest.replaced.Count) replaced, $($manifest.added.Count) added"

# 4. Install and verify.
foreach ($rel in $candFiles) {
    $src = Join-Path $Cand $rel; $dst = Join-Path $Pkg $rel
    New-Item -ItemType Directory -Force (Split-Path $dst) | Out-Null
    Copy-Item -LiteralPath $src -Destination $dst -Force
    if ((Get-FileHash $src).Hash -ne (Get-FileHash $dst).Hash) { throw "install hash mismatch for $rel" }
    Say "installed $rel $((Get-FileHash $dst).Hash)"
}

# 5. Restart.
if (-not $NoRestart) {
    $before = (Get-CimInstance Win32_Service -Filter "Name='$Service'").ProcessId
    Restart-Service -Name $Service -Force
    Start-Sleep 5
    $after = Get-CimInstance Win32_Service -Filter "Name='$Service'"
    Say "service restarted: pid $before -> $($after.ProcessId) state $($after.State)"
}
$log | Set-Content (Join-Path $BackupDir 'install-log.txt') -Encoding utf8
$log
