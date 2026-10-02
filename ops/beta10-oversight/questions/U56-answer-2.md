# U56 round 3 - the fix is installed (C4) and the live hole SHRANK but did NOT close

C4 = your `staging\U56` (engine.py 41b4c8e8 -> 7509ed0a) installed 2026-09-27 00:04:05, service restarted 00:04:43
(pid 29168). Live hash verified = 7509ed0a.

## First two live seamless changeovers after C4 (coordinator, OBSERVED, ffprobe packet pts on plain copies of the
keeper store; per-segment max intra-segment step)
```
government commit ~00:35:23  logged rebase-reference ends=[video=1799.500,audio=1800.085] switch_running_time=1800.085
   seg000000898.ts 00:35:22  v=0.033  a=0.021
   seg000000899.ts 00:35:24  v=0.403 @+0.833   a=0.021      <-- HOLE 0.403 s (pre-fix shape would be ~0.585)
   seg000000900.ts 00:35:26  v=0.033  a=0.021
public     commit ~00:35:28  logged ends=[video=1799.567,audio=1800.128] switch_running_time=1800.128
   seg000000899.ts 00:35:25  v=0.033
   seg000000900.ts 00:35:27  v=0.136 @+0.000   a=0.021      <-- HOLE 0.136 s (~4 frames; pre-fix ~0.561)
   seg000000901.ts 00:35:29  v=0.033
```
Copies: `%TEMP%\cohw-full-public-*` and `%TEMP%\cohw-full-government-*` (the whole keeper store at ~00:37:40; copy them
into `fixtures\U56-live\` NOW before %TEMP% cleanup). Worker logs: `C:\ProgramData\CivicCast\data\egress\<ch>\logs\gst-worker.stderr.log`
(read with a shared read; the reload_id for these is the latest `rebase-reference` before 00:36).
Both programmes here were 1800 s filler/programme items; the plan boundary was at running time ~1800.

Your round-2 doubt was right: the value bound helps only while the selector still reads the old pad, and on the
live station part of the retiring tail is still lost (0.182 s of 0.585 recovered on government, 0.425 of 0.561
on public). Your synthetic A/B closed 0.744 fully, so the harness does not reproduce the live timing.

## Work
1. From the two live workers' stderr around these commits, establish exactly which retiring-video buffers were
   dropped and by what (the fence, the selector's `active-pad` flip, the drain gate, the old-leg detach). Quote the
   diagnostic lines. The number to explain: 0.403 s lost on government, 0.136 s on public.
2. Make the harness reproduce a PARTIAL hole like the live one (e.g. real-time pacing, queue depths, the
   production `pipeline_running_time`, two channels at once under load - find what differs), RED on C4 bytes
   (7509ed0a), then fix so the retiring video is aired up to the switch point (still no synthetic frames), GREEN.
   `start /low`, <= 10 min per run.
3. Stage `staging\U56b\` from LIVE bytes (base 7509ed0a), installed-base.sha256 in the usual format. Report Part
   III, receipt last. Do not touch the station.

## Addendum 01:06 (coordinator, OBSERVED) - fourth live changeover on C4: NO improvement at all
```
government commit 01:05:24, reload_id=2, ends=[video=3598.985,audio=3599.701]  (disparity 0.716 s)
   seg000001798.ts (mtime 01:05:23)  video max step 0.732 s @+1.367   audio 0.021
```
Copies: `fixtures\U56-live\government-0105\seg0000017{96..99}.ts, seg00000180{0,1}.ts`.
And education commit 00:38:04 (ends=[video=1799.433,audio=1800.000], disparity 0.567) was CLEAN (max 0.033).
So on C4 live: 0.567 -> 0.000, 0.561 -> 0.136, 0.585 -> 0.403, 0.716 -> 0.732. The value-bounded fence is a race
that sometimes wins. Find the deterministic cause.
public commit 01:05:29: seg000001799.ts video max step 0.740 s @+1.067, audio 0.021 (copies fixtures\U56-live\public-0105\).
education commit 01:08:03: seg000001799.ts video max step 0.733 s @+0.967, audio 0.021 (fixtures\U56-live\education-0108\).
