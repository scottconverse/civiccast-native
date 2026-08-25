# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Gate B prerequisite probe -- DETECT AND REPORT, NEVER ELEVATE.
#
# Gate B needs a Windows environment that can REBOOT and come back. Windows
# Sandbox (which Gate A uses) structurally cannot: it is a disposable VM that
# is destroyed rather than restarted, which is why the 3.0 MASTER spec §12
# reboot requirement has no home in Gate A at all. Gate B's primary target is
# therefore a Hyper-V VM on the runner box.
#
# Enabling Hyper-V is a one-time ELEVATED, REBOOT-REQUIRING machine change.
# This script deliberately does not attempt it, does not prompt for it, and
# does not run anything as administrator. It probes, and if the feature is
# off it writes HYPERV-UNAVAILABLE.txt naming the ONE command an operator must
# run, and exits 3. scripts/gate_b_verdict.py turns that marker into a
# HYPERV_UNAVAILABLE verdict -- explicitly NOT a product FAIL, because a gate
# that never ran has observed nothing about the candidate.
#
# WHY THE PROBE IS UNELEVATED, AND WHAT THAT COSTS. The obvious probe --
# Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All --
# requires elevation and fails with "The requested operation requires
# elevation" in a normal session, including under a self-hosted runner started
# from an interactive logon task. So this uses THREE unelevated instruments of
# different kinds and reports what each one saw:
#
#   1. CIM Win32_OptionalFeature.InstallState  (1=Enabled 2=Disabled 3=Absent)
#   2. The Hyper-V management service (vmms) and its binary on disk
#   3. The Hyper-V PowerShell module's availability
#
# Any single one of those can be misread on its own. In particular,
# Win32_ComputerSystem.HypervisorPresent is TRUE on a box with Hyper-V
# DISABLED whenever WSL2, Windows Sandbox, VBS/HVCI or the Windows Hypervisor
# Platform is in use -- they all run on the same hypervisor. Treating
# HypervisorPresent as "Hyper-V is available" is the exact shape of error this
# script exists to avoid, so it is recorded as context and never used as the
# verdict.
#
# Exit codes:
#   0  Hyper-V is enabled and usable -- Gate B can provision a VM
#   2  the probe itself failed (CIM unavailable, etc) -- a harness error, not
#      a finding either way
#   3  Hyper-V is not enabled -- HYPERV-UNAVAILABLE.txt written

[CmdletBinding()]
param(
    # Where to write HYPERV-UNAVAILABLE.txt and the probe record. Optional:
    # with no -OutDir this is a pure console probe an operator can run to see
    # where the box stands.
    [string]$OutDir = $null
)

$ErrorActionPreference = 'Continue'

# The ONE elevated command that enables everything Gate B needs. -All pulls in
# the hypervisor, the management service, the management clients and the
# Hyper-V PowerShell module in a single feature; -NoRestart lets the operator
# choose when to take the (mandatory) reboot.
$EnableCommand = 'Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All -All -NoRestart'
$EnableCommandDism = 'DISM /Online /Enable-Feature /FeatureName:Microsoft-Hyper-V-All /All /NoRestart'

$probe = [ordered]@{
    probed_utc              = (Get-Date).ToUniversalTime().ToString('o')
    os_caption              = $null
    os_version              = $null
    optional_feature_state  = $null
    optional_feature_raw    = $null
    vmms_service_present    = $false
    vmms_binary_present     = $false
    hyperv_module_present   = $false
    session_can_manage_vms  = $false
    session_is_elevated     = $false
    session_in_hyperv_admins = $false
    hypervisor_present      = $null
    hypervisor_present_note = 'CONTEXT ONLY -- true on any box running WSL2 / Windows Sandbox / VBS, with Hyper-V itself disabled. Never used as the verdict.'
    verdict                 = 'unknown'
    instruments_agreeing    = 0
    enable_command          = $EnableCommand
    enable_command_dism     = $EnableCommandDism
    probe_errors            = @()
}

try {
    $os = Get-CimInstance -ClassName Win32_OperatingSystem -ErrorAction Stop
    $probe.os_caption = $os.Caption
    $probe.os_version = $os.Version
} catch {
    $probe.probe_errors += "Win32_OperatingSystem query failed: $_"
}

