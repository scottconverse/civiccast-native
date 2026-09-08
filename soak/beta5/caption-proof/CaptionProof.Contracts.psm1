# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-CaptionRequiredProperty {
    param(
        [Parameter(Mandatory)] $Object,
        [Parameter(Mandatory)][string] $Name,
        [Parameter(Mandatory)][string] $Context
    )
    if ($null -eq $Object) { throw "$Context is null." }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { throw "$Context is missing '$Name'." }
    return $property.Value
}

function Get-CaptionSha256Bytes {
    param([Parameter(Mandatory)][byte[]] $Bytes)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return (($sha.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }) -join '')
    } finally {
        $sha.Dispose()
    }
}

function Get-CaptionSha256Text {
    param([Parameter(Mandatory)][string] $Text)
    return Get-CaptionSha256Bytes ([Text.Encoding]::UTF8.GetBytes($Text))
}

function Get-CaptionReceiptKeys {
    param([Parameter(Mandatory)] $Receipt)
    if ($Receipt -is [Collections.IDictionary]) { return @($Receipt.Keys | ForEach-Object { "$_" }) }
    return @($Receipt.PSObject.Properties.Name)
}

function Get-CaptionReceiptValue {
    param([Parameter(Mandatory)] $Receipt, [Parameter(Mandatory)][string] $Name)
    if ($Receipt -is [Collections.IDictionary]) {
        if (-not $Receipt.Contains($Name)) { return $null }
        return $Receipt[$Name]
    }
    $property = $Receipt.PSObject.Properties[$Name]
    return $(if ($null -eq $property) { $null } else { $property.Value })
}

