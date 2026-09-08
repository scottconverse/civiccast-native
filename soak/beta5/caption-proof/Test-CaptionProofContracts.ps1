# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot 'CaptionProof.Contracts.psm1') -Force
Import-Module (Join-Path $PSScriptRoot 'CaptionProof.Http.psm1') -Force

$handlerTypeDefinition = @'
using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

public sealed class CaptionProofRequestRecord
{
    public string Method { get; set; }
    public string Uri { get; set; }
    public string Authorization { get; set; }
    public string Body { get; set; }
}

public sealed class CaptionProofRecordingHandler : HttpMessageHandler
{
    public readonly Queue<HttpResponseMessage> Responses = new Queue<HttpResponseMessage>();
    public readonly List<CaptionProofRequestRecord> Requests = new List<CaptionProofRequestRecord>();

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        if (Responses.Count == 0) throw new InvalidOperationException("No fake HTTP response queued.");
        Requests.Add(new CaptionProofRequestRecord {
            Method = request.Method.Method,
            Uri = request.RequestUri.AbsoluteUri,
            Authorization = request.Headers.Authorization == null ? null : request.Headers.Authorization.ToString(),
            Body = request.Content == null ? null : request.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        });
        return Task.FromResult(Responses.Dequeue());
    }
}
'@
if ($PSVersionTable.PSEdition -eq 'Desktop') {
    Add-Type -ReferencedAssemblies 'System.Net.Http.dll' -TypeDefinition $handlerTypeDefinition
} else {
    Add-Type -TypeDefinition $handlerTypeDefinition
}

function Assert-True([string] $Name, [bool] $Value) {
    if (-not $Value) { throw "Assertion failed: $Name" }
}

function Assert-Contains([string] $Name, [string] $Value, [string] $Expected) {
    if (-not $Value.Contains($Expected)) { throw "Assertion failed: $Name did not contain '$Expected'" }
}

function Assert-Throws([string] $Name, [scriptblock] $Action, [string] $Expected) {
    try {
        & $Action
        throw "Assertion failed: $Name did not throw"
    } catch {
        if ($_.Exception.Message -like 'Assertion failed:*') { throw }
        if ($Expected -and -not $_.Exception.Message.Contains($Expected)) { throw "Assertion failed: $Name threw unexpected error '$($_.Exception.Message)'" }
    }
}

function New-JsonResponse($Body, [int] $Status = 200) {
    return [pscustomobject]@{ status = $Status; content_type = 'application/json'; body_json = $Body; body_text = $null; body_bytes = $null }
}

function New-TextResponse([string] $Body, [string] $ContentType) {
    return [pscustomobject]@{ status = 200; content_type = $ContentType; body_json = $null; body_text = $Body; body_bytes = $null }
}

function New-BinaryResponse([byte[]] $Body, [string] $ContentType) {
    return [pscustomobject]@{ status = 200; content_type = $ContentType; body_json = $null; body_text = $null; body_bytes = $Body }
}

function Add-FakeHttpResponse {
    param(
        [Parameter(Mandatory)][CaptionProofRecordingHandler] $Handler,
        [Parameter(Mandatory)][int] $Status,
        [Parameter(Mandatory)][AllowEmptyCollection()][byte[]] $Bytes,
        [string] $ContentType = 'application/octet-stream',
        [string] $Location
    )
    $response = [Net.Http.HttpResponseMessage]::new([Net.HttpStatusCode] $Status)
    $response.Content = [Net.Http.ByteArrayContent]::new($Bytes)
    $response.Content.Headers.ContentType = [Net.Http.Headers.MediaTypeHeaderValue]::Parse($ContentType)
    if ($Location) { $response.Headers.Location = [uri] $Location }
    $Handler.Responses.Enqueue($response)
    return $response
}

