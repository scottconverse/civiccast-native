# AUTORUN-9zg soak #5: fetch kit 609273d + CLEAN reinstall (uninstall, wipe, fresh /S install)
- mission: soak8-e1acfe6 (second soak, kit 609273da22b968b8ed9320dfc158d67b01eb30b3)
- host: DESKTOP-VBMA6O5
- utc: 20260906T004626Z
- kit: http://192.168.0.135:8766/609273da22b968b8ed9320dfc158d67b01eb30b3/

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
existing: version='1.0.0-beta.5' quiet-uninstall='"C:\CivicCastHostStore\install\uninstall.exe" /S _?=C:\CivicCastHostStore\install'
service before: Running
uninstaller exit=0
service after uninstall: absent
removed C:\ProgramData\CivicCast
removed C:\CivicCastHostStore\install
silent install started 2026-09-06T01:47:19.6068170Z
installer exit=0 at 2026-09-06T01:55:26.7393657Z

## install-progress.log tail
```
      "bytes": 113720712,
      "sha256": "7966e503ce220c0697b486d7c788ac1b44a1635b554932f11399194511520f8b"
    },
    {
      "path": "lib/ollama/cuda_v12/cublasLt64_12.dll",
      "b[2026-09-05 19:49:26] step d3-engine: begin (old=none)
[2026-09-05 19:49:28] step d3-engine: evidence route=FRESH_INSTALL engine_exit=11
[2026-09-05 19:49:28] step d3-engine: SKIPPED (routed to fresh install; existing data adopted, not deleted)
[2026-09-05 19:49:28] step d4-provision: begin
[2026-09-05 19:49:42] step d4-provision: returned 0
[2026-09-05 19:49:42] step d4-activate-station: begin
[2026-09-05 19:49:42] step d4-activate-station: source EXEDIR (kit side-load C:\CivicCastSoak\kit-609273da22b968b8ed9320dfc158d67b01eb30b3\station\station-index.json)
[2026-09-05 19:54:49] step d4-activate-station: returned 0
[2026-09-05 19:54:49] step d4-service-registration: begin
[2026-09-05 19:55:21] step d4-service-registration: returned 0
[2026-09-05 19:55:21] step d4-service-registration: restored site-packages service host member
[2026-09-05 19:55:21] step d4-firewall-rule: begin
[2026-09-05 19:55:22] step d4-firewall-rule: returned 0
[2026-09-05 19:55:26] postinstall: EstimatedSize corrected to 12384255 KB (measured C:\CivicCastHostStore\install: 10741 files, 1116 dirs)
[2026-09-05 19:55:26] postinstall: SUCCESS (InstalledVersion 1.0.0-beta.5 recorded)
[2026-09-05 19:55:26] postinstall: QuietUninstallString registered (_?=C:\CivicCastHostStore\install)
[2026-09-05 19:55:26] postinstall: InstallLocation rewritten unquoted
[2026-09-05 19:55:26] postinstall: Start Menu operator console shortcut written
[2026-09-05 19:55:26] postinstall: Start Menu public portal shortcut written
[2026-09-05 19:55:26] postinstall: Desktop operator console shortcut written
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
RESULT: installer_exit=0 healthy=True fresh_install=True