function Assert-CaptionRuntimeChildPath {
    param(
        [Parameter(Mandatory)][string] $RuntimeRoot,
        [Parameter(Mandatory)][string] $CandidatePath
    )
    $root = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\')
    $candidate = [IO.Path]::GetFullPath($CandidatePath).TrimEnd('\')
    $prefix = $root + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Installed runtime path leaves fixed runtime root '$root': $candidate"
    }
    $cursor = $candidate
    while ($cursor.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or $cursor.Equals($root, [StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Installed runtime path crosses a reparse point: $cursor" }
        }
        if ($cursor.Equals($root, [StringComparison]::OrdinalIgnoreCase)) { break }
        $parent = Split-Path -Parent $cursor
        if (-not $parent -or $parent -eq $cursor) { throw "Could not walk installed runtime path to '$root'." }
        $cursor = $parent.TrimEnd('\')
    }
    return $candidate
}

function Assert-CaptionInstalledRuntimeHashes {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Identity,
        [string] $RuntimeRoot = 'C:\CivicCastHostStore\install\runtime'
    )
    $targets = @(
        'Lib/site-packages/civiccast/egress/daemon.py',
        'Lib/site-packages/civiccast/egress/gst/strategy.py'
    )
    $expectedReceipt = Get-CaptionRequiredProperty $Identity 'expected_runtime_file_sha256' 'run identity'
    $recordedReceipt = Get-CaptionRequiredProperty $Identity 'actual_runtime_file_sha256' 'run identity'
    foreach ($entry in @([pscustomobject]@{ name = 'expected'; receipt = $expectedReceipt }, [pscustomobject]@{ name = 'recorded'; receipt = $recordedReceipt })) {
        $keys = @(Get-CaptionReceiptKeys $entry.receipt)
        if ($keys.Count -ne $targets.Count) { throw "Run identity $($entry.name) runtime hash receipt must contain exactly two keys." }
        foreach ($key in $keys) {
            if ($targets -cnotcontains $key) { throw "Run identity $($entry.name) runtime hash receipt contains an unexpected key: $key" }
        }
        foreach ($target in $targets) {
            if ($keys -cnotcontains $target) { throw "Run identity $($entry.name) runtime hash receipt is missing: $target" }
        }
    }
    $root = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\')
    if (-not (Test-Path -LiteralPath $root -PathType Container)) { throw "Installed runtime root is absent: $root" }
    $null = Assert-CaptionRuntimeChildPath $root (Join-Path $root 'Lib')
    $files = @()
    foreach ($relative in $targets) {
        $expected = "$(Get-CaptionReceiptValue $expectedReceipt $relative)"
        $recorded = "$(Get-CaptionReceiptValue $recordedReceipt $relative)"
        if ($expected -notmatch '^[0-9a-f]{64}$' -or $recorded -notmatch '^[0-9a-f]{64}$') { throw "Runtime hash receipt is not lowercase SHA-256: $relative" }
        if ($recorded -cne $expected) { throw "Historical installed runtime receipt does not match the candidate payload: $relative" }
        $installedPath = Join-Path $root ($relative -replace '/', '\')
        $installedPath = Assert-CaptionRuntimeChildPath $root $installedPath
        if (-not (Test-Path -LiteralPath $installedPath -PathType Leaf)) { throw "Installed runtime file is absent: $relative" }
        $current = (Get-FileHash -LiteralPath $installedPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($current -cne $expected) { throw "Current installed runtime file does not match the candidate payload: $relative" }
        $files += [pscustomobject][ordered]@{
            relative_path = $relative
            installed_path = $installedPath
            expected_sha256 = $expected
            current_sha256 = $current
        }
    }
    return [pscustomobject][ordered]@{
        runtime_root = $root
        checked_utc = (Get-Date).ToUniversalTime().ToString('o')
        files = $files
    }
}

function Get-CaptionEncodedId {
    param([Parameter(Mandatory)][string] $Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { throw 'An identifier is blank.' }
    return [uri]::EscapeDataString($Value)
}

function Test-CaptionPathRequiresAuthorization {
    param([Parameter(Mandatory)][string] $Path)
    return $Path.StartsWith('/api/staff/', [StringComparison]::Ordinal)
}

function Get-CaptionJsonBody {
    param(
        [Parameter(Mandatory)] $Response,
        [Parameter(Mandatory)][string] $Context,
        [int[]] $AllowedStatus = @(200)
    )
    $status = [int] (Get-CaptionRequiredProperty $Response 'status' $Context)
    if ($status -notin $AllowedStatus) { throw "$Context returned HTTP $status." }
    return Get-CaptionRequiredProperty $Response 'body_json' $Context
}

function Assert-CaptionContentType {
    param(
        [Parameter(Mandatory)] $Response,
        [Parameter(Mandatory)][string] $ExpectedPattern,
        [Parameter(Mandatory)][string] $Context
    )
    $contentType = "$(Get-CaptionRequiredProperty $Response 'content_type' $Context)"
    if ($contentType -notmatch $ExpectedPattern) {
        throw "$Context returned unexpected Content-Type '$contentType'."
    }
}

function Get-CaptionTextBody {
    param(
        [Parameter(Mandatory)] $Response,
        [Parameter(Mandatory)][string] $Context,
        [Parameter(Mandatory)][string] $ContentTypePattern
    )
    $status = [int] (Get-CaptionRequiredProperty $Response 'status' $Context)
    if ($status -ne 200) { throw "$Context returned HTTP $status." }
    Assert-CaptionContentType $Response $ContentTypePattern $Context
    return "$(Get-CaptionRequiredProperty $Response 'body_text' $Context)"
}

function Assert-CaptionLocalManifest {
    param(
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][string] $ManifestUrl
    )
    $encoded = Get-CaptionEncodedId $AssetId
    $expected = "/media/vod/$encoded/playlist.m3u8"
    if ($ManifestUrl -cne $expected) {
        throw "Asset '$AssetId' is not bound to the expected local VOD manifest '$expected'; actual='$ManifestUrl'."
    }
    return $expected
}

function Resolve-CaptionLocalReference {
    param(
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][string] $ParentPath,
        [Parameter(Mandatory)][string] $Reference
    )
    if ([string]::IsNullOrWhiteSpace($Reference)) { throw 'An HLS reference is blank.' }
    $origin = [uri] 'http://127.0.0.1:8000'
    $parent = [uri]::new($origin, $ParentPath)
    $resolved = [uri]::new($parent, $Reference)
    if ($resolved.Scheme -ne 'http' -or $resolved.Host -ne '127.0.0.1' -or $resolved.Port -ne 8000) {
        throw "HLS reference leaves the local station: $Reference"
    }
    if ($resolved.Query -or $resolved.Fragment -or $resolved.UserInfo) {
        throw "HLS reference contains unsupported query, fragment, or user information: $Reference"
    }
    $encoded = Get-CaptionEncodedId $AssetId
    $prefix = "/media/vod/$encoded/"
    if (-not $resolved.AbsolutePath.StartsWith($prefix, [StringComparison]::Ordinal)) {
        throw "HLS reference leaves the selected asset package: $Reference"
    }
    return $resolved.AbsolutePath
}

function Get-CaptionPlaylistReferences {
    param(
        [Parameter(Mandatory)][string] $Playlist,
        [Parameter(Mandatory)][string] $Context
    )
    $rows = @($Playlist -split "`r?`n" | Where-Object { $_ -and -not $_.StartsWith('#') })
    if ($rows.Count -lt 1) { throw "$Context contains no media reference." }
    $result = @($rows | ForEach-Object { $_.Trim() })
    if (@($result | Sort-Object -Unique).Count -ne $result.Count) { throw "$Context contains duplicate media references." }
    return @($result)
}

function Get-CaptionSubtitleUri {
    param(
        [Parameter(Mandatory)][string] $Manifest,
        [Parameter(Mandatory)][ValidateSet('en', 'es')][string] $Language
    )
    $subtitleMatches = @()
    foreach ($line in @($Manifest -split "`r?`n")) {
        if ($line -notmatch '^#EXT-X-MEDIA:TYPE=SUBTITLES,') { continue }
        if ($line -notmatch ('(?:^|,)LANGUAGE="' + [regex]::Escape($Language) + '"(?:,|$)')) { continue }
        if ($line -notmatch '(?:^|,)URI="([^"]+)"(?:,|$)') {
            throw "The $Language subtitle declaration has no URI."
        }
        $subtitleMatches += $Matches[1]
    }
    if ($subtitleMatches.Count -ne 1) {
        throw "Expected exactly one $Language subtitle declaration; found $($subtitleMatches.Count)."
    }
    return $subtitleMatches[0]
}

function Assert-CaptionVttBody {
    param(
        [Parameter(Mandatory)][string] $Body,
        [Parameter(Mandatory)][string] $Context
    )
    if ($Body -notmatch '^\uFEFF?WEBVTT(?:\r?\n|\s)') { throw "$Context is not a WebVTT document." }
    if ($Body -notmatch '(?m)^\s*\d{2}:\d{2}(?::\d{2})?\.\d{3}\s+-->\s+\d{2}:\d{2}(?::\d{2})?\.\d{3}') {
        throw "$Context contains no timed cue."
    }
}

function Assert-CaptionReviewRows {
    param(
        [Parameter(Mandatory)][object[]] $Rows,
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][ValidateSet('en', 'es')][string] $Language,
        [Parameter(Mandatory)][int] $ExpectedCount
    )
    if ($Rows.Count -ne $ExpectedCount) {
        throw "Expected $ExpectedCount pending $Language review rows for '$AssetId'; found $($Rows.Count)."
    }
    $reviewIds = @{}
    $cueIds = @{}
    foreach ($row in $Rows) {
        $reviewId = "$(Get-CaptionRequiredProperty $row 'review_item_id' "$Language review row")"
        $actualAsset = "$(Get-CaptionRequiredProperty $row 'asset_id' "$Language review row '$reviewId'")"
        $actualLanguage = "$(Get-CaptionRequiredProperty $row 'language' "$Language review row '$reviewId'")"
        $status = "$(Get-CaptionRequiredProperty $row 'status' "$Language review row '$reviewId'")"
        $cue = Get-CaptionRequiredProperty $row 'cue' "$Language review row '$reviewId'"
        $cueId = "$(Get-CaptionRequiredProperty $cue 'cue_id' "$Language review row '$reviewId' cue")"
        $cueText = "$(Get-CaptionRequiredProperty $cue 'text' "$Language review row '$reviewId' cue")"
        $originalText = "$(Get-CaptionRequiredProperty $row 'original_text' "$Language review row '$reviewId'")"
        if ([string]::IsNullOrWhiteSpace($reviewId) -or [string]::IsNullOrWhiteSpace($cueId) -or
            [string]::IsNullOrWhiteSpace($cueText) -or [string]::IsNullOrWhiteSpace($originalText)) {
            throw "$Language review row has a blank review ID, cue ID, cue text, or original text."
        }
        if ($actualAsset -cne $AssetId -or $actualLanguage -cne $Language -or $status -cne 'pending') {
            throw "$Language review row '$reviewId' does not match the selected asset/language/pending contract."
        }
        if ($reviewIds.ContainsKey($reviewId) -or $cueIds.ContainsKey($cueId)) { throw "$Language review rows contain duplicate review or cue IDs." }
        $reviewIds[$reviewId] = $true
        $cueIds[$cueId] = $true
    }
}

function Get-CaptionProofChannelSnapshot {
    param(
        [Parameter(Mandatory)] $Identity,
        [Parameter(Mandatory)][scriptblock] $ApiInvoker
    )
    $result = @()
    foreach ($channel in @($Identity.channels)) {
        $channelId = "$($channel.channel_id)"
        $encoded = Get-CaptionEncodedId $channelId
        $config = Get-CaptionJsonBody (& $ApiInvoker 'GET' "/api/staff/egress/channels/$encoded/config" $null 'json') "channel '$channelId' config"
        $state = Get-CaptionJsonBody (& $ApiInvoker 'GET' "/api/staff/egress/channels/$encoded/state" $null 'json') "channel '$channelId' state"
        if ("$(Get-CaptionRequiredProperty $config 'channel_id' "channel '$channelId' config")" -cne $channelId) { throw "Channel config identity mismatch for '$channelId'." }
        if ("$(Get-CaptionRequiredProperty $state 'channel_id' "channel '$channelId' state")" -cne $channelId) { throw "Channel state identity mismatch for '$channelId'." }
        $stateName = "$(Get-CaptionRequiredProperty $state 'state' "channel '$channelId' state")"
        if ($stateName -notin @('ON_AIR', 'FALLBACK_SLATE')) { throw "Channel '$channelId' is not healthy: $stateName" }
        $workerPid = $null
        $pidProperty = $state.PSObject.Properties['pid']
        if ($null -ne $pidProperty -and $null -ne $pidProperty.Value) {
            $parsedPid = [int64] 0
            if (-not [int64]::TryParse("$($pidProperty.Value)", [ref] $parsedPid) -or $parsedPid -le 0) { throw "Channel '$channelId' has an invalid worker PID." }
            $workerPid = $parsedPid
        }
        $configJson = $config | ConvertTo-Json -Depth 30 -Compress
        $result += [pscustomobject][ordered]@{
            channel_id = $channelId
            state = $stateName
            current_source_label = $(if ($null -ne $state.PSObject.Properties['current_source_label']) { $state.current_source_label } else { $null })
            worker_pid = $workerPid
            config_sha256 = Get-CaptionSha256Text $configJson
        }
    }
    return @($result)
}

function Assert-CaptionProofContinuity {
    param(
        [Parameter(Mandatory)] $BeforeService,
        [Parameter(Mandatory)] $AfterService,
        [Parameter(Mandatory)][object[]] $BeforeChannels,
        [Parameter(Mandatory)][object[]] $AfterChannels
    )
    if ([int64] $BeforeService.service_process_id -ne [int64] $AfterService.service_process_id -or
        "$($BeforeService.service_process_started_utc)" -cne "$($AfterService.service_process_started_utc)") {
        throw 'CivicCastSupervisor PID or start time changed during caption acceptance.'
    }
    if ($BeforeChannels.Count -ne 3 -or $AfterChannels.Count -ne 3) { throw 'Caption acceptance requires exactly three channel snapshots.' }
    $transitions = @()
    foreach ($before in $BeforeChannels) {
        $after = @($AfterChannels | Where-Object { "$($_.channel_id)" -ceq "$($before.channel_id)" })
        if ($after.Count -ne 1) { throw "Missing or duplicate after-snapshot for channel '$($before.channel_id)'." }
        $current = $after[0]
        if ("$($current.config_sha256)" -cne "$($before.config_sha256)") { throw "Channel '$($before.channel_id)' configuration changed during caption acceptance." }
        if ("$($before.state)" -notin @('ON_AIR', 'FALLBACK_SLATE') -or "$($current.state)" -notin @('ON_AIR', 'FALLBACK_SLATE')) {
            throw "Channel '$($before.channel_id)' left the allowed healthy automation states."
        }
        if ($null -ne $before.worker_pid -or $null -ne $current.worker_pid) {
            if ($null -eq $before.worker_pid -or $null -eq $current.worker_pid -or [int64] $before.worker_pid -ne [int64] $current.worker_pid) {
                throw "Channel '$($before.channel_id)' GStreamer worker PID changed or became unavailable."
            }
        }
        $transitions += [pscustomobject][ordered]@{
            channel_id = "$($before.channel_id)"
            before_state = "$($before.state)"
            after_state = "$($current.state)"
            legitimate_automation_transition_observed = ("$($before.state)" -cne "$($current.state)")
            config_unchanged = $true
            worker_pid_check = $(if ($null -ne $before.worker_pid) { 'stable' } else { 'unavailable-from-state-api' })
        }
    }
    return @($transitions)
}

function Add-CaptionProofEvent {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.ArrayList] $Events,
        [Parameter(Mandatory)][scriptblock] $EventRecorder,
        [Parameter(Mandatory)] $Event
    )
    $null = $Events.Add($Event)
    & $EventRecorder $Event
}

