# Virgin-machine evidence

- Completed: 2026-08-29T12:57:00Z
- Registry `QuietUninstallString`: `"C:\CivicCastHostStore\install\uninstall.exe" /S _?=C:\CivicCastHostStore\install`
- Quiet-uninstall launch result: could not launch because the referenced `uninstall.exe` was absent. This stale-uninstaller condition was observed before cleanup.
- Residual service cleanup: `CivicCastSupervisor` stopped and deleted.
- `CivicCastSupervisor` present after cleanup: **no**
- `http://127.0.0.1:8000/api/health` responding after cleanup: **no** (status 0 after a 3-second bounded request)
- `C:\ProgramData\CivicCast` present after ordered deletion: **no**
- `C:\CivicCastHostStore\install` present after cleanup: **no**
- HKLM uninstall key present after cleanup: **no**
- CivicCast Start Menu/Desktop shortcut candidates present: **none**
- Prior kit directories removed before candidate #16 acquisition: `C:\CivicCastSoak\kit`, `C:\CivicCastSoak\kit13`

The machine is virgin for this test: service, health endpoint, product data, installed payload, uninstall registration, known shortcuts, and old kit directories are absent.
