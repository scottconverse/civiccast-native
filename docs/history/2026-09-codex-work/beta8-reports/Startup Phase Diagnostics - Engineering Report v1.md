# Startup phase diagnostics - engineering report v1

## Purpose and limits

This is opt-in observation, not a startup fix or a release acceptance claim.
The existing logs cannot distinguish initial retention verification from model
preparation as the cause of historical startup overloads. These receipts expose
those boundaries without changing caption policy, thresholds, scheduling,
session resets, retention decisions, GPU settings, or service configuration.

Enable with `CIVICCAST_CAPTION_STARTUP_DIAGNOSTICS=1` in the intended worker's
environment before constructing it. Default is off. The existing settings loader
passes it to both embedded and external tap workers. No environment or service
was changed during this implementation.

Records use the existing INFO logger, prefix `Caption startup diagnostic`, then
JSON containing monotonic nanoseconds, a unique sequence, PID, numeric thread ID,
channel/session metadata where applicable, and phase metadata. Global retention
and preparation are not attributed to a particular channel. Records contain no
audio, speech text, paths, credentials, or exception messages.

## What is recorded

- Initial retention begin/end: initial flag, ready verdict, error class. A failed
  initial verification remains initial on its next attempt. Later asynchronous
  sweeps are intentionally outside this diagnostic's retention coverage.
- Reset begin/end: channel and generation before reset, error class. Successful
  completion additionally records actual resulting generation and discarded
  count, including zero.
- Backlog snapshot: settled indices (first 16 only), full count, truncation flag,
  actual atomic-segment mode, threshold, channel and generation. This is taken
  before the existing backlog decision, including empty scans.
- Preparation and batch begin/end; batches include channel, generation and
  segment index. A batch includes the existing process_batch work, not exclusively
  GPU inference, so its duration must not be labeled pure ASR latency.

## Bounds and overhead

At most 512 attempted receipts and 300 seconds from **worker construction**, not
from each session or first scan. Bounds can truncate pairs: missing end records
do not prove a stalled operation. Handler failures can lose records too.

No new locks are added. CPython's `next(itertools.count)` claims unique budget
slots across the worker threads. Timestamps are captured before JSON formatting
or log-handler execution; log-line order is not a cross-thread execution order.

Default off avoids diagnostic clocks, formatting, counter advancement and log
output, but method calls, keyword arguments and context-manager overhead remain.
When enabled, existing synchronous logging handlers may delay work, including
inside existing session locks. Bounded does not mean zero overhead: measured
timing can be perturbed by diagnostics. Logging exceptions are isolated so they
cannot replace the original operational exception. Ordinary operational logging
and its behavior are not changed.

The external observer remains necessary for output, state and fresh file
publication evidence. These logs alone do not prove historical causation or
sustained captions-ON performance.

## Verification so far

Integration base: a1b377a2; its tap-worker product bytes are unchanged from
904a8453. This change is uncommitted and does not touch service state.

Baseline command:
`.venv\Scripts\python.exe -m pytest tests/captions/test_caption_tap_worker.py -q`

Result: `68 passed in 5.28s`.

Initial new-test run before implementation:
`.venv\Scripts\python.exe -m pytest tests/captions/test_startup_diagnostics.py -q`

Result: `2 failed, 1 passed in 1.30s`. The real reset/retention emission test failed
because the phase set was empty; the error-path test reached an empty-record
IndexError rather than its final assertion (not claimed as sensitive RED proof).

Final focused command:
`.venv\Scripts\python.exe -m pytest tests/captions/test_startup_diagnostics.py tests/captions/test_caption_tap_worker.py -q`

Result: `77 passed in 5.48s`.

`.venv\Scripts\python.exe -m mypy --follow-imports=silent civiccast/captions/tap_worker.py`:
`Success: no issues found in 1 source file`.

`ruff check civiccast/captions/tap_worker.py tests/captions/test_startup_diagnostics.py`:
`All checks passed!`. `git diff --check`: exit 0.

