## Coordinator verdict - 8h-post-c9, 2026-09-27 12:44:50 -> 20:45:03 (-06:00): FAIL (1 real defect, found + fix staged)

Engine C9 = engine.py 8a3722c9 (+ graph 309ffac7, pipeline e3d7767a, preparer aafb0b5d). Service pid 5044 for the whole
8 h 0 m (no restart, no crash, no slate). Rung tool verdict: FAIL, failures 1 (loudness #12, see below).

| Check | Result |
|---|---|
| Service up / pid unchanged (30 s samples) | PASS, 8 h, pid 5044 throughout |
| Channels live, A/V skew in live samples | PASS, all samples ok, max a-v 0.020 s |
| Verify (captions embedded + decode-back, timing, playback) | 45/45 OK |
| Loudness 240 s windows, -16 +/- 1 LUFS | 15/16 PASS; #12 government INSTRUMENT_ERROR (playlist referenced an already-deleted segment, seg000010168, first poll); government retry 18:28:59 PASS -16.1 LUFS / TP -1.2 (loudness-12-government-retry.json). Instrument miss, not an audio failure. |
| Seamless changeovers (keeper scan of every commit) | 46 CLEAN / 1 HOLE; worker commit counts since the C9 start: education 16, government 15, public 16 = 47, all scored |
| Relay rewinds ('Invalid timestamps') | 0 at every changeover |
| Caption pauses in window | 0 |

**The one real defect:** government commit 19:15:49 (reload_id=13): VIDEO HOLE 4.148 s (held last frame), audio clean
(0.043 s max step), relay 0. Worker: `switch-at-shorter-leg video_end=23466.200 audio_end=23471.381 spread=5.181 >
bound 2.000 -> trimmed=none` (C7 fail-open by design). Retiring leg = 2 prepared pieces (18:28-18:32, 253 s); each
prepared piece is audio-long by its video keyframe lag and the engine chains a leg's pieces per stream, so the lags sum
(U59). Fixture: fixtures\C9-government-1915. Counter-cases: education 2-piece leg 19:42 spread 0.801 and public 2-piece
leg 20:22 spread 0.663, both CLEAN (piece 2 keyframe-aligned).

**Fix:** U59 (reports\U59.md, second section): preparer pins each piece's audio to its own video window. Coordinator
re-run evidence\coord-u59-rerun-2015.txt: leg spread +2.080 (bound exceeded) -> -0.075. Staged staging\U59-install
(preparer.py aafb0b5d -> 7f2fcef6). Installing as C10 after this rung; new 8 h rung on C10 required.

**Also listed (not beta-blocking):** playlist-references-deleted-segment race (2nd occurrence; POST-BETA10-BACKLOG);
long first-time preparations 208-342 s against a 690 s lead (all in time; worst 50 % of lead).