$recordingHandler = [CaptionProofRecordingHandler]::new()
$recordingClient = [Net.Http.HttpClient]::new($recordingHandler, $false)
$httpBase = [uri] 'http://127.0.0.1:8000/'
try {
    $queuedJson = Add-FakeHttpResponse $recordingHandler 200 ([Text.Encoding]::UTF8.GetBytes('{"ok":true}')) 'application/json; charset=utf-8'
    $jsonEnvelope = Invoke-CaptionProofHttpRequest -Client $recordingClient -BaseUri $httpBase -BearerToken 'unit-secret' -Method POST -Path '/api/staff/captions/review-items/r1/approve' -Body ([ordered]@{ low_confidence_acknowledged = $true }) -ResponseKind json
    Assert-True 'HTTP wrapper parses JSON' ($jsonEnvelope.status -eq 200 -and $jsonEnvelope.body_json.ok -eq $true)
    Assert-True 'HTTP wrapper authenticates staff request' ($recordingHandler.Requests[0].Authorization -eq 'Bearer unit-secret')
    Assert-True 'HTTP wrapper encodes JSON request body' ($recordingHandler.Requests[0].Body -match '"low_confidence_acknowledged":true')
    $responseDisposed = $false
    try { $null = $queuedJson.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult() } catch { $responseDisposed = $true }
    Assert-True 'HTTP wrapper disposes response after materializing it' $responseDisposed

    $null = Add-FakeHttpResponse $recordingHandler 200 ([Text.Encoding]::UTF8.GetBytes("#EXTM3U`n")) 'application/vnd.apple.mpegurl'
    $textEnvelope = Invoke-CaptionProofHttpRequest -Client $recordingClient -BaseUri $httpBase -BearerToken 'unit-secret' -Method GET -Path '/api/public/assets/a' -Body $null -ResponseKind text
    Assert-True 'HTTP wrapper returns text' ($textEnvelope.body_text.StartsWith('#EXTM3U'))
    Assert-True 'HTTP wrapper leaves public request anonymous' ($null -eq $recordingHandler.Requests[1].Authorization)

    $null = Add-FakeHttpResponse $recordingHandler 200 ([byte[]](1, 2, 3, 4)) 'audio/wav'
    $binaryEnvelope = Invoke-CaptionProofHttpRequest -Client $recordingClient -BaseUri $httpBase -BearerToken 'unit-secret' -Method GET -Path '/media/vod/a/captions/en/seg000.vtt' -Body $null -ResponseKind binary
    Assert-True 'HTTP wrapper preserves binary bytes' ($binaryEnvelope.body_bytes.Count -eq 4 -and $binaryEnvelope.body_bytes[3] -eq 4)
    Assert-True 'HTTP wrapper leaves media request anonymous' ($null -eq $recordingHandler.Requests[2].Authorization)

    $null = Add-FakeHttpResponse $recordingHandler 302 ([byte[]]@()) 'text/plain' 'https://external.invalid/escape'
    $redirectRefused = $false
    try {
        $null = Invoke-CaptionProofHttpRequest -Client $recordingClient -BaseUri $httpBase -BearerToken 'unit-secret' -Method GET -Path '/media/vod/a/playlist.m3u8' -Body $null -ResponseKind text
    } catch {
        $redirectRefused = $_.Exception.Message -like '*redirect refused*'
    }
    Assert-True 'HTTP wrapper refuses redirect' $redirectRefused
    Assert-True 'redirect request remains local and anonymous' ($recordingHandler.Requests[3].Uri -eq 'http://127.0.0.1:8000/media/vod/a/playlist.m3u8' -and $null -eq $recordingHandler.Requests[3].Authorization)
} finally {
    $recordingClient.Dispose()
    $recordingHandler.Dispose()
}
$factoryClient = New-CaptionProofHttpClient
try {
    Assert-True 'production HTTP client factory loads on this PowerShell runtime' ($factoryClient.GetType().FullName -eq 'System.Net.Http.HttpClient' -and $factoryClient.Timeout.TotalSeconds -eq 30)
} finally {
    $factoryClient.Dispose()
}

function New-ReviewRow([string] $AssetId, [string] $Language, [int] $Index, [bool] $LowConfidence = $false) {
    return [pscustomobject]@{
        review_item_id = "$AssetId-$Language-review-$Index"
        asset_id = $AssetId
        cue = [pscustomobject]@{ cue_id = "$AssetId-$Language-cue-$Index"; start_seconds = ($Index - 1); end_seconds = $Index; text = "cue $Index"; confidence = 0.9; low_confidence = $LowConfidence }
        language = $Language
        status = 'pending'
        original_text = "cue $Index"
        reviewed_text = $null
        low_confidence = $LowConfidence
        audio_evidence_available = $LowConfidence
        reviewer_note = $null
    }
}

