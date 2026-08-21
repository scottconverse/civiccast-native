# SPDX-License-Identifier: Apache-2.0
# Verify the live UDP MPEG-TS sinks emitted by start-encoders.ps1.
#
# Required env:
#   $env:RUN_ROOT - $Root\soak-4h-run
# Optional env:
#   $env:TSP or $env:CIVICCAST_TSDUCK_PATH - path to tsp.exe / TSDuck bin

param(
    [Parameter(Mandatory=$true)] [int]$HeartbeatIndex,
    [int]$Seconds = 10,
    [string]$Stamp = ""
)

$ErrorActionPreference = "Stop"

if (-not $env:RUN_ROOT) {
    throw "RUN_ROOT must be set (e.g. C:\CivicCastTester\soak-4h-run)"
}
if ($Seconds -le 0) {
    throw "Seconds must be greater than zero"
}
if (-not $Stamp) {
    $Stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
}

function Resolve-Tsp {
    if ($env:TSP -and (Test-Path $env:TSP)) {
        return $env:TSP
    }
    if ($env:CIVICCAST_TSDUCK_PATH) {
        foreach ($candidate in @(
            $env:CIVICCAST_TSDUCK_PATH,
            (Join-Path $env:CIVICCAST_TSDUCK_PATH "tsp.exe"),
            (Join-Path $env:CIVICCAST_TSDUCK_PATH "tsp")
        )) {
            if (Test-Path $candidate) {
                return $candidate
            }
        }
    }
    $cmd = Get-Command tsp -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Read-IntField {
    param(
        [object]$Object,
        [string]$Name
    )
    if ($null -eq $Object) {
        return 0
    }
    $prop = $Object.PSObject.Properties[$Name]
    if ($null -eq $prop -or $null -eq $prop.Value) {
        return 0
    }
    return [int]$prop.Value
}

$channels = @(
    @{ channel = "public";     port = 9001; destination = "udp://127.0.0.1:9001?pkt_size=1316" }
    @{ channel = "education";  port = 9002; destination = "udp://127.0.0.1:9002?pkt_size=1316" }
    @{ channel = "government"; port = 9003; destination = "udp://127.0.0.1:9003?pkt_size=1316" }
)

$root = Join-Path $env:RUN_ROOT "egress-verify"
$null = New-Item -ItemType Directory -Force -Path $root
$tsp = Resolve-Tsp
$results = @()

foreach ($c in $channels) {
    $channelRoot = Join-Path $root $c.channel
    $null = New-Item -ItemType Directory -Force -Path $channelRoot
    $report = Join-Path $channelRoot "$Stamp-tsduck-report.json"
    $log = Join-Path $channelRoot "$Stamp-tsduck.log"
    $stdout = Join-Path $channelRoot "$Stamp-tsduck.stdout.log"
    $stderr = Join-Path $channelRoot "$Stamp-tsduck.stderr.log"

    if (-not $tsp) {
        $results += @{
            channel = $c.channel
            destination = $c.destination
            verdict = "not-run"
            detail = "TSDuck tsp not found; set TSP or CIVICCAST_TSDUCK_PATH"
            report = $null
            log = $null
        }
        continue
    }

    $args = @(
        "-I", "ip", "$($c.port)",
        "--buffer-size", "16777216",
        "-P", "until", "--seconds", "$Seconds",
        "-P", "analyze", "--json", "--output-file", $report,
        "-O", "drop"
    )
    $timeoutSeconds = $Seconds + 20
    $proc = Start-Process -FilePath $tsp -ArgumentList $args -PassThru -NoNewWindow -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $timedOut = $false
    try {
        Wait-Process -Id $proc.Id -Timeout $timeoutSeconds -ErrorAction Stop
    } catch {
        $timedOut = $true
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        Wait-Process -Id $proc.Id -Timeout 5 -ErrorAction SilentlyContinue
    }
    $proc.Refresh()
    $exitCode = if ($timedOut) { -1 } else { $proc.ExitCode }
    $out = @()
    if (Test-Path $stdout) {
        $out += Get-Content -Path $stdout
    }
    if (Test-Path $stderr) {
        $out += Get-Content -Path $stderr
    }
    Set-Content -Path $log -Value (($out | Out-String).Trim()) -Encoding utf8

    if ($null -eq $exitCode -and (Test-Path $report)) {
        $exitCode = 0
    }

    if ($exitCode -ne 0 -or -not (Test-Path $report)) {
        $detail = if ($timedOut) {
            "tsp timed out after $timeoutSeconds seconds without a usable report"
        } else {
            "tsp exited $exitCode without a usable report"
        }
        $results += @{
            channel = $c.channel
            destination = $c.destination
            verdict = "fail"
            detail = $detail
            report = $report
            log = $log
        }
        continue
    }

    $json = Get-Content -Raw -Path $report | ConvertFrom-Json
    $invalidSyncs = Read-IntField -Object $json.ts.packets -Name "invalid-syncs"
    $transportErrors = Read-IntField -Object $json.ts.packets -Name "transport-errors"
    $discontinuities = 0
    foreach ($streamPid in @($json.pids)) {
        $discontinuities += Read-IntField -Object $streamPid.packets -Name "discontinuities"
    }
    $verdict = "pass"
    if ($invalidSyncs -ne 0 -or $transportErrors -ne 0 -or $discontinuities -ne 0) {
        $verdict = "fail"
    }
    $results += @{
        channel = $c.channel
        destination = $c.destination
        verdict = $verdict
        checks = @{
            invalid_syncs = $invalidSyncs
            transport_errors = $transportErrors
            discontinuities = $discontinuities
        }
        report = $report
        log = $log
    }
}

$overall = "pass"
if ($results | Where-Object { $_.verdict -eq "fail" }) {
    $overall = "fail"
} elseif ($results | Where-Object { $_.verdict -eq "not-run" }) {
    $overall = "not-run"
}

$artifact = Join-Path $root "egress-verify-$Stamp.json"
$body = @{
    schema = "civiccast-soak-egress-verify-v1"
    heartbeat_index = $HeartbeatIndex
    utc = $Stamp
    seconds = $Seconds
    overall_verdict = $overall
    channels = $results
} | ConvertTo-Json -Depth 7
Set-Content -Path $artifact -Value $body -Encoding utf8

Write-Host "egress verify $overall written: $artifact"
if ($overall -eq "pass") {
    exit 0
}
if ($overall -eq "not-run") {
    exit 2
}
exit 1