function Invoke-CaptionApprovalPass {
    param(
        [Parameter(Mandatory)][object[]] $Rows,
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][ValidateSet('en', 'es')][string] $Language,
        [Parameter(Mandatory)][string] $ReviewerNote,
        [Parameter(Mandatory)][scriptblock] $ApiInvoker,
        [Parameter(Mandatory)][scriptblock] $EventRecorder,
        [Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.ArrayList] $Events
    )
    foreach ($row in $Rows) {
        $reviewId = "$($row.review_item_id)"
        $cueId = "$($row.cue.cue_id)"
        $cueText = "$($row.cue.text)"
        $lowConfidence = [bool] $row.low_confidence
        if ($lowConfidence) {
            if ($null -eq $row.PSObject.Properties['audio_evidence_available'] -or -not [bool] $row.audio_evidence_available) {
                throw "Low-confidence review row '$reviewId' has no advertised audio evidence."
            }
            $encodedReview = Get-CaptionEncodedId $reviewId
            $clip = & $ApiInvoker 'GET' "/api/staff/captions/review-items/$encodedReview/clip" $null 'binary'
            $clipStatus = [int] (Get-CaptionRequiredProperty $clip 'status' "review clip '$reviewId'")
            if ($clipStatus -ne 200) { throw "Review clip '$reviewId' returned HTTP $clipStatus." }
            Assert-CaptionContentType $clip '^audio/(?:wav|x-wav)(?:;|$)' "review clip '$reviewId'"
            $clipBytes = [byte[]] (Get-CaptionRequiredProperty $clip 'body_bytes' "review clip '$reviewId'")
            if ($clipBytes.Length -le 44) { throw "Review clip '$reviewId' is empty or shorter than a WAV header." }
            Add-CaptionProofEvent $Events $EventRecorder ([pscustomobject][ordered]@{
                event = 'low-confidence-preview-fetched'
                asset_id = $AssetId
                review_item_id = $reviewId
                cue_id = $cueId
                language = $Language
                byte_count = $clipBytes.Length
                sha256 = Get-CaptionSha256Bytes $clipBytes
                recorded_before_acknowledgement = $true
            })
        }
        $body = [ordered]@{
            reviewer_note = $ReviewerNote
            low_confidence_acknowledged = $lowConfidence
        }
        $encoded = Get-CaptionEncodedId $reviewId
        Add-CaptionProofEvent $Events $EventRecorder ([pscustomobject][ordered]@{
            event = 'caption-review-approval-intent'
            asset_id = $AssetId
            review_item_id = $reviewId
            cue_id = $cueId
            language = $Language
            low_confidence_acknowledgement_intended = $lowConfidence
            recorded_before_post = $true
        })
        $approved = Get-CaptionJsonBody (& $ApiInvoker 'POST' "/api/staff/captions/review-items/$encoded/approve" $body 'json') "approve '$reviewId'"
        $approvedCue = Get-CaptionRequiredProperty $approved 'cue' "approved review '$reviewId'"
        $approvedCueText = "$(Get-CaptionRequiredProperty $approvedCue 'text' "approved review '$reviewId' cue")"
        $reviewedText = "$(Get-CaptionRequiredProperty $approved 'reviewed_text' "approved review '$reviewId'")"
        if ("$(Get-CaptionRequiredProperty $approved 'review_item_id' "approved review '$reviewId'")" -cne $reviewId -or
            "$(Get-CaptionRequiredProperty $approved 'asset_id' "approved review '$reviewId'")" -cne $AssetId -or
            "$(Get-CaptionRequiredProperty $approved 'language' "approved review '$reviewId'")" -cne $Language -or
            "$(Get-CaptionRequiredProperty $approved 'status' "approved review '$reviewId'")" -cne 'approved' -or
            "$(Get-CaptionRequiredProperty $approvedCue 'cue_id' "approved review '$reviewId' cue")" -cne $cueId -or
            [string]::IsNullOrWhiteSpace($approvedCueText) -or [string]::IsNullOrWhiteSpace($reviewedText)) {
            throw "Approval response identity mismatch for review '$reviewId'."
        }
        Add-CaptionProofEvent $Events $EventRecorder ([pscustomobject][ordered]@{
            event = 'caption-review-approved'
            asset_id = $AssetId
            review_item_id = $reviewId
            cue_id = $cueId
            language = $Language
            low_confidence_acknowledged = $lowConfidence
            input_text_sha256 = Get-CaptionSha256Text $cueText
            approved_text_sha256 = Get-CaptionSha256Text $reviewedText
        })
    }
}

