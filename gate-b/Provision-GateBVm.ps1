# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
#
# Gate B VM provisioning -- create (or reuse) the persistent Hyper-V VM the
# 24h reboot soak runs inside, deliver the candidate kit into it, and hand the
# caller a live PowerShell Direct session.
#
# ---------------------------------------------------------------------------
# WHY POWERSHELL DIRECT, AND WHY NO MAPPED FOLDER
# ---------------------------------------------------------------------------
# Gate A ships evidence through a Windows Sandbox mapped folder (VSMB). That
# channel cost it three silent late-run hangs and one measured ~2x slowdown of
# every install step that crossed it (docs/ops/gate-a.md, "Mapped-folder
# stalls" and "Run 7: what the shipper cost the installer"). Gate B does not
# reproduce that architecture, for two independent reasons:
#
#   1. It does not have to. Hyper-V offers PowerShell Direct -- an in-band
#      VMBus control channel that needs no networking, no shared folder and no
#      credentials on the wire. The HOST pulls evidence out on its own
#      schedule; the guest never pushes into a share it does not control. A
#      wedged pull costs one pull, and the next one gets fresh handles.
#   2. A 24-hour run cannot afford Gate A's failure mode. Gate A's stalls cost
#      it 47 minutes and 8 minutes. The same class of wedge in a soak whose
#      whole point is 1440 uninterrupted minutes costs the entire run.
#
# The kit does NOT come in over that channel either -- a ~21 GB copy over
# VMBus would be slower than the artifact download it replaces. Instead the
# host builds a one-shot VHDX from the kit directory and attaches it to the VM
# READ-ONLY. That is a block device, not a file share: the installer reads
# packs\ and station\ off it exactly as it reads a mapped folder, at local-disk
# speed, with no share to wedge. Gate A's own install code already proves the
# read-only-payload assumption holds (it runs setup.exe straight off a
# read-only mapped payload for the same 21 GB reason).
#
# ---------------------------------------------------------------------------
# WHAT THE OPERATOR MUST SUPPLY
# ---------------------------------------------------------------------------
#   -BaseVhdx <path>      A prepared Windows 11/Server VHDX that has already
#                         completed OOBE and carries a known local account in
#                         Administrators. PRIMARY PATH. Never modified: the VM
#                         gets a DIFFERENCING disk whose parent is this file,
#                         so a failed run costs a differencing disk, not the
#                         base image, and the next run starts clean.
#         -- or --
#   -WindowsIso <path>    A Windows installation ISO. ALTERNATIVE PATH: this
#                         script applies install.wim to a fresh VHDX, injects
#                         gate-b/answer/autounattend.xml so OOBE completes
#                         unattended, and makes that the base. Slower (tens of
#                         minutes) and it only has to happen once -- the
#                         result is a base VHDX you should then keep and pass
#                         with -BaseVhdx forever after.
#
#   -GuestCredentialPath  A file the OPERATOR created with:
#                             Get-Credential | Export-CliXml <path>
#                         holding the guest's local admin credential. This
#                         script imports it and hands it to PowerShell Direct.
#                         It never prompts for a password, never takes one on
#                         the command line, and never writes one anywhere:
#                         Export-CliXml protects the secret with DPAPI scoped
#                         to the operator's own account, so the file is inert
#                         if it is ever copied off this box.
#
#   -KitDir <path>        The extracted candidate kit -- setup.exe + packs\ +
#                         station\ at the root, the same flat layout Gate A's
#                         Run-GateA.ps1 validates.
#
# Exit codes: 0 provisioned; 2 harness error (bad inputs, Hyper-V refused,
# guest never answered). This script never returns a product finding.

[CmdletBinding(DefaultParameterSetName = 'FromBaseVhdx')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'FromBaseVhdx')]
    [string]$BaseVhdx,

    [Parameter(Mandatory = $true, ParameterSetName = 'FromIso')]
    [string]$WindowsIso,

    [Parameter(Mandatory = $true)]
    [string]$GuestCredentialPath,

    [Parameter(Mandatory = $true)]
    [string]$KitDir,

    [string]$VmName = 'CivicCastGateB',

    # Working root for this run's disks. Fresh-dir-on-conflict: if the
    # directory exists and cannot be cleared (a locked VHD from a run whose VM
    # is still around), a timestamped sibling is used instead of fighting it.
    [string]$VmRoot = 'C:\CivicCastGateB',

    [int]$MemoryStartupGb = 16,
    [int]$ProcessorCount = 6,

    # Windows-image index inside install.wim for the -WindowsIso path.
    [int]$IsoImageIndex = 6,
    [int]$OsDiskGb = 200,

    # Minutes to wait for PowerShell Direct to start answering after the VM is
    # started. A cold first boot of a freshly-applied image is genuinely slow.
    [int]$GuestReadyMinutes = 30,

    # Reuse an existing VM of this name instead of recreating it. Off by
    # default: a gate that silently reuses a dirty VM is a gate that proves
    # nothing about a clean install.
    [switch]$ReuseExistingVm
)

