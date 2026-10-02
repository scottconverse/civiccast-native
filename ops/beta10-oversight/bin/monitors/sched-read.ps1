param([long]$From)
$fs=[IO.File]::Open('C:\ProgramData\CivicCast\logs\control_plane-app.log','Open','Read','ReadWrite')
if ($From -le 0 -or $From -gt $fs.Length) { $From = $fs.Length }
$fs.Seek($From,'Begin')|Out-Null; $t=(New-Object IO.StreamReader($fs)).ReadToEnd(); $len=$fs.Length; $fs.Dispose()
"POS $len"
($t -split "`n") | Where-Object { $_ -match 'past due|preparation for .* took [0-9]{2,}\.|worker exited' -or ($_ -match 'FALLBACK_SLATE' -and $_ -match 'egress state') } | ForEach-Object { $_.Substring(0,[Math]::Min(230,$_.Length)).TrimEnd() }
