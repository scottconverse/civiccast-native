# C14 follow-on soak (6 h) — runner verdict FAIL (2); coordinator reading: PASS with 2 listed no-speech windows, pending Scott

Rung `soak-post-c14`, 2026-09-28 18:04:48 → 2026-09-29 00:05:08 (360 min), service pid 28832 throughout (no restart), same
build as the passed 8 h rung (C14). Runner line: `RUNG soak-post-c14 END verdict FAIL verifies 33 loudness 12 failures 2`.

## Results

| Gate | Result |
|---|---|
| Captions / timing / playback verify | 31 / 33 OK; the 2 FAILs are government caption_decode_back during on-air council breaks (below) |
| Loudness 240 s windows | 12 / 12 PASS (education 21:52 window EXCLUDED_QUIET_SOURCE under the settled quiet-window rule: source -30.9 LUFS, max reach -24.5, aired -18.2) |
| Changeovers | 37 / 37 CLEAN (education 18:05:43 first scored HOLE = keeper gap between rungs, rescored CLEAN; see changeover-holes.log correction) |
| Forced switches / delivery-lag WARN / video pace < 0.94 | 0 / 0 / 0 |
| Slate on air | 0 |
| Aborted reloads | 1 — public 23:44:57 aborted:timeout on a ~1 s lead tail; daemon retry dropped the 0.7 s tail, re-prepped 16.7 s, accepted 23:45:16; changeover 23:52:56 CLEAN; no on-air effect |
| Worker exits / station restarts | 0 |
| Disk (C:) | 58 → 30–34 GB free (conform-cache growth, see OVERSIGHT-LOG 23:59) |

## The two FAILs (no-speech council breaks)
Both on government, "City Council Regular Session - September 8, 2026":
1. verify #10 19:43:32 — cue "…take a five minute break." (143:38:10) → next speech cue 143:45:26 "…get back to consent agenda item".
2. verify #17 20:59:54 — cue "Five minutes, that's fine." then side chatter (~20:56) → captions resume 21:01:15, "So I am going to turn it over to Joanne".
Caption tap alive and within capacity throughout; education and public captioned continuously. Evidence: `VERIFY-10-GOVERNMENT-RECESS.md`,
`government-active-vtt-recess-1945.vtt`. Coordinator classification LISTED (no speech in source), analogous to the settled loudness
quiet-window rule. If Scott rules no-speech windows are failures, this soak stands as FAIL.

## Live test #2 (U59g) inside this soak — PASS
Government Senior Citizens June hot stretch ~22:31: pace 0.974–1.018 (block 0.971–1.029, 120 windows), 0 forced switch, natural end,
full plan aired. `LIVE-TEST-2-SCJ-GOVERNMENT.md`.

## New observations (backlog candidates, not blockers)
- Intra-plan piece join, government 22:05:18: one future-dated video frame dropped (ahead = piece-1 length 597.93 s) → 0.033 s video
  gap, 0.021 s audio overlap. Education's 22:28 join was clean.
- Short lead tail first-attempt abort recurred (public 23:44, ~1 s tail → timeout). Backlog item extended: drop tails < ~2 s up front.
- Cold preps still up to ~2× the automation lead model (education 361.5 s vs ~170 s budget at 22:13); all accepted with ≥ 5 min margin.
- Conform-cache growth drives disk use (egress data 33 GB, conform-cache 15 GB / 16 files); needs a retention cap.

## Continuation
Second 8 h rung `8h2-post-c14` started 23:59:06 (overlapping this soak so the segment keeper never stopped), ends ~07:59.
