# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
# Used after the launcher patch and by NSIS !uninstfinalize. Credentials remain
# in the inherited environment, never in command arguments or generated scripts.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$LiteralPath)
$ErrorActionPreference = 'Stop'
try {
    $file = (Get-Item -LiteralPath $LiteralPath -ErrorAction Stop).FullName
    Import-Module ArtifactSigning -RequiredVersion 0.1.8 -ErrorAction Stop
    Invoke-ArtifactSigning -Endpoint 'https://wcus.codesigning.azure.net' `
        -CodeSigningAccountName 'scottconverse-signing' `
        -CertificateProfileName 'ScottConversePublic' -Files $file `
        -FileDigest SHA256 -TimestampRfc3161 'http://timestamp.acs.microsoft.com' `
        -TimestampDigest SHA256
    $signature = Get-AuthenticodeSignature -LiteralPath $file
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|,\s*)CN=Scott Converse(,|$)' -or -not $signature.TimeStamperCertificate) {
        throw 'Expected a valid timestamped Authenticode signature from Scott Converse.'
    }
    Write-Host "Verified installed executable signature: $([System.IO.Path]::GetFileName($file))"
    exit 0
} catch {
    Write-Error $_
    exit 1
}
