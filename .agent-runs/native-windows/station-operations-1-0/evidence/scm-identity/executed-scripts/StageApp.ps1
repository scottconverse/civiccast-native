$ErrorActionPreference='Stop'
Copy-Item -LiteralPath 'C:\CivicCastSource\app.py' -Destination 'C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\civiccast\app.py' -Force
Get-FileHash -LiteralPath 'C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\civiccast\app.py' | Select-Object Hash,Path | ConvertTo-Json | Set-Content 'C:\CivicCastEvidence\corrected-app-source.json'