try {
    $cs = Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction Stop
    $probe.hypervisor_present = [bool]$cs.HypervisorPresent
} catch {
    $probe.probe_errors += "Win32_ComputerSystem query failed: $_"
}

# --- Instrument 1: CIM optional-feature install state (unelevated) ---------
$featureState = $null
try {
    $feature = Get-CimInstance -ClassName Win32_OptionalFeature `
        -Filter "Name='Microsoft-Hyper-V-All'" -ErrorAction Stop | Select-Object -First 1
    if ($feature) {
        $featureState = [int]$feature.InstallState
        $probe.optional_feature_raw = $featureState
        switch ($featureState) {
            1 { $probe.optional_feature_state = 'Enabled' }
            2 { $probe.optional_feature_state = 'Disabled' }
            3 { $probe.optional_feature_state = 'Absent' }
            default { $probe.optional_feature_state = "Unknown($featureState)" }
        }
    } else {
        $probe.optional_feature_state = 'not-reported'
        $probe.probe_errors += "Win32_OptionalFeature returned no row for Microsoft-Hyper-V-All"
    }
} catch {
    $probe.optional_feature_state = 'query-failed'
    $probe.probe_errors += "Win32_OptionalFeature query failed: $_"
}

# --- Instrument 2: the management service and its binary -------------------
try {
    $vmms = Get-Service -Name 'vmms' -ErrorAction Stop
    $probe.vmms_service_present = $true
    $probe | Add-Member -NotePropertyName 'vmms_status' -NotePropertyValue "$($vmms.Status)" -Force
} catch {
    $probe.vmms_service_present = $false
}
$probe.vmms_binary_present = Test-Path -LiteralPath (Join-Path $env:SystemRoot 'System32\vmms.exe')

# --- Instrument 3: the Hyper-V PowerShell module ---------------------------
try {
    $module = Get-Module -ListAvailable -Name 'Hyper-V' -ErrorAction SilentlyContinue | Select-Object -First 1
    $probe.hyperv_module_present = [bool]$module
} catch {
    $probe.hyperv_module_present = $false
}

# --- Instrument 4: may THIS session actually create and drive a VM? --------
# Hyper-V being installed is not the same as this process being allowed to use
# it. Creating a VM, mounting a VHD and partitioning it all require either
# elevation or membership of the local "Hyper-V Administrators" group. A gate
# that discovers this halfway through provisioning reports it as a mysterious
# access-denied; discovering it here reports it as what it is.
try {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    $probe.session_is_elevated = $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
    # S-1-5-32-578 is the well-known SID of the built-in Hyper-V
    # Administrators group -- matched by SID, not by name, because the group's
    # display name is localised.
    $hyperVAdmins = New-Object System.Security.Principal.SecurityIdentifier('S-1-5-32-578')
    $probe.session_in_hyperv_admins = $principal.IsInRole($hyperVAdmins)
} catch {
    $probe.probe_errors += "session authorization probe failed: $_"
}
$probe.session_can_manage_vms = ($probe.session_is_elevated -or $probe.session_in_hyperv_admins)

# --- Verdict: all three instruments must agree that it is THERE ------------
# Fail-closed: "enabled" requires positive evidence from every instrument.
# Anything less is reported as unavailable with the disagreement spelled out,
# because a half-enabled Hyper-V (feature staged, reboot not taken) is exactly
# the state that produces a confusing mid-run failure instead of a clean
# refusal at the gate's front door.
$agree = 0
if ($featureState -eq 1) { $agree++ }
if ($probe.vmms_service_present -and $probe.vmms_binary_present) { $agree++ }
if ($probe.hyperv_module_present) { $agree++ }
$probe.instruments_agreeing = $agree

if ($agree -eq 3) {
    if ($probe.session_can_manage_vms) {
        $probe.verdict = 'available'
    } else {
        # Hyper-V is installed; this session simply may not drive it. A
        # genuinely different condition from "the feature is off", and it needs
        # a different remedy, so it gets its own verdict value rather than
        # being folded into 'unavailable'.
        $probe.verdict = 'not-authorized'
    }
} elseif ($agree -eq 0) {
    $probe.verdict = 'unavailable'
} else {
    $probe.verdict = 'partial'
}

$report = @()
$report += "gate-b prereq probe $($probe.probed_utc)"
$report += "os=$($probe.os_caption) $($probe.os_version)"
$report += "instrument_1_optional_feature=Microsoft-Hyper-V-All:$($probe.optional_feature_state) (raw InstallState=$($probe.optional_feature_raw))"
$report += "instrument_2_vmms=service_present:$($probe.vmms_service_present) binary_present:$($probe.vmms_binary_present)"
$report += "instrument_3_hyperv_module=$($probe.hyperv_module_present)"
$report += "instrument_4_session_can_manage_vms=$($probe.session_can_manage_vms) (elevated:$($probe.session_is_elevated) hyperv_admins:$($probe.session_in_hyperv_admins))"
$report += "context_hypervisor_present=$($probe.hypervisor_present)  # $($probe.hypervisor_present_note)"
$report += "instruments_agreeing=$($probe.instruments_agreeing)/3"
$report += "verdict=$($probe.verdict)"
$reportText = ($report -join [Environment]::NewLine)

Write-Host $reportText

if ($OutDir) {
    if (-not (Test-Path -LiteralPath $OutDir)) {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    }
    $probe | ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath (Join-Path $OutDir 'gate-b-prereqs.json') -Encoding UTF8
}

if ($probe.verdict -eq 'available') {
    Write-Host "Hyper-V is enabled. Gate B can provision a VM on this box."
    exit 0
}

if ($probe.verdict -eq 'partial') {
    Write-Warning "Hyper-V is only PARTIALLY present ($agree of 3 instruments). The most common cause is that the feature was enabled but the mandatory reboot has not been taken yet."
}

$unavailableText = @()
$unavailableText += $reportText
$unavailableText += ''
$unavailableText += 'Gate B requires a persistent, rebootable Windows VM. Windows Sandbox (Gate A) cannot reboot.'
if ($probe.verdict -eq 'not-authorized') {
    $unavailableText += 'Hyper-V IS enabled on this box. What is missing is authorization: this session can neither'
    $unavailableText += 'elevate nor claim membership of the built-in Hyper-V Administrators group (S-1-5-32-578),'
    $unavailableText += 'and creating a VM, mounting a VHD and partitioning it all require one of the two.'
    $unavailableText += ''
    $unavailableText += 'Remedy (elevated, once) -- add the account the Gate B runner logs on as to that group:'
    $unavailableText += ''
    $unavailableText += '    Add-LocalGroupMember -SID S-1-5-32-578 -Member <DOMAIN\User-or-.\User>'
    $unavailableText += ''
    $unavailableText += 'then log that account off and on again so the new group lands in its token.'
    $unavailableText += ''
} else {
    $unavailableText += 'ONE elevated command enables everything Gate B needs (Administrator PowerShell), then REBOOT:'
    $unavailableText += ''
    $unavailableText += "    $EnableCommand"
    $unavailableText += ''
    $unavailableText += 'Equivalent with DISM, if you prefer:'
    $unavailableText += ''
    $unavailableText += "    $EnableCommandDism"
    $unavailableText += ''
    $unavailableText += 'This script did NOT attempt that command and did NOT elevate: enabling a hypervisor is a'
    $unavailableText += 'machine-scope change with a mandatory reboot, and a release gate must not take a runner box'
    $unavailableText += 'down on its own authority. Run it yourself, reboot, then re-run Gate B.'
    $unavailableText += ''
}
$unavailableText += 'Documented alternative if this box must not run Hyper-V: point Gate B at a spare physical'
$unavailableText += 'Windows box instead -- see docs/ops/gate-b.md, "Alternative target: a spare physical box".'

if ($OutDir) {
    ($unavailableText -join [Environment]::NewLine) |
        Set-Content -LiteralPath (Join-Path $OutDir 'HYPERV-UNAVAILABLE.txt') -Encoding UTF8
    Write-Host "Wrote $(Join-Path $OutDir 'HYPERV-UNAVAILABLE.txt')"
}

Write-Host ''
Write-Host ($unavailableText -join [Environment]::NewLine)
exit 3
