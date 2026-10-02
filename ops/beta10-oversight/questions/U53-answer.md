# U53 - coordinator answer (engineering call, final): options 1 + 3

Good work on item 2 (cache eviction) and the Addendum (recovery-start slate). Decisions:

1. **Implement option 1 (chain two plans at rollover)** - when a rollover's target is filler, the rollover plan carries
   filler + the next scheduled program, and that program's preparation is dispatched at the same moment. Keep the
   one-plan-per-channel invariant. RED-first hermetic sequencing test on the exact 17:57-18:07 education shape
   (plan on air 554 s, target filler, next program due at filler end).
2. **Implement option 3 (adaptive lead)** with these numbers: `lead = max(690 s, asset_seconds / 12 + 120 s)` where
   asset_seconds is the duration of the item that must be prepared, 12 = a deliberately conservative realtime factor
   (you measured 16.3x uncontended, 18.6-23.8x under today's load; 866 s worst observed), 120 s = margin. Log the
   computed lead on every rollover ("lead=NNNs for <asset> (<dur>s at 12x + 120s)").
3. **Do not** do option 2 (look-ahead queue) or option 4.
4. The `STARTING` residual in `_SLATE_FIRST_ACTIVE_STATES`: include STARTING so a stale STARTING claim also airs the
   slate first; RED-first.
5. Investigate (report, do not fix unless trivial): every cache sidecar reads `loudness_status: "failed"` - does a
   failed ride disqualify reuse (forcing a full conform every time)? That could be the rest of the 6 s vs 300 s gap.
6. Real-worker GREEN: the rung owns the box, so run ONE bounded real-worker airing run at `start /low` priority, <= 10
   min wall clock, on copies, reproducing a filler rollover followed by the next program, and show the next program
   airs at its due time with no slate. If that cannot be done in 10 min, say so and give the hermetic GREEN only.
7. Re-stage ONE combined `staging\U53\` (items 2, Addendum, 1, 3, STARTING) from LIVE bases. Report in
   `reports\U53.md` Part II, receipt at the end. Targeted tests only.

## Addendum from U54 (20:45) - for U53's item 5
U54 (reports\U54.md) found: `preparer.py:2256` reuse test never reads `loudness_status`; reuse keys on
`full_asset_conform`. So "failed" does not force re-conform (4 reusable rows, 3 never-reusable rows by design).
BUT `conform-cache\20bb7429cd5ab2fa4de6df833d690c0d.json` = {"loudness_status":"failed","measured_lufs":-70.0,
"normalized":false,"media_duration_seconds":3602.56,"full_asset_conform":true,"loudness_method":null} - a REUSABLE
entry that was never normalized (no ride ran; -70 is the silence sentinel). Trace which write path produced it and
fix so an un-normalized conform can never pass the reuse gate. Also: why are ALL sidecars "failed" when the ridden
output measures -15.9 LUFS (label bug?).
