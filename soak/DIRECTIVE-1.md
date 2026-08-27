# DIRECTIVE 1 — from the coordinator (read on your ~5-min poll)

New standing rule first: **`git pull --rebase` before every push from now on** — the
coordinator commits directives to this branch, and your pushes must not fight them.
Check for new `soak/DIRECTIVE-*.md` files at every phase boundary.

## Why your install failed
The uninstaller preserves the old station's data by design. Your fresh install then
ADOPTED that months-old leftover database and provisioning failed (return 75, exit 116).
The owner has declared everything on this box dead. Full wipe is authorized.

## Do now, in this order

1. ARCHIVE THE EVIDENCE FIRST (it is valuable — do not skip):
   Copy into `soak/evidence-provision-failure/` in the repo and commit:
   - the installer's own log file (the one you quoted from)
   - everything under `C:\ProgramData\CivicCast\provision\` (if present)
   - the newest files under `C:\ProgramData\CivicCast\logs\` (last ~200 lines of each
     is enough; note filenames and sizes)
   - `Get-ChildItem -Recurse` listings (names + sizes only) of `C:\ProgramData\CivicCast`
     and `C:\CivicCastHostStore` so we know exactly what the adopt path saw.

2. FULL WIPE of all CivicCast remnants (owner-authorized; nothing on this box is live):
   - Confirm no CivicCast service exists (`sc query CivicCastSupervisor` → 1060) and
     nothing answers on 127.0.0.1:8000. (Both were already true after your uninstall.)
   - Delete, elevated: `C:\ProgramData\CivicCast`, `C:\CivicCastHostStore`,
     `C:\Program Files\CivicCast (Native)` (if any remnant), and any
     `CivicCast*` scheduled tasks left from old testing (query first, delete what you find).
   - Do NOT touch `C:\CivicCastSoak` (your own working dir) or anything non-CivicCast.
   - Verify each path is gone (Test-Path false). Commit `soak/CLEANUP.md` with what you
     deleted, sizes, and the verification results.

3. INSTALL ATTEMPT #3 on the now-clean box: exactly as originally instructed
   (`setup.exe /S /D=C:\CivicCastHostStore\install`), then the full original mission:
   health checks → `soak/INSTALL.md` → soak.ps1 + startup task → 10-min heartbeats,
   15-min pushes → T+4h reboot → unattended recovery → T+8h `soak/final-verdict.json`.
   The 8-hour clock starts at your first post-install heartbeat.

4. If install attempt #3 fails on a CLEAN box: archive its logs the same way, commit
   `soak/INSTALL-FAILED-3.md`, and STOP. That would be a hard product failure and the
   evidence is the deliverable.

Honest failures over silent success, as always.
