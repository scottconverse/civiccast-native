# Install-GstRuntime.ps1 - run ELEVATED via ClaudeElevatedHelper (RunTrustedPowerShellScript).
# Swaps the bundled GStreamer runtime tree under the installed product for a staged, verified tree.
#   Install:  -Stage <...\staging\U17\gstreamer> -ExpectManifestSha256 <sha>
#   Rollback: -Rollback   (restores the newest gstreamer.bak-* beside the live tree)
# Steps: verify stage (manifest sha + every SHA256SUMS line) -> stop service -> wait for runtime processes
# to exit -> rename live tree to gstreamer.bak-<ts> -> copy stage -> re-verify installed copy -> start service.
# On any failure after the rename, the backup is put back before the service is started again.
param(
    [string]$Stage,
    [string]$ExpectManifestSha256,
    [switch]$Rollback,
    [string]$Deps = 'C:\Program Files\CivicCast (Native)\runtime\dependencies'
)
$ErrorActionPreference = 'Stop'
$Service = 'CivicCastSupervisor'
$Live = Join-Path $Deps 'gstreamer'
$RuntimeRoot = 'C:\Program Files\CivicCast (Native)'
$log = New-Object System.Collections.Generic.List[string]
function Say($m) { $log.Add("$(Get-Date -Format 'HH:mm:ss') $m") }

function Test-Tree($root) {
    # Every SHA256SUMS line must match; returns the number of files checked.
    $sums = Join-Path $root 'SHA256SUMS'
    if (-not (Test-Path $sums)) { throw "SHA256SUMS missing in $root" }
    $n = 0
    foreach ($line in Get-Content $sums) {
        if ($line -notmatch '^\s*([0-9A-Fa-f]{64})\s+\*?(.+?)\s*$') { continue }
        $want = $Matches[1].ToUpper(); $rel = $Matches[2].Replace('/', '\')
        $p = Join-Path $root $rel
        if (-not (Test-Path -LiteralPath $p)) { throw "missing $rel in $root" }
        $got = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
        if ($got -ne $want) { throw "hash mismatch $rel in $root" }
        $n++
    }
    if ($n -eq 0) { throw "SHA256SUMS in $root parsed to zero entries" }
    return $n
}

function Stop-Station {
    $before = (Get-CimInstance Win32_Service -Filter "Name='$Service'").ProcessId
    Stop-Service $Service -Force
    $deadline = (Get-Date).AddSeconds(90)
    do {
        $left = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($RuntimeRoot, 'OrdinalIgnoreCase') -and $_.Name -ne 'ollama.exe' })
        if ($left.Count -eq 0) { break }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    foreach ($p in $left) { Say "killing leftover $($p.Name) pid $($p.ProcessId)"; Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Say "service stopped (pid was $before)"
}

function Start-Station {
    Start-Service $Service
    $svc = Get-CimInstance Win32_Service -Filter "Name='$Service'"
    Say "service started: pid $($svc.ProcessId) state $($svc.State)"
}

try {
    if ($Rollback) {
        $bak = Get-ChildItem $Deps -Directory -Filter 'gstreamer.bak-*' | Sort-Object Name -Descending | Select-Object -First 1
        if (-not $bak) { throw 'no gstreamer.bak-* to roll back to' }
        Say "rollback source $($bak.FullName) verified $(Test-Tree $bak.FullName) files"
        Stop-Station
        $failed = Join-Path $Deps ("gstreamer.rolledback-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Rename-Item $Live $failed
        Rename-Item $bak.FullName $Live
        Say "restored; replaced tree kept at $failed"
        Start-Station
    } else {
        if (-not $Stage -or -not $ExpectManifestSha256) { throw 'install needs -Stage and -ExpectManifestSha256' }
        $m = (Get-FileHash (Join-Path $Stage 'runtime-manifest.json') -Algorithm SHA256).Hash
        if ($m -ne $ExpectManifestSha256.ToUpper()) { throw "stage manifest sha $m != expected $ExpectManifestSha256" }
        if (Get-ChildItem $Stage -Recurse -Directory -Filter '__pycache__') { throw 'stage contains __pycache__ (would fail the manifest verifier)' }
        Say "stage verified: manifest $m, $(Test-Tree $Stage) files"
        Say "live tree before: $((Get-Content (Join-Path $Live 'runtime-manifest.json') -Raw | ConvertFrom-Json).gstreamer_version)"
        Stop-Station
        $bakPath = Join-Path $Deps ("gstreamer.bak-" + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        Rename-Item $Live $bakPath
        Say "live tree moved to $bakPath"
        try {
            Copy-Item $Stage $Live -Recurse
            Say "installed copy verified: $(Test-Tree $Live) files, version $((Get-Content (Join-Path $Live 'runtime-manifest.json') -Raw | ConvertFrom-Json).gstreamer_version)"
        } catch {
            Say "copy/verify FAILED: $($_.Exception.Message) - restoring backup"
            if (Test-Path $Live) { Remove-Item $Live -Recurse -Force }
            Rename-Item $bakPath $Live
            Start-Station
            throw
        }
        Start-Station
    }
} catch {
    Say "ERROR: $($_.Exception.Message)"
    $log -join "`n"
    exit 1
}
$log -join "`n"
