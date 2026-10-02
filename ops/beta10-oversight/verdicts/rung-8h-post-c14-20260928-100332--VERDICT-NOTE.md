# C14 8-hour rung — VERDICT: PASS

Rung `8h-post-c14`, 2026-09-28 10:03:33 → 18:04:21 -06:00 (480 min), service pid 28832 throughout (no restart).
Installed build: C14 = engine 931390b1 (U59e + U62 on fe5a5306) + bridge 14edd5c3 (U59g: openh264enc
slice-mode=n-slices, num-slices=4, multi-thread=4). Runner line: `RUNG 8h-post-c14 END verdict PASS verifies 45 loudness 16 failures 0`.

## Results

| Gate | Result |
|---|---|
| Captions / timing / playback verify (3 channels each) | 45 / 45 OK |
| Loudness, 240 s windows, −16 ±1 LUFS (3 channels each) | 16 / 16 PASS (no INSTRUMENT_ERROR, no quiet-window listings) |
| Changeovers scored by `changeover_hole_watch.py` | 48 CLEAN, 0 HOLE, 1 PARTIAL |
| Forced switches / delivery-lag WARN / video pace <0.94 | 0 / 0 / 0 |
| Slate on air | government ~107 s at service start only |
| Aborted reloads | 1 (12:58, 0.2 s tail first-attempt abort; daemon retry landed; nothing on air affected) |
| Station restarts / worker exits | 0 |
| Disk (C:) | 45–58 GB free throughout |

Changeover count note: `evidence/changeover-holes.log` lines 238+ hold 49 CLEAN lines; government 16:29:18 and
16:29:20 are the same changeover scored by two overlapping watches → 48 unique CLEAN.

PARTIAL = education 13:38:15, not PTS-scanned (keeper had rolled the segments before the re-armed watch reached
them); engine evidence clean: spread 0.631 s ≤ bound, mux-tail released 0.047 s, relay invalid_ts 0, verify OK.

## Live test inside the rung (U59g)
Education 11:02: the Senior Citizens June hot stretch (source ~1555–1590 s) aired with pace 0.971–1.026, no
forced switch, natural EOS at 11:05:52, 2002.0 of 2003.6 s aired (C11 lost 212 s on the same plan). See
`LIVE-TEST-SCJ-HOT-STRETCH.md`. Second live test: government ~22:49 ±25 min (post-rung, watched).

## Observations (not failures)
- Cold preps ran well past the automation lead model: education 332.2 s (15:32), public 304.3 s (15:34),
  public 355.7 s (17:35; model ~170 s), government 281.4 s (17:48; model ~270 s). All accepted before plan end
  (margins 5–7 min). Risk: a longer cold window under 3-channel load could overrun the lead → slate.
  Backlog candidate.
- Preparer warned Parks & Rec Aug 2026 full-program leveling missed its gate (worst 4-min 5.86 LU); the aired
  1800 s window passed loudness #12 on public.
- Caption tap "behind" during preps (known; live captions continued).

## Coordinator process slips (no evidence lost)
- 16:02 and 16:51: watch sets not renewed before expiry; changeover watch down for seconds, no changeover in the
  gap. Fixed with a dedicated 25-min renewal alarm.

## Known issues carried to the tag
1. Slate→program handover residue < 0.1 s (0.064–0.085 s audio gap, ≤2 clamped frames) — U62b fixes it,
   audited, NOT installed.
2. 0.2 s tail first-attempt abort — self-heals via retry (backlog).
3. Cold-prep duration exceeds the automation lead model by up to ~2× (backlog).
4. Caption tap lag during preps.
