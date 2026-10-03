# U71 audit: `git diff beta10-u70 beta10-u71` (c97c8c07 + faaf62ea)

Auditor: Sonnet 5.5, skeptical read-only review, 2026-10-02. Worktree under test: `civiccast-ds-u71` @ faaf62ea. No tracked file was modified anywhere; no commit/push; no live-station or ProgramData access.

## TL;DR verdict: SHIP into the next candidate

No Blocker, Critical or Major finding. Part 1 (env-var spelling) is correct for all three switches in all nine two-C/one-C/unset combinations, defaults unchanged. Part 2 (timing split) is behaviour-neutral for every shape faster-whisper can actually return: my differential probe of u70 vs u71 shows identical hypotheses and identical exception outcomes in 23 of 26 scenarios. The 3 differing scenarios are contrived non-float values (see M-1) that real `TranscriptionInfo`/`Segment` objects never produce. Test results: failure NAMES identical between u70 and u71 (same 16 known/pre-existing; zero new). New tests are sensitive (25 of them fail on the pre-change source; three hand-made mutations each caught by exactly the intended test).

Five Minor items below. M-1 and M-2 are cheap (one to three lines each) and worth folding into the next U-unit, but neither gates the candidate.

## What I ran (evidence)

| Check | Command / method | Result |
|---|---|---|
| Test suites, both revs | `python -m pytest tests/captions tests/egress/test_preparer.py -p no:cacheprovider -q -rf`, BelowNormal priority, from each worktree root (import path verified: `civiccast.__file__` resolves inside the worktree under test) | u70: 16 failed / 659 passed / 1 skipped (676 collected). u71: 16 failed / 687 passed / 1 skipped (704 collected). `diff` of sorted FAILED names: IDENTICAL. |
| The 16 failures | by name | 5x `test_caption_tap_batch_diagnostic.py` (TestOverloadCarriesPrecedingBatchDuration x3, TestPrecedingBatchSessionScoping x2), 9x `test_startup_diagnostics.py`, 2x `test_preparer.py::test_evict_cache_over_budget_{reaps_orphaned_tmp_and_meta,counts_live_tmp_bytes_toward_budget}`. Exactly the known list. +28 passed in u71 = +28 collected = the new tests. |
| Lint | `ruff check` on the 4 changed source files + changed tests | All checks passed |
| Switch matrix | script calling the three real readers with every combination of {two-C unset/0/1} x {one-C unset/0/1}, run against u70 and u71 | see M table in finding section 1 |
| Differential decode probe | 26 fake-model scenarios (live and batch; normal, mid-iteration raise, raise at call, info None, NaN/inf/str/MagicMock/huge-int temperatures, zero segments, multi chunk, early generator close) run against both trees; compared hypotheses + exception text | 23 identical; 3 differ (M-1) |
| Stale/thread probe | one pooled worker thread, batch A decodes, batch B fails before decode | stale leak reproduced (M-2) |
| Diagnostic JSON probe | `ShedDiagnosticCollector` driven with 31 batches incl. NaN/inf/negative/str/None/huge | bounded, serializable, old-style call OK (section 3) |
| Sensitivity | temp worktree `u71-audit-sens`: (A) whole `civiccast/` reverted to u70 with u71 tests; (B) three single-hunk mutations of runtime.py | see section 4 |
| Fresh-interpreter import | `import civiccast.captions.runtime` then call fallback reader, and same for `tap_shed_diagnostic` | no circular-import error; egress package is loaded lazily on first call |

## Findings

### 1. Part 1 correctness: PASS