$script:assetId = 'sample-one'
$script:manifestPath = '/media/vod/sample-one/playlist.m3u8'
$script:identity = [pscustomobject]@{
    mission = 'beta5-proof-test'
    candidate_source_sha = ('a' * 40)
    channels = @(
        [pscustomobject]@{ channel_id = 'public'; udp_port = 9001 },
        [pscustomobject]@{ channel_id = 'education'; udp_port = 9002 },
        [pscustomobject]@{ channel_id = 'government'; udp_port = 9003 }
    )
    approved_assets = @(
        [pscustomobject]@{ asset_id = $script:assetId; title = 'Mission sample one'; duration_seconds = 60 },
        [pscustomobject]@{ asset_id = 'sample-two'; title = 'Mission sample two'; duration_seconds = 61 }
    )
}
$script:englishRows = @(
    (New-ReviewRow $script:assetId 'en' 1 $true),
    (New-ReviewRow $script:assetId 'en' 2 $false)
)
$script:spanishRows = @(
    (New-ReviewRow $script:assetId 'es' 1 $false),
    (New-ReviewRow $script:assetId 'es' 2 $false)
)
$script:master = @'
#EXTM3U
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",LANGUAGE="en",NAME="English",DEFAULT=YES,AUTOSELECT=YES,URI="captions/en/playlist.m3u8"
#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subtitles",LANGUAGE="es",NAME="Spanish",DEFAULT=NO,AUTOSELECT=YES,URI="captions/es/playlist.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=414000,SUBTITLES="subtitles"
240p/playlist.m3u8
'@
$script:captionPlaylist = @'
#EXTM3U
#EXT-X-TARGETDURATION:2
#EXTINF:2.000,
seg000.vtt
#EXT-X-ENDLIST
'@
$script:vtt = @'
WEBVTT

00:00.000 --> 00:01.000
Acceptance cue.
'@

function Reset-FakeApi {
    $script:calls = [Collections.ArrayList]::new()
    $script:events = [Collections.ArrayList]::new()
    $script:approvedEnglish = [Collections.ArrayList]::new()
    $script:approvedSpanish = [Collections.ArrayList]::new()
    $script:channelStateCalls = @{}
    $script:channelConfigCalls = @{}
    $script:externalManifest = $false
    $script:wrongApprovalCue = $false
    $script:suppressSpanish = $false
    $script:driftConfig = $false
    $script:driftService = $false
}

