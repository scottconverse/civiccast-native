# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Host-Launch-Sandbox-Test.ps1
# Runs ON THE HOST (not in Sandbox). Generates CivicCastSandboxTest.wsb from
# CivicCastSandboxTest.wsb.template (Windows Sandbox requires absolute host
# paths in its MappedFolder entries, so the template is rendered against
# -Root on every launch rather than checked in as a fixed .wsb), launches
# Windows Sandbox with it, polls the host-visible output folder for the
# in-sandbox script's DONE.json, then prints the collected summary. Times out
# rather than hanging forever (e.g. if a UAC consent dialog is blocking the
# unattended run inside the sandbox).
#
# Imported into civiccast-native/sandbox-lab/ from the standalone proven
# harness at C:\Users\scott\Desktop\Code\sandbox-lab\ (Gate A project). Only
# change from the original: -Root is now a parameter (default = this script's
# own directory) instead of a hardcoded absolute path, and the .wsb is
# generated from a template instead of being a static checked-in file.
#
# HARDENED 2026-08-17 (inherited from the original harness): polls for
# DONE.json (not DONE.marker). DONE.json is the LAST file
# In-Sandbox-Report.ps1 writes, written only after summary.json's final
# flush -- DONE.marker alone was ambiguous (a stale copy, or a marker written
# before summary.json finished, could in theory race). This script's own
# polling loop below is also the reason a real Gate A run should reliably
# produce a DONE.json: it waits for the authoritative marker instead of
# racing ahead on an intermediate result line the way the old manual
# Watch-Run.ps1 monitor did (see sandbox-lab/scripts/Watch-Run.ps1's own
# header comment and docs/ops/gate-a.md's "Known harness quirk" section for
# the history of why the Aug-19 reference run's own output is missing
# DONE.json despite every other check passing).

param(
    [string]$Root = $PSScriptRoot,
    [int]$TimeoutMinutes = 30,
    # Minutes for In-Sandbox-Report.ps1's T5 soak loop (it defaults to 20 when
    # SOAK_MINUTES.txt is absent). Written into output\SOAK_MINUTES.txt AFTER
    # this script's own output-dir wipe (step 1) so a caller (Run-GateA.ps1)
    # does not need a separate hook point to seed it -- pass -SoakMinutes
    # here instead of writing the file directly.
    [int]$SoakMinutes = 20
)

$ErrorActionPreference = 'Stop'

$OutDir = Join-Path $Root 'output'
$TemplatePath = Join-Path $Root 'CivicCastSandboxTest.wsb.template'
$WsbPath = Join-Path $Root 'CivicCastSandboxTest.wsb'
$DoneMarker = Join-Path $OutDir 'DONE.json'
$SummaryPath = Join-Path $OutDir 'summary.json'

Write-Host "=== CivicCast Native Gate A -- Windows Sandbox station-acceptance harness ===" -ForegroundColor Cyan
Write-Host "Root: $Root"

if (-not (Test-Path $TemplatePath)) {
    Write-Error "Missing .wsb template at $TemplatePath"
    exit 1
}

# 0. Render the .wsb from the template. Windows Sandbox's MappedFolder
#    HostFolder elements must be absolute host paths -- they cannot be
#    relative to the .wsb file's own location -- so this file is regenerated
#    on every launch against the resolved $Root rather than checked in as a
#    static file with a stale developer-machine path baked in.
$templateContent = Get-Content -Path $TemplatePath -Raw
$rendered = $templateContent.Replace('{{ROOT}}', $Root)
Set-Content -Path $WsbPath -Value $rendered -Encoding UTF8
Write-Host "Rendered $WsbPath from template (Root=$Root)"

# 1. Stamp a clean output dir so a stale DONE.marker from a previous run can
#    never be mistaken for this run's completion.
if (Test-Path $OutDir) {
    Get-ChildItem -Path $OutDir -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
} else {
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
}
$launchStamp = Get-Date
Set-Content -Path (Join-Path $OutDir '_HOST_LAUNCHED.marker') -Value $launchStamp.ToString('o') -Encoding UTF8
Set-Content -Path (Join-Path $OutDir 'SOAK_MINUTES.txt') -Value "$SoakMinutes" -Encoding UTF8
Write-Host "Output dir stamped clean: $OutDir (SOAK_MINUTES=$SoakMinutes)"

# 2. Launch Windows Sandbox with the .wsb config. WindowsSandbox.exe opens the
#    config and starts the VM; it returns once the sandbox window is up (it
#    does not block for the LogonCommand to finish).
Write-Host "Launching Windows Sandbox ($WsbPath)..."
Start-Process -FilePath 'C:\Windows\System32\WindowsSandbox.exe' -ArgumentList "`"$WsbPath`"" | Out-Null
# NOTE: WindowsSandbox.exe is a launcher stub -- it starts the VM (vmwp.exe /
# WindowsSandboxServer.exe / WindowsSandboxRemoteSession.exe) and exits almost
# immediately by design. Its own exit code/HasExited is NOT a signal of
# success or failure; the real VM lifecycle is tracked by those child
# processes and, ultimately, by the DONE.json marker below.
Start-Sleep -Seconds 5
$vmAlive = Get-Process -Name 'WindowsSandboxRemoteSession', 'WindowsSandboxServer', 'vmwp' -ErrorAction SilentlyContinue
if (-not $vmAlive) {
    Write-Error "No Windows Sandbox VM process found running a few seconds after launch. Sandbox feature may not be enabled, or the .wsb failed to parse."
    exit 1
}
Write-Host "Windows Sandbox VM is running (PID(s): $(($vmAlive | Select-Object -ExpandProperty Id) -join ', ')). Waiting for in-sandbox report to finish (timeout ${TimeoutMinutes}m)..."

# 3. Poll for the done-marker. This is the authoritative completion signal --
#    unlike the old manual Watch-Run.ps1 monitor (kept in scripts/ for
#    interactive debugging only), this loop does not declare done on an
#    intermediate result line; it waits for DONE.json itself, up to the
#    timeout.
$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$found = $false
while ((Get-Date) -lt $deadline) {
    if (Test-Path $DoneMarker) {
        $found = $true
        break
    }
    Start-Sleep -Seconds 10
}

if (-not $found) {
    Write-Warning "Timed out after $TimeoutMinutes minutes waiting for $DoneMarker."
    Write-Warning "Sandbox may still be running (e.g. blocked on a UAC dialog or a long extraction). Leaving the sandbox window open for manual inspection."
    if (Test-Path (Join-Path $OutDir '_BEFORE_INSTALL.marker')) {
        Write-Host "Evidence: installer launch WAS reached before the timeout (_BEFORE_INSTALL.marker present)."
    } else {
        Write-Host "Evidence: installer launch was NOT reached before the timeout (_BEFORE_INSTALL.marker absent)."
    }
    exit 2
}

Write-Host "Done-marker found. Sandbox report completed." -ForegroundColor Green

# 4. Read and print the summary.
if (Test-Path $SummaryPath) {
    $summary = Get-Content -Path $SummaryPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
    $summary | ConvertTo-Json -Depth 8 | Write-Host
} else {
    Write-Warning "DONE.json present but summary.json is missing at $SummaryPath."
}

# 5. Close the sandbox VM (it does not auto-close after LogonCommand exits).
Write-Host ""
Write-Host "Closing the Sandbox VM..."
Get-Process -Name 'WindowsSandboxClient' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process -Name 'WindowsSandboxRemoteSession' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Done. Full evidence (transcript, install-progress.log, summary.json) is in $OutDir" -ForegroundColor Cyan
exit 0
