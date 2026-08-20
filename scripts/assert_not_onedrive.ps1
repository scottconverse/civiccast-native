# SPDX-License-Identifier: Apache-2.0
# Fail fast if a CivicCast automation is launched from a OneDrive-backed path.

[CmdletBinding()]
param(
    [string]$Path = (Get-Location).Path
)

$resolved = [System.IO.Path]::GetFullPath($Path)
if ($resolved -like "C:\Users\scott\OneDrive\*") {
    throw "Refusing to run from OneDrive path: $resolved. Use C:\Dev\Claude\repos\scottconverse\civiccast."
}