function Get-CaptionJobForAsset {
    param(
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][scriptblock] $ApiInvoker,
        [string] $JobId,
        [switch] $RequireAwaiting
    )
    $encoded = Get-CaptionEncodedId $AssetId
    $jobs = @(Get-CaptionJsonBody (& $ApiInvoker 'GET' "/api/staff/captions/offline-jobs?asset_id=$encoded" $null 'json') "offline caption jobs for '$AssetId'")
    foreach ($job in $jobs) {
        if ("$(Get-CaptionRequiredProperty $job 'asset_id' 'offline caption job')" -cne $AssetId) { throw 'Offline-job filter returned a different asset.' }
    }
    if ($JobId) {
        $matches = @($jobs | Where-Object { "$($_.job_id)" -ceq $JobId })
    } else {
        $matches = @($jobs | Where-Object { "$($_.state)" -ceq 'awaiting_review' })
    }
    if ($matches.Count -ne 1) { throw "Expected exactly one selected offline caption job for '$AssetId'; found $($matches.Count)." }
    $job = $matches[0]
    if ($RequireAwaiting -and "$($job.state)" -cne 'awaiting_review') { throw "Caption job '$($job.job_id)' is not awaiting review." }
    return $job
}

function Wait-CaptionReviewRows {
    param(
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][ValidateSet('en', 'es')][string] $Language,
        [Parameter(Mandatory)][int] $ExpectedCount,
        [Parameter(Mandatory)][scriptblock] $ApiInvoker,
        [Parameter(Mandatory)][scriptblock] $SleepInvoker,
        [Parameter(Mandatory)][int] $PollIntervalSeconds,
        [Parameter(Mandatory)][int] $MaxPollSeconds
    )
    $encoded = Get-CaptionEncodedId $AssetId
    $attempts = [Math]::Max(1, [int] [Math]::Ceiling($MaxPollSeconds / [double] $PollIntervalSeconds))
    for ($attempt = 1; $attempt -le $attempts; $attempt++) {
        $rows = @(Get-CaptionJsonBody (& $ApiInvoker 'GET' "/api/staff/captions/review-items?asset_id=$encoded&status_filter=pending&language=$Language" $null 'json') "pending $Language caption reviews")
        if ($rows.Count -eq $ExpectedCount) {
            Assert-CaptionReviewRows $rows $AssetId $Language $ExpectedCount
            return @($rows)
        }
        if ($rows.Count -gt 0) {
            foreach ($row in $rows) {
                if ("$(Get-CaptionRequiredProperty $row 'asset_id' "$Language review row")" -cne $AssetId -or "$(Get-CaptionRequiredProperty $row 'language' "$Language review row")" -cne $Language) {
                    throw "Pending $Language review query returned a different asset or language."
                }
            }
        }
        if ($attempt -lt $attempts) { & $SleepInvoker $PollIntervalSeconds }
    }
    throw "Timed out waiting for exactly $ExpectedCount pending $Language caption rows for '$AssetId'."
}

