$results=@()
foreach($path in @('HKLM:\SYSTEM\CurrentControlSet\Services\CivicCastSupervisor','HKLM:\SYSTEM\CurrentControlSet\Services\CivicCastSupervisor\PythonClass','HKLM:\SYSTEM\CurrentControlSet\Services\CivicCastSupervisor\PythonPath')) {
  $entry=[ordered]@{path=$path}
  try{$entry.sddl=(Get-Acl -LiteralPath $path -ErrorAction Stop).Sddl}catch{$entry.aclError=$_.Exception.Message}
  try{$entry.defaultValue=(Get-Item -LiteralPath $path -ErrorAction Stop).GetValue('')}catch{$entry.readError=$_.Exception.Message}
  $results += $entry
}
$results | ConvertTo-Json -Depth 5 | Set-Content 'C:\CivicCastEvidence\migration-registry-acls.json'
