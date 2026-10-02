# U59 round 6 - reproduce the 2-piece leg offline and find where its video falls short

Round 5 ACCEPTED (coordinator 07:12, re-ran your RED 11 failed/1 passed on fe5a5306 and GREEN 22 passed on
e56fa96b in a scratch copy). The plan-shape finding is the strongest lead we have: both holes were on a
2-segment plan = City Council Sep 8 tail (595 / 592 s) + Senior Citizens June from 0 for ~1580 s, a ~2170-2180 s
leg, ending on a mid-file cut. U59e stays staged; it will go in with the next install batch.
Install-note fix needed (do it): staging\U59e\installed-base.sha256 rows must be `<hash> *civiccast/egress/gst/<file>`
(the install script verifies by that relative path); yours are `*engine.py`.

## Work (no station action; C12 8 h rung live until ~14:41; tests small, low priority, <= 10 min per run,
## never two heavy ffmpeg/gst jobs at once; a full 36-min leg replay may run longer only if it is a single
## low-priority process and you say so in the report)
1. Why is piece 2 ~1580 s and not 1800 s? The 06:16:36 rollover line expected the live plan to end at 06:28:05
   but it switched at 06:24:14 (231 s early); C9's 19:01:55 line was ~96 s LATE. Read the automation/source-plan
   code that builds a 2-segment plan (tail + head) and say how piece 2's duration is chosen, what the automation
   believes the plan length is, and why they disagree. Cite lines.
2. Reproduce: build the same 2-segment plan offline with the LIVE preparer recipe (Council Sep 8 last 595 s +
   Senior Citizens June 0..1585 s) and run it through your run-leg harness on the LIVE engine (C12 = fe5a5306).
   Does the leg's video end short of its audio by >2 s, with the ingress rate sagging in the last ~15-20 s? Then
   control: the same run with a 1-segment 1800 s plan of Senior Citizens June 0..1800. If you can shorten the
   repro (e.g. a smaller tail, or starting the harness near the end), prove the short version shows the same
   shortfall before relying on it.
3. If it reproduces: find the element where the video falls behind (per-element buffer counts / timestamps at
   the piece-2 boundary and at the end), propose the smallest fix with RED/GREEN in tests, stage staging\U59f
   on top of U59e. If it does not reproduce, say what differs between harness and station and what to measure
   next.
4. From the live schedule/automation state, predict when the station will next build a 2-segment plan of this
   shape on any channel (so we can watch it live). Read only.
Report "Round 6" in reports\U59.md, plain English first, receipt last.