Matrix output (u71; value = reader's result; "twoC" = `CIVICCAST_*`, "oneC" = `CIVICAST_*`). Identical shape for all three switches:

| twoC | oneC | preparer low-prio | shed diagnostic on | whisper temp fallback |
|---|---|---|---|---|
| unset | unset | True (default) | True (default) | False (default) |
| unset | 0 | False | False | False |
| unset | 1 | True | True | True |
| 0 | unset | False | False | False |
| 0 | 0 | False | False | False |
| 0 | 1 | False (two-C wins) | False (two-C wins) | False (two-C wins) |
| 1 | unset | True | True | True |
| 1 | 0 | True (two-C wins) | True (two-C wins) | True (two-C wins) |
| 1 | 1 | True | True | True |

u70 for comparison: every two-C-only row returned the default (inert); that is the bug, now fixed. Defaults unchanged: unset/unset is identical at u70 and u71 for all three. One-C only: unchanged from u70 (still honoured, now with one deprecation warning). Source: `civiccast/egress/preparer.py:485-499` (`resolve_renamed_env` then `env_name`/`raw`), `civiccast/captions/tap_shed_diagnostic.py:764-778`, `civiccast/captions/runtime.py:392-403`. Invalid-value warnings now name the spelling actually read (`env_name`), good.

Remaining new-env-var reads that are one-C only: NONE among U68/U69/U70. `PHASE_TIMING_ENV_VAR` was already two-C (`civiccast/captions/phase_timing.py:60`); only comments were wrong and are fixed. Pre-existing, out of U71 scope, FYI: one-C reads that still exist and were not introduced by U68-U70: `CIVICAST_WORKER_PERSISTENT` (`egress/gst/reload_policy.py:75`), `CIVICAST_GST_LEG_RATE_DIAG` (`egress/gst/engine.py:656,3337`), `CIVICAST_CAPTION_PROOF_POLL_SECONDS`/`_TIMEOUT_SECONDS` (`app.py:1673-1675`), `CIVICAST_OBS_WEBSOCKET_PASSWORD` and `CIVICAST_WSL_DRIVE_MOUNT_ROOT`/`CIVICAST_TRANSLATE_WINDOWS_BACKUP_PATHS` (`lpm_lab_stage45.py`, `installer/service.py:1130`). Whether any of those is also set two-C in the registry is the same class of trap; worth a sweep, not part of this diff.

Lazy import: `from civiccast.egress.env_vars import resolve_renamed_env` runs inside `_live_tap_temperature_fallback_enabled` (called once at runtime construction, `runtime.py:902`, not per chunk) and inside `shed_diagnostic_from_env` (once per tap worker). It pulls in the whole `civiccast.egress` package on first call (verified: `civiccast.egress` not in `sys.modules` before, present after). `tap_worker.py:2781` already imports `civiccast.egress.automation`, so egress is already in the service process; no new dependency in practice. Not verified: a captions-only process on a box where egress's optional deps are absent.

### 2. Part 2 behaviour-neutrality

PASS for all real inputs; three contrived hardening gaps (M-1), one stale-value gap (M-2), one cosmetic batch-path note (M-3).

What holds, with evidence:
- Lazy generator: the timer starts before `_transcribe_source` and the `finally` runs after the `for ... in enumerate(segments)` loop (`runtime.py:1162` timer start, `:1205-1206` finally; loop body unchanged apart from the temperature line). Exceptions raised at the model call or mid-iteration surface at exactly the same point with the same type/text (probe: `live|batch/callraise`, `live|batch/midraise` SAME). Probe also covers early `close()` of the batch generator: SAME.
- What is yielded/when: probe hypotheses (id, start, end, text, confidence) byte-identical u70 vs u71 for normal, empty-text, zero-segment, multi-chunk, `info=None`, `NaN`/`inf`/str/MagicMock temperature.
- The `finally` only does a `perf_counter()` subtraction and one attribute store; it cannot realistically raise and never swallows (no `except`).
- Live path: `process_batch` consumes `transcribe` via `list(...)` on the same thread (`captions/pipeline.py:89`, one chunk per batch from `tap_worker.py` `process_batch([chunk], ...)`), so the per-thread slot read at `tap_worker.py:1776` is the same thread that wrote it. Cross-channel mixing while a decode is in flight is impossible: `threading.local`, and the test `test_the_decode_record_is_thread_local` is sensitive (mutation M2 below).
- Tap side: `_last_decode_metrics()` has its own try/except and returns None on non-dict/raise (`tap_worker.py:2004-2022`); `record_batch` is invoked through `_note_shed_diagnostic`, which swallows `Exception`; `NullShedDiagnostic.record_batch(**_)` accepts the new kwargs. No path raises into the tap.
- Memory: slot holds one dict of 3 floats per thread; `last_decode_metrics()` returns a copy; no audio/segment/info reference is stored (`metrics` receives only `_optional_float(...)` results).

#### M-1 (Minor) Three non-float inputs raise into the decode where u70 did not
Probe (u70 outcome `exc: null`, u71 outcome shown):
- `info.duration_after_vad` is a property that raises: u71 raises `RuntimeError` out of `_transcribe_source` (`runtime.py` `getattr(info, "duration_after_vad", None)` only guards AttributeError).
- `info.duration_after_vad = 10**400`: u71 raises `OverflowError` (`_optional_float` catches only `TypeError, ValueError`).
- `segment.temperature = 10**400`: u71 raises `OverflowError` from `_higher_temperature`.
Reachability: faster-whisper's `TranscriptionInfo.duration_after_vad` and `Segment.temperature` are plain floats, so none of these occurs in production; this is hardening against the stated worst case ("a bug that raises inside the hot path"). Fix path (2 lines): in `_optional_float` use `except (TypeError, ValueError, OverflowError)`; wrap the `getattr(info, ...)` in `_transcribe_source` in `contextlib.suppress(Exception)` / try-except so a diagnostic read can never fail a decode.

#### M-2 (Minor) Stale slot leaks into a batch that never reached the decode
Reproduced (`stale.py`): one pooled thread; batch A decodes (temp 0.6, vad 7.0); batch B (non-16 kHz chunk, WAV write raises before the timed region) then returns A's exact record from `last_decode_metrics()`. In the tap this means a batch that failed before the decode, on a pooled channel thread last used by a different channel, is stamped with that channel's `transcribe_s`/`duration_after_vad`/`max_segment_temperature`. Window is narrow (pre-decode failure points: the temp-WAV write for non-16 kHz chunks, or the 16 kHz float conversion, e.g. an odd-length PCM buffer raising ValueError in `np.frombuffer`) and diagnostic-only, hence Minor. Fix path: reset the slot at the top of `FasterWhisperRuntime.transcribe()` (`self._decode_metrics.last = None`), or have the tap call a `clear` before `process_batch`.

#### M-3 (Minor, cosmetic) Batch/VOD path: timer spans consumer time
In the non-live path `yield hypothesis` sits inside the `try` (`runtime.py` `else: yield hypothesis` inside `try/finally`), so `transcribe_s` there includes whatever the consumer does between yields and is only stored when the generator is exhausted/closed. No output change (probe: batch scenarios SAME), and the tap only reads it for the live runtime, so no impact today. Worth a one-line comment so nobody reads batch numbers as decode time.

### 3. Diagnostic JSON: PASS (one hygiene gap)

- Bounded: 8-record cap unchanged (`DEFAULT_MAX_BATCH_RECORDS`, deque maxlen). With 31 batches fed (8 retained, all four new fields populated, including 1e300 and 12345.679 values), one emitted line was 3291 bytes. The four new fields add roughly 100 bytes per record, about 0.8 KB worst case per line. Rate limit (one line per channel/event/30 s) unchanged.
- Old records / old-style callers: `record_batch(channel, wait, feed, asr)` with none of the new args yields `transcribe_s/persist_s/duration_after_vad/max_segment_temperature = None` -> JSON null, record shape stable; `persist_s` is None unless both `transcribe_s` and `stabilize_s` are known (`tap_shed_diagnostic.py` `persist_rounded`). Pre-U71 lines simply lack the keys; the reader is a log line, no schema consumer in the repo.
- Hygiene gap (Minor, M-4): `_optional_rounded` does not reject NaN/inf/negative values (`round(float('inf'),3)` is inf), so a direct caller passing them gets non-RFC JSON (`Infinity`/`NaN`; Python's `json.loads` accepts them, strict parsers do not) and a derived `persist_s` from a negative `transcribe_s` is nonsense (observed `persist_s: 10.76` from `transcribe_s: -5.0`). Not reachable from the runtime (`_optional_float` filters with `isfinite`; `perf_counter` deltas are finite and >= 0), so diagnostic-only. Fix: `return round(v, 3) if isfinite(v) and v >= 0 else None` (note `_optional_rounded` is also used for temperature, which is >= 0 too).
- Semantics note: `persist_s = asr_s - transcribe_s - stabilize_s` is a residual. It also absorbs anything else inside `process_batch`: translation, audio-evidence creation, per-phase timing overhead, and, on non-16 kHz chunks, the temp-WAV write (outside the timer by design). It is clamped to >= 0 by `_round`, so a clock skew would read as 0.0 rather than negative. Reasonable, but the docs call it "HLS publish and review persistence" only (see section 5).

### 4. Tests

Names: see table above; zero new failing names at u71. 28 new tests, all passing at u71.

Sensitivity (all in temp worktree `u71-audit-sens`, tracked worktrees untouched):
- (A) u71 tests against u70 `civiccast/` source: 25 failures = the 2 known preparer ones + 23 new/changed tests: 4 temperature-spelling and 5 decode-metrics tests in `test_captions_core.py`; 4 `TestTheDecodeSplitFields`, 4 `TestShedDiagnosticEnvSpelling`, 2 tap-level (`test_the_decode_split_reaches_the_batch_record`, `test_a_metrics_getter_that_raises_does_not_break_the_tap`) in `test_caption_tap_shed_diagnostic.py`; 4 in `TestForegroundLowPriorityEnvSpelling`. So the env-spelling and timing tests do fail on the pre-change code.
- (B) Hunk mutations of u71 `runtime.py`, `-k decode` selection:
  - M1 time only the model call, not the lazy generator: fails `test_the_decode_split_times_the_whole_lazy_generator` (and only that).
  - M2 `threading.local()` replaced by a plain shared object: fails `test_the_decode_record_is_thread_local` (and only that).
  - M3 `finally` replaced by `else` (a failing decode reports nothing): fails `test_a_failing_decode_still_reports_its_elapsed_time` (and only that).
- Gaps (Minor, M-5): (i) `tests/egress/test_preparer.py::TestForegroundLowPriorityEnvSpelling::test_the_registry_spelling_is_the_two_c_one` asserts class-local literals (`self._PRIMARY`) against strings, so it passes on the old code and checks nothing about `preparer.py`; assert `preparer_module.FOREGROUND_PREPARATION_LOW_PRIORITY_ENV` instead. `test_a_whitespace_registry_value_falls_through_to_the_legacy` also passes on old code (it is a regression guard, fine). The phase-timing spelling test passes on old code by design (documented). (ii) No test covers M-1 (a diagnostic read that raises must not fail the decode) or M-2 (no stale slot).

### 5. Docs `docs/ops/background-workers.md`: accurate, two nits

Verified against code: the field list and meanings match `runtime.last_decode_metrics` / `record_batch`; the worked example is internally consistent (5.833 - 5.771 - 0.041 = 0.021, `persist_s` 0.021); the disable switch is now spelled `CIVICCAST_CAPTION_TAP_SHED_DIAGNOSTIC=0` (matches `SHED_DIAGNOSTIC_ENV_VAR`). Nits (Minor, M-6, doc-only):
- "All four are `null` when the runtime does not publish them": `persist_s` is also null when `stabilize_s` is null even if the runtime does publish; and `max_segment_temperature` is null when a chunk yields no segments, which is not "runtime does not publish".
- `persist_s` is described as "HLS publish and review persistence"; it is the residual (also translation, audio evidence, phase overhead, non-16 kHz WAV prep).
- The doc does not mention that the one-C name still works as a deprecated fallback, and the other two switches (`CIVICCAST_EGRESS_PREPARE_LOW_PRIORITY`, `CIVICCAST_WHISPER_LIVE_TEMPERATURE_FALLBACK`) are not documented in `docs/ops` at all (grep: only the shed switch appears).

## Operational note (not a defect)
The fix makes the two-C names live. If the station registry already carries any of these three variables set two-C with a non-default value (a `0` for the first two, a `1` for temperature fallback), that value will start taking effect on the next restart of the service where previously it was silently inert. The installer does not write them (`grep` of `civiccast/installer` finds none), so only an operator-set value is at risk. I did not inspect the live registry.

## What I did NOT check
- Any real model: no faster-whisper/CTranslate2/GPU run; `segment.temperature` and `info.duration_after_vad` field types were taken from the project's expectations and fakes, not from the installed faster-whisper source.
- The live station: no service registry read, no ProgramData, no live HLS, no running service. I did not verify what values the registry currently holds for the three switches.
- Real-clock behaviour: all timing assertions are from fakes/`time.sleep`; I did not measure actual overhead of the extra `perf_counter()` calls under load (expected negligible).
- Whisper.cpp runtime path: only read-through (it has no `last_decode_metrics`, so the tap emits nulls); not executed.
- Full-suite impact: I ran only `tests/captions` and `tests/egress/test_preparer.py`; other test directories that import the changed modules (e.g. `tests/egress` beyond the preparer file, `tests/app`) were not run.
- Concurrency under real load: thread-safety was argued from `threading.local` semantics plus the single-thread-reuse probe; I did not stress it with many concurrent channels.
- mypy / type-check: only ruff was run.
- The root causes of the 16 pre-existing failures: confirmed identical by name at both revisions, not investigated.
- A `.mypy_cache` directory exists untracked/ignored in the `civiccast-ds-u71` worktree and pytest `__pycache__` dirs may now exist there from my first test run (git status clean, so ignored); no tracked file changed.
