# U56 round 2 - coordinator answer (engineering call, final)

## Audit of round 1
- Your `questions\U56.md` "CODER RESPONSE" says you could NOT reproduce (public 23:32:31 / government 23:34:15:
  "0 ticks of video hole... all segments exactly 60 frames"). Your `reports\U56.md`, written 31 s later, says both
  have a ~0.6 s hole. These contradict. I re-measured your copies myself (ffprobe packet pts on
  `%TEMP%\u56\hot\...`): public seg3655 = 35 video packets, video max gap 0.600 s at +0.833 s, audio max gap
  0.021 s; government seg3711 = video max gap 0.581 s, audio 0.021 s; neighbours 60 packets / 0.033 s.
  **The report is right; the question file's response is superseded.** Say in Part II which instrument produced
  the false "0 ticks" and why, so it is not reused.
- Diagnosis accepted: retiring-leg fence is instant-bounded and drops the video between video-end and the audio
  switch point. None of options A-D in the question file: you already chose the right fix (value-bounded fence).

## Round 2 work
1. **Real-worker proof (required before I install anything that changes what airs).** A real GStreamer worker
   test of a seamless reload between two synthetic programmes whose video ends ~0.6 s before audio (reproduce the
   live `ends=[video=X,audio=X+0.6]` shape). Assert: across the boundary, emitted video packet max gap <= 1 frame
   (0.034 s at 30 fps) and audio max gap <= 0.03 s, measured by ffprobe on the emitted segments. RED on a copy of
   the INSTALLED package (must show the ~0.6 s hole), GREEN on the installed copy + your engine.py overlay.
   `start /low`, <= 10 min each. If the fix does not close the hole (your 3.4 doubt: the selector flips
   microseconds later), say so with the numbers and find what does - still no synthetic frames (option C is out).
2. **Stage from LIVE bytes**: `staging\U56\candidate\civiccast\egress\gst\engine.py` built on the installed
   engine.py (read its sha256 first and record it in `staging\U56\installed-base.sha256` as
   `<sha> *civiccast/egress/gst/engine.py`). Your worktree is on `beta10-int` @ 521438fe, which is NOT the
   installed lineage - carry the change onto the live file, do not copy the worktree file.
3. Commit your worktree change + tests (DCO `Signed-off-by: Scott Converse <scott@civiccast.dev>`), no push.
4. Report Part II in `reports\U56.md`, receipt at the end. The station is live; do not touch it.
