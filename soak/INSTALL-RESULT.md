# AUTORUN-1 kit fetch + install
- mission: soak8-e1acfe6
- host: DESKTOP-VBMA6O5
- utc: 20260903T193516Z
- kit: http://192.168.0.135:8766/b78b9c7dfa4d66b442172759439553381ec8be44/

manifest lines: 19
fetching CivicCast (Native)_1.0.0-beta.4_x64-setup.exe
fetching packs/native-app-payload.ccpack
fetching packs/native-cuda-runtime.ccpack
fetching packs/native-ffmpeg-runtime.ccpack
fetching packs/native-ollama-runtime.ccpack
fetching packs/native-server-binaries.ccpack
fetching station/core-notice.txt
fetching station/core.ccpack
fetching station/native-station-bundle-report.json
fetching station/station-index.json
kit verify bad=0
installer: CivicCast (Native)_1.0.0-beta.3_x64-setup.exe (289180536 bytes)
authenticode: Valid
kit version: 1.0.0-beta.3
existing install: service=Running version='1.0.0-beta.3' quiet-uninstall='"C:\CivicCastHostStore\install\uninstall.exe" /S _?=C:\CivicCastHostStore\install'
same version (or no reliable version/uninstall string) -- upgrading in place, no uninstall
silent install started 2026-09-03T19:49:53.7321405Z
installer exit=123 at 2026-09-03T19:51:33.7587853Z

## install-progress.log tail
```
      "b[2026-09-03 13:51:22] step d2-verify-ollama-runtime: begin
[2026-09-03 13:51:28] step d2-verify-ollama-runtime: verification report: {
  "path": "C:\\CivicCastHostStore\\install\\packs\\native-ollama-runtime.ccpack",
  "sha256": "a3bcc3b6d48fcdaf8be3ce158118a86fafc09735f63fe1b587f24f8c29b8178a",
  "component": "native-ollama-runtime",
  "product_version": "1.0.0-beta.3",
  "compatible_core": "1.0.0-beta.3",
  "signing_key_id": "civiccast-production-2026-beta1",
  "file_count": 69,
  "total_bytes": 1941210728,
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
      "b[2026-09-03 13:51:28] step d3-engine: begin (old=1.0.0-beta.3)
[2026-09-03 13:51:30] step d3-engine: evidence route=SAME_VERSION_NO_OP engine_exit=12
[2026-09-03 13:51:30] step d3-engine: NO-OP (same version 1.0.0-beta.3 already installed; no migration to run)
[2026-09-03 13:51:30] step d4-provision: begin
[2026-09-03 13:51:32] step d4-provision: returned 0
[2026-09-03 13:51:32] step d4-activate-station: begin
[2026-09-03 13:51:32] step d4-activate-station: source EXEDIR (kit side-load C:\CivicCastSoak\kit\station\station-index.json)
[2026-09-03 13:51:33] step d4-activate-station: returned 66
[2026-09-03 13:51:33] ALERT: CivicCast (Native) setup could not activate the station from the signed station index it found. If you installed from a CivicCast kit folder, make sure its station folder was copied across whole; otherwise the station's component packs could not be obtained from this machine's pack cache. See the installer log above for the exact underlying error.
[2026-09-03 13:51:33] postinstall: FAILED, aborting with exit code 123
```

## /health
```json
```
RESULT: installer_exit=123 healthy=False
