# DIRECTIVE 5 — TODAY: LPM dress rehearsal + 8h daytime soak of candidate #13

Supersedes DIRECTIVES 1-4 (all complete). This is today's full mission. Tomorrow the
operator installs at LPM on a machine WITH A PREVIOUS FAILED INSTALL — today you
rehearse exactly that on this box, then soak it.

New working branch (yours alone): `tester/lpm-rehearsal-407e507-DESKTOP-VBMA6O5`
(create from origin/main in C:\CivicCastSoak\repo; `git pull --rebase` before EVERY push).
Directives keep arriving on THIS branch — poll it before each phase and every 15 min.

## Phase 0 — ACK + preflight
Commit soak/ACK-2.md: timestamp, confirmation that the current station (last night's
99db2c6 install) answers 200 on http://127.0.0.1:8000/api/health. If it's not healthy,
say so in the ACK and continue anyway (the uninstall comes next regardless).

## Phase 1 — UNINSTALL, PRESERVING DATA (this sets up the LPM scenario)
1. Registry QuietUninstallString (as you did last night), elevated. Do NOT delete
   C:\ProgramData\CivicCast afterward — the preserved data/journal IS the test this time.
2. Verify: CivicCastSupervisor gone (SCM 1060), nothing on :8000,
   C:\ProgramData\CivicCast still present (record its file count + bytes).
3. Commit soak/UNINSTALL-2.md with those results.

## Phase 2 — get candidate #13
The kit is building now on the coordinator box (source sha starts 407e507). When it is
staged, DIRECTIVE-6 will arrive on this branch with the LAN URL. Poll every 10 min.
Download over LAN into C:\CivicCastSoak\kit13 (delete any partial first), verify
setup.exe + packs\ + station\, commit soak/KIT-2.md (duration, file count, bytes).

## Phase 3 — THE CRITICAL INSTALL (adopt-over-preserved-data)
Run elevated from C:\CivicCastSoak\kit13:
  & ".\<the setup exe>" /S /D=C:\CivicCastHostStore\install
This install will ADOPT the preserved ProgramData from Phase 1 — the exact path that
failed with return 75 two days ago and was since fixed. Expectations:
- Installer exit 0; health 200 within 20 min; operator/ and / also 200.
- Commit soak/INSTALL-2.md: exit code, minutes-to-healthy, the three statuses, plus any
  installer-log lines mentioning the provision journal / adoption / stale (quote them —
  they prove which path ran).
- IF IT FAILS: this is a BETA-BLOCKER. Archive the installer log AND everything under
  C:\ProgramData\CivicCast\provision\ (PROVISION-RECOVERY.md must now exist — its
  presence/absence is itself evidence), commit soak/INSTALL-2-FAILED.md + the archive,
  and STOP. Do not wipe anything.

## Phase 4 — 8h soak, daytime, with the CORRECTED judge
Same machinery as last night (soak.ps1 + SYSTEM startup scheduled task; 10-min beats to
soak/heartbeat-2.log; push every 15 min with pull-rebase; ALERT file on 3 consecutive
failures; REBOOT-BEGIN marker then `shutdown /r /t 60` at T+4h; RECOVERY.md with
boot-to-healthy minutes). Before the reboot, re-prove REBOOT-READY exactly like last
night (task runs as SYSTEM at startup; one test push from the task context).

JUDGE FIX (last night's verdict script had a bug — it claimed a >25-min gap that did not
exist; its gap list also serialized as malformed nested arrays). Requirements for
soak/final-verdict-2.json at T+8h:
1. Parse every heartbeat timestamp as ISO-8601 UTC ([datetime]::Parse with
   InvariantCulture + AdjustToUniversal). SELF-TEST the parser on the first 3 log lines
   and refuse to run the verdict if any fails to parse.
2. Gap = seconds between consecutive parsed timestamps. The reboot window (REBOOT-BEGIN
   marker time → first post-reboot beat) is excluded.
3. Include in the JSON: max_nonreboot_gap_minutes (a number), nonreboot_gaps_over_25min
   (a FLAT array of {from,to,minutes} objects — use explicit @() array construction so
   PowerShell cannot flatten/nest it), pre/post unhealthy beat counts, recovery minutes,
   installer exit code.
4. verdict PASS iff: installer exit 0 AND unhealthy beats 0 (pre and post) AND recovery
   <= 10 min AND nonreboot_gaps_over_25min is empty.
5. VALIDATE the final JSON parses (ConvertFrom-Json round-trip) before committing. If
   the round-trip fails, fix and re-emit — never commit malformed JSON.

Timing target: Phase 3 install should complete this morning so T+8h lands this evening.
Honest failures over silent success, always. Every push is your ping to the coordinator.
