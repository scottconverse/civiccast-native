# Beta10 verifier snapshot — independent mechanical audit

**Verdict: HOLD.** No patch was applied to main or installed; no live verifier, station control, or restart was run. Main repo verifier prehash matched the supplied SHA-256. The isolated patch/source/test hashes also matched supplied values. Main-tree patch applicability check passed.

## Hashes and applicability

- Patch `verifier-snapshot-fix.patch`: `BCEA960DAEBCE1872465FCEABA153628C2FF0A49078E9D58E1086CE662D1274F` — MATCH.
- Isolated source: `D4E0133415D139945BCCFAEEC82084487F8C4BFE81601885BA028D69E96E31AA` — MATCH.
- Isolated test: `2067C4F6169C99EEB559CDD796191ED71A7FE0874F423A5EE6E8CD63AA2D505D` — MATCH.
- Main source prehash: `C16BADC515FAC77F9783B6C2AB36E2AC0B25AE5E8C23154C0251F2D2315DECE4` — MATCH.
- Command on main: `git apply --check --whitespace=error <patch>` — exit 0.

## Executed checks

- In isolated snapshot: `python -m pytest -q tests/native/test_verify_beta10_live_hls_media.py` — exit 1; **67 passed, 1 failed** in 2.95s.
- Failure: `test_safe_rmtree_refuses_temp_root_and_unowned_and_outside`, assertion at test line 1207. `_safe_rmtree` removed `C:/Users/scott/AppData/Local/Temp/pytest-of-scott/pytest-158/test_safe_rmtree_refuses_temp_0/civiccast-verify-outside`, although this was not created by the verifier. The test detected the deletion; no other test data was targeted by this failing assertion.
- In isolated snapshot: `python -m ruff check scripts/verify_beta10_live_hls_media.py tests/native/test_verify_beta10_live_hls_media.py` — exit 1; 12 findings. Material: F821 undefined `segment_seconds` and `segments` in `measure_audio` (lines 698–699), plus unused `fail_count`; remaining findings include import formatting, broad swallowed exception, type exception, and unused test imports.

## Focused review findings

- **Scratch recursive-delete containment — BLOCKER:** `_safe_rmtree` checks only that the resolved basename begins `civiccast-verify-` and that it is under a temp root. Any unrelated descendant with that prefix qualifies. The included outside-temp test is incorrectly designed: pytest's `tmp_path` itself is under `tempfile.gettempdir()`, so its purported “outside” child passes containment and gets recursively deleted. Directory-name prefix is not ownership proof.
- **Snapshot TOCTOU — residual:** `_snapshot_one_channel` resolves/checks a segment path and then separately calls `is_file` and `_snapshot_segment` (`read_bytes` then `stat`). A concurrently replaced symlink/file can change after containment checking; size-only post-read validation also cannot detect same-size replacement during read. Hash identifies captured bytes, but does not establish they were one stable source version. No adversarial concurrent mutation was independently reproduced in this audit.
- **Bounds and traversal:** `validate_max_segments` rejects bool/non-int and values outside 1..16; channel IDs reject separators/traversal before reads. Playlist segment names must be bare `.ts` basenames and resolved paths contained in channel directory. Matching test assertions exist, but no separate mutation/red reproduction was run.
- **Presnapshot ownership:** `verify_all` owns shared scratch and deletes it in `finally`; per-channel code consumes presnapshot paths and creates/cleans its own scratch. Tests assert cleanup and snapshot use; full suite result above prevents calling the suite green.
- **Sparse cue verdict:** implementation aggregates clean decode with at least one cue as PASS, all clean/no cues as FAIL, any UNVERIFIED as UNVERIFIED. Tests assert these cases. They are test-stub assertions, not independent live-stream reproduction.
- **Short-window loudness:** implementation marks non-silent windows below 120 seconds UNVERIFIED and retains silence as FAIL. Test asserts 8s -> UNVERIFIED and 180s -> PASS using mocked ffmpeg output. Independent ffmpeg measurement was not performed. Ruff's undefined references inside `measure_audio` are a separate correctness blocker for that function.

## Test sensitivity / evidence limits

The failing cleanup test is a real red assertion against current code and caused the prohibited target to be deleted before the assertion failed. Other regression tests contain assertions for the listed bounds, traversal, snapshot, caption, and loudness behaviors. The isolated receipt documents prior RED claims, but this audit did not independently run those tests against a pre-fix baseline; those claims remain author-reported, not independently reproduced. Patch applies cleanly to main's current expected source, but test and Ruff failures block acceptance.