function Invoke-FakeApi($Method, $Path, $Body, $ResponseKind) {
    $null = $script:calls.Add([pscustomobject]@{ method = $Method; path = $Path; body = $Body; response_kind = $ResponseKind })
    if ($Method -eq 'GET' -and $Path -match '^/api/staff/egress/channels/([^/]+)/config$') {
        $id = [uri]::UnescapeDataString($Matches[1])
        if (-not $script:channelConfigCalls.ContainsKey($id)) { $script:channelConfigCalls[$id] = 0 }
        $script:channelConfigCalls[$id]++
        $label = if ($script:driftConfig -and $script:channelConfigCalls[$id] -gt 1 -and $id -eq 'public') { 'changed' } else { 'stable' }
        return New-JsonResponse ([pscustomobject]@{ channel_id = $id; enabled = $true; auto_start = $true; slate_message = $label; sinks = @([pscustomobject]@{ kind = 'udp-ts'; uri = 'udp://127.0.0.1:9001' }) })
    }
    if ($Method -eq 'GET' -and $Path -match '^/api/staff/egress/channels/([^/]+)/state$') {
        $id = [uri]::UnescapeDataString($Matches[1])
        if (-not $script:channelStateCalls.ContainsKey($id)) { $script:channelStateCalls[$id] = 0 }
        $script:channelStateCalls[$id]++
        $state = if ($id -eq 'public' -and $script:channelStateCalls[$id] -gt 1) { 'FALLBACK_SLATE' } else { 'ON_AIR' }
        $workerPid = switch ($id) { 'public' { 101 }; 'education' { 102 }; default { 103 } }
        return New-JsonResponse ([pscustomobject]@{ channel_id = $id; state = $state; current_source_label = 'acceptance source'; pid = $workerPid })
    }
    if ($Method -eq 'GET' -and $Path -eq '/api/staff/assets/sample-one') {
        $manifest = if ($script:externalManifest) { 'https://cdn.invalid/sample-one/playlist.m3u8' } else { $script:manifestPath }
        return New-JsonResponse ([pscustomobject]@{ asset_id = $script:assetId; title = 'Mission sample one'; duration_seconds = 60; state = 'validated'; manifest_url = $manifest; published_at = '2026-09-08T00:00:00Z' })
    }
    if ($Method -eq 'GET' -and $Path -eq '/api/public/assets/sample-one') {
        return New-JsonResponse ([pscustomobject]@{ asset_id = $script:assetId; title = 'Mission sample one'; duration_seconds = 60; manifest_url = $script:manifestPath; published_at = '2026-09-08T00:00:00Z' })
    }
    if ($Method -eq 'GET' -and $Path -like '/api/staff/captions/offline-jobs?*') {
        $complete = $script:approvedSpanish.Count -eq 2
        return New-JsonResponse @([pscustomobject]@{ job_id = 'job-one'; asset_id = $script:assetId; state = $(if ($complete) { 'complete' } else { 'awaiting_review' }); cue_count = 2; published_cue_count = $(if ($complete) { 2 } else { 0 }); last_error = ''; next_attempt_at = $null })
    }
    if ($Method -eq 'GET' -and $Path -like '*review-items?*language=en') {
        return New-JsonResponse @($script:englishRows | Where-Object { $script:approvedEnglish -notcontains $_.review_item_id })
    }
    if ($Method -eq 'GET' -and $Path -like '*review-items?*language=es') {
        if ($script:suppressSpanish -or $script:approvedEnglish.Count -ne 2) { return New-JsonResponse @() }
        return New-JsonResponse @($script:spanishRows | Where-Object { $script:approvedSpanish -notcontains $_.review_item_id })
    }
    if ($Method -eq 'GET' -and $Path -like '*/clip') {
        return New-BinaryResponse ([byte[]](0..63)) 'audio/wav'
    }
    if ($Method -eq 'POST' -and $Path -match '/review-items/([^/]+)/approve$') {
        $reviewId = [uri]::UnescapeDataString($Matches[1])
        $row = @($script:englishRows + $script:spanishRows | Where-Object { $_.review_item_id -eq $reviewId })
        if ($row.Count -ne 1) { throw "Unknown fake review $reviewId" }
        if ($row[0].language -eq 'en') { $null = $script:approvedEnglish.Add($reviewId) } else { $null = $script:approvedSpanish.Add($reviewId) }
        $cueId = if ($script:wrongApprovalCue) { 'wrong-cue' } else { $row[0].cue.cue_id }
        return New-JsonResponse ([pscustomobject]@{ review_item_id = $reviewId; asset_id = $row[0].asset_id; cue = [pscustomobject]@{ cue_id = $cueId; text = $row[0].cue.text }; language = $row[0].language; status = 'approved'; reviewed_text = $row[0].cue.text })
    }
    if ($Method -eq 'GET' -and $Path -eq $script:manifestPath) { return New-TextResponse $script:master 'application/vnd.apple.mpegurl' }
    if ($Method -eq 'GET' -and $Path -in @('/media/vod/sample-one/captions/en/playlist.m3u8', '/media/vod/sample-one/captions/es/playlist.m3u8')) { return New-TextResponse $script:captionPlaylist 'application/vnd.apple.mpegurl' }
    if ($Method -eq 'GET' -and $Path -in @('/media/vod/sample-one/captions/en/seg000.vtt', '/media/vod/sample-one/captions/es/seg000.vtt', '/media/vod/sample-one/captions/captions.vtt', '/media/vod/sample-one/captions/captions.es.vtt')) { return New-TextResponse $script:vtt 'text/vtt; charset=utf-8' }
    throw "Unexpected fake API call: $Method $Path ($ResponseKind)"
}

function Invoke-FakeInstalledIdentity {
    $script:serviceCalls++
    $servicePid = if ($script:driftService -and $script:serviceCalls -gt 1) { 778 } else { 777 }
    return [pscustomobject]@{ service_process_id = $servicePid; service_process_started_utc = '2026-09-08T00:00:00Z'; health = [pscustomobject]@{ status = 'healthy'; schema = 'current'; version = '1.0.0-beta.5' } }
}

