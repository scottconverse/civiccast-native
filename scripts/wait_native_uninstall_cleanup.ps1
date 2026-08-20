param(
    [Parameter(Mandatory = $true)]
    [string] $InstallLocation,

    [string] $DisplayName = "CivicCast (Native)",

    [string[]] $RegistryRoots = @(
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    ),

    [ValidateRange(1, 600000)]
    [int] $TimeoutMilliseconds = 30000,

    [ValidateRange(1, 60000)]
    [int] $PollMilliseconds = 100
)

$ErrorActionPreference = "Stop"

function Get-MatchingArpEntries {
    $entries = @()
    foreach ($root in $RegistryRoots) {
        $entries += @(
            Get-ItemProperty -Path (Join-Path $root "*") -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -eq $DisplayName }
        )
    }
    return @($entries)
}

$timeline = [System.Collections.Generic.List[object]]::new()
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$verdict = "TIMEOUT"

while ($true) {
    $arpCount = @(Get-MatchingArpEntries).Count
    $installLocationExists = Test-Path -LiteralPath $InstallLocation
    $timeline.Add([ordered]@{
        observed_at = (Get-Date).ToUniversalTime().ToString("o")
        elapsed_ms = [int]$stopwatch.ElapsedMilliseconds
        arp_count = $arpCount
        install_location_exists = $installLocationExists
    })

    if ($arpCount -eq 0 -and -not $installLocationExists) {
        $verdict = "PASS"
        break
    }
    if ($stopwatch.ElapsedMilliseconds -ge $TimeoutMilliseconds) {
        break
    }

    $remaining = $TimeoutMilliseconds - [int]$stopwatch.ElapsedMilliseconds
    Start-Sleep -Milliseconds ([Math]::Min($PollMilliseconds, [Math]::Max(1, $remaining)))
}

$receipt = [ordered]@{
    schema_version = 1
    verdict = $verdict
    display_name = $DisplayName
    install_location = $InstallLocation
    timeout_ms = $TimeoutMilliseconds
    poll_ms = $PollMilliseconds
    elapsed_ms = [int]$stopwatch.ElapsedMilliseconds
    final_arp_count = $arpCount
    install_location_removed = -not $installLocationExists
    timeline = @($timeline)
}

$receipt | ConvertTo-Json -Depth 5 -Compress
if ($verdict -eq "PASS") {
    exit 0
}
exit 1
