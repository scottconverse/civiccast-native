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