function Invoke-Workflow {
    $script:serviceCalls = 0
    $api = { param($Method, $Path, $Body, $ResponseKind) Invoke-FakeApi $Method $Path $Body $ResponseKind }
    $service = { Invoke-FakeInstalledIdentity }
    $recorder = { param($Event) $null = $script:events.Add($Event) }
    return Invoke-CaptionProofWorkflow -Identity $script:identity -AssetId $script:assetId -ApiInvoker $api -InstalledIdentityInvoker $service -EventRecorder $recorder -SleepInvoker { param($Seconds) } -PollIntervalSeconds 10 -MaxPollSeconds 10
}

Reset-FakeApi
$pass = Invoke-Workflow
if ($pass.verdict -ne 'PASS') { Write-Host ($pass | ConvertTo-Json -Depth 30) }
Assert-True 'happy workflow passes' ($pass.verdict -eq 'PASS')
Assert-True 'installed identity invoker runs before and after workflow' ($script:serviceCalls -eq 2)
Assert-True 'exactly four review approvals issued' (@($script:calls | Where-Object { $_.method -eq 'POST' }).Count -eq 4)
Assert-True 'all mutations are selected-item approvals' (@($script:calls | Where-Object { $_.method -eq 'POST' -and $_.path -notmatch '^/api/staff/captions/review-items/[^/]+/approve$' }).Count -eq 0)
Assert-True 'no channel or schedule mutation issued' (@($script:calls | Where-Object { $_.method -ne 'GET' -and ($_.path -like '*egress*' -or $_.path -like '*schedule*') }).Count -eq 0)
$clipIndex = @($script:calls.path).IndexOf('/api/staff/captions/review-items/sample-one-en-review-1/clip')
$approveIndex = @($script:calls.path).IndexOf('/api/staff/captions/review-items/sample-one-en-review-1/approve')
Assert-True 'low-confidence preview precedes acknowledgement' ($clipIndex -ge 0 -and $approveIndex -gt $clipIndex)
$enSelectedEvent = @($script:events | Where-Object { $_.event -eq 'caption-review-pass-selected' -and $_.language -eq 'en' })[0]
$esSelectedEvent = @($script:events | Where-Object { $_.event -eq 'caption-review-pass-selected' -and $_.language -eq 'es' })[0]
$previewEventIndex = @($script:events.event).IndexOf('low-confidence-preview-fetched')
$intentEventIndex = @($script:events.event).IndexOf('caption-review-approval-intent')
$approvedEventIndex = @($script:events.event).IndexOf('caption-review-approved')
Assert-True 'English IDs selected before approvals' ($enSelectedEvent.review_item_ids.Count -eq 2 -and $script:events[0].event -eq 'caption-review-pass-selected')
Assert-True 'Spanish IDs selected before Spanish approvals' ($esSelectedEvent.review_item_ids.Count -eq 2)
Assert-True 'preview and durable intent precede approval evidence' ($previewEventIndex -gt 0 -and $intentEventIndex -gt $previewEventIndex -and $approvedEventIndex -gt $intentEventIndex)
Assert-True 'bilingual public artifacts proven' ($pass.public_artifacts.languages.Count -eq 2 -and $pass.public_artifacts.flat_sidecars.Count -eq 2)
Assert-True 'every referenced caption segment is proven' (@($pass.public_artifacts.languages | Where-Object { @($_.segments).Count -ne 1 }).Count -eq 0)
Assert-True 'legitimate automation transition retained' (@($pass.channel_continuity | Where-Object { $_.channel_id -eq 'public' -and $_.legitimate_automation_transition_observed }).Count -eq 1)
Assert-True 'browser playback remains explicitly unproven' ($pass.resident_browser_playback -like 'NOT_RUN*')
Assert-True 'automated workflow does not certify editorial accuracy' ($pass.transcript_editorial_accuracy -like 'NOT_CERTIFIED*')
Assert-True 'token not recorded' (-not (($pass | ConvertTo-Json -Depth 30).Contains('secret-test-token')))
Assert-True 'staff API requires bearer auth' (Test-CaptionPathRequiresAuthorization '/api/staff/captions/offline-jobs')
Assert-True 'public API is anonymous' (-not (Test-CaptionPathRequiresAuthorization '/api/public/assets/sample-one'))
Assert-True 'media delivery is anonymous' (-not (Test-CaptionPathRequiresAuthorization '/media/vod/sample-one/playlist.m3u8'))

Reset-FakeApi
$script:externalManifest = $true
$external = Invoke-Workflow
Assert-True 'external manifest fails' ($external.verdict -eq 'FAIL')
Assert-Contains 'external manifest reason' $external.primary_error 'not bound to the expected local VOD manifest'
Assert-True 'external manifest fails before any product mutation' (@($script:calls | Where-Object { $_.method -eq 'POST' }).Count -eq 0)

