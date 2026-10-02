# U59 round 8 - all three lag cuts sag at the SAME place in the SAME recording

Round 7 ACCEPTED (coordinator 08:5x). Spot-checked: the 06:18:53 preparer window `in=1799.4s dur=1800s`; education
stdout L3464; education's leg start 04:06:37.812 on Senior Citizens June. No U59f, agreed.

## What your own numbers show (coordinator)
All three `video stream running Xs behind audio` cuts were on "Senior Citizens Advisory Board - June 2026.mp4",
and at the same source position:
  public     C11 06:24  SCJ piece aired 1588.0 s from in=0      -> cut at SCJ source ~1588 s; sag seen ~15 s before
  government C9  19:15  SCJ piece aired 1577.9 s from in=0      -> cut at SCJ source ~1578 s; sag seen ~21 s before
  education  pre-C 04:32 SCJ aired 1558.3 s from in=23.7412     -> cut at SCJ source ~1582 s
So the sag starts somewhere in SCJ source ~1555..1590 s every time, on three channels, three installs, and two plan
shapes (2-piece and 1-piece). Round 5 scanned the source + conform for packet gaps / <29.5 pkt/s there and found
them clean - packet COUNT is not the question. Round 6's offline replay ran clean - one channel, no concurrent load.
Hypothesis: that stretch is expensive to process in real time (decode and/or encode cost per frame), and with three
channels plus captions running the worker's video path falls below 30 fps there.

## Work (C13 8 h rung live until ~16:29; no station action; single low-priority process at a time, <= 10 min per
## run, never two heavy ffmpeg/gst jobs at once; C: ~24 GB free - no large scratch, delete yours when done)
1. Name the worker's video path on the live bytes (C13 = engine 931390b1, graph 309ffac7, pipeline e3d7767a): which
   decoder (and its threads), which scaler/rate elements, which encoder with which preset/threads/bitrate, what
   is shared between the three channel workers (GPU encoder sessions? CPU cores?). Cite lines.
2. Characterise SCJ source ~1500..1650 s vs a control stretch (e.g. 600..750 s) in BOTH the upload and the prepared
   plan the preparer emits for it: per-second video bytes, frame type mix, and a decode-only and a
   decode+live-encode speed test (the live encoder settings from item 1), each as a single low-priority process,
   reported as a real-time factor per 10 s window. Is the 1555..1590 window measurably costlier?
3. Contention: from retained logs, what else was running at each of the three cut minutes (preparations in
   progress, caption tap "behind" lines, other channels' changeovers)? One table.
4. Predict from the live schedule / automation state when SCJ source ~1550..1600 will next air on any channel, so
   the coordinator can watch it live with the U59e detector now on air.
5. If items 2-3 confirm a cost spike: propose the smallest fix (for example an encoder preset/threads change or a
   preparer-side re-encode of the offending stretch) with RED/GREEN where it can be tested, staged as
   staging\U59f on top of the C13 engine 931390b1 (NOT fe5a5306). If they do not confirm it, say what the three
   events share that the control stretch does not.
Report "Round 8" in reports\U59.md, plain English first, receipt last.