function Wait-CaptionJobComplete {
    param(
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][string] $JobId,
        [Parameter(Mandatory)][int] $ExpectedCueCount,
        [Parameter(Mandatory)][scriptblock] $ApiInvoker,
        [Parameter(Mandatory)][scriptblock] $SleepInvoker,
        [Parameter(Mandatory)][int] $PollIntervalSeconds,
        [Parameter(Mandatory)][int] $MaxPollSeconds
    )
    $attempts = [Math]::Max(1, [int] [Math]::Ceiling($MaxPollSeconds / [double] $PollIntervalSeconds))
    for ($attempt = 1; $attempt -le $attempts; $attempt++) {
        $job = Get-CaptionJobForAsset $AssetId $ApiInvoker $JobId
        if ("$($job.state)" -eq 'failed') { throw "Caption job '$JobId' failed: $($job.last_error)" }
        if ("$($job.state)" -eq 'complete') {
            if ([int] $job.cue_count -ne $ExpectedCueCount -or [int] $job.published_cue_count -ne $ExpectedCueCount -or
                -not [string]::IsNullOrEmpty("$($job.last_error)") -or $null -ne $job.next_attempt_at) {
                throw "Caption job '$JobId' completed without the exact published-cue contract."
            }
            return $job
        }
        if ("$($job.state)" -ne 'awaiting_review') { throw "Caption job '$JobId' entered unexpected state '$($job.state)'." }
        if ($attempt -lt $attempts) { & $SleepInvoker $PollIntervalSeconds }
    }
    throw "Timed out waiting for caption job '$JobId' to complete."
}

