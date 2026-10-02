# log.ps1 - append one timestamped row to OVERSIGHT-LOG.md. Every log row goes through here.
# Usage: log.ps1 -Kind <UNIT|AUDIT|DECISION|BASELINE|NOTE|LIVE> -Text "<one line>"
param(
    [Parameter(Mandatory)] [string]$Kind,
    [Parameter(Mandatory)] [string]$Text
)
$Log = Join-Path (Split-Path $PSScriptRoot -Parent) 'OVERSIGHT-LOG.md'
$ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz')
$row = "| $ts | $Kind | $($Text -replace '\|','/' -replace '\r?\n',' ') |"
if (-not (Test-Path $Log)) {
    $head = "# Oversight log - CivicCast beta.10 (coordinator: Claude; coder: DeepSeek)`n`n| Time (local) | Kind | Entry |`n|---|---|---|`n"
    [IO.File]::WriteAllText($Log, $head, (New-Object Text.UTF8Encoding $false))
}
[IO.File]::AppendAllText($Log, "$row`n", (New-Object Text.UTF8Encoding $false))
$row
