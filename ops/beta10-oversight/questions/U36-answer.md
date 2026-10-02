# U36 - coordinator answer: good correction. Keep the cap; fix the clock-drift sliver on BOTH the rollover and the relaunch path with the tail floor.

Your measurement stands: the rows are not long; the ~3.6 s is schedule clock vs the leg's real start. The 14:51
case is a different defect (reload aborted by a decodebin error and discarded without retry) - that goes to a
separate unit (U37), not you.

## One thing your report leaves open, and it is the first exit
At 14:17 the FIRST worker exit happened before any relaunch: reload_id=5 (the 14:06:54 reload built by the
14:06:50 rollover) committed, and its NEW leg delivered ~1.6 s (`mux-in 1.6s: video=+24 audio=+37`) and then EOS.
So reload 5's own new leg was a sliver. Coordinator reading (confirm or refute with the evidence, e.g. the reload's
plan / `playout-graph.json` history / the rollover's resolved segment list in the log): the 14:06:50 rollover
resolved the item AT ITS HORIZON (14:17:54) with the drifted schedule clock, which still placed the July 23 program
there with ~3 s left, so the reload's single segment was "July 23 from ~664 s" = the last seconds of the program
that was about to end. That is the same clock-drift bookkeeping as the relaunch, on the rollover path.

## Decisions (engineering; mine)
1. **Q1: keep `b0f2e49c`** as a class-level guard (harmless, tested).
2. **Q3: yes.** Apply the 30 s schedule tail floor to (i) horizon-bound rollover resolution and (ii) the relaunch
   path: when the item resolved for a new leg has less than `_SCHEDULE_TAIL_FLOOR_SECONDS` of media remaining, the
   leg starts the NEXT program instead (slate only if there is no next program). Say exactly where it applies and
   prove it cannot skip a program that genuinely has more than the floor left.
3. **Q2: (a) as part of 2(ii)**; (b) (make the rotation's start times agree with the leg's real start) is recorded
   as a follow-up, not in this unit. Report how large the drift gets over 8 h (does it accumulate per boundary, or
   is it bounded?), from the logs; if it accumulates, say so plainly, because then (b) is needed before the 8 h
   rung.
4. **Real-worker end-to-end:** U34 ran real GStreamer pipelines in its worktree; read `reports\U34.md` section 7.4
   for how it set `CIVICAST_GSTREAMER_RUNTIME_ROOT` (the installed runtime under
   `C:\Program Files\CivicCast (Native)`) and do the same for one program->program boundary with the sliver case,
   red at `1fdeaae6`, green at HEAD. At most 4 GStreamer pipelines.
5. Gates as briefed (check no other full suite is running first). Small commits, never amend. No staging.
Append to `reports\U36.md`.

## Addendum (coordinator, after reading more evidence): 14:51 is probably the SAME defect, plus a missing retry
- Education ALSO exited at 14:51:22,209 (evidence `evidence\education-exit1-1451\`): slate at 14:51:15, a
  scheduled-program reload prepared in 2.2 s for 1 segment, then `CTRL reload aborted: new program errored before
  commit (source=decodebin14)` with debug `gst_decode_bin_expose (): ... all streams without buffers`, exit 1.
- "all streams without buffers" is what a 0-byte / past-EOF segment produces - and your own section 1.4 measured
  that a past-EOF copy-out is 0-byte. public's aborted 14:44 reload (b770230c, 1 segment, 2.3 s) is likely the
  same: a drifted-clock sliver whose in-point is at or past the media end. The worker stdout also shows many
  earlier `reload aborted ... filesrc ... Internal data stream error` lines on public.
So, in this unit:
6. For public b770230c (14:44) and education's 14:51 reload, identify the prepared segment (source, in-point,
   duration, file size) from the logs / reload-status / prepared plan dirs if they still exist. If they are
   past-EOF or sub-floor slivers, it is the same defect and decision 2 covers it; say so. Count the historical
   `reload aborted` lines by cause in both channels' stdout logs.
7. **Never leave a channel with nothing prepared at a boundary.** When a reload is discarded for `aborted:error`,
   the daemon must re-resolve (with the tail floor) and retry the reload before the horizon, bounded (e.g. 2
   retries); if it still cannot land one, it switches to the slate AT the boundary instead of letting the outgoing
   leg run out into a stall exit. Tests red then green for both (retry lands; retries exhausted -> slate, no exit).
   Also: a prepared segment of 0 bytes or with no decodable stream must be rejected at preparation time (before it
   reaches the worker) with a WARNING naming the source and in-point.