function Get-CaptionPublicArtifactProof {
    param(
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][string] $ManifestPath,
        [Parameter(Mandatory)][scriptblock] $ApiInvoker
    )
    $masterResponse = & $ApiInvoker 'GET' $ManifestPath $null 'text'
    $master = Get-CaptionTextBody $masterResponse 'public VOD master manifest' '(?i)(?:application/(?:vnd\.apple\.mpegurl|x-mpegurl)|audio/mpegurl)'
    if ($master -notmatch '^#EXTM3U') { throw 'Public VOD master is not an HLS manifest.' }
    $proof = [ordered]@{
        master_path = $ManifestPath
        master_sha256 = Get-CaptionSha256Text $master
        languages = @()
        flat_sidecars = @()
    }
    foreach ($language in @('en', 'es')) {
        $captionReference = Get-CaptionSubtitleUri $master $language
        $captionPath = Resolve-CaptionLocalReference $AssetId $ManifestPath $captionReference
        $captionPlaylistResponse = & $ApiInvoker 'GET' $captionPath $null 'text'
        $captionPlaylist = Get-CaptionTextBody $captionPlaylistResponse "$language caption playlist" '(?i)(?:application/(?:vnd\.apple\.mpegurl|x-mpegurl)|audio/mpegurl)'
        if ($captionPlaylist -notmatch '^#EXTM3U') { throw "$language caption playlist is not HLS." }
        $segments = @()
        foreach ($segmentReference in @(Get-CaptionPlaylistReferences $captionPlaylist "$language caption playlist")) {
            $segmentPath = Resolve-CaptionLocalReference $AssetId $captionPath $segmentReference
            if ($segmentPath -notmatch '(?i)\.vtt$') { throw "$language caption playlist references a non-VTT media item: $segmentPath" }
            $segmentResponse = & $ApiInvoker 'GET' $segmentPath $null 'text'
            $segment = Get-CaptionTextBody $segmentResponse "$language caption segment '$segmentPath'" '(?i)^text/vtt(?:;|$)'
            Assert-CaptionVttBody $segment "$language caption segment '$segmentPath'"
            $segments += [pscustomobject][ordered]@{ path = $segmentPath; sha256 = Get-CaptionSha256Text $segment }
        }
        $proof.languages += [pscustomobject][ordered]@{
            language = $language
            playlist_path = $captionPath
            playlist_sha256 = Get-CaptionSha256Text $captionPlaylist
            segments = $segments
        }
    }
    $encoded = Get-CaptionEncodedId $AssetId
    foreach ($name in @('captions.vtt', 'captions.es.vtt')) {
        $path = "/media/vod/$encoded/captions/$name"
        $response = & $ApiInvoker 'GET' $path $null 'text'
        $body = Get-CaptionTextBody $response "flat sidecar '$name'" '(?i)^text/vtt(?:;|$)'
        Assert-CaptionVttBody $body "flat sidecar '$name'"
        $proof.flat_sidecars += [pscustomobject][ordered]@{ path = $path; sha256 = Get-CaptionSha256Text $body }
    }
    return [pscustomobject] $proof
}

