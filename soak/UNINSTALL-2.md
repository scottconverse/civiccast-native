# LPM rehearsal preserved-data uninstall

- Started (UTC): `2026-08-27T17:32:04.7732738Z`
- Completed (UTC): `2026-08-27T17:32:50.2901815Z`
- Duration: approximately `45.5 seconds`
- Registered command: `"C:\CivicCastHostStore\install\uninstall.exe" /S _?=C:\CivicCastHostStore\install`
- Recorded uninstaller PID: `19960`
- Uninstaller exit code: `0`
- Timed out: `false`
- Launch error: `null`

Verification at `2026-08-27T17:33:04.2327993Z`:

- `sc.exe query CivicCastSupervisor` returned exit `1060`: service does not exist.
- `http://127.0.0.1:8000/api/health` refused the connection: nothing answered on port 8000.
- `C:\ProgramData\CivicCast` remains present as required.
- Preserved ProgramData file count: `1,775`.
- Preserved ProgramData total bytes: `71,940,976`.

No CivicCast ProgramData was deleted. This preserved state is the adopt-over-existing-data input for candidate 13.