Reset-FakeApi
$script:wrongApprovalCue = $true
$wrongCue = Invoke-Workflow
Assert-True 'approval cue mismatch fails' ($wrongCue.verdict -eq 'FAIL')
Assert-Contains 'approval cue mismatch reason' $wrongCue.primary_error 'Approval response identity mismatch'

Reset-FakeApi
$script:suppressSpanish = $true
$bounded = Invoke-Workflow
Assert-True 'missing Spanish phase fails bounded' ($bounded.verdict -eq 'FAIL')
Assert-Contains 'missing Spanish reason' $bounded.primary_error 'Timed out waiting for exactly 2 pending es caption rows'

Reset-FakeApi
$script:driftConfig = $true
$configDrift = Invoke-Workflow
Assert-True 'channel config drift fails' ($configDrift.verdict -eq 'FAIL')
Assert-Contains 'channel config drift reason' $configDrift.continuity_error 'configuration changed'

Reset-FakeApi
$script:driftService = $true
$serviceDrift = Invoke-Workflow
Assert-True 'service drift fails' ($serviceDrift.verdict -eq 'FAIL')
Assert-Contains 'service drift reason' $serviceDrift.continuity_error 'PID or start time changed'

Assert-True 'asset traversal reference rejected' $(try { Resolve-CaptionLocalReference 'sample-one' $script:manifestPath '../../other/playlist.m3u8' | Out-Null; $false } catch { $true })

$runtimeRoot = Join-Path ([IO.Path]::GetTempPath()) ('beta5-caption-runtime-' + [guid]::NewGuid().ToString('N'))
try {
    $daemonPath = Join-Path $runtimeRoot 'Lib\site-packages\civiccast\egress\daemon.py'
    $strategyPath = Join-Path $runtimeRoot 'Lib\site-packages\civiccast\egress\gst\strategy.py'
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $daemonPath) | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $strategyPath) | Out-Null
    Set-Content -LiteralPath $daemonPath -Value 'candidate daemon bytes' -Encoding utf8
    Set-Content -LiteralPath $strategyPath -Value 'candidate strategy bytes' -Encoding utf8
    $daemonHash = (Get-FileHash -LiteralPath $daemonPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $strategyHash = (Get-FileHash -LiteralPath $strategyPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $receipt = [pscustomobject][ordered]@{
        'Lib/site-packages/civiccast/egress/daemon.py' = $daemonHash
        'Lib/site-packages/civiccast/egress/gst/strategy.py' = $strategyHash
    }
    $runtimeIdentity = [pscustomobject]@{ expected_runtime_file_sha256 = $receipt; actual_runtime_file_sha256 = $receipt.PSObject.Copy() }
    $runtimeProof = Assert-CaptionInstalledRuntimeHashes -Identity $runtimeIdentity -RuntimeRoot $runtimeRoot
    Assert-True 'current runtime hash proof checks exact two files' ($runtimeProof.files.Count -eq 2 -and @($runtimeProof.files | Where-Object { $_.expected_sha256 -ne $_.current_sha256 }).Count -eq 0)

    Set-Content -LiteralPath $daemonPath -Value 'changed daemon bytes' -Encoding utf8
    Assert-Throws 'changed current runtime rejected' { Assert-CaptionInstalledRuntimeHashes -Identity $runtimeIdentity -RuntimeRoot $runtimeRoot } 'does not match the candidate payload'
    Set-Content -LiteralPath $daemonPath -Value 'candidate daemon bytes' -Encoding utf8
    Remove-Item -LiteralPath $strategyPath -Force
    Assert-Throws 'missing current runtime rejected' { Assert-CaptionInstalledRuntimeHashes -Identity $runtimeIdentity -RuntimeRoot $runtimeRoot } 'is absent'
    Set-Content -LiteralPath $strategyPath -Value 'candidate strategy bytes' -Encoding utf8

    $extraExpected = [pscustomobject][ordered]@{
        'Lib/site-packages/civiccast/egress/daemon.py' = $daemonHash
        'Lib/site-packages/civiccast/egress/gst/strategy.py' = $strategyHash
        'Lib/site-packages/civiccast/egress/extra.py' = ('e' * 64)
    }
    $extraIdentity = [pscustomobject]@{ expected_runtime_file_sha256 = $extraExpected; actual_runtime_file_sha256 = $receipt.PSObject.Copy() }
    Assert-Throws 'extra runtime receipt key rejected' { Assert-CaptionInstalledRuntimeHashes -Identity $extraIdentity -RuntimeRoot $runtimeRoot } 'exactly two keys'
} finally {
    Remove-Item -LiteralPath $runtimeRoot -Recurse -Force -ErrorAction SilentlyContinue
}

foreach ($file in @('CaptionProof.Contracts.psm1', 'Invoke-Beta5CaptionAcceptance.ps1', 'Get-Beta5BrowserPrerequisites.ps1')) {
    $tokens = $null
    $errors = $null
    $null = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file), [ref] $tokens, [ref] $errors)
    Assert-True "$file parses" (@($errors).Count -eq 0)
}
$moduleText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'CaptionProof.Contracts.psm1') -Raw
Assert-True 'caption core contains no channel commands route' (-not $moduleText.Contains('/commands'))
Assert-True 'caption core contains no schedule route' (-not $moduleText.Contains('/api/staff/schedule'))
Assert-True 'caption core contains no retry route' (-not $moduleText.Contains('/retry'))
$inventoryText = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Get-Beta5BrowserPrerequisites.ps1') -Raw
Assert-True 'browser inventory has exact host guard' ($inventoryText.Contains("[ValidateSet('DESKTOP-VBMA6O5')]"))
Assert-True 'browser inventory does not start processes' (-not $inventoryText.Contains('Start-Process'))
Assert-True 'browser inventory does not scan recursively' (-not $inventoryText.Contains('Get-ChildItem'))

