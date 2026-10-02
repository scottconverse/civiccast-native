# C15 8 h rung (8h-post-c15) - raw FAIL (4); adjudicated: 0 station failures, 3 items pending owner rulings

Rung `8h-post-c15`, 2026-09-29 02:59:55 -> 11:00:18 (full 480 min). Build C15 = C14 + U63 automation.py
(sha256 50dc48c8...). Service pid 37584 for the entire rung: no restart, no crash.

rung.log END line: `verdict FAIL verifies 44 loudness 16 failures 4`.

## The four raw failures, one by one
| # | What | Adjudication | Owner action |
|---|---|---|---|
| verify #1 03:00:10 | government freshness FAIL, public checks None | COORDINATOR SLIP: rung started 28 s after the C15 install restart (service 02:59:27), before all channels were on air (slip #4, logged). Startup artefact, not a steady-state station fault. | Accept as startup artefact, or require a re-run |
| verify #22 06:51:37 | public caption_decode_back FAIL | Council recess, no speech: last cues "a five minute break", resume after. Evidence public-active-vtt-recess-0651.vtt | Ruling on no-speech breaks (recommend: list) |
| verify #29 08:10:00 | public caption_decode_back FAIL | Council recess, no speech: cues stop 180:33:06 ("five minutes"), resume 180:38:11 "Break is over". Evidence public-vtt-recess-0805.vtt | Same ruling |
| loudness #9 07:18:54 | education -21.9 LUFS | EXCLUDED_QUIET_SOURCE after re-adjudication at the correct source position (7121 s): 171/197 s unreachable, need 60, range 141-171. The rung adjudicator's log-derived position (3226.3 s) was wrong (ignored part offsets). Source -44.7 LUFS vs g_max 18 dB; on-air -26 LUFS exactly as the clamp predicts. Files: INCIDENT-0718-LOUDNESS.md, loudness-09.readjudicated-pos7121.json | None - owner's settled quiet-window rule (2026-09-26) lists it |

If the owner rules no-speech breaks are listed and accepts verify #1 as a startup artefact, the rung is a PASS with
0 station failures.

## Gate totals
| Gate | Result |
|---|---|
| Captions / timing / playback verify | 44 run: 41 OK, 1 startup artefact, 2 council recesses |
| Loudness 240 s windows | 16 run: 15 PASS, 1 EXCLUDED_QUIET_SOURCE (#9) |
| Changeovers | 50 / 50 CLEAN (every one scored live; picture <= 1 frame, sound <= 0.040 s) |
| Slate / filler on air | none after the ~20 s startup slate at 03:00 |
| Aborted first attempts | 2 (education 04:22, 04:54; daemon-side short tail; retry landed, no on-air effect) |
| Station restarts / crashes | 0 |

## Known limits observed (not gate failures; all on POST-BETA10-BACKLOG)
1. Quiet source stretches beyond the 18 dB ride: education ~07:15-07:19 (-26 LUFS on air, gated as #9 above);
   government ~09:21-09:24 (-18..-26 LUFS, coordinator side-measurement government-quiet-0921-keeper-measure.txt;
   fell between loudness #13 and #14, so no gate verdict). U64 recommends a re-ride of failing stretches.
2. Caption-tap audio discards under CPU load: 08:12 public 5 s, 09:38 public 20 s, 10:20 education 50 s (CPU 75-88%).
   The 08:12 one may have been worsened by coordinator measurements; the other two had no coordinator load.
   No verify failed because of them.
3. Full-asset conform rebuilt three times for the same asset (August 11: 00:55, 07:53, 10:12) - self-invalidating cache
   sidecar (U64: preparer.py:2817 probe-only rewrite drops full_asset_conform). Avoidable CPU/disk load; likely
   contributor to 2.
4. Piece-join single-frame video drop: education 04:19, government ~09:52 (known; 2-segment plans).
5. Cold prep times up to 449 s (government 09:44) against ~11 min lead; every prep landed in time (min margin ~3.5 min).
6. Daemon first-attempt short-tail aborts (04:22, 04:54) - backlog top item from U63.

## Coordinator slips in this rung
- Started before all channels were on air (verify #1).
- 07:22 told the owner loudness #9 was a real station failure and to not tag on C15; retracted 08:14 after U64 + own
  re-measurement. Root cause: trusted the rung adjudicator's log-derived position.
- 08:05-08:12 ran source measurements at normal priority and a whole-disk find (stopped 08:20).

## Fixes exercised live
U63 fix A (short-tail re-resolve) at 04:19, 04:31, 04:52, 05:00. Fix B not observed on air.
