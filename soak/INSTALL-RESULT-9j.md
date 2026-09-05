# AUTORUN-9j second soak: kit fetch + upgrade install + soak reset
- mission: soak8-e1acfe6 (second soak, kit 91caebccc6a6decef476fea5cd785a9ff19abfe6)
- host: DESKTOP-VBMA6O5
- utc: 20260905T165616Z
- kit: http://192.168.0.135:8766/91caebccc6a6decef476fea5cd785a9ff19abfe6/

manifest lines: 19
fetching CivicCast (Native)_1.0.0-beta.5_x64-setup.exe
fetching QUICKSTART-OPERATOR.md
fetching packs/native-app-payload.ccpack
fetching packs/native-cuda-runtime.ccpack
fetching packs/native-ffmpeg-runtime.ccpack
fetching packs/native-ollama-runtime.ccpack
fetching packs/native-server-binaries.ccpack
fetching samples/YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_001_1080p.mp4
fetching samples/YTDown.com_YouTube_Help-Upgrade-the-LPM-Podcast-Studio_Media_oiYNSJEysvs_003_360p.mp4
fetching samples/YTDown.com_YouTube_Longmont-Weather-Report-July-23-2026-to-_Media_6yBccmsSnDc_002_360p.mp4
fetching samples/YTDown.com_YouTube_Serving-Locally-with-Michelle-SMART-Reco_Media_lVVzrRCX9_w_001_1080p.mp4
fetching station/captions-floor.ccpack
fetching station/core-notice.txt
fetching station/core.ccpack
fetching station/native-station-bundle-report.json
fetching station/station-index.json
fetching station/summary-gemma4-12b.ccpack
fetching station/summary-gemma4-e4b.ccpack
fetching station/translation-translategemma-4b.ccpack
kit verify bad=0
installer: CivicCast (Native)_1.0.0-beta.5_x64-setup.exe (289300032 bytes)
authenticode: Valid
existing station: service=Running; installing the full kit OVER it (customer upgrade path)
silent install started 2026-09-05T18:03:24.4136303Z
installer exit=0 at 2026-09-05T18:14:48.4339068Z

## install-progress.log tail
```
  "metadata": {
    "ollama_executables": [
      "ollama.exe"
    ],
    "ollama_spdx_license": "MIT",
    "ollama_version": "0.30.6"
  },
  "files": [
    {
      "path": "lib/ollama/cuda_v12/concrt140.dll",
      "bytes": 311688,
      "sha256": "7d793fed7886cfb2305d7e17b8ba2db874abf3211e47e90d0876b86442b93a7f"
    },
    {
      "path": "lib/ollama/cuda_v12/cublas64_12.dll",
      "bytes": 113720712,
      "sha256": "7966e503ce220c0697b486d7c788ac1b44a1635b554932f11399194511520f8b"
    },
    {
      "path": "lib/ollama/cuda_v12/cublasLt64_12.dll",
      "b[2026-09-05 12:07:11] step d3-engine: begin (old=1.0.0-beta.5)
[2026-09-05 12:07:13] step d3-engine: evidence route=SAME_VERSION_NO_OP engine_exit=12
[2026-09-05 12:07:13] step d3-engine: NO-OP (same version 1.0.0-beta.5 already installed; no migration to run)
[2026-09-05 12:07:13] step d4-provision: begin
[2026-09-05 12:07:19] step d4-provision: returned 0
[2026-09-05 12:07:19] step d4-activate-station: begin
[2026-09-05 12:07:19] step d4-activate-station: source EXEDIR (kit side-load C:\CivicCastSoak\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6\station\station-index.json)
[2026-09-05 12:12:38] step d4-activate-station: returned 0
[2026-09-05 12:12:38] step d4-service-registration: begin
[2026-09-05 12:13:22] step d4-service-registration: returned 0
[2026-09-05 12:13:23] step d4-service-registration: restored site-packages service host member
[2026-09-05 12:13:23] step d4-firewall-rule: begin
[2026-09-05 12:13:23] step d4-firewall-rule: returned 0
[2026-09-05 12:14:47] postinstall: EstimatedSize corrected to 12384044 KB (measured C:\CivicCastHostStore\install: 10740 files, 1284 dirs)
[2026-09-05 12:14:47] postinstall: SUCCESS (InstalledVersion 1.0.0-beta.5 recorded)
[2026-09-05 12:14:48] postinstall: QuietUninstallString registered (_?=C:\CivicCastHostStore\install)
[2026-09-05 12:14:48] postinstall: InstallLocation rewritten unquoted
[2026-09-05 12:14:48] postinstall: Start Menu operator console shortcut written
[2026-09-05 12:14:48] postinstall: Start Menu public portal shortcut written
[2026-09-05 12:14:48] postinstall: Desktop operator console shortcut written
```

## /health
```json
{
    "status":  "healthy",
    "version":  "1.0.0-beta.5",
    "schema":  "current",
    "schema_db_revision":  "0087_retention_terms",
    "schema_expected_head":  "0087_retention_terms",
    "mode":  "normal"
}
```
install RESULT: installer_exit=0 healthy=True
channels ON_AIR after upgrade: 0 []
## raw channel state (egress state.json per channel)
```
public : missing
education : missing
government : missing
```