Tests exercise actual emitted logs, real normal scan order, zero reset, preserved
reset errors, retention fail-closed behavior, diagnostic handler failure,
multithreaded count bounding, time bounding, bounded metadata, and default-off
clock/counter behavior. They use synthetic runtime/audio; no real GPU validation
is claimed. Wider command `.venv\Scripts\python.exe -m pytest tests/captions -q`:
`383 passed, 1 skipped in 28.91s`. The skip is the external Postgres test
(`tests/captions/test_review_persistence.py:479`), server not configured.
Independent review disposition follows separately.

Root integrated check:
`.venv\Scripts\python.exe -m pytest tests/captions tests/egress/test_daemon.py tests/egress/test_gst_strategy.py tests/egress/test_worker_pipe_seam.py work/release-beta8-startup-investigation/test_watch_tap_metadata.py -q -p no:cacheprovider`

`669 passed, 8 skipped in 39.46s`.

Skip details: one external Postgres server not configured
(`test_review_persistence.py:479`); six POSIX/WSL FIFO control-path contracts
(`test_gst_strategy.py:177,444,461,587,1096,1112`) run on Ubuntu CI instead,
with native-Windows worker-pipe coverage exercised here; one unavailable `gi`
import (`test_worker_pipe_seam.py:389`). No failures or warnings in that run.
These skips are not passing checks and do not certify external Postgres or
GStreamer bindings in this Python environment.

Root Ruff check returned `All checks passed!`; Ruff format check returned
`4 files already formatted` for tap_worker, its diagnostic tests, the metadata
watcher and watcher tests. `git diff --check` exited 0.

## Review notes

Critical trigger: cross-thread bounded diagnostic state and metadata privacy.
Existing caller and builder signatures remain compatible; the new dataclass
field is appended so old positional argument meanings are preserved. No existing
tests or assertions were weakened. Only tap_worker.py, the dedicated diagnostic
test file, and this report were edited by this subtask. Parent owns integration,
public documentation synchronization and independent reviewer disposition.


---

## Addendum v2 - measured root-cause candidate for the startup overload (2026-09-17)

Added after the controlled cold-start measurement. This addendum records what is
PROVEN, what remains UNPROVEN, and which earlier hypothesis is now contradicted.
Mountain Time throughout.

### What is proven

