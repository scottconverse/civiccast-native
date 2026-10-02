# Clear-ConformCache.ps1 - delete named conform-cache entries (<key>.ts + <key>.json) so they are re-prepared.
# Usage: -Keys key1,key2  (32-hex cache keys). An entry in use by a running worker fails to delete and is reported.
param([Parameter(Mandatory)] [string[]]$Keys)
$dir = 'C:\ProgramData\CivicCast\data\egress\conform-cache'
foreach ($k in ($Keys -split ',')) {
    $k = $k.Trim()
    if ($k -notmatch '^[0-9a-f]{32}$') { "SKIP bad key $k"; continue }
    foreach ($ext in '.ts', '.json') {
        $p = Join-Path $dir "$k$ext"
        if (-not (Test-Path -LiteralPath $p)) { "absent $k$ext"; continue }
        try { Remove-Item -LiteralPath $p -Force -ErrorAction Stop; "deleted $k$ext" }
        catch { "LOCKED $k$ext : $($_.Exception.Message)" }
    }
}