function Invoke-CaptionProofWorkflow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] $Identity,
        [Parameter(Mandatory)][string] $AssetId,
        [Parameter(Mandatory)][scriptblock] $ApiInvoker,
        [Parameter(Mandatory)][scriptblock] $InstalledIdentityInvoker,
        [Parameter(Mandatory)][scriptblock] $EventRecorder,
        [scriptblock] $SleepInvoker = { param($Seconds) Start-Sleep -Seconds $Seconds },
        [ValidateRange(1, 60)][int] $PollIntervalSeconds = 10,
        [ValidateRange(10, 3600)][int] $MaxPollSeconds = 1800,
        [string] $ReviewerNote = 'beta.5 post-soak automated caption workflow acceptance'
    )
    $events = [Collections.ArrayList]::new()
    $started = (Get-Date).ToUniversalTime().ToString('o')
    $beforeService = $null
    $afterService = $null
    $beforeChannels = @()
    $afterChannels = @()
    $transitions = @()
    $selectedAsset = $null
    $job = $null
    $completedJob = $null
    $publicProof = $null
    $primaryError = $null
    $continuityError = $null
    try {
        $beforeService = & $InstalledIdentityInvoker
        $beforeChannels = @(Get-CaptionProofChannelSnapshot $Identity $ApiInvoker)
        $receipts = @($Identity.approved_assets | Where-Object { "$($_.asset_id)" -ceq $AssetId })
        if ($receipts.Count -ne 1) { throw "Selected asset '$AssetId' is not exactly one approved-assets receipt entry." }
        $receipt = $receipts[0]
        $encodedAsset = Get-CaptionEncodedId $AssetId
        $selectedAsset = Get-CaptionJsonBody (& $ApiInvoker 'GET' "/api/staff/assets/$encodedAsset" $null 'json') "staff asset '$AssetId'"
        if ("$(Get-CaptionRequiredProperty $selectedAsset 'asset_id' 'staff asset')" -cne $AssetId -or
            "$(Get-CaptionRequiredProperty $selectedAsset 'title' 'staff asset')" -cne "$($receipt.title)" -or
            [int] (Get-CaptionRequiredProperty $selectedAsset 'duration_seconds' 'staff asset') -ne [int] $receipt.duration_seconds -or
            "$(Get-CaptionRequiredProperty $selectedAsset 'state' 'staff asset')" -notin @('validated', 'recorded') -or
            $null -eq (Get-CaptionRequiredProperty $selectedAsset 'published_at' 'staff asset')) {
            throw "Selected asset '$AssetId' does not match its approved-assets receipt and published state."
        }
        $manifestPath = Assert-CaptionLocalManifest $AssetId "$(Get-CaptionRequiredProperty $selectedAsset 'manifest_url' 'staff asset')"
        $publicAsset = Get-CaptionJsonBody (& $ApiInvoker 'GET' "/api/public/assets/$encodedAsset" $null 'json') "public asset '$AssetId'"
        if ("$(Get-CaptionRequiredProperty $publicAsset 'asset_id' 'public asset')" -cne $AssetId -or
            "$(Get-CaptionRequiredProperty $publicAsset 'manifest_url' 'public asset')" -cne $manifestPath -or
            $null -eq (Get-CaptionRequiredProperty $publicAsset 'published_at' 'public asset')) {
            throw "Public asset '$AssetId' does not match the selected local published package."
        }
        $job = Get-CaptionJobForAsset $AssetId $ApiInvoker -RequireAwaiting
        $cueCount = [int] (Get-CaptionRequiredProperty $job 'cue_count' 'offline caption job')
        if ($cueCount -le 0 -or [int] (Get-CaptionRequiredProperty $job 'published_cue_count' 'offline caption job') -ne 0) {
            throw "Caption job '$($job.job_id)' is not at the clean generation-complete/review-pending boundary."
        }
        $english = @(Wait-CaptionReviewRows $AssetId 'en' $cueCount $ApiInvoker $SleepInvoker $PollIntervalSeconds $PollIntervalSeconds)

        # No product mutation occurs before this point. Identity, soak evidence,
        # service/channels, receipt, local manifest, public row, job, and every
        # English review-row identity have all been checked first.
        Add-CaptionProofEvent $events $EventRecorder ([pscustomobject][ordered]@{
            event = 'caption-review-pass-selected'
            asset_id = $AssetId
            language = 'en'
            review_item_ids = @($english | ForEach-Object { "$($_.review_item_id)" })
            cue_ids = @($english | ForEach-Object { "$($_.cue.cue_id)" })
            selected_before_any_approval = $true
        })
        Invoke-CaptionApprovalPass $english $AssetId 'en' $ReviewerNote $ApiInvoker $EventRecorder $events
        $spanish = @(Wait-CaptionReviewRows $AssetId 'es' $cueCount $ApiInvoker $SleepInvoker $PollIntervalSeconds $MaxPollSeconds)
        Add-CaptionProofEvent $events $EventRecorder ([pscustomobject][ordered]@{
            event = 'caption-review-pass-selected'
            asset_id = $AssetId
            language = 'es'
            review_item_ids = @($spanish | ForEach-Object { "$($_.review_item_id)" })
            cue_ids = @($spanish | ForEach-Object { "$($_.cue.cue_id)" })
            selected_before_any_approval = $true
        })
        Invoke-CaptionApprovalPass $spanish $AssetId 'es' $ReviewerNote $ApiInvoker $EventRecorder $events
        $completedJob = Wait-CaptionJobComplete $AssetId "$($job.job_id)" $cueCount $ApiInvoker $SleepInvoker $PollIntervalSeconds $MaxPollSeconds
        $publicProof = Get-CaptionPublicArtifactProof $AssetId $manifestPath $ApiInvoker
    } catch {
        $primaryError = "$($_.Exception.GetType().Name): $($_.Exception.Message) at $($_.ScriptStackTrace)"
    } finally {
        try {
            $afterService = & $InstalledIdentityInvoker
            $afterChannels = @(Get-CaptionProofChannelSnapshot $Identity $ApiInvoker)
            if ($null -ne $beforeService -and $beforeChannels.Count -gt 0) {
                $transitions = @(Assert-CaptionProofContinuity $beforeService $afterService $beforeChannels $afterChannels)
            }
        } catch {
            $continuityError = "$($_.Exception.GetType().Name): $($_.Exception.Message) at $($_.ScriptStackTrace)"
        }
    }
    $passed = $null -eq $primaryError -and $null -eq $continuityError
    return [pscustomobject][ordered]@{
        schema = 'civiccast-native-beta5-caption-acceptance-v1'
        verdict = $(if ($passed) { 'PASS' } else { 'FAIL' })
        mission = "$($Identity.mission)"
        candidate_source_sha = "$($Identity.candidate_source_sha)"
        asset_id = $AssetId
        started_utc = $started
        completed_utc = (Get-Date).ToUniversalTime().ToString('o')
        software_workflow = $(if ($passed) { 'PASS' } else { 'FAIL' })
        transcript_editorial_accuracy = 'NOT_CERTIFIED_AUTOMATED_ACCEPTANCE_ONLY'
        resident_browser_playback = 'NOT_RUN_REQUIRES_SEPARATE_BROWSER_PROOF'
        primary_error = $primaryError
        continuity_error = $continuityError
        service_before = $beforeService
        service_after = $afterService
        channels_before = $beforeChannels
        channels_after = $afterChannels
        channel_continuity = $transitions
        caption_job_before = $job
        caption_job_after = $completedJob
        public_artifacts = $publicProof
        events = @($events)
        token_recorded = $false
        product_mutations = 'caption review approvals for the selected asset only'
        forbidden_mutations_issued = $false
    }
}

Export-ModuleMember -Function @(
    'Assert-CaptionInstalledRuntimeHashes',
    'Assert-CaptionLocalManifest',
    'Assert-CaptionProofContinuity',
    'Assert-CaptionReviewRows',
    'Get-CaptionProofChannelSnapshot',
    'Get-CaptionPublicArtifactProof',
    'Invoke-CaptionProofWorkflow',
    'Resolve-CaptionLocalReference',
    'Test-CaptionPathRequiresAuthorization'
)
