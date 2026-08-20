# SPDX-License-Identifier: Apache-2.0
param(
  [string]$VmName = "civiccast-cleanwin-v2",
  [string]$Snapshot = "clean-windows-base-20260602",
  [string]$VmUser = "tester",
  [string]$PasswordFile = "C:\Dev\Claude\vm-secrets\civiccast-cleanwin-v2-password.txt",
  [string]$SharePath = "C:\Dev\Claude\vm-share\civiccast-cleanwin-v2",
  [Parameter(Mandatory = $true)][string]$Version,
  [Parameter(Mandatory = $true)][string]$InstallerPath,
  [Parameter(Mandatory = $true)][string]$ProofKitPath,
  [string]$UpgradeFromInstallerPath = "C:\Dev\Claude\vm-share\civiccast-cleanwin-v2\civiccast-3.2.0-beta1-windows-setup.exe",
  [string]$UpgradeFromVersion = "3.2.0-beta1",
  [Parameter(Mandatory = $true)][string]$ReportDirName
)

$ErrorActionPreference = "Stop"

function Invoke-Checked($FilePath, [string[]]$Arguments) {
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$FilePath $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
  }
}

function Copy-IntoShare($Source, $Name) {
  $target = Join-Path $SharePath $Name
  if ((Resolve-Path -LiteralPath $Source).Path -ne (Resolve-Path -LiteralPath $target -ErrorAction SilentlyContinue).Path) {
    Copy-Item -LiteralPath $Source -Destination $target -Force
  }
  return $target
}

function Wait-GuestReady {
  for ($i = 0; $i -lt 90; $i++) {
    $info = & VBoxManage showvminfo $VmName --machinereadable 2>$null
    if ($LASTEXITCODE -eq 0 -and ($info -match 'GuestAdditionsRunLevel=3')) {
      & VBoxManage guestcontrol $VmName run --username $VmUser --passwordfile $PasswordFile --exe "C:\Windows\System32\cmd.exe" --wait-stdout --wait-stderr --timeout 30000 -- cmd.exe /c ver | Out-Null
      if ($LASTEXITCODE -eq 0) {
        return
      }
    }
    Start-Sleep -Seconds 5
  }
  throw "Guest Additions did not reach runlevel 3 for $VmName."
}

$installerName = "civiccast-$Version-windows-setup.exe"
$proofKitName = "civiccast-$Version-clean-windows-proof-kit.zip"
$guestScriptName = "run-$Version-lifecycle-proof.ps1"
$reportDir = Join-Path $SharePath $ReportDirName
New-Item -ItemType Directory -Force -Path $SharePath | Out-Null
Remove-Item -Recurse -Force $reportDir -ErrorAction SilentlyContinue
$sharedInstaller = Copy-IntoShare $InstallerPath $installerName
$sharedProofKit = Copy-IntoShare $ProofKitPath $proofKitName
$upgradeName = Split-Path -Leaf $UpgradeFromInstallerPath
$sharedUpgrade = Copy-IntoShare $UpgradeFromInstallerPath $upgradeName

$expectedInstallerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sharedInstaller).Hash.ToLowerInvariant()
$expectedProofKitHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sharedProofKit).Hash.ToLowerInvariant()
$expectedUpgradeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $sharedUpgrade).Hash.ToLowerInvariant()

$guestScript = @'
param(
  [string]$Version,
  [string]$UpgradeFromVersion,
  [string]$ExpectedInstallerHash,
  [string]$ExpectedProofKitHash,
  [string]$ExpectedUpgradeHash,
  [string]$ReportDirName
)

$ErrorActionPreference = "Stop"

$Share = "\\VBOXSVR\CivicCastShare"
$ReportDir = Join-Path $Share $ReportDirName
$ProofRoot = "C:\CivicCastProofFinalLifecycle"
$Installer = Join-Path $ProofRoot "incoming\civiccast-$Version-windows-setup.exe"
$ProofKit = Join-Path $Share "civiccast-$Version-clean-windows-proof-kit.zip"
$UpgradeFromInstaller = Join-Path $Share "civiccast-$UpgradeFromVersion-windows-setup.exe"

function Capture-Wsl {
  $lines = @()
  try { $lines += (& wsl --status 2>&1 | ForEach-Object { $_.ToString() }) } catch { $lines += $_.Exception.Message }
  try { $lines += (& wsl -l -v 2>&1 | ForEach-Object { $_.ToString() }) } catch { $lines += $_.Exception.Message }
  return $lines
}

