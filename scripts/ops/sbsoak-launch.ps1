# sbsoak-launch.ps1 -Sha <full sha> -Run <label> [-Minutes 15] [-Seamless] [-WorkerEnv "NAME=VALUE;..."]
# Launches Run-SandboxSoak.ps1 detached from the cc-sbsoak-run worktree (detached at origin/main since #184 merged),
# refuses if any sandbox process is alive, prints the pid + output folder.
param(
    [Parameter(Mandatory)][string]$Sha,
    [Parameter(Mandatory)][string]$Run,
    [int]$Minutes = 15,
    [switch]$Seamless,
    [int]$OnAirBound = 0,
    [switch]$CaptionsOff,
    [string[]]$WorkerEnv
)
$ErrorActionPreference = 'Stop'
$wt = 'C:\Users\scott\Desktop\Code\cc-sbsoak-run'
$S = 'C:\Users\scott\AppData\Local\Temp\claude\C--Users-scott-Desktop-Code\9e39825a-17bf-473c-8ada-72211a0f3e03\scratchpad'
Set-Location $wt
git fetch -q origin
git checkout -q --detach origin/main
"lane head $(git rev-parse --short HEAD) (origin/main)"
if (Get-Process -Name WindowsSandboxClient,WindowsSandboxRemoteSession,WindowsSandboxServer,vmmemWindowsSandbox -ErrorAction SilentlyContinue) { "SANDBOX BUSY"; exit 3 }
$short = $Sha.Substring(0,7)
$log = "$S\sbsoak-$short-$Run.log"
$args = @('-NoProfile','-ExecutionPolicy','Bypass','-File',"$wt\sandbox-lab\Run-SandboxSoak.ps1",'-Sha',$Sha,'-Minutes',"$Minutes")
if ($Seamless) { $args += '-SeamlessReload' }
if ($CaptionsOff) { $args += '-CaptionsOff' }
if ($OnAirBound -gt 0) { $args += @('-OnAirBoundMinutes', "$OnAirBound") }
if ($WorkerEnv) { $args += @('-WorkerEnv', ($WorkerEnv -join ';')) }
$p = Start-Process -FilePath pwsh -ArgumentList $args -RedirectStandardOutput $log -RedirectStandardError "$S\sbsoak-$short-$Run.err" -PassThru -WindowStyle Hidden
$h = $p.Handle
"pid $($p.Id) started $(Get-Date -Format u) seamless=$($Seamless.IsPresent) captionsOff=$($CaptionsOff.IsPresent) log=$log"
Start-Sleep 70
Get-Content $log -Tail 2
Get-Content "$S\sbsoak-$short-$Run.err" -Tail 3
$m = (Get-Content $log | Select-String "soak-$short-[0-9]+-[0-9]+Z" | Select-Object -First 1)
if ($m) { "OUTPUT " + $m.Matches[0].Value } else { "OUTPUT not found yet" }
