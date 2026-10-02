
## Coordinator stop - 2026-09-27 09:36 (-06:00): FAIL (changeover holes); stopped to install C7 (U56e)
Ran 07:06:20 -> ~09:36 (2h30m of 8h). Engine C6 = 77251b70.
- verify: 14/14 OK (captions, sync, playback, all three channels).
- loudness: 4 PASS, 1 BAD (#2 07:52 education INSTRUMENT_ERROR = VIDEO_HOLE seg000001333 from the 07:50 changeover hole, not a loudness miss).
- changeovers (evidence/changeover-holes.log): 10 CLEAN / 4 HOLE. Every HOLE = video 0.733 s + audio dropout
  (education 07:50 a0.068, public 08:15 a0.213, government 08:35 a0.137, government 09:14 a0.229).
  Relay 'Invalid timestamps' = 0 at every changeover (C5 rewind gone).
- Live clue: all 4 changeovers into an A/V-aligned incoming file (new-leg-first-buffer pts 0.700/0.401) were CLEAN;
  changeovers into a picture-late file (pts 0.000) were 4 HOLE / 6 CLEAN.
Verdict: FAIL on A/V continuity at changeovers. Stopped by the coordinator to install C7 (staging\U56e, b4c1fdff).