1. **The service was not running the branch.** Before this work the installed
   runtime was an older revision (installed `captions/stabilize.py` was 13,405
   bytes vs the branch's 24,234; `captions/models.py` lacked `CaptionWord`).
   The branch's modules were staged into
   `C:\Program Files\CivicCast (Native)\runtime\Lib\site-packages` and the
   supervisor was cleanly restarted. 672 of 674 tracked `civiccast/**/*.py`
   modules now byte-match the worktree; the two exceptions are
   `apps/ott-native/tizen/{fix_signing_profile,validate_config}.py`, Tizen build
   helpers the native installer never ships. Receipt:
   `work/installed-runtime-staged-20260917T1408/runtime-identity.json`.
   Loaded process: supervisor PID 34544, control-plane PID 32116 on
   `http://127.0.0.1:8000`, health `healthy` / beta.8 / schema
   `0087_retention_terms`.

2. **The historical startup overload reproduced live on the candidate bytes.**
   `14:07:55.639` caption tap starting; `14:08:12.216` WARNING
   `Caption tap overload for channel public: 4 settled segments exceeds the
   maximum 2. Live captions are PAUSED for 120s ... active captions were cleared
   and the stale audio was discarded.` That is 16.6 s after tap start, the same
   signature as the historical "13-14 s after tap-thread startup" observations.
   Log: `C:\ProgramData\CivicCast\logs\control_plane-app.log`.

3. **The tap backlog is real and was unbounded.** At 14:10 MT:
   `public/processed` = **12,980 files / 1,980.8 MB**, chunk indices 0..13,857,
   oldest 2026-09-14 23:55, newest 2026-09-17 14:04:36. `government` = 275 files
   / 42 MB, `education` = 295 files / 45 MB. Receipt:
   `work/coldstart-diag-20260917T1415/t0-prestate.json`.

4. **Retention pruning stopped permanently at index ~570 for every channel.**
   The retention audit log
   (`C:\ProgramData\CivicCast\data\egress\caption-retention-audit.jsonl`)
   contains 818 records, all `pruned` / `raw-chunk-expired-after-derived-evidence`,
   covering public indices 65-569, government 60-545, education 72-554, and
   nothing after. 12,737 public chunks sit above that frontier.

5. **The mechanism is in `_discover_candidates` / `_is_eligible`.** A raw chunk
   was eligible only when `derived_evidence_verified AND aged >= 24 h`, and
   `derived_evidence_verified` is computed from review-store evidence windows
   against the chunk's absolute window `index * segment_seconds`. A chunk whose
   covering evidence never appears can never become eligible, so it is retained
   forever.

6. **The tap is not currently producing.** Over 90 s (14:18:55 to 14:20:26)
   `public/processed` stayed at 12,980 files and the newest chunk stayed
   `chunk-013857.wav`; evidence WAVs stayed at 1,487 with newest mtime
   06:59:25. The station was not ON AIR during that window, so the backlog is a
   frozen historical accumulation, not live growth. Receipts:
   `work/coldstart-diag-20260917T1415/watch-start.json` / `watch-end.json`.

### Controlled cold-start result (2026-09-17 14:44 MT) - CORRECTS the causal link

A second controlled cold start was run under unchanged operational settings with
a normal supervisor Stop/Start and the same candidate bytes:

| observation | 14:08 start | 14:44 cold start |
| --- | --- | --- |
| caption tap starts | 4 | 2 |
| retention-worker starts | 2 | 1 |
| overload warnings | 1 at +16.577 s | **0** |
| public processed before/after | 12,980 | 12,980 (delta 0) |

Receipts: `work/coldstart-diag-20260917T1430/pre-run-inventory.json`,
`post-run-inventory.json`, `phase-log.txt`; earlier run:
`work/coldstart-diag-20260917T1415/startup-receipt.json`.

Three consequences, stated plainly:

1. **The overload is intermittent, not deterministic.** Identical bytes, backlog
   and settings produced one overload at 14:08 and none at 14:44. The historical
   "13-14 s after tap-thread startup" signature is a timing coincidence of a
   start that happened to overlap a retention sweep, not a fixed property of
   every start.
2. **The 2 GB `processed/` accumulation does NOT by itself cause the 120 s
   pause.** At 14:44 that backlog was fully present and no pause occurred. The
   gate trips on SETTLED SEGMENTS IN THE CHANNEL DIRECTORY, not on the size of
   the `processed/` archive. The accumulation is therefore a storage/retention
   defect (disk growth, and work for every sweep), not the direct trigger of the
   caption blackout.
3. **`75ac6754` bounds storage growth; it is NOT shown to fix the startup
   overload.** The commit message says so, and this run is the reason to keep
   that boundary. Any claim that this fix removes the 120 s pause would be
   unsupported.

Open question this leaves: what makes a given start trip the gate. Candidates
worth measuring next are the retention sweep's own duration (~9 s measured over
13,550 candidates) overlapping the first scans, and whether an unsettled segment
is inherited when a start races a still-open writer. Neither is established.

### What is UNPROVEN

- **That this specific accumulation is what trips the historical gate.** The
  overload reproduced once at startup against the inherited backlog, which is
  consistent, but no per-scan receipt ties the historical 13-14 s pauses to these
  exact files. The cold-start diagnostic remains the intended receipt; it could
  not be enabled here because the diagnostic switch is read at tap-worker
  construction and the supervisor launches its control-plane child with a fixed
  env dict (`children.py`: `env = dict(extra_env or {})`), so a machine-level
  variable does not reach it without a product change.
- **Why public evidence coverage stops at index ~569.** Only the review store
  knows each evidence row's `source_start_seconds`; the service reads its DSN
  from `HKLM\SOFTWARE\CivicCast\Native\DatabaseUrl` (LocalSystem-readable)
  and `pg_hba.conf` requires `scram-sha-256`, so this was not readable from the
  session. Whether public chunks above 569 have *partially covering* rows
  (mis-aligned windows) or *no* rows (evidence path stalled) is undetermined and
  changes the correct fix.