# Exercise the actual readiness expressions with portable PATH-only installs.
$inventoryTokens = $null
$inventoryErrors = $null
$inventoryAst = [Management.Automation.Language.Parser]::ParseInput($inventoryText, [ref] $inventoryTokens, [ref] $inventoryErrors)
$readinessAst = $inventoryAst.Find({ param($Node) $Node -is [Management.Automation.Language.HashtableAst] -and @($Node.KeyValuePairs | Where-Object { $_.Item1.Extent.Text -eq 'node_present' }).Count -eq 1 }, $true)
Assert-True 'inventory readiness table exists' ($null -ne $readinessAst)
$executables = @()
foreach ($case in @(@('node_present', 'node.exe'), @('npm_present', 'npm.cmd'))) {
    $expression = @($readinessAst.KeyValuePairs | Where-Object { $_.Item1.Extent.Text -eq $case[0] })[0].Item2.Extent.Text
    $pathDiscovery = @([pscustomobject]@{ name = $case[1]; found = $true })
    Assert-True "PATH-only $($case[0]) is available" ([bool] (& ([scriptblock]::Create($expression))))
    $pathDiscovery = @([pscustomobject]@{ name = $case[1]; found = $false })
    Assert-True "missing $($case[0]) is unavailable" (-not [bool] (& ([scriptblock]::Create($expression))))
}

