# Candidate 13 LPM rehearsal install

- Candidate SHA: `75cc13f46a4682a3a9972d91656bd6d57eac9c07`
- Installer source: `D:\civiccast-kit-75cc13f\CivicCast (Native)_1.0.0-beta.1_x64-setup.exe` (verified delivery USB)
- Arguments: `/S /D=C:\CivicCastHostStore\install`
- Started (UTC): `2026-08-27T20:21:19.8222942Z`
- First healthy response (UTC): `2026-08-27T20:56:43.3221190Z`
- Minutes from installer launch to first healthy response: `35.392`
- Installer exit code: `0`
- `GET /api/health`: `200`
- `GET /operator/`: `200`
- `GET /`: `200`
- `CivicCastSupervisor`: `Running`
- Provision recovery document present: `false` (success path)
- Provision journal present: `C:\ProgramData\CivicCast\provision\provision-journal.json`

The 35.392-minute launch-to-health interval includes approximately 24 minutes of station-pack activation from the USB. The first post-installer health probe succeeded.

## Preserved-data adoption and provision evidence

From `C:\ProgramData\CivicCast\install-progress.log`:

> `[2026-08-27 14:32:07] step d3-engine: SKIPPED (routed to fresh install; existing data adopted, not deleted)`
>
> `[2026-08-27 14:32:07] step d4-provision: begin`
>
> `[2026-08-27 14:32:13] step d4-provision: returned 0`
>
> `[2026-08-27 14:56:30] postinstall: SUCCESS (InstalledVersion 1.0.0-beta.1 recorded)`

From `C:\ProgramData\CivicCast\upgrade\upgrade-engine.log`:

> `2026-08-27T20:32:07.768613+00:00 route: fresh_install -- No CivicCast (Native) product is installed on this machine (the CivicCastSupervisor service is not registered), so there is nothing to upgrade and the install/upgrade engine is not applicable and did not run. Setup found an existing data root at C:\ProgramData\CivicCast\upgrade; that existing data is preserved and adopted by this installation as-is, never deleted.`

Install verdict: `PASS`.
