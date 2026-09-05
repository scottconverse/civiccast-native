# AUTORUN-9 clean reinstall
- mission: soak8-e1acfe6
- host: DESKTOP-VBMA6O5
- utc: 20260905T193632Z
- kit: C:\CivicCastSoak\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6
- DryRun: False

installer: CivicCast (Native)_1.0.0-beta.5_x64-setup.exe (289300032 bytes) sha256=a9363be187fa83abe216862a0dd76c894771486a89c71e3232e37d1997cf7dc1
existing: version='1.0.0-beta.5' quiet-uninstall='"C:\CivicCastHostStore\install\uninstall.exe" /S _?=C:\CivicCastHostStore\install'
service before: Running
uninstaller exit=0
service after uninstall: absent
removed C:\ProgramData\CivicCast
removed C:\CivicCastHostStore\install
silent install started 2026-09-05T19:37:58.9007773Z
installer exit=0 at 2026-09-05T19:46:26.1062647Z

## install-progress.log tail
```
      "bytes": 113720712,
      "sha256": "7966e503ce220c0697b486d7c788ac1b44a1635b554932f11399194511520f8b"
    },
    {
      "path": "lib/ollama/cuda_v12/cublasLt64_12.dll",
      "b[2026-09-05 13:40:10] step d3-engine: begin (old=none)
[2026-09-05 13:40:12] step d3-engine: evidence route=FRESH_INSTALL engine_exit=11
[2026-09-05 13:40:12] step d3-engine: SKIPPED (routed to fresh install; existing data adopted, not deleted)
[2026-09-05 13:40:12] step d4-provision: begin
[2026-09-05 13:40:26] step d4-provision: returned 0
[2026-09-05 13:40:26] step d4-activate-station: begin
[2026-09-05 13:40:26] step d4-activate-station: source EXEDIR (kit side-load C:\CivicCastSoak\kit-91caebccc6a6decef476fea5cd785a9ff19abfe6\station\station-index.json)
[2026-09-05 13:45:49] step d4-activate-station: returned 0
[2026-09-05 13:45:49] step d4-service-registration: begin
[2026-09-05 13:46:21] step d4-service-registration: returned 0
[2026-09-05 13:46:21] step d4-service-registration: restored site-packages service host member
[2026-09-05 13:46:21] step d4-firewall-rule: begin
[2026-09-05 13:46:22] step d4-firewall-rule: returned 0
[2026-09-05 13:46:25] postinstall: EstimatedSize corrected to 12384250 KB (measured C:\CivicCastHostStore\install: 10741 files, 1388 dirs)
[2026-09-05 13:46:25] postinstall: SUCCESS (InstalledVersion 1.0.0-beta.5 recorded)
[2026-09-05 13:46:25] postinstall: QuietUninstallString registered (_?=C:\CivicCastHostStore\install)
[2026-09-05 13:46:25] postinstall: InstallLocation rewritten unquoted
[2026-09-05 13:46:25] postinstall: Start Menu operator console shortcut written
[2026-09-05 13:46:25] postinstall: Start Menu public portal shortcut written
[2026-09-05 13:46:25] postinstall: Desktop operator console shortcut written
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
