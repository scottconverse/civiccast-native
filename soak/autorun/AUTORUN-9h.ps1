# AUTORUN-9h (soak8-e1acfe6) -- read-only: count and timestamp the automation rollover /
# reload / relaunch / stall lines in the control-plane log, per channel, so the restart cause
# on this real box is measured, not inferred. No changes to the box.
$ErrorActionPreference = 'Continue'
$root  = 'C:\CivicCastSoak'
$repo  = "$root\repo"
$br    = "tester/soak8-e1acfe6-$env:COMPUTERNAME"
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$out   = @("# AUTORUN-9h rollover / relaunch timeline", "- host: $env:COMPUTERNAME", "- utc: $stamp", "")
$log = 'C:\ProgramData\CivicCast\logs\control_plane-app.log'
$lines = @(Get-Content $log -ErrorAction SilentlyContinue)
$out += "log lines: $($lines.Count) (bytes $((Get-Item $log -ErrorAction SilentlyContinue).Length))"
$patterns = [ordered]@{
  rollover   = 'rollover'
  reload     = 'reload'
  relaunch   = 'relaunch'
  stall      = 'stall'
  starting   = 'egress state -> STARTING'
  stopped    = 'egress state -> STOPPED'
  error      = 'ERROR'
  automation = 'automation'
  horizon    = 'horizon'
}
$out += "## counts (whole log)"
$out += '```'
foreach ($k in $patterns.Keys) { $out += "$k = $(@($lines | Where-Object { $_ -match $patterns[$k] }).Count)" }
$out += '```'
foreach ($k in 'rollover','reload','relaunch','starting','stopped','error') {
  $hits = @($lines | Where-Object { $_ -match $patterns[$k] } | Select-Object -Last 40)
  $out += "## $k (last 40)"
  $out += '```'
  $out += ($hits | ForEach-Object { $_.Substring(0, [Math]::Min(220, $_.Length)) })
  $out += '```'
}
# Per-channel ON_AIR write cadence over the last 200 ON_AIR lines: the automation tick length.
$onair = @($lines | Where-Object { $_ -match 'egress state -> ON_AIR' } | Select-Object -Last 200)
$out += "## ON_AIR write cadence (last 200 lines)"
$out += '```'
$out += "first: $($onair[0].Substring(0,23))  last: $($onair[-1].Substring(0,23))  n=$($onair.Count)"
$out += '```'
New-Item -Force -ItemType Directory "$repo\soak" | Out-Null
Set-Content "$repo\soak\DIAG-9h-$stamp.md" -Value ($out -join "`n") -Encoding utf8
git -C $repo add "soak/DIAG-9h-$stamp.md"
git -C $repo commit --quiet -m "test: autorun-9h rollover timeline $stamp soak8-e1acfe6"
git -C $repo push --quiet origin $br 2>&1 | Out-Null
exit 0
