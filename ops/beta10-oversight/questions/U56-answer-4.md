# U56 round 5 - C5 (U56c) is live; it fired correctly and the hole did NOT close: it moved to the INCOMING leg

C5 = staging\U56c (engine.py f1883d04) installed 2026-09-27 03:45:18, service pid 37860, live hash verified.

## First live changeover on C5 (coordinator, OBSERVED)
Public, commit 04:16:39. Worker stderr, verbatim order:
```
outgoing EOS observed stream=video (1/2 stream(s))
rebase-reference reload_id=1 ... ends=[video=1798.400,audio=1799.147] switch_running_time=1798.400
switch-at-shorter-leg reload_id=1 video_end=1798.400 audio_end=1799.147 trimmed=audio:0.747 spread=0.747 bound=2.000 bound_exceeded=no switch_running_time=1798.400
stage=rebase-drain-wait pads=sink_66=5 ; outgoing EOS observed stream=audio (2/2) ; stage=rebase-drain-drained waited=1.157s
stage=switching-selector ; holds-released ; selector-handoff-confirmed
new-leg-first-buffer stream=audio applied_offset=1798.400 pts=0.220 running_time=0.000
new-leg-selector-first-buffer stream=audio pad=sink_2 applied_offset=1798.400 pts=0.220 running_time=1798.400
new-leg-first-buffer stream=video applied_offset=1798.400 pts=0.220 running_time=0.000
new-leg-selector-first-buffer stream=video pad=sink_2 applied_offset=1798.400 pts=0.220 running_time=1798.400
stage=committed elements=52
```
No QoS/late/drop/WARN lines in that span.

Emitted video packet PTS (plain copies, `fixtures\C5-public-0416\seg000000896..902.ts`; emitted PTS = running time + ~1.367):
```
seg898: ... 1799.333322 1799.366656   (continuous)
seg899: 1799.400000 ... 1799.733322 1799.766656 | 1800.567989 1800.568000 1800.601311 ...  <- 0.801 s gap
        audio in seg899: 1799.416000 .. 2125.322, max step 0.021 (continuous)
```
- 1799.766656 emitted is running 1798.400. The OUTGOING video now airs fully to the switch point. C5's selection
  and fence worked as designed.
- The missing 0.801 s is the INCOMING leg's first ~24 frames (running 1798.400 -> ~1799.2). The selector log says
  those frames passed the selector at running_time=1798.400. So they are lost DOWNSTREAM of the input-selector.
  The incoming audio is not lost.
- Two emitted frames 11 us apart at the resume (1800.567989 / 1800.568000). That looks like a videorate
  closing-duplicate or a re-timestamp at the resume point.
- Note: the new video resumes at running ~1799.2, about the OLD audio end (1799.147). This may be a coincidence
  or a clue: something downstream still tracks the retiring audio's position, or the lateness from the 1.157 s
  wall-clock drain.

So the C4-era reading ("the hole is the outgoing video-vs-audio deficit") was at least incomplete. C4 holes equalled
audio_end - video_end, and so does this one's resume point. The hole appears to be "no video is aired between the
video end and the old audio end", whichever leg's video that is.

## Work
1. From the installed engine, list every element DOWNSTREAM of the video input-selector to the mux (videorate,
   caption injector / cc combiner, converters, encoder, queues, clocksync, mux). Quote the construction lines.
   For each one, say whether it can drop or hold a buffer whose running time is below its current position
   or segment position. Find which element's position sat at ~1799.147 (the retiring audio end) when the new
   video arrived at 1798.400.
2. Reproduce on a real worker. out_shortv.ts on C5 bytes aired clean in your harness, so find what differs
   from live: live-source pacing; the caption injector with real cues; the output chain the live worker builds
   (`--caps production` vs live caps); the 1.157 s drain happening in wall-clock time on a live clock. RED on
   C5 bytes (f1883d04), then fix, then GREEN: video maxgap <= 0.034 s and audio <= 0.050 s across the join,
   2/2, U57 packet-PTS method, no synthetic frames.
3. Stage `staging\U56d\` from LIVE bytes (base f1883d04), `installed-base.sha256`. Report Part V, plain-English
   summary first, receipt last. No station action. An 8 h rung is live (C5); keep load small, `start /low`.

## Addendum 04:21 - second C5 changeover, same shape
government commit 04:19:49: switch-at-shorter-leg video_end=1799.433 audio_end=1800.000 trimmed=audio:0.567 ->
HOLE 0.621 s in seg000000899.ts (audio max 0.021). Copies: fixtures\C5-government-0419\seg000000897..901.ts.
Emitted video gap 1800.800000 -> 1801.421333. Minus the ~1.367 emitted offset, that is running 1799.433 (the switch
= video end) -> ~1800.054 (about the OLD AUDIO END, 1800.000). Same pattern as public: no video airs from the
switch point until the retiring audio's end, even though that audio was trimmed. Something downstream still waits
for, or holds video behind, the retiring audio position.

## Addendum 05:16 - C5 is NOT deterministic on live
public commit 05:15:01: switch-at-shorter-leg trimmed=audio:0.577 -> CLEAN (video max 0.033). Same fix, same spread
class as the HOLEs (public 04:46 trimmed 0.576 -> HOLE 0.631). C5 live tally: 1 clean / 5 HOLE. It is a race. Your
reproduction must explain why this one was clean. Also: your RED printed NO switch-at-shorter-leg line, but live
prints it at every changeover, so your RED path is not the live path. Reconcile both before proposing a fix.
