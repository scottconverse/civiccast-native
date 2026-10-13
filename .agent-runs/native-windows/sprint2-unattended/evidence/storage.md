# Sprint 2 storage evidence

Branch: `codex/sprint2-unattended`. Results below are from the existing recorded runs; no checks were rerun to create this note.

## Recorded focused checks

The following exact invocations and summaries were present in the retained tool output:

```text
Command: npm run test:unit -- --run src/screens/SystemHealthAlerting.test.tsx
Test Files  1 passed (1)
Tests  28 passed (28)
Duration  1.15s (transform 185ms, setup 139ms, import 321ms, tests 162ms, environment 397ms)
```

```text
Command: python -m pytest -q tests/test_schema_check.py::test_expected_head_matches_the_single_migration_head tests/test_schema_check.py::test_expected_head_does_not_depend_on_current_working_directory tests/recording/test_models_and_store.py::TestMigration0056AndMerge::test_repository_has_single_current_head tests/schedule/test_migration_0087.py::test_single_head tests/live/test_migration_0086.py::test_single_head
.....                                                                    [100%]
5 passed in 1.40s
```

Other completed focused checks recorded in the task history:

- `tests/egress/test_store.py` and `tests/egress/test_router.py`: **99 passed in 41.50s**.
- Real-child GStreamer log rotation/bounds and short-output-while-alive checks: **2 passed in 1.62s**.
- Native shared-drainer checks for drain/low-disk behavior: **2 passed in 1.71s**.
- `npx tsc -b --pretty false`: exit code **0**, before the final role-gate helper was added. Parent integration TypeScript/lint checks remain authoritative for the integrated tree.
- Focused Ruff checks and `git diff --check` on the scoped files completed without reported issues.

The exact shell invocations for the egress/native/Ruff checks were not retained in the available tool transcript, so they are identified by test scope and recorded summary only; no command text is reconstructed here.

## Teardown warning limitation

The first schema-check selection included `tests/test_schema_check.py::test_read_db_revision_raises_database_missing_error_on_invalid_catalog_name` and ended with **13 passed, 1 failed in 4.88s**. The failure was pytest teardown promotion of an unclosed SQLite connection (`PytestUnraisableExceptionWarning` / `ResourceWarning: unclosed database`), not a migration-head assertion failure.

A narrower selection that included `test_schema_check_reports_current_from_non_repo_working_directory` printed **6 passed in 1.76s** but also exited nonzero during teardown with the same unclosed SQLite connection warning. The final head-only command above omitted that DB-backed case and exited successfully with **5 passed**. No unrelated SQLite resource-lifecycle change was made.

## Independent recovery review

Read-only review of `daemon.py`, `supervisor.py`, `automation.py`, and the changed recovery tests found no concrete defect in the requested current-process cooldown/retry, failed-slate one-shot handling, stop/drain precedence through automation, or stderr rotation-offset compatibility. No tests were run as part of this review. The operator-stop latch is process-local; a full application restart loses it, so an `auto_start` channel may start again after restart.

## Documentation guidance

Document `/api/staff/egress/storage` and its role-gated System Health panel; worker logs are capped at 10 MiB with 10 backups per stream; consumed command history is pruned per channel in bounded batches while pending commands remain; low disk warns below 20 GiB free; output continues draining if log persistence fails. Record that this cleanup does not delete recordings.
