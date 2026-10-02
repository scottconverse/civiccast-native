# Elevated: restart the CivicCast supervisor (same call Install-Candidate.ps1 uses). No file changes.
$ErrorActionPreference = 'Stop'
Restart-Service -Name 'CivicCastSupervisor' -Force
(Get-Service 'CivicCastSupervisor').Status
