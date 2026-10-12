# Install CivicCast on Windows

The current release is **`v1.0.0-beta.14`**, the signed native Windows station. It includes Python, PostgreSQL, FFmpeg, GStreamer and local AI runtimes. You do not need Git, Python, Docker, WSL, Ollama or GitHub CLI installed separately.

[Beta 14 downloads](https://github.com/scottconverse/civiccast-native/releases/tag/v1.0.0-beta.14) · [User manual](docs/USER-MANUAL.md) · [Package verification](docs/releases/v1.0.0-beta.14-verification.md)

## Download and install the complete station

Use Windows 11 x64, internet for the download, and a Windows administrator account for setup. Allow about **100 GB free** for preparation and installation, plus your media and recordings. The model download is about 22 GB; preparation temporarily holds the parts, assembled archive and extracted models.

Open **Windows PowerShell** and paste:

```powershell
$installerScript = Join-Path $env:TEMP 'CivicCast-Install-Beta14.ps1'
Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/scottconverse/civiccast-native/releases/download/v1.0.0-beta.14/download_windows_release_artifacts.ps1' -OutFile $installerScript
powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installerScript -Install -Destination "$env:USERPROFILE\Downloads\CivicCast-Beta14"
```

The helper downloads the installer, all five runtime packs and all six signed station packs. It verifies SHA-256 hashes and the installer's valid **Scott Converse** Authenticode signature, and creates the `packs` and `station` folders setup needs. Windows requests administrator approval if needed. Setup uses supported silent mode with the complete kit, without the separate optional raw-model acquisition screen. Wait for it to finish; any actual nonzero exit is reported as failure.

Keep the PowerShell window open until it reports **Done**. During silent
setup, the installer writes a timestamped progress heartbeat before and after
each step to `C:\ProgramData\CivicCast\install-progress.log`; its latest line
names the step in progress.

For download only, replace `-Install` with `-IncludePacks`. Keep the resulting folder together when copying it to USB. The complete folder supplies the dependencies for offline installation.

[Downloader source](scripts/download_windows_release_artifacts.ps1). It targets this exact release.

## First start

Open **CivicCast Operator Console** from the desktop or Start menu, or visit <http://127.0.0.1:8000/operator/> on the station computer.

1. Name the station and create the first administrator.
2. Print or save the recovery kit somewhere safe.
3. Open **System Health**, then configure storage, channels and media or live sources.

The live-caption path automatically retries Whistle while Whisper supplies backup captions. Whistle is the CPU primary for live captions. Whisper supplies recorded transcription and live fallback; supported NVIDIA hardware can accelerate Whisper. The installation path does not require a dedicated GPU.

## Existing or partially installed stations

Use the same complete download and run setup over the installation. Do not uninstall or delete station data first. Setup stops the station during upgrade: back up a working station and plan the interruption. It is intended to preserve accounts, settings, schedules, recordings and model caches. The verification record identifies the exact paths observed; it does not guarantee every historical version pair.

The Beta 14 package passed a fresh offline Windows Sandbox installation and one normal development-host upgrade; setup exited 0 in both. After the host upgrade, the service was healthy at Beta 14 schema 89, with all three channels using Whistle as primary and within capacity. See the [Beta 14 verification record](docs/releases/v1.0.0-beta.14-verification.md) for exact scope and limits.

Historical Beta 13 installation evidence: its normal Beta 11 upgrade, controlled interruption and same-candidate repair, and separate fresh installation apply to Beta 13 only. See the [Beta 13 verification record](docs/releases/v1.0.0-beta.13-verification.md) and [fresh-install evidence](docs/ops/evidence/beta13-fresh-install-observations-2026-10-11.json). Raw Whisper or Ollama directories do not substitute for signed station packs.

For an unknown existing administrator password, a Windows administrator on the station can use the supported interactive reset with the service stopped:

```powershell
Stop-Service CivicCastSupervisor
& 'C:\Program Files\CivicCast (Native)\runtime\python.exe' -I -m civiccast.cli admin reset-password
Start-Service CivicCastSupervisor
```

It prompts privately, preserves station data and revokes that administrator's existing sessions and recovery codes. Do not place passwords in command arguments or reports.

## Folder layout

The release's `station-models.zip.001`, `.002` and subsequent parts form one ZIP64 archive. **Use the helper to verify and extract them.** Individual parts are not runtime packs.

```text
CivicCast-Beta14/
  setup.exe
  packs/
    native-app-payload.ccpack
    native-server-binaries.ccpack
    native-ffmpeg-runtime.ccpack
    native-ollama-runtime.ccpack
    native-cuda-runtime.ccpack
  station/
    station-index.json
    SHA256SUMS.txt
    core.ccpack
    captions-floor.ccpack
    captions-whistle.ccpack
    summary-gemma4-12b.ccpack
    summary-gemma4-e4b.ccpack
    translation-translategemma-4b.ccpack
```

Downloading only setup, placing runtime packs flat beside it, or using a source ZIP does not prepare this layout.

## If installation fails

Read `C:\ProgramData\CivicCast\install-progress.log`. Exit 110 concerns runtime-pack staging; exit 123 concerns station activation or its self-test. Preserve the log and actual exit code. An Apps entry or copied files alone do not prove success.

First setup must be opened on the station. If its URL refuses connection, check the `CivicCastSupervisor` Windows service and installation log. A missing service is an installation failure, not a password problem.

See [Windows release trust](docs/install/windows-release-trust.md) and [Support](SUPPORT.md). Exclude passwords, recovery codes and provider secrets from reports.
