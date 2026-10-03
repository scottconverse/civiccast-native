$kit='C:\Users\scott\Documents\Codex\2026-09-16\re\beta10-kit\kit2'
$out='C:\Users\scott\Documents\Codex\2026-09-16\re\beta10-kit\gatea5'
New-Item -ItemType Directory -Force $out | Out-Null
$pwsh='C:\Users\scott\AppData\Local\Microsoft\WindowsApps\pwsh.exe'
$args=@('-NoProfile','-File','C:\Users\scott\Documents\Codex\2026-09-16\re\civiccast-gatea-t4\sandbox-lab\Run-GateA.ps1','-KitDir',$kit,'-SourceSha','b652084707367d45913807ed2a525f15a9a1e4a4','-RunId','37039304786','-SoakMinutes','5')
$p=Start-Process -FilePath $pwsh -ArgumentList $args -WindowStyle Hidden -PassThru -RedirectStandardOutput "$out\run.out.txt" -RedirectStandardError "$out\run.err.txt"
"$($p.Id) $(Get-Date -Format s)" | Set-Content "$out\pid.txt"