$ErrorActionPreference = 'Stop'

function Write-Step {
    param([string]$Message)
    Write-Host ("[{0}] {1}" -f (Get-Date).ToUniversalTime().ToString('HH:mm:ssZ'), $Message)
}

function Exit-HarnessError {
    param([string]$Message)
    Write-Error "gate-b provisioning: $Message"
    exit 2
}

function Get-FreshWorkingRoot {
    <#
        Fresh-dir-on-conflict. A VHD that is still attached to a running VM
        cannot be deleted, and retrying the delete in a loop is how a harness
        turns someone else's stale state into its own hang. If the root cannot
        be cleared, take a new one and say so.
    #>
    param([string]$Root)

    if (-not (Test-Path -LiteralPath $Root)) {
        New-Item -ItemType Directory -Force -Path $Root | Out-Null
        return $Root
    }
    try {
        Get-ChildItem -LiteralPath $Root -Force -ErrorAction Stop |
            Remove-Item -Recurse -Force -ErrorAction Stop
        return $Root
    } catch {
        $fresh = "$Root-$((Get-Date).ToUniversalTime().ToString('yyyyMMdd-HHmmssZ'))"
        Write-Warning "Could not clear $Root ($_). Using a fresh working root instead: $fresh"
        New-Item -ItemType Directory -Force -Path $fresh | Out-Null
        return $fresh
    }
}

# --- 0. Hyper-V must be there, and this session must be allowed to use it ---
$prereq = Join-Path $PSScriptRoot 'Test-GateBPrereqs.ps1'
if (-not (Test-Path -LiteralPath $prereq)) {
    Exit-HarnessError "Test-GateBPrereqs.ps1 not found beside this script at $prereq"
}
& $prereq | Out-Null
if ($LASTEXITCODE -ne 0) {
    Exit-HarnessError "Hyper-V prerequisites are not satisfied (Test-GateBPrereqs.ps1 exit $LASTEXITCODE). Run it directly to see the one command that fixes it."
}
Import-Module Hyper-V -ErrorAction Stop

# --- 1. Validate the operator-supplied inputs ------------------------------
if (-not (Test-Path -LiteralPath $GuestCredentialPath)) {
    Exit-HarnessError "guest credential file not found at $GuestCredentialPath. Create it with: Get-Credential | Export-CliXml '$GuestCredentialPath'"
}
try {
    $guestCredential = Import-CliXml -LiteralPath $GuestCredentialPath
} catch {
    Exit-HarnessError "guest credential file at $GuestCredentialPath could not be imported: $_. Export-CliXml protects it with DPAPI scoped to the account that created it, so a file copied from another account or machine will not open here -- recreate it as the account the Gate B runner uses."
}
if (-not ($guestCredential -is [System.Management.Automation.PSCredential])) {
    Exit-HarnessError "the file at $GuestCredentialPath did not deserialize to a PSCredential."
}

if (-not (Test-Path -LiteralPath $KitDir)) {
    Exit-HarnessError "kit directory not found at $KitDir"
}
$kitSetup = @(Get-ChildItem -LiteralPath $KitDir -Filter '*setup.exe' -ErrorAction SilentlyContinue)
$kitStation = Join-Path $KitDir 'station'
if ($kitSetup.Count -lt 1) {
    Exit-HarnessError "no *setup.exe at the root of $KitDir -- Gate B expects the same flat kit layout Gate A validates (setup.exe + packs\ + station\)."
}
if (-not (Test-Path -LiteralPath $kitStation)) {
    Exit-HarnessError "no station\ directory at $KitDir -- the signed station bundle is what activation imports."
}
$stationFiles = @(Get-ChildItem -LiteralPath $kitStation -Recurse -File -ErrorAction SilentlyContinue)
$stationBytes = 0
foreach ($f in $stationFiles) { $stationBytes += $f.Length }
Write-Step ("kit resolved: {0}; station bundle {1} files, {2:N0} bytes" -f $kitSetup[0].FullName, $stationFiles.Count, $stationBytes)