- **That the committed fix drains the existing backlog.** Measured with the
  real directory and an empty store: 813 of 13,550 raw chunks eligible,
  124.1 MB reclaimable. With the real store, public supplies *some* windows, so
  `evidence_pending` is `true` channel-wide and the new branch does not fire for
  public. The fix bounds *future* accumulation and makes the age cap reachable;
  it is **not** shown to clear the existing 2 GB.

### Hypothesis now contradicted

An earlier note (`_startup_finding.py`, ~04:37) proposed that the overload came
from **leftover settled segments being inherited at a session start**, implying
non-atomic session handling. The current receipts contradict that as the
explanation:

- The handoff's atomic-start description is supported: a real channel Start
  resets the caption session and discards numbered chunks *before* the new
  encoder starts (`begin_channel_session` -> `_begin_channel_session_locked` ->
  `_discard_settled_segments`), and the reset receipt records the discarded
  count including zero.
- The measured accumulation is **not** leftover in the "not yet settled" sense.
  It is 12,980 files that were already consumed and moved into
  `processed/`, i.e. the post-consumption archive, pruned only on the evidence
  rule above. That is a retention-eligibility defect, not a session-boundary
  defect.

The retention-eligibility mechanism therefore wins over the leftover-segments
hypothesis: the leftovers are real, but they are *consumed* leftovers in
`processed/`, and their cause is the prune predicate, not session reset.

### Reclassification of the 14:08 "4 tap starts" (receipts-based, 2026-09-17)

The 14:08 run's doubled worker starts were **an artifact of how that run was
initiated**, not an overlap or restart loop. `supervisor.log` shows two
sequential service lifetimes:

- `14:04:28` stop -> `14:05:02` supervisor PID 35888 starts -> `14:05:43`
  `startup halted at child control_plane: readiness budget (30.0s) exhausted`
  -> `14:06:20` `restart of child control_plane not ready` -> `14:07:06`
  stop requested (child recovery aborted). This process was the incomplete
  stage that raised `ImportError: cannot import name 'CaptionWord'`.
- `14:07:38` supervisor PID 34544 starts -> `14:08:12.216` overload.

So 2 + 2 tap starts across two lifetimes, plus the supervisor's own recovery
retry. The two constructions were in DIFFERENT processes separated by a full
stop, so "overlapping/duplicated tap starts collide on settled segments" is not
supported and is retired as a hypothesis.

What the receipts do leave visible: the one observed overload happened in the
process that started immediately after a FAILED start, while the two clean
starts (14:07:39 and 14:44:04) produced none. Candidate mechanisms for a future
investigation, none established here:

1. the failed PID 35888 died mid-work and the next start inherited unsettled
   files as settled segments (channel directories currently contain only
   `processed/`, so no leftovers were present at 14:43);
2. cold model preparation immediately after a failed start.

### Release classification (decided 2026-09-17)

**Intermittent, mechanism unresolved; storage growth bounded by `75ac6754`;
acceptance to be validated by the soak.** No further code change is warranted
for the overload on the present evidence: two clean starts produced zero
overloads against one overload that followed a failed-start sequence caused by
this work session. A speculative change to a release candidate is not justified
by a 1-in-3 rate with a confound. The soak must record whether any
`Caption tap overload` appears, with timestamps, so the classification can be
revisited on real data.

### Committed change

`75ac6754` - `fix(captions): bound raw tap retention when evidence can never
arrive` (DCO-signed). Discovery records `evidence_pending`; `_is_eligible`
retires a raw chunk on the age cap when no evidence window can ever cover it,
while chunks whose evidence is genuinely pending stay protected at any age and
review-evidence files keep their protect-until-resolved rule.
RED: `TestUnverifiedRawChunkCannotLeakForever` failed on prior behavior.
GREEN: `tests/captions/test_caption_retention.py` 13 passed;
`tests/captions` 385 passed, 1 skipped (external Postgres not configured).
