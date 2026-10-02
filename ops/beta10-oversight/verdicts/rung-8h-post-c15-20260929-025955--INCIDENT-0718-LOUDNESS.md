# C15 loudness #9 FAIL - education 07:14:00-07:18:00 window -21.9 LUFS (target -16 +/- 1)

## What aired
- Education 07:15:25 changeover to the next 1800 s part of "City Council Regular Session - August 11, 2026" (prep 07:04, 7.5 s,
  served from the full-asset conform cache `conform-cache\757519c35f332cae334f7b5e5d8e62e8.ts`, built 2026-09-29 ~00:55-01:16 on C14 bytes;
  the ride code is identical on C15 - U63 touched only automation.py).
- Verifier: window integrated -21.9 LUFS, LRA 15.6; "only 0s of 241.667s missed -17.00 LUFS at g_max 18.00 dB" -> reachable, not corrected -> FAIL (not a quiet-source listing).

## Coordinator measurements (07:2x)
- Keeper copies (on-air, after the window): 40 s chunks -29.0 / -25.5 / -24.9 LUFS.
- Prepared file `education\prepared\5c1bbfc49b16\segment-0001.ts` (1800.1 s), 120 s chunks from t=0: -26.0, -26.0, -17.1, -16.0 LUFS.
  => the quiet ~4 min is IN THE CONFORMED FILE; playout did not lose level.

## The station knew
- conform-cache json: {"loudness_status": "failed", "measured_lufs": -25.8, "full_asset_conform": true, "loudness_method": "ride"}.
- 00:55:44 WARNING: full-asset ride (in=0s dur=15949.2s) "kept attempt misses the loudness gate (worst 4-minute stretch 10.02 LU, whole program 0.06 LU)".
- The 1800 s WINDOW rides of the same asset in the same night logged "loudness ok" (in=1s, in=1799.6s). The full-asset path is the one that misses.
- History: 2026-09-27 00:29 window in=6810.19 also missed (worst stretch 8.42 LU).

## Verdict impact
C15 8h rung loudness gate now FAIL (8/9). Rung continues for stability/changeover/caption evidence. Diagnosis dispatched as U64.
Files: ride-august11-full-asset-0055.log, conform-757519c3-august11.json, loudness-09.json.

## Correction 07:33 (coordinator)
The conform-cache json `loudness_status: failed` is NOT proof the station judged its OUTPUT failed: all three cache entries
(757519c3 August 11, 53f0942a 7964 s asset, 125e31ca 14999 s asset still being built - .ts.tmp) say "failed", 125e31ca's json
was written before its ride finished, and 757519c3's json was rewritten at 07:24:12 (now full_asset_conform=false,
loudness_method=null). It likely records the SOURCE measurement. The firm evidence that the ride output missed is the
00:55:44 WARNING "kept attempt misses the loudness gate (worst 4-minute stretch 10.02 LU)" plus the coordinator's own
measurement of the prepared file (-26 LUFS first ~4 min). U64: say what loudness_status means (preparer.py:709,
continuity.py:442-487) and why the json was rewritten at 07:24.

## RESOLUTION 08:15 (coordinator) - loudness #9 is EXCLUDED_QUIET_SOURCE; the FAIL was a rung-instrument position error
- U64 (reports/U64.md) located the aired part at SOURCE 7206.0 s (two disjoint correlation slices agree). Coordinator
  re-measured the source independently: [7206,+240) -44.7 LUFS, [7446,+240) -19.8, [7686,+240) -22.9. -44.7 + g_max 18
  = -26.7, matching the -26 LUFS measured on the prepared file. The ride was pinned at its ceiling; the station behaved as designed.
- The rung adjudicator had no --air-audio, so it used T2 (log): captured_at minus the FIRST ON_AIR of the August 11 run
  -> position 3226.3 s. Wrong: the channel had aired earlier parts, so the log-derived position ignores part offsets.
- Re-adjudicated with the station runtime python at --position education=7121 (window opened 85 s before the 07:15:25
  change onto the 7206 s part): EXCLUDED_QUIET_SOURCE, unreachable 171 s of 197 scorable (need 60), sweep range 141-171,
  not borderline. File: loudness-09.readjudicated-pos7121.json (original: loudness-09.adjudicated.json).
- Under the owner's settled quiet-window rule (2026-09-26) this window is LISTED, not failed.
- Instrument fix (oversight tooling, coordinator's): rung_check must feed the adjudicator the keeper copies as --air-audio
  (T1) or refuse T2 when the asset has aired more than one part. Filed; not changed mid-rung.
- U64 station candidate (quiet-source exclusion in the ride's own gate, WARNING->INFO; no audio change) is NOT needed for
  the tag: no on-air effect. Parked on POST-BETA10-BACKLOG with U64's re-ride recommendation and the self-invalidating
  cache sidecar finding (preparer.py:2817 rewrite -> full 4.4 h rebuild).