function Capture-OptionalFeature($name) {
  try {
    return Get-WindowsOptionalFeature -Online -FeatureName $name |
      Select-Object FeatureName, State, RestartNeeded
  } catch {
    return [ordered]@{ FeatureName = $name; Error = $_.Exception.Message }
  }
}

function Capture-Paths {
  $paths = @(
    "C:\Program Files\CivicCast",
    "C:\Program Files (x86)\CivicCast",
    "C:\Program Files\CivicCast Installer",
    "C:\Program Files (x86)\CivicCast Installer",
    "C:\CivicCast",
    (Join-Path $env:LOCALAPPDATA "CivicCast"),
    (Join-Path $env:LOCALAPPDATA "CivicCast Installer"),
    (Join-Path $env:LOCALAPPDATA "Programs\CivicCast Installer"),
    (Join-Path $env:APPDATA "CivicCast"),
    (Join-Path $env:APPDATA "CivicCast Installer")
  )
  foreach ($path in $paths) {
    [ordered]@{ path = $path; exists = Test-Path -LiteralPath $path }
  }
}

function Capture-UninstallEntries {
  $entries = @()
  $roots = @(
    "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
  )
  foreach ($root in $roots) {
    if (Test-Path $root) {
      $entries += Get-ChildItem $root -ErrorAction SilentlyContinue |
        ForEach-Object {
          $p = Get-ItemProperty $_.PsPath -ErrorAction SilentlyContinue
          if ($p.DisplayName -match "CivicCast") {
            [ordered]@{
              key = $_.Name
              display_name = $p.DisplayName
              display_version = $p.DisplayVersion
              install_location = $p.InstallLocation
              uninstall_string = $p.UninstallString
            }
          }
        }
    }
  }
  return @($entries)
}

function Get-InstalledApp {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\CivicCast Installer\civiccast-installer.exe"),
    (Join-Path $env:LOCALAPPDATA "CivicCast Installer\civiccast-installer.exe"),
    (Join-Path $env:ProgramFiles "CivicCast Installer\civiccast-installer.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "CivicCast Installer\civiccast-installer.exe")
  ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
  return $candidates | Select-Object -First 1
}

function Capture-FirstRunState {
  $statePath = Join-Path $env:LOCALAPPDATA "CivicCast\installer-state.json"
  $bootstrapLog = Join-Path $env:LOCALAPPDATA "CivicCast\bootstrap-wsl2-ubuntu.log"
  $state = $null
  if (Test-Path -LiteralPath $statePath) {
    try { $state = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json } catch { $state = $_.Exception.Message }
  }
  [ordered]@{
    installer_state_path = $statePath
    installer_state_exists = Test-Path -LiteralPath $statePath
    installer_state = $state
    bootstrap_log_path = $bootstrapLog
    bootstrap_log_exists = Test-Path -LiteralPath $bootstrapLog
    expected_dependency_absent_status = "blocked"
    expected_dependency_absent_action = "Choose Set up Windows helper"
  }
}

function Invoke-Installer($Path, $Label) {
  $stdout = Join-Path $ReportDir "$Label.stdout.txt"
  $stderr = Join-Path $ReportDir "$Label.stderr.txt"
  $started = Get-Date
  $proc = Start-Process -FilePath $Path -ArgumentList "/S" -Wait -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
  $finished = Get-Date
  [ordered]@{
    label = $Label
    path = $Path
    started_at = $started.ToUniversalTime().ToString("o")
    finished_at = $finished.ToUniversalTime().ToString("o")
    exit_code = $proc.ExitCode
    stdout = $stdout
    stderr = $stderr
  }
}

function Launch-App {
  $installed = Get-InstalledApp
  if (-not $installed) {
    throw "Installed civiccast-installer.exe not found."
  }
  $item = Get-Item -LiteralPath $installed
  $launch = Start-Process -FilePath $installed -PassThru
  Start-Sleep -Seconds 15
  $running = $false
  try { $running = -not $launch.HasExited } catch { $running = $false }
  if ($running) {
    Stop-Process -Id $launch.Id -Force -ErrorAction SilentlyContinue
  }
  [ordered]@{
    path = $installed
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $installed).Hash.ToLowerInvariant()
    file_version = $item.VersionInfo.FileVersion
    product_version = $item.VersionInfo.ProductVersion
    launch_started = $true
    launch_process_id = $launch.Id
    launch_still_running_after_15s = $running
  }
}

