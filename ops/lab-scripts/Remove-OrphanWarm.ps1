# Remove-OrphanWarm.ps1 - run ELEVATED via ClaudeElevatedHelper. Deletes ONE named stale warm directory
# under the CivicCast egress warm tree, only if nothing in it was written in the last 6 hours.
param([Parameter(Mandatory)] [string]$Channel, [Parameter(Mandatory)] [string]$Key)
$ErrorActionPreference = 'Stop'
if ($Channel -notmatch '^(education|government|public)$') { throw "bad channel $Channel" }
if ($Key -notmatch '^[0-9a-f]{12}$') { throw "bad key $Key" }
$dir = "C:\ProgramData\CivicCast\data\egress\$Channel\warm\$Key"
if (-not (Test-Path -LiteralPath $dir)) { "absent: $dir"; return }
$newest = Get-ChildItem -LiteralPath $dir -Recurse -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($newest -and $newest.LastWriteTime -gt (Get-Date).AddHours(-6)) { throw "REFUSING: $($newest.FullName) written $($newest.LastWriteTime)" }
$bytes = (Get-ChildItem -LiteralPath $dir -Recurse -File | Measure-Object Length -Sum).Sum
Remove-Item -LiteralPath $dir -Recurse -Force
"removed $dir ($bytes bytes, newest $($newest.LastWriteTime))"
