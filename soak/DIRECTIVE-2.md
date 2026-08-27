# DIRECTIVE 2 — recovery after your crash (coordinator-authored)

## Channel change (permanent)
The coordinator will NEVER write to your working branch again — my earlier commit there
is what collided with your git state and crashed you. From now on:
- **Your working branch (`tester/soak8h-99db2c6-DESKTOP-VBMA6O5`) is yours alone.**
- **All directives live on THIS branch (`tester/soak8h-99db2c6-directives`).** Poll it
  for new `soak/DIRECTIVE-*.md` files before each phase and at least every 15 minutes:
  `git fetch origin tester/soak8h-99db2c6-directives` and read the files at that ref
  (no need to check it out — `git show origin/tester/soak8h-99db2c6-directives:soak/DIRECTIVE-2.md`).

## Recover your git state
Your local repo may be mid-conflict from my bad commit. Reset it:
```
git -C C:\CivicCastSoak\repo fetch origin
git -C C:\CivicCastSoak\repo checkout tester/soak8h-99db2c6-DESKTOP-VBMA6O5
git -C C:\CivicCastSoak\repo reset --hard origin/tester/soak8h-99db2c6-DESKTOP-VBMA6O5
```
(Nothing of yours is lost — every report you made is already pushed.)

## Then resume DIRECTIVE 1 (its full text is in soak/DIRECTIVE-1.md on this branch and on
your branch's history). Check the DISK to see how far you actually got before crashing:
1. Evidence archived? (soak/evidence-provision-failure/ committed?) If not, do it first.
2. Full wipe done? (C:\ProgramData\CivicCast, C:\CivicCastHostStore,
   C:\Program Files\CivicCast (Native) all gone, CivicCast* scheduled tasks removed?)
   Finish it and commit soak/CLEANUP.md.
3. Install attempt #3 run? If not, run it and continue the full original mission:
   health checks → soak/INSTALL.md → soak.ps1 + startup task → 10-min heartbeats with
   15-min pushes → T+4h reboot → unattended recovery → T+8h soak/final-verdict.json.
   The 8-hour clock starts at your first post-install heartbeat.
4. If install #3 fails on the clean box: archive logs, commit soak/INSTALL-FAILED-3.md, STOP.

Honest failures over silent success.
