# CivicCast Native prior-install removal

- Started UTC: `2026-08-26T23:36:46.7482669Z`
- Completed UTC: `2026-08-26T23:38:17.5633976Z`
- Duration seconds: `90.815`
- Registered quiet command: `"C:\Program Files\CivicCast (Native)\uninstall.exe" /S _?=C:\Program Files\CivicCast (Native)`
- Recorded uninstaller PID: `16368`
- Exit code: `0`
- Process timed out: `false`
- `CivicCastSupervisor` present after uninstall: `false`
- `sc query CivicCastSupervisor`: failed with SCM error `1060` (service does not exist)
- `http://127.0.0.1:8000/api/health` responding after uninstall: `false`
- Verification: **PASS**
