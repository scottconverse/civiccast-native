# CivicCast Native soak install failed

- Candidate: `99db2c6e60f10dabc6503b4ada25ba09aef0491d`
- Installer: `CivicCast (Native)_1.0.0-beta.1_x64-setup.exe`
- Silent command: `setup.exe /S /D=C:\CivicCastHostStore\install`
- Install attempt started UTC: `2026-08-26T22:50:51Z`
- Installer refusal recorded UTC: `2026-08-26T22:51:06Z`
- Installer exit code: `120`
- Result: **FAILED — soak not started**

The candidate installer refused because an existing `CivicCastSupervisor` service was already registered. The pre-existing station continued returning HTTP 200 from `/api/health`, but that is not candidate-install proof and was not counted as a post-install heartbeat. No scheduled soak task was registered and the eight-hour clock never started.

The elevated helper remained in its install job without writing `C:\CivicCastSoak\install-result.json`; no process was killed and no product service was stopped or relaunched.

## Authoritative installer log excerpt

```text
[2026-08-26 16:50:55] preinstall: checking for a live existing install (install-only refusal)
[2026-08-26 16:51:06] preinstall: REFUSED (CivicCastSupervisor service is registered in the SCM)
[2026-08-26 16:51:06] ALERT: An existing CivicCast (Native) installation is present on this machine (the CivicCastSupervisor service is registered). This beta is install-only and does not support installing over a live install.

To update: uninstall CivicCast (Native) first from Windows Settings > Apps. Your recorded data and database are preserved by uninstall and will be adopted by the new installation. Then run this installer again.
[2026-08-26 16:51:06] postinstall: FAILED, aborting with exit code 120
```

## Fresh install after verified uninstall

- Attempt started UTC: `2026-08-26T23:42:50Z`
- Failure recorded UTC: `2026-08-26T23:55:54Z`
- Silent command: `setup.exe /S /D=C:\CivicCastHostStore\install`
- Pack staging: completed far enough to enter `d3-engine` and `d4-provision`
- Provision return code: `75`
- Installer exit code: `116`
- `CivicCastSupervisor` after failure: absent (SCM error `1060`)
- `http://127.0.0.1:8000/api/health` after failure: no response
- Referenced `C:\ProgramData\CivicCast\provision\PROVISION-RECOVERY.md`: absent
- Result: **FAILED — soak not started**

```text
[2026-08-26 17:55:45] step d3-engine: begin (old=none)
[2026-08-26 17:55:51] step d3-engine: SKIPPED (routed to fresh install; existing data adopted, not deleted)
[2026-08-26 17:55:51] step d4-provision: begin
[2026-08-26 17:55:54] step d4-provision: returned 75
[2026-08-26 17:55:54] ALERT: CivicCast (Native) setup could not provision the PostgreSQL server. See the installer log and C:\ProgramData\CivicCast\provision\PROVISION-RECOVERY.md for details.
[2026-08-26 17:55:54] postinstall: FAILED, aborting with exit code 116
```

### Provisioning-path diagnosis

Read-only follow-up found a path mismatch after the custom `/D=` install:

- Candidate payload exists under `C:\CivicCastHostStore\install`, including `packs`, `runtime`, `dependencies`, and `CivicCast Native.exe`.
- `C:\Program Files\CivicCast (Native)` contains only a residual `uninstall.exe`; it has no `packs` directory.
- The preserved `C:\ProgramData\CivicCast\provision\provision-journal.json` records `server_pack_path` as `C:\Program Files\CivicCast (Native)\packs\native-server-binaries.ccpack`.
- The journal is stale from `2026-08-16`, remains in phase `complete`, and was not updated by the failed `2026-08-26` attempt.
- The upgrade engine explicitly chose `fresh_install` while preserving and adopting the existing ProgramData root as-is.

This evidence is consistent with provisioning return `75` being caused by the adopted provisioning state referring to the default Program Files pack path while the requested candidate payload was installed under `C:\CivicCastHostStore\install`. No preserved data or candidate files were modified to test that inference.
