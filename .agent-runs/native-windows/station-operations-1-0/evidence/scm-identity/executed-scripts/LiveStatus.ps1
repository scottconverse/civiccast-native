$service = Get-CimInstance Win32_Service -Filter "Name='CivicCastSupervisor'"
$service | Select-Object State,StartName,ProcessId | ConvertTo-Json | Set-Content 'C:\CivicCastEvidence\live-service.json'
Get-CimInstance Win32_Process | Where-Object {$_.Name -in @('postgres.exe','python.exe','pythonservice.exe')} | Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Depth 4 | Set-Content 'C:\CivicCastEvidence\live-processes.json'
if(Test-Path 'C:\ProgramData\CivicCast\logs'){Get-ChildItem 'C:\ProgramData\CivicCast\logs' -Filter '*.log' | ForEach-Object {Copy-Item -LiteralPath $_.FullName -Destination 'C:\CivicCastEvidence' -Force -ErrorAction SilentlyContinue}}
