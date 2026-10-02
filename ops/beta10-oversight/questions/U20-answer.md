# U20 - coordinator answer / part 2 (2026-09-25 00:26 MDT)

Excellent unit - the cache-cut root cause (section 2.2) is exactly what was needed. Two engineering decisions
(mine) and one measurement task, then restage. Same worktree rules as part 1 (`civiccast-ds`, `beta10-ds`; U22 is
running read-only against that worktree, so do not rewrite history; small commits, `git status --porcelain`
first, never amend).

## Decision 1 - a failed measurement pass DEGRADES, it does not block
Do NOT fail closed. If the loudnorm measurement pass fails or its JSON is unusable (H3 full-asset path and H5
segment path), log ONE WARNING naming the source, segment window and reason, and conform with the SINGLE-PASS
filter exactly as the installed station does today. Record the outcome in the prepared/cache metadata
(e.g. `loudness_method: "single-pass-fallback"` vs `"two-pass"`), and make sure a fallback conform is NOT cached
under the two-pass key (so a later successful run replaces it) - prove that with a test. Cancellation and real
prepare errors keep their current behaviour. Red then green; the five base-era tests that failed only because of
fail-closed should pass again (list them).

## Task 2 - measure the loudness RANGE setting against 240 s windows, then pick
The acceptance rung measures integrated loudness over any ~240 s window of the emitted audio (target -16 +/- 1),
not the whole program. Your own table shows two-pass windows at -18.1 (56f1) and -18.3 (4d36). Using the same
harness and the same three sources PLUS one education program (pick the longest education prepared source), run
two-pass with `LRA=11` (current), `LRA=7` and `LRA=5` (keep `I=-16`), and for each report: whole-program I/LRA/TP,
every non-overlapping 240 s window, the worst window, `normalization_type`, and max true peak per window (the
4d36 tail window measured +2.2 dBFS - find out whether that survives `TP=-1.5`, and if not, why; check with
`ebur128=peak=true`). Also listen-proxy: report the per-window LRA so a flattened, pumping result is visible.
Pick the LARGEST LRA whose worst 240 s window is within -16 +/- 1 on all four sources, and whose true peak never
exceeds -1.0 dBTP. If none qualifies, report the table and stop - do not invent another filter.

## Then
Commit the chosen setting (and bump `_LOUDNORM_METHOD_VERSION` if the filter string changes, so old two-pass
entries are not reused - test it), rerun the egress sweep (1 known failure only), ruff with `--config` + mypy on
`preparer.py`, and RESTAGE `staging\U20\` from the LIVE base exactly as before (the live preparer is still
`b211d1eb...`), with all five proofs re-run. Append "U20 part 2" to `reports\U20.md`.
