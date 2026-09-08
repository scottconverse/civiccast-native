# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http

function New-CaptionProofHttpClient {
    $handler = [Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [Net.Http.HttpClient]::new($handler, $true)
    $client.Timeout = [TimeSpan]::FromSeconds(30)
    return $client
}

function Invoke-CaptionProofHttpRequest {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][Net.Http.HttpClient] $Client,
        [Parameter(Mandatory)][uri] $BaseUri,
        [Parameter(Mandatory)][string] $BearerToken,
        [Parameter(Mandatory)][ValidateSet('GET', 'POST')][string] $Method,
        [Parameter(Mandatory)][string] $Path,
        $Body,
        [Parameter(Mandatory)][ValidateSet('json', 'text', 'binary')][string] $ResponseKind
    )
    if ($BaseUri.Scheme -ne 'http' -or $BaseUri.Host -ne '127.0.0.1' -or $BaseUri.Port -ne 8000) {
        throw 'Caption acceptance HTTP is restricted to http://127.0.0.1:8000.'
    }
    if (-not $Path.StartsWith('/')) { throw "API path is not root-relative: $Path" }
    $uri = [uri]::new($BaseUri, $Path.TrimStart('/'))
    if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1' -or $uri.Port -ne 8000) { throw "API request leaves loopback: $Path" }
    $request = [Net.Http.HttpRequestMessage]::new([Net.Http.HttpMethod]::new($Method), $uri)
    if ($Path.StartsWith('/api/staff/', [StringComparison]::Ordinal)) {
        $request.Headers.Authorization = [Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $BearerToken)
    }
    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 12 -Compress
        $request.Content = [Net.Http.StringContent]::new($json, [Text.Encoding]::UTF8, 'application/json')
    }
    $response = $null
    try {
        $response = $Client.SendAsync($request).GetAwaiter().GetResult()
        $status = [int] $response.StatusCode
        if ($status -ge 300 -and $status -lt 400) { throw "HTTP redirect refused for $Method $Path (status $status)." }
        $bytes = $response.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
        $contentType = if ($null -ne $response.Content.Headers.ContentType) { "$($response.Content.Headers.ContentType)" } else { '' }
        $text = [Text.Encoding]::UTF8.GetString($bytes)
        $jsonBody = $null
        if ($ResponseKind -eq 'json' -and $text) {
            try { $jsonBody = $text | ConvertFrom-Json } catch { throw "HTTP $status $Method $Path returned invalid JSON." }
        }
        return [pscustomobject][ordered]@{
            status = $status
            content_type = $contentType
            body_json = $jsonBody
            body_text = $(if ($ResponseKind -eq 'binary') { $null } else { $text })
            body_bytes = $(if ($ResponseKind -eq 'binary') { $bytes } else { $null })
        }
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $request.Dispose()
    }
}

Export-ModuleMember -Function New-CaptionProofHttpClient, Invoke-CaptionProofHttpRequest
