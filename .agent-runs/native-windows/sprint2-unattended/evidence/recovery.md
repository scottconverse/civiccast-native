# Recovery implementation and focused review evidence

## Recovery checks (recorded; no reruns for this receipt)

- `.\.venv\Scripts\python.exe -m pytest tests/egress/test_daemon_freeze_escalation.py tests/egress/test_daemon_output_av_guard.py tests/egress/test_automation.py tests/egress/test_daemon.py -q` — **342 passed in 9.76s**.
- `git diff --check` (recovery-owned changes) — **passed**.
- Lane: **Critical** (recovery and concurrency/state-ordering behavior).

Recovery semantics: guard-budget exhaustion requests the existing forced fallback slate once; freeze and A/V guards share the existing one-hour cooldown anchored at the latest recent restart; cooldown expiry allows one return-to-program attempt only while the exact recovery-slate reason remains. Failed fallback/exit calls do not repeat per poll. Stop/drain takes precedence. A session-local intentional-operator-stop latch blocks automatic recovery and `auto_start`; explicit enabled operator start clears it, and service restart clears it. Stderr diagnostic reading resets its offset on file identity/size shrink, ignores pre-spawn stale content, and caps scanned tail at 256 KiB.

## Focused independent storage review

Review scope: bounded child logs, command pruning/retention, storage endpoint, and SystemHealth panel/query. One concrete mismatch: `/api/staff/egress/storage` is authorized for setup_admin/support_admin/meeting_operator, while the SystemHealth screen unconditionally queries it and the sidebar entry is not role-filtered. publish_operator and records_clerk therefore see a 403 rendered as a storage failure. Parent confirmed the finding and requested role-based query/panel gating. No other product finding in the reviewed storage paths. No tests were run in this read-only review; storage worker separately recorded its own check results in `storage.md`.

## Focused scheduling backend review

- Auto-schedule expansion used `now.date()` in UTC. Inline repro at `2026-01-01 00:30Z` with `Pacific/Honolulu` gives station date `2025-12-31`; a Wednesday 18:00–22:00 block expanded from UTC date began `2026-01-07 18:00 -10:00`, while local-date expansion includes `2025-12-31 18:00 -10:00`. This misses the current local-day block.
- Program-log materialization deduplicated only exact UTC starts and did not reconcile already-persisted future rows when the profile timezone changed. Profile PATCH updates station state but does not invoke program-log cancellation. The schedule store's general `cancel` transitions both scheduled and published items, so blind cancellation can erase an operator-published commitment; existing occurrences also lack timezone/calendar-date provenance.
- Recording recurrence with `time_zone='station'` resolves the current profile timezone, but schedule PATCH only cancels jobs when disabling a schedule. Recurrence/timezone edits leave pending jobs; the next expansion can add changed UTC starts beside old jobs. Existing all-pending cancellation cannot be reused for edits because materializer idempotency includes jobs in any state, so canceled unchanged starts remain taken.
- No defect found in DST gap/fold handling: the wall-clock resolver skips nonexistent clocks and chooses the earlier fold; relevant program-log/recording tests cover both. Legacy recording recurrence JSON without `time_zone` parses as UTC. TypeScript helper follows the same gap/fold policy. Auto-schedule compile duration comes from asset seconds and is persisted as elapsed duration.

Scheduling reconciliation worker subsequently reported implementing preserve-horizon behavior and 97 focused tests passing; this review did not inspect or rerun that change. Re-review remains pending if requested.


## Re-review of timezone reconciliation (bounded; not green)

The author reported 99 focused tests passing in 4.01s and Ruff clean; I did not rerun them. Re-review found an uncovered last-day duplicate for a 26-hour zone shift. With an old daily 18:00 item on 2026-06-14 in Etc/GMT+12, its instant is 2026-06-15 06:00Z / 20:00 in Pacific/Kiritimati. The stored logical cutoff is still June 14, so a new-zone June 15 18:00 item at 04:00Z is admitted; a 1-hour candidate ends at 05:00Z and does not overlap the existing 30-minute item at 06:00Z. Both can air on June 15, two hours apart. The cutoff must account for existing starts as projected into the current timezone, in addition to the stored logical date. Finding sent to the reconciliation worker and parent; awaiting correction before a green disposition.

Concurrency boundary: app lifespan wires one background program-log worker and one background auto-schedule compiler per app instance, but program-log create/update/manual-materialize routes run `run_once` synchronously, and the auto-schedule compile route can run `compile()` while its worker runs. No in-process run mutex was present in the first candidate. Same-instant DB constraints/idempotency cover some races, but different timezone snapshots can create distinct starts. The corrected candidate adds in-process locks, reviewed below. No distributed locking changes were reviewed or requested.

## Re-review of corrected timezone reconciliation (green, bounded)

The author fixed the 26-hour boundary case by setting all three preservation cutoffs to the maximum of each persisted logical day and that persisted instant projected into the current station timezone. This prevents admitting a new-zone candidate on the local calendar day occupied by the old horizon's final commitment. Autoschedule and recording have explicit over-one-day offset regression tests; program-log uses the same projected-date calculation and existing zone-change tests. Materializers preserve existing schedule rows/jobs/occurrences without canceling or rewriting them; new extensions proceed only beyond the projected cutoff. The concurrent auto-schedule test confirms the second compile does not read its timezone provider until the first compile commits.

Author-reported checks (not rerun during review): 115 passed in 4.64s across the five affected test files; Ruff clean on eight files. Code review found no remaining defect in the two requested corrections. Programlog's module RLock wraps the entire `run_once` boundary; auto-schedule API and background compile paths share `COMPILE_LOCK`, with timezone resolution inside the lock. These locks serialize threads within one process; they do not serialize multiple server processes.

## Existing daemon recovery expectation alignment

CI's ordinary pre-mutation baseline reported this test as the single failure among 3,955 tests because its budget-exhaustion assertion still expected the old "NOT restarting the worker again" wording. The test already protects exact escalation/restart/heal/spawn counts, leaves the last worker and relay alive at refusal, and asserts no additional spawns or kills in the tail. Updated only its expected product message and tail log expectation: the new quality-recovery latch defers the spent guard throughout cooldown, so the tail retains one initial CRITICAL rather than periodic repeat CRITICALs. The first local run after the wording change exposed that stale tail expectation; after aligning it to the cooldown behavior, the focused check passed:

- `.\.venv\Scripts\python.exe -m pytest tests/egress/test_hls_relay_progress.py::test_daemon_tick_sequence_with_escalation_is_bounded_not_a_storm -q` — **1 passed in 1.53s**.
