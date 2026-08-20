# Non-Technical Tester Walkthrough

Use this path if your job is to see whether CivicCast makes sense for a clerk,
meeting operator, AV helper, or public-access volunteer.

For the final station-side acceptance pass, use
[Public Station Implementation Walkthrough](station-implementation-walkthrough.md)
with the release owner after the release gates and soak evidence are complete.

## Install

> **Use `v1.0.0-rc18`** — the current controlled beta. Do not install rc13 or any
> earlier prerelease. Confirm the filename, size, and SHA-256 against
> [START-HERE](START-HERE.md) before you run the installer.

1. Download `civiccast-1.0.0-rc18-windows-setup.exe` from the
   [public rc18 release](https://github.com/scottconverse/civiccast/releases/tag/v1.0.0-rc18).
2. Do not use the repository source ZIP, tester handoff files, or Git LFS files
   for installation.
3. Open the checksum page if you were given one and confirm the filename and
   version match the release.
4. Run the setup app. Windows will show a blue **"Windows protected your PC"**
   screen — this is expected and not a sign of a problem. Read
   [SMARTSCREEN-WALKTHROUGH.md](SMARTSCREEN-WALKTHROUGH.md) beforehand so you know
   exactly what to click (it's two clicks: **More info**, then **Run anyway**).
5. Let the setup app finish. WSL2 (Windows Subsystem for Linux) + Ubuntu setup can take several minutes, but
   the installer must keep showing the current phase, step, elapsed time, and a
   regularly updating heartbeat. It must explicitly say when a restart is
   required. If feedback stops updating, record it as a failure.
6. When the dashboard opens, continue in the operator console.

## First Admin

1. Open **Setup**.
2. Enter the station name.
3. Create the first admin username and password.
4. Save or print the recovery kit.
5. Put the recovery kit somewhere the organization controls.

## Backup And Restore

1. In **Setup**, choose a backup folder or drive.
2. Select **Verify backup**.
3. Open **System Health**.
4. Select **Run restore rehearsal**.
5. Confirm the database drill passes and says that media, configuration, and
   credentials are not covered.

## Live Safety Check

1. Open **System Health**.
2. Without a configured server-side media probe (the system that checks your camera/encoder before going live), confirm the screen says
   **Source preview unavailable** and does not allow live start.
3. Do not use this build for a real meeting unless an integrator has separately
   configured and proven the station's live ingest path.

## First Test Meeting

1. Open **Run Meeting**.
2. Choose the source option that matches your real equipment.
3. If no camera is ready, use a sample recording or upload a short test file.
4. Open **System Health** and choose **Run private rehearsal**. Confirm the
   result says the exact sample was copied, a private recording was created,
   and resident preview loaded.
5. Package the uploaded or sample recording.
6. Confirm it is not visible to residents before approval.
7. Approve the Portal publication surface.
8. Open resident preview in another browser and confirm playback.

## If You Get Stuck

1. Open **System Health**.
2. Create a support bundle.
3. Select **Download support bundle** and keep the downloaded JSON file.
4. Use [bug-report-template.md](bug-report-template.md).
5. Do not paste passwords, recovery codes, private keys, provider secrets,
   resident data, or private meeting content into a public report.
