# U37 - coordinator note: the 15:23 shape REPEATED at 15:55, deterministically

Evidence: `evidence\public-freeze-1555\` (stderr last commit at line ~81211; control-plane 15:30-15:59).
- After the 15:24 escalation the relaunched worker started "City Council Regular Session - August 11, 2026.mp4"
  from prepared `public\prepared\9a975f75dd84\segment-0001.ts` (1.2 GB, one 30-minute segment).
- ~30 min later (15:55) a deferred reload committed with EXACTLY the same numbers as 15:23:
  `rebase-reference reload_id=1 mode=deferred ends=[video=1799.267,audio=1799.967] switch_running_time=1799.967`.
- This time the post-commit mux-in counts are STEADY and healthy (`video=+150 audio=+235` per 5 s) - not bursty -
  yet the mux src total still advances only ~+233..+235 per 5 s (audio-only) and the HLS window froze; U30
  escalation restarted the worker at 15:56:44; on air 15:58:42.
- So: first leg = a 30-min prepared segment whose VIDEO ends 0.700 s before its AUDIO; switch at the audio end;
  every time, the mux stops emitting video although video buffers keep entering it. This is reproducible from
  that exact prepared file (`...\prepared\9a975f75dd84\segment-0001.ts` - copy it to your scratch; do not modify
  the live file) followed by any second program: that is your red case, no synthetic shape needed. Measure the
  video buffers' PTS/DTS/running time at the mux sink after the switch vs audio's, and what mpegtsmux does with
  them (GST_DEBUG=mpegtsmux:6,aggregator:6 for the 60 s around the switch).

## Addendum 16:40 (from U36's measurement)
The relaunches are NOT replaying: in-points progress with the schedule (1372.5 / 1978.5 / 3321.5 / 3931.5 s).
So the freeze happens at EVERY 30-minute prepared-segment boundary of this long asset (City Council Aug 11,
15,949 s): each relaunch prepares one trimmed 1800 s segment from the schedule position, and every such segment
ends with video 0.700 s short of audio; the deferred switch to the next segment freezes the video in the mux.
Check the preparer's segment cutting too (why does a trimmed 1800 s segment's video end 0.7 s before its audio -
keyframe/GOP alignment, `-ss` placement, `-t` applied per stream?). A fix in either place (the prepared segment's
streams end together, or the engine/mux tolerates a 0.7 s A/V end offset at the switch) ends the cycle; the engine
must tolerate it regardless, since other media will have the same shape.

## Addendum 17:42: a counter-example - the 17:34 boundary did NOT freeze
Public's 17:34 deferred switch (reload 371fcaa3, accepted 17:26:26) committed and output continued normally.
Its rebase line: CTRL reload diagnostic: rebase-reference reload_id=1 mode=deferred streams=2 fallback=no ends=[video=1799.233,audio=1799.967] pipeline_running_time=none switch_running_time=1799.967
Compare with the freezing ones (ends video=1799.267 audio=1799.967). Copy the current
/c/ProgramData/CivicCast/data/egress/public/logs/gst-worker.stderr.log now if you need it (it rotates).
Saved copy: evidence\public-nofreeze-1734\ . Nearly identical ends (video 1799.233 vs 1799.267) but no freeze: the freeze is a race, not a deterministic property of the A/V end offset - 4 of the last 5 such boundaries froze.
