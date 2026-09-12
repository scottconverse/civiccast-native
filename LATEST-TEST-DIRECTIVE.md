# soak8-e1acfe6 Latest Test Directive
Current: soak/DIRECTIVE-16.md
Branch: soak8-e1acfe6-directives
Updated: 2026-09-12T06:19Z - Directive15 preserved; Windows locked a worker log
during Get-FileHash. Retrieve the same bounded tails without hashing open files.
See Directive16. beta.5/beta.6 rejected; next candidate beta.7.
Updated: 2026-09-12T06:00Z - R3 measured ON phase failed on a real nonzero
GStreamer output-stall exit. Return missing worker/service logs read-only; do not
restart. See Directive15.
Updated: 2026-09-12T05:41Z - All three channels ON_AIR in returned logs. Attach
R3 measurement to existing playout and publish actual phase starts. See Directive14.
Updated: 2026-09-12T05:30Z - R2 startup timed out before measurement. Return
worker/service log evidence via read-only Directive13; preserve failed runs.
Updated: 2026-09-12T05:21Z - Return read-only R2 phase-start and progress evidence.
Leave the current attempt unchanged. See soak/DIRECTIVE-12.md.
Updated: 2026-09-12T05:02Z - R1 failed harness preflight before measurement.
Correct array handling/report archiving and launch isolated R2. See Directive11.
Updated: 2026-09-12T04:44Z - Physical job STARTED confirmed. Return a read-only
phase-start/progress snapshot; leave the running soak unchanged. See Directive10.
Updated: 2026-09-12T04:19Z - Exact candidate upgrade PASS and all three Gate A
lanes PASS. Launch the dedicated captions ON/OFF physical soak task once.
See soak/DIRECTIVE-9.md. Historical entries below are not new orders.
Updated: 2026-09-12T03:00Z - R4 readiness passed. Install exact fixed candidate
39e7ec3c in place on dedicated tester; preserve station data. See soak/DIRECTIVE-8.md.
Updated: 2026-09-12T02:49Z - Tester execution/reporting repaired. R4 replaces
failed readiness serialization with bounded scalar data. See soak/DIRECTIVE-7.md.
Updated: 2026-09-12T02:12Z - R3 returns the poll and R1/R2 error evidence directly,
without rerunning probes or changing the station. See soak/DIRECTIVE-6.md.
Updated: 2026-09-12T01:55Z - READINESS-R2 returns the readiness JSON explicitly;
the existing poller's .log files are ignored by Git. See soak/DIRECTIVE-5.md.
Updated: 2026-09-12T01:40Z - Fixed beta takeover. New read-only readiness order:
soak/autorun/AUTORUN-SEP11-FIXED-BETA-READINESS-R1.ps1. Candidate39e7ec3c/build34633364038.
The dated entries below are historical, not new install orders.
Updated: 2026-09-05T19:19Z (rev 23 - AUTORUN-9o read-only: is the caption-tap fix active? runtime-status.json, caption/stall/relaunch log lines, station profile, per-process CPU)
Updated: 2026-09-05T18:47Z (rev 22 - AUTORUN-3 verdict: 3-minute warm-up grace after soak-started; warm-up probes listed in warmup_probes_excluded, never deleted)
Updated: 2026-09-05T18:34Z (rev 21 - AUTORUN-9m: the channels are up but on FALLBACK_SLATE because soak #1 schedule ran out; reschedule 2h15 of the approved soak assets per channel + commit-to-air, start, wait ON_AIR, archive soak #1, start soak #2)
Updated: 2026-09-05T18:28Z (rev 20 - AUTORUN-9l: send start to the three channels (they only auto-resume with auto_start=true), wait 3/3 ON_AIR, then archive soak #1 and start soak #2 on kit 91caebc)
Updated: 2026-09-05T18:26Z (rev 19 - AUTORUN-9k read-only: why 0/3 channels ON_AIR after the 91caebc upgrade; egress dir, raw channel/schedule/playout API, installed version)
Updated: 2026-09-05T16:50Z (rev 18 - AUTORUN-9j: upgrade to kit 91caebc (PR #172 caption-tap fix) and restart the 2-hour soak; soak #1 probes archived)
Updated: 2026-09-05T10:35Z (rev 17 - AUTORUN-9i read-only CPU attribution: caption/summary/ollama log lines, per-process CPU sample, asset/caption job states)
Platform prompt: PROMPT-WINDOWS-CODEX.md (the one paste for a Codex-desktop tester on a Windows box)
Autoruns queued: soak/autorun/AUTORUN-5.ps1 (fetch the e5020746 kit into a fresh kit-<sha> folder, verify, install OVER the existing station), soak/autorun/AUTORUN-9e.ps1 (after AUTORUN-9 clean reinstall; first-admin + three channels + start, 2h15m schedule), soak/autorun/AUTORUN-3.ps1 (TSDuck egress proof, engine-per-channel, relaunch tracking, worker CPU/RSS, 30-min rollups, T+2h verdict)

Updated: 2026-09-03T21:25Z (rev 4 - mission on hold; soak runs on the coordinator box)

Updated: 2026-09-03T20:15Z (rev 2 -- kit re-pointed to the #154 candidate b78b9c7dfa4d66b442172759439553381ec8be44: GStreamer decoder-rank fix; same mission id, same tasks)