$planRoot = Join-Path ([IO.Path]::GetTempPath()) ('beta5-caption-plan-' + [guid]::NewGuid().ToString('N'))
$oldComputerName = $env:COMPUTERNAME
try {
    $env:COMPUTERNAME = 'DESKTOP-VBMA6O5'
    $mission = 'beta5-caption-plan-test'
    $missionRoot = Join-Path $planRoot "missions\$mission"
    $returnRepo = Join-Path $missionRoot 'return-repo'
    $verdictDir = Join-Path $returnRepo "soak\beta5\$mission"
    New-Item -ItemType Directory -Force -Path $verdictDir | Out-Null
    $runtimeHash = ('d' * 64)
    $planIdentity = [ordered]@{
        schema = 'civiccast-native-tester-run-identity-v3'
        mission = $mission
        candidate_source_sha = ('a' * 40)
        build_source_sha = ('a' * 40)
        gate_a_source_sha = ('a' * 40)
        expected_manifest_sha256 = ('b' * 64)
        expected_installer_sha256 = ('c' * 64)
        expected_version = '1.0.0-beta.5'
        build_run_id = 123
        build_conclusion = 'success'
        gate_a_run_id = 456
        gate_a_verdict = 'PASS'
        kit_base_url = ('http://127.0.0.1:8766/' + ('a' * 40) + '/')
        return_repository_url = 'https://github.com/scottconverse/civiccast-native.git'
        return_branch = 'tester/soak8-e1acfe6-DESKTOP-VBMA6O5'
        hostname = 'DESKTOP-VBMA6O5'
        expected_hostname = 'DESKTOP-VBMA6O5'
        tester_root = $planRoot
        mission_state_root = $missionRoot
        return_repo_path = $returnRepo
        planned_seconds = 7200
        sample_interval_seconds = 60
        channels = @(
            [ordered]@{ channel_id = 'public'; udp_port = 9001 },
            [ordered]@{ channel_id = 'education'; udp_port = 9002 },
            [ordered]@{ channel_id = 'government'; udp_port = 9003 }
        )
        approved_assets = @(
            [ordered]@{ asset_id = 'sample-one'; title = 'Mission sample one'; duration_seconds = 60 },
            [ordered]@{ asset_id = 'sample-two'; title = 'Mission sample two'; duration_seconds = 61 }
        )
        installed_version = '1.0.0-beta.5'
        actual_manifest_sha256 = ('b' * 64)
        actual_installer_sha256 = ('c' * 64)
        native_app_payload_source_sha = ('a' * 40)
        expected_runtime_file_sha256 = [ordered]@{ 'Lib/site-packages/civiccast/egress/daemon.py' = $runtimeHash; 'Lib/site-packages/civiccast/egress/gst/strategy.py' = $runtimeHash }
        actual_runtime_file_sha256 = [ordered]@{ 'Lib/site-packages/civiccast/egress/daemon.py' = $runtimeHash; 'Lib/site-packages/civiccast/egress/gst/strategy.py' = $runtimeHash }
    }
    $identityPath = Join-Path $missionRoot 'run-identity.json'
    New-Item -ItemType Directory -Force -Path $missionRoot | Out-Null
    $planIdentity | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $identityPath -Encoding utf8
    $verdictPath = Join-Path $verdictDir 'final-verdict.json'
    [ordered]@{ schema = 'civiccast-native-beta5-media-verdict-v3'; mission = $mission; candidate_source_sha = ('a' * 40); verdict = 'PASS' } | ConvertTo-Json | Set-Content -LiteralPath $verdictPath -Encoding utf8
    $runner = Join-Path $PSScriptRoot 'Invoke-Beta5CaptionAcceptance.ps1'
    $missingTokenPath = Join-Path $planRoot 'must-not-be-read-token'
    $deployedCommon = Join-Path $PSScriptRoot '..\Beta5Tester.Common.ps1'
    $deployedContracts = Join-Path $PSScriptRoot '..\filler-probe\ProbeContracts.psm1'
    $runnerArguments = @{
        ExpectedSha = ('a' * 40)
        ExpectedVersion = '1.0.0-beta.5'
        AssetId = 'sample-one'
        RunIdentityPath = $identityPath
        FinalVerdictPath = $verdictPath
        OperatorTokenPath = $missingTokenPath
    }
    if (-not (Test-Path -LiteralPath $deployedCommon -PathType Leaf) -or -not (Test-Path -LiteralPath $deployedContracts -PathType Leaf)) {
        $runnerArguments.TesterPrepRoot = Join-Path $PSScriptRoot '..\tester-beta5-prep'
        $runnerArguments.EvidenceContractsPath = Join-Path $PSScriptRoot '..\tester-beta5-filler-probe\ProbeContracts.psm1'
    }
    $planOutput = @(& $runner @runnerArguments) -join "`n"
    $parsedPlan = $planOutput | ConvertFrom-Json
    Assert-True 'runner planning mode reuses source/PASS guards' ($parsedPlan.schema -eq 'civiccast-native-beta5-caption-acceptance-plan-v1' -and -not $parsedPlan.execute -and $parsedPlan.candidate_source_sha -eq ('a' * 40))
    Assert-True 'runner planning mode does not read or record a token' ($parsedPlan.token_recorded -eq $false -and -not $planOutput.Contains('secret-test-token'))
} finally {
    $env:COMPUTERNAME = $oldComputerName
    Remove-Item -LiteralPath $planRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host 'PASS: source/asset/cue/language binding, low-confidence preview ordering, bounded EN+ES workflow, local bilingual VTT, non-mutating channel continuity, and browser-proof qualification.'
