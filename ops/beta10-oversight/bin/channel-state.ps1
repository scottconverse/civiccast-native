# channel-state.ps1 - READ-ONLY: last daemon egress state line per channel (shared-read of control_plane-app.log).
$fs=[IO.File]::Open('C:\ProgramData\CivicCast\logs\control_plane-app.log','Open','Read','ReadWrite')
$fs.Seek([Math]::Max(0,$fs.Length-300000),'Begin')|Out-Null; $t=(New-Object IO.StreamReader($fs)).ReadToEnd(); $fs.Dispose()
$lines = $t -split "`n"
foreach ($c in 'public','government','education') {
  $l = $lines | Where-Object { $_ -match "channel ${c}: egress state" } | Select-Object -Last 1
  if ($l) { $l.Substring(0,[Math]::Min(200,$l.Length)).TrimEnd() } else { "${c}: no state line" }
}