$VmRoot = Get-FreshWorkingRoot -Root $VmRoot

# --- 2. Resolve the base VHDX (building one from an ISO if asked) ----------
if ($PSCmdlet.ParameterSetName -eq 'FromIso') {
    if (-not (Test-Path -LiteralPath $WindowsIso)) {
        Exit-HarnessError "Windows ISO not found at $WindowsIso"
    }
    $answerFile = Join-Path $PSScriptRoot 'answer\autounattend.xml'
    if (-not (Test-Path -LiteralPath $answerFile)) {
        Exit-HarnessError "answer file not found at $answerFile -- the -WindowsIso path needs it to complete OOBE unattended."
    }
    $BaseVhdx = Join-Path $VmRoot 'gate-b-base.vhdx'
    Write-Step "Building a base VHDX from $WindowsIso (this is the slow path; keep the result and use -BaseVhdx next time)"

    $mounted = Mount-DiskImage -ImagePath (Resolve-Path -LiteralPath $WindowsIso).Path -PassThru
    try {
        $isoDrive = ($mounted | Get-Volume).DriveLetter
        if (-not $isoDrive) { Exit-HarnessError "the ISO mounted but exposed no drive letter." }
        $wim = "${isoDrive}:\sources\install.wim"
        if (-not (Test-Path -LiteralPath $wim)) {
            $esd = "${isoDrive}:\sources\install.esd"
            if (Test-Path -LiteralPath $esd) {
                Exit-HarnessError "this ISO ships install.esd, not install.wim. DISM cannot apply an .esd directly here -- supply an ISO with install.wim, or prepare the base VHDX yourself and use -BaseVhdx."
            }
            Exit-HarnessError "no sources\install.wim on the mounted ISO."
        }

        New-VHD -Path $BaseVhdx -SizeBytes ($OsDiskGb * 1GB) -Dynamic | Out-Null
        $vhdDisk = Mount-VHD -Path $BaseVhdx -Passthru | Initialize-Disk -PartitionStyle GPT -PassThru
        try {
            # Gen 2 layout: a FAT32 EFI system partition plus the NTFS OS
            # partition. bcdboot writes the boot files into the ESP.
            $efi = New-Partition -DiskNumber $vhdDisk.Number -Size 512MB -GptType '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}'
            $efiVolume = Format-Volume -Partition $efi -FileSystem FAT32 -NewFileSystemLabel 'System' -Confirm:$false
            $efi | Set-Partition -NewDriveLetter 'S'
            $os = New-Partition -DiskNumber $vhdDisk.Number -UseMaximumSize -GptType '{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}'
            $osVolume = Format-Volume -Partition $os -FileSystem NTFS -NewFileSystemLabel 'Windows' -Confirm:$false
            $os | Set-Partition -NewDriveLetter 'W'
            Write-Step ("applying image index {0} to W: (efi volume {1})" -f $IsoImageIndex, $efiVolume.FileSystemLabel)
            & dism.exe /Apply-Image /ImageFile:"$wim" /Index:$IsoImageIndex /ApplyDir:W:\ | Out-Null
            if ($LASTEXITCODE -ne 0) { Exit-HarnessError "dism /Apply-Image failed with exit code $LASTEXITCODE" }

            # Injecting the answer file at Windows\Panther\unattend.xml is what
            # makes the FIRST boot unattended -- without it the image stops at
            # OOBE forever and no soak ever starts.
            New-Item -ItemType Directory -Force -Path 'W:\Windows\Panther' | Out-Null
            Copy-Item -LiteralPath $answerFile -Destination 'W:\Windows\Panther\unattend.xml' -Force
            Write-Step ("injected {0} -> W:\Windows\Panther\unattend.xml (os volume {1})" -f (Split-Path $answerFile -Leaf), $osVolume.FileSystemLabel)

            & bcdboot.exe W:\Windows /s S: /f UEFI | Out-Null
            if ($LASTEXITCODE -ne 0) { Exit-HarnessError "bcdboot failed with exit code $LASTEXITCODE" }
        } finally {
            Dismount-VHD -Path $BaseVhdx -ErrorAction SilentlyContinue
        }
    } finally {
        Dismount-DiskImage -ImagePath (Resolve-Path -LiteralPath $WindowsIso).Path -ErrorAction SilentlyContinue | Out-Null
    }
    Write-Step "base VHDX built: $BaseVhdx"
}

