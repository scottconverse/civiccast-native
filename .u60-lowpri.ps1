param(
  [Parameter(Mandatory = $true)][string]$Out,
  [Parameter(Mandatory = $true)][string]$Targets
)
$ErrorActionPreference = "Stop"
$root = "C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-ds-u60"
Set-Location $root
$targetList = $Targets -split "," | Where-Object { $_ -ne "" }
$pytestArgs = @("-m", "pytest") + $targetList + @("-q", "-p", "no:randomly", "-rf")
$proc = Start-Process -FilePath "python" -ArgumentList $pytestArgs -NoNewWindow -PassThru `
  -RedirectStandardOutput $Out -RedirectStandardError "$Out.err" -WorkingDirectory $root
# The station's 8h rung owns the box: run the suite at idle priority.
try { (Get-Process -Id $proc.Id).PriorityClass = [System.Diagnostics.ProcessPriorityClass]::Idle } catch {}
Wait-Process -Id $proc.Id
"exit=$($proc.ExitCode)"
