$processes=@(Get-CimInstance Win32_Process | Where-Object {$_.Name -in @('postgres.exe','python.exe','pythonservice.exe','ollama.exe')} | Select-Object ProcessId,Name)
ConvertTo-Json -InputObject $processes -Depth 3 | Set-Content 'C:\CivicCastEvidence\stopped-guest-processes.json'
if($processes.Count){throw 'Guest product/AI process remains running before Sandbox shutdown.'}
