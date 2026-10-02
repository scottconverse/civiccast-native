# U53 round 3 - C2 installed; restart-recovery "slate first" is STATE-ONLY: all three channels DARK

C2 (your staging\U53, five files) was installed 21:26:21; service restarted 21:26:59 (pid 26380 -> 36340).
Live hashes verified = your candidates (preparer aafb0b5d, models e7e774a6, automation df12d148,
source_plan 82dcccbf, daemon e10a5663). Coordinator RED re-run of your tests on pre-fix code: 1+5 failed. Audit PASS.

## What the station did (control_plane-app.log, OBSERVED)
```
21:27:19,099 WARNING daemon: channel education: cleared stale persisted ON_AIR claim (dead encoder pid 30864) and atomically queued restart-recovery start restart-recovery-ON_AIR-...
21:27:19,169 hls_relay: HLS relay start: cleared 9 stale file(s) ... education
21:27:19,184 daemon: channel education: egress state -> FALLBACK_SLATE (source=-, pid=-, last_error=Preparing the scheduled program; airing the fallback slate so the channel stays up while it conforms.)
21:27:19,190 daemon: channel education: start source preparation queued
21:27:20,936 preparer: Loudness sample for 'slate-fill-e7a2ae37c029eac606a32824.ts' measured at the silence floor (-70.0 LUFS) at 1441.0s in; resampling at 2521.8s in before treating the asset as silent.
(same for government 21:27:19/22, public 21:27:26/30)
```
Then NOTHING from egress for 3+ minutes. `live-hls\{public,government,education}\` are EMPTY (no playlist, no
segments). TS relays and HLS relays are up. State says FALLBACK_SLATE with **pid=-**: no slate encoder was
launched. The slate-fill .ts exists (54,674,912 B, written 21:27 for government/public). So the addendum
declares the slate but nothing airs it; the channel is dark exactly as before (C1 restart: government dark 6m55s).

Your D test proved the filler-rollover chain on a real worker; the Addendum/STARTING path (restart-recovery
slate-first) was hermetic only. This is the gap.

## Work (RED-first)
1. From the code at the installed bytes, find why the restart-recovery slate-first start sets FALLBACK_SLATE but
   launches no encoder (pid=-). Candidates: slate start waits on the same preparation it is meant to cover; the
   slate-fill goes through the preparer's loudness probe/conform path and blocks; the relay/worker start is
   gated behind the program's prep; the slate is only planned, never started. Quote the lines.
2. RED: a REAL-WORKER test (reuse the U47/U53 harness) of a restart-recovery start with a program that takes
   >= 30 s to prepare: assert a playlist with slate segments appears within 15 s of the recovery start. It must
   fail on the installed bytes. Then fix; GREEN the same test. <= 10 min wall clock, `start /low`, on copies.
3. Also answer: the slate-fill is loudness-sampled at 1441 s and 2521.8 s in - how long is the slate fill, why is
   a silent slate going through the loudness probe at all, and does that probe sit on the slate's start path?
4. Stage `staging\U53b\` from the LIVE bytes (the C2 hashes above are now the bases). Report `reports\U53.md`
   Part III, receipt at the end. Targeted tests only. The station is live - do not touch it.

## Addendum 21:31 (coordinator, OBSERVED after you were resumed)
The slate encoder finally launched ~3 min after the recovery start, then the program's prep (a cache hit) took 3.5 s:
```
21:30:21,596 daemon: channel education: egress state -> FALLBACK_SLATE (source=CivicCast slate, pid=-, ...)
21:30:25,025 daemon: channel government: egress state -> FALLBACK_SLATE (source=CivicCast slate, pid=6776, last_error=-)
21:30:25,545 daemon: Content-reload source preparation for government took 3.5s for 1 segment(s)
21:30:25,552 WARNING daemon: channel government: terminating the worker deliberately for a reload (reload out of fallback slate ...)
```
So: ~3 min of dark before the slate, for a program that needed 3.5 s. Something between 21:27:31 and 21:30:21 held
the slate start (nothing was logged in that window). Find it - the slate-fill loudness probe is the first suspect.
The RED test must show the slate playlist appears within 15 s of the recovery start.

## Addendum 21:39 - item 3 is inert on the station (OBSERVED)
```
21:36:55,262 automation: Channel automation computed the rollover lead for education: lead=690s (no asset duration available for the boundary; the timeout-derived floor stands).
```
The first live rollover after C2 had no asset duration, so the adaptive lead never applied. Trace why the caller
passes None for a real scheduled programme (your II.6 said this was untraced), fix it RED-first, include in U53b.