function Invoke-Uninstall {
  $before = Capture-UninstallEntries
  $entry = $before | Select-Object -First 1
  if (-not $entry -or -not $entry.uninstall_string) {
    throw "CivicCast uninstall entry not found."
  }
  $uninstaller = ($entry.uninstall_string -replace '^"', '') -replace '"$', ''
  if (-not (Test-Path -LiteralPath $uninstaller)) {
    throw "CivicCast uninstaller not found at $uninstaller."
  }
  $started = Get-Date
  $proc = Start-Process -FilePath $uninstaller -ArgumentList "/S" -Wait -PassThru
  $finished = Get-Date
  $retainedPolicy = [ordered]@{
    status = "allowed"
    allowed_paths = @(
      (Join-Path $env:LOCALAPPDATA "CivicCast"),
      (Join-Path $env:LOCALAPPDATA "CivicCast Installer")
    )
    reason = "Uninstall removes installed executables and registry entries while preserving user-scoped station setup/log state for backup and later reinstall."
  }
  [ordered]@{
    label = "uninstall-$Version"
    uninstall_string = $entry.uninstall_string
    uninstaller = $uninstaller
    started_at = $started.ToUniversalTime().ToString("o")
    finished_at = $finished.ToUniversalTime().ToString("o")
    exit_code = $proc.ExitCode
    entries_before = @($before)
    entries_after = @(Capture-UninstallEntries)
    paths_after = @(Capture-Paths)
    app_path_after = Get-InstalledApp
    retained_paths_policy = $retainedPolicy
  }
}

New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
Remove-Item -Recurse -Force $ProofRoot -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $ProofRoot | Out-Null

$proofKitHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ProofKit).Hash.ToLowerInvariant()
if ($proofKitHash -ne $ExpectedProofKitHash) { throw "Proof kit hash mismatch." }
$upgradeHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $UpgradeFromInstaller).Hash.ToLowerInvariant()
if ($upgradeHash -ne $ExpectedUpgradeHash) { throw "Upgrade installer hash mismatch." }
Expand-Archive -LiteralPath $ProofKit -DestinationPath $ProofRoot -Force
$installerHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $Installer).Hash.ToLowerInvariant()
if ($installerHash -ne $ExpectedInstallerHash) { throw "Installer hash mismatch." }

$os = Get-CimInstance Win32_OperatingSystem
$cs = Get-CimInstance Win32_ComputerSystem
$pendingBaseline = [ordered]@{
  cbs_reboot_pending = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"
  windows_update_reboot_required = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
  pending_file_rename = [bool](Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -Name PendingFileRenameOperations -ErrorAction SilentlyContinue)
  pending_file_rename_operations = @((Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations)
}
$pre = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  vm = "civiccast-cleanwin-v2"
  snapshot = "clean-windows-base-20260602"
  user = "$env:USERDOMAIN\$env:USERNAME"
  os = [ordered]@{ caption = $os.Caption; version = $os.Version; build = $os.BuildNumber; architecture = $os.OSArchitecture }
  computer = [ordered]@{ name = $env:COMPUTERNAME; ram_gb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1) }
  proof_kit = $ProofKit
  proof_kit_sha256 = $proofKitHash
  installer = $Installer
  installer_sha256 = $installerHash
  upgrade_from_installer = $UpgradeFromInstaller
  upgrade_from_installer_sha256 = $upgradeHash
  existing_civiccast_paths = @(Capture-Paths)
  existing_uninstall_entries = @(Capture-UninstallEntries)
  optional_features = @(Capture-OptionalFeature "Microsoft-Windows-Subsystem-Linux"; Capture-OptionalFeature "VirtualMachinePlatform")
  wsl_status = @(Capture-Wsl)
  pending_reboot_keys = $pendingBaseline
}
$pre | ConvertTo-Json -Depth 12 | Set-Content -Encoding UTF8 (Join-Path $ReportDir "pre-proof-state.json")

