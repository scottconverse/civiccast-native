$ErrorActionPreference='Stop'
Copy-Item -LiteralPath 'C:\CivicCastSource\native\install_service_identity.py' -Destination 'C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\civiccast\native\install_service_identity.py' -Force
Get-FileHash -LiteralPath 'C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages\civiccast\native\install_service_identity.py' | Select-Object Hash,Path | ConvertTo-Json | Set-Content 'C:\CivicCastEvidence\corrected-identity-source.json'