if (-not (Test-Path -LiteralPath $BaseVhdx)) {
    Exit-HarnessError "base VHDX not found at $BaseVhdx"
}

# --- 3. Create (or reuse) the VM -------------------------------------------
$existing = Get-VM -Name $VmName -ErrorAction SilentlyContinue
if ($existing -and -not $ReuseExistingVm) {
    Write-Step "removing the existing VM '$VmName' (pass -ReuseExistingVm to keep it)"
    if ($existing.State -ne 'Off') { Stop-VM -Name $VmName -TurnOff -Force -ErrorAction SilentlyContinue }
    Remove-VM -Name $VmName -Force -ErrorAction Stop
    $existing = $null
}

if (-not $existing) {
    $osDisk = Join-Path $VmRoot "$VmName-os.vhdx"
    Write-Step "creating differencing disk $osDisk from base $BaseVhdx"
    New-VHD -Path $osDisk -ParentPath (Resolve-Path -LiteralPath $BaseVhdx).Path -Differencing | Out-Null

    Write-Step "creating Gen 2 VM '$VmName' ($MemoryStartupGb GB, $ProcessorCount vCPU, NO network adapter)"
    $vm = New-VM -Name $VmName -Generation 2 -MemoryStartupBytes ($MemoryStartupGb * 1GB) `
        -VHDPath $osDisk -Path $VmRoot -ErrorAction Stop
    Set-VM -Name $VmName -ProcessorCount $ProcessorCount -AutomaticStartAction Nothing `
        -AutomaticStopAction ShutDown -CheckpointType Disabled -ErrorAction Stop
    # Static memory. Dynamic memory under a 24h media workload produces
    # balloon-driven pressure that looks exactly like a memory leak in the
    # soak's own RSS sampling -- an instrument artefact the run must not have.
    Set-VMMemory -VMName $VmName -DynamicMemoryEnabled $false -ErrorAction Stop
    # No network adapter at all. §12's soak is about the station staying on
    # air, and the syndication/IA tiers are out of Gate B's scope exactly as
    # they are out of Gate A's; an isolated VM also means the soak cannot be
    # perturbed by, or perturb, anything else on this box.
    Get-VMNetworkAdapter -VMName $VmName | Remove-VMNetworkAdapter -ErrorAction SilentlyContinue
    # Guest Services carries PowerShell Direct's file-copy support.
    Enable-VMIntegrationService -VMName $VmName -Name 'Guest Service Interface' -ErrorAction SilentlyContinue
} else {
    Write-Step "reusing existing VM '$VmName' (-ReuseExistingVm)"
    $vm = $existing
    if ($vm.State -ne 'Off') { Stop-VM -Name $VmName -Force -ErrorAction SilentlyContinue }
    # Drop any kit disk left attached by a previous run before adding this
    # run's -- otherwise the guest sees two CCKIT volumes and picks one at
    # random.
    Get-VMHardDiskDrive -VMName $VmName |
        Where-Object { $_.Path -like '*-kit.vhdx' } |
        Remove-VMHardDiskDrive -ErrorAction SilentlyContinue
}

# --- 4. Build the kit VHDX and attach it read-only -------------------------
$kitVhdx = Join-Path $VmRoot "$VmName-kit.vhdx"
if (Test-Path -LiteralPath $kitVhdx) { Remove-Item -LiteralPath $kitVhdx -Force -ErrorAction SilentlyContinue }

$kitBytes = 0
Get-ChildItem -LiteralPath $KitDir -Recurse -File -ErrorAction SilentlyContinue |
    ForEach-Object { $kitBytes += $_.Length }
# 25% headroom over the measured kit size, floored at 32 GB. Dynamic, so the
# headroom costs nothing until it is used.
$kitDiskBytes = [math]::Max([int64](32GB), [int64]($kitBytes * 1.25))
Write-Step ("building kit disk {0} ({1:N0} bytes of kit, {2:N0}-byte dynamic VHDX)" -f $kitVhdx, $kitBytes, $kitDiskBytes)

