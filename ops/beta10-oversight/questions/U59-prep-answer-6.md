# U59 round 7 - the forced switch: census, content lost, and why the guard fired

Round 6 ACCEPTED (coordinator 08:1x). The discriminator you found changes the picture: the 06:24 leg did not
reach EOS; the engine FORCED the switch ("video stream running 2.3s behind audio after replacement preroll;
forcing switch"), 212 s before the plan's declared end. Coordinator census of the live stdout logs (08:1x):

  education  3 forcing lines: 2x "output stalled after replacement preroll", 1x "video stream running 3.4s behind audio ..."
  government 3 forcing lines: 2x "output stalled ...",                    1x "video stream running 4.4s behind audio ..."
  public     5 forcing lines: 4x "output stalled ...",                    1x "video stream running 2.3s behind audio ..."

The government 4.4 s one is presumably C9 19:15 and public 2.3 s is C11 06:24. The EDUCATION 3.4 s one has not
been identified by the coordinator - it may be a third occurrence nobody scored.

## Work (read only + tests; C12 8 h rung live until ~14:41; no station action; C: has only ~19 GB free, so no
## new large scratch - delete your own round-6-and-later scratch when done; leave rounds 2-3's alone)
1. Census with wall-clock times: for every "forcing switch" line in the three stdout logs, pin it to its
   stderr running time and to control_plane-app.log wall-clock time (and to which install C-number was live).
   For each: reason, channel, the outgoing plan's shape (pieces, declared seconds), how many seconds of the
   declared plan had aired when it fired, and whether the output shows a hole. Identify the education 3.4 s event.
2. Content lost: at 06:24 did the viewer lose ~212 s of Senior Citizens June (i.e. did the NEXT plan start at
   source 1800 s, skipping 1588..1800)? Prove from the next plan's inpoint (control-plane / prepared plan /
   worker stderr). Same question for the C9 19:15 and the education event.
3. The guard: read the engine code that emits "video stream running Xs behind audio after replacement preroll;
   forcing switch" and "output stalled after replacement preroll". What does it measure, from when, what
   threshold, and why is its remedy to cut the outgoing leg immediately rather than wait for EOS or trim?
   Explain why it fired ~4 min after the replacement prerolled at 06:20:20. Is the "video behind audio"
   measured on the outgoing leg's chain-in (the ingress sag) or something the replacement's preroll causes?
4. If the guard's early cut is what turns a small A/V lag into lost program + a picture hole, propose the
   smallest safe change (e.g. keep the outgoing leg to its natural EOS and trim/hold at the switch), RED/GREEN
   in tests, stage staging\U59f on top of U59e. If the sag itself is the cause and the guard is right, say so
   and say what next occurrence data the U59e lag detector will give us.
Report "Round 7" in reports\U59.md, plain English first, receipt last.