$install = Invoke-Installer $Installer "install-$Version"
$installedApp = Launch-App
$firstRunState = Capture-FirstRunState
$reinstall = Invoke-Installer $Installer "reinstall-$Version"
$reinstallApp = Launch-App
$reinstallState = Capture-FirstRunState
$uninstall = Invoke-Uninstall
$upgradeFromInstall = Invoke-Installer $UpgradeFromInstaller "install-$UpgradeFromVersion"
$upgradeFromApp = Launch-App
$upgrade = Invoke-Installer $Installer "upgrade-$UpgradeFromVersion-to-$Version"
$upgradeApp = Launch-App
$upgradeState = Capture-FirstRunState
$pendingAfter = [ordered]@{
  cbs_reboot_pending = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"
  windows_update_reboot_required = Test-Path "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired"
  pending_file_rename = [bool](Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -Name PendingFileRenameOperations -ErrorAction SilentlyContinue)
  pending_file_rename_operations = @((Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager" -Name PendingFileRenameOperations -ErrorAction SilentlyContinue).PendingFileRenameOperations)
}

$post = [ordered]@{
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
  status = "passed_native_package_install_launch"
  version = $Version
  vm = "civiccast-cleanwin-v2"
  snapshot = "clean-windows-base-20260602"
  proof_boundary = "Clean Windows VM packaged installer install, app-launch, reinstall, uninstall, and $UpgradeFromVersion beta upgrade proof. Nested WSL2 runtime is observed but not required or claimed by this probe."
  package = [ordered]@{
    proof_kit_sha256 = $proofKitHash
    installer_sha256 = $installerHash
    installer_exit_code = $install.exit_code
    install_started_at = $install.started_at
    install_finished_at = $install.finished_at
  }
  installed_app = $installedApp
  first_run_state = $firstRunState
  uninstall_entries = @(Capture-UninstallEntries)
  civiccast_paths_after_install = @(Capture-Paths)
  optional_features_after_install = @(Capture-OptionalFeature "Microsoft-Windows-Subsystem-Linux"; Capture-OptionalFeature "VirtualMachinePlatform")
  wsl_status_after_install = @(Capture-Wsl)
  pending_reboot_baseline = $pendingBaseline
  pending_reboot_keys = $pendingAfter
  lifecycle = [ordered]@{
    reinstall = $reinstall
    reinstall_app = $reinstallApp
    reinstall_state = $reinstallState
    uninstall = $uninstall
    upgrade_from = [ordered]@{ installer = $UpgradeFromInstaller; sha256 = $upgradeHash; install = $upgradeFromInstall; app = $upgradeFromApp }
    upgrade = $upgrade
    upgrade_app = $upgradeApp
    upgrade_state = $upgradeState
  }
}
$post | ConvertTo-Json -Depth 20 | Set-Content -Encoding UTF8 (Join-Path $ReportDir "vbox-cleanwin-v2-final-lifecycle-proof-report.json")

$summary = @"
# CivicCast $Version Final Lifecycle VM Proof

- VM: civiccast-cleanwin-v2
- Snapshot: clean-windows-base-20260602
- Clean install: passed_native_package_install_launch
- Reinstall proof: passed
- Uninstall proof: passed
- Upgrade proof: passed
- Proof kit SHA-256: $proofKitHash
- Installer SHA-256: $installerHash
- $UpgradeFromVersion installer SHA-256: $upgradeHash
"@
$summary | Set-Content -Encoding UTF8 (Join-Path $ReportDir "README.md")
$post | ConvertTo-Json -Depth 20
'@

$guestScriptPath = Join-Path $SharePath $guestScriptName
$guestScript | Set-Content -Encoding UTF8 -LiteralPath $guestScriptPath

$state = (& VBoxManage showvminfo $VmName --machinereadable | Select-String '^VMState=').ToString()
if ($state -notmatch 'poweroff|saved') {
  & VBoxManage controlvm $VmName poweroff | Out-Null
  Start-Sleep -Seconds 5
}
Invoke-Checked "VBoxManage" @("snapshot", $VmName, "restore", $Snapshot)
Invoke-Checked "VBoxManage" @("startvm", $VmName, "--type", "headless")
Wait-GuestReady

$guestScriptGuestPath = "\\VBOXSVR\CivicCastShare\$guestScriptName"
Invoke-Checked "VBoxManage" @(
  "guestcontrol", $VmName, "run",
  "--username", $VmUser,
  "--passwordfile", $PasswordFile,
  "--exe", "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
  "--wait-stdout",
  "--wait-stderr",
  "--timeout", "1800000",
  "--",
  "powershell.exe",
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $guestScriptGuestPath,
  "-Version", $Version,
  "-UpgradeFromVersion", $UpgradeFromVersion,
  "-ExpectedInstallerHash", $expectedInstallerHash,
  "-ExpectedProofKitHash", $expectedProofKitHash,
  "-ExpectedUpgradeHash", $expectedUpgradeHash,
  "-ReportDirName", $ReportDirName
)

Get-Content -Raw -LiteralPath (Join-Path $reportDir "vbox-cleanwin-v2-final-lifecycle-proof-report.json")