New-VHD -Path $kitVhdx -SizeBytes $kitDiskBytes -Dynamic | Out-Null
$kitLetter = $null
try {
    $kitDisk = Mount-VHD -Path $kitVhdx -Passthru | Initialize-Disk -PartitionStyle GPT -PassThru
    $kitPartition = New-Partition -DiskNumber $kitDisk.Number -UseMaximumSize -AssignDriveLetter
    Format-Volume -Partition $kitPartition -FileSystem NTFS -NewFileSystemLabel 'CCKIT' -Confirm:$false | Out-Null
    $kitLetter = (Get-Partition -DiskNumber $kitDisk.Number | Where-Object { $_.DriveLetter } |
        Select-Object -First 1).DriveLetter
    if (-not $kitLetter) { Exit-HarnessError "the kit VHDX formatted but exposed no drive letter." }

    Write-Step "copying kit into ${kitLetter}: (robocopy /E /NP /R:2 /W:2)"
    # /MT is deliberately NOT used: this is one bulk stream onto a freshly
    # created local VHDX, where thread contention buys nothing and makes the
    # failure modes harder to read.
    & robocopy.exe (Resolve-Path -LiteralPath $KitDir).Path "${kitLetter}:\" /E /NP /NFL /NDL /R:2 /W:2 | Out-Null
    # robocopy's exit codes are a bitmask: < 8 means files were copied and/or
    # skipped with no failure. >= 8 is a real copy failure.
    if ($LASTEXITCODE -ge 8) { Exit-HarnessError "robocopy of the kit failed with exit code $LASTEXITCODE" }
} finally {
    Dismount-VHD -Path $kitVhdx -ErrorAction SilentlyContinue
}

Write-Step "attaching kit disk to '$VmName' as READ-ONLY"
Add-VMHardDiskDrive -VMName $VmName -Path $kitVhdx -ErrorAction Stop
# SupportPersistentReservations off + the VHD's own read-only flag: the guest
# mounts it, the installer reads it, and nothing in the VM can modify the
# candidate it is being judged on.
Set-VMHardDiskDrive -VMName $VmName -Path $kitVhdx -SupportPersistentReservations $false -ErrorAction SilentlyContinue
Set-ItemProperty -LiteralPath $kitVhdx -Name IsReadOnly -Value $true -ErrorAction SilentlyContinue

# --- 5. Start it and wait for PowerShell Direct ----------------------------
Write-Step "starting '$VmName'"
Start-VM -Name $VmName -ErrorAction Stop

$deadline = (Get-Date).AddMinutes($GuestReadyMinutes)
$session = $null
$attempt = 0
while ((Get-Date) -lt $deadline) {
    $attempt++
    try {
        $session = New-PSSession -VMName $VmName -Credential $guestCredential -ErrorAction Stop
        break
    } catch {
        if (($attempt % 6) -eq 0) {
            Write-Step ("waiting for PowerShell Direct (attempt {0}): {1}" -f $attempt, $_.Exception.Message)
        }
        Start-Sleep -Seconds 10
    }
}
if (-not $session) {
    Exit-HarnessError "the guest never answered PowerShell Direct within $GuestReadyMinutes minutes. If this is a freshly built image, it is almost certainly still sitting at OOBE -- check gate-b/answer/autounattend.xml, or prepare the base VHDX by hand and pass -BaseVhdx."
}

$guestKitDrive = Invoke-Command -Session $session -ScriptBlock {
    $volume = Get-Volume -FileSystemLabel 'CCKIT' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($volume) { return "$($volume.DriveLetter):" }
    return $null
}
if (-not $guestKitDrive) {
    Remove-PSSession $session -ErrorAction SilentlyContinue
    Exit-HarnessError "the guest booted and answered, but no volume labelled CCKIT is visible inside it -- the kit disk did not attach."
}

Write-Step "guest is up; kit is visible at $guestKitDrive inside the VM"
Remove-PSSession $session -ErrorAction SilentlyContinue

$provision = [ordered]@{
    schema             = 'civiccast-gate-b-provision-v1'
    provisioned_utc    = (Get-Date).ToUniversalTime().ToString('o')
    vm_name            = $VmName
    vm_root            = $VmRoot
    base_vhdx          = (Resolve-Path -LiteralPath $BaseVhdx).Path
    os_disk_is_differencing = $true
    kit_vhdx           = $kitVhdx
    kit_source_dir     = (Resolve-Path -LiteralPath $KitDir).Path
    kit_bytes          = $kitBytes
    kit_setup_exe      = $kitSetup[0].FullName
    station_file_count = $stationFiles.Count
    station_bytes      = $stationBytes
    guest_kit_drive    = $guestKitDrive
    memory_gb          = $MemoryStartupGb
    processor_count    = $ProcessorCount
    network_adapters   = 0
}
$provisionPath = Join-Path $VmRoot 'gate-b-provision.json'
$provision | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $provisionPath -Encoding UTF8
Write-Host $provisionPath
exit 0
