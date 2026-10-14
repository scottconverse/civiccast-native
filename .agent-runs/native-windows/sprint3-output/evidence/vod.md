# Sprint 3 item 11: recorded-caption settings evidence

Branch: `codex/sprint3-output-completion`
Workspace: `C:\Dev\Claude\civiccast-beta15-completion`

## Delivery

Added station settings `enabled`, `languages` (`en` always selected; optional `es`), and `completion_requirement` (`all_selected_languages` or `english_reviewed`). Defaults remain enabled, English plus Spanish, and all selected languages. Legacy environment values initialize defaults only until the station saves `offline-caption-settings.json` beside `station-state.json`; first Save writes the file even when values equal current defaults.

The settings are exposed at `GET/PUT /api/staff/captions/settings`, rendered in Setup > Station Profile, and read by the worker on each scan. Disabling settings skips new publish enqueue and pauses existing jobs in their current state. `english_reviewed` attaches only reviewed English while leaving the job active for selected Spanish translation/review; the job completes after Spanish is also reviewed and attached. English-only selected settings complete with reviewed English. The translation doctor text now follows the station settings. The existing backup inventory already includes JSON siblings of the station-state file; the focused backup test now asserts this file is present in an archive.

No live station configuration or services were changed. No commit, push, generated OpenAPI artifact, or generated/manual docs were produced; docs/OpenAPI remain with the parent owner. Supported translation languages remain the implemented English and Spanish only.

## Baseline

- `& '.venv\Scripts\python.exe' -m pytest tests/captions/test_offline_caption_job.py tests/captions/test_offline_caption_job_router.py tests/captions/test_offline_caption_job_persistence.py -q` — 95 passed in 12.77s.
- From `civiccast\apps\portal-operator`: `npm run test:unit -- src/screens/StationProfileScreen.test.tsx` — 24 passed in 16.53s (jsdom emitted its existing unsupported-navigation diagnostic).

## Final focused checks

- `.\.venv\Scripts\python.exe -m pytest tests/captions/test_offline_caption_job.py tests/captions/test_offline_caption_job_router.py tests/captions/test_offline_caption_job_persistence.py tests/captions/test_recorded_caption_settings.py tests/captions/test_doctor_translation_check.py tests/publish/test_offline_caption_enqueue.py tests/dr/test_station_backup_runtime.py::test_runtime_backup_includes_station_state_and_portable_credentials -q` — 119 passed in 17.79s.
- From `civiccast\apps\portal-operator`: `npm run test:unit -- src/screens/StationProfileScreen.test.tsx` — 26 passed in 2.30s (jsdom emitted its existing unsupported-navigation diagnostic).
- From `civiccast\apps\portal-operator`: `npx tsc -b --pretty false` — passed.
- `.\.venv\Scripts\ruff.exe check civiccast/app.py civiccast/captions/settings.py civiccast/captions/settings_router.py civiccast/captions/vod_job.py civiccast/publish/router.py civiccast/cli.py tests/captions/test_offline_caption_job.py tests/captions/test_recorded_caption_settings.py tests/captions/test_doctor_translation_check.py tests/publish/test_offline_caption_enqueue.py tests/dr/test_station_backup_runtime.py` — all checks passed.
- `.\.venv\Scripts\ruff.exe format --check civiccast/app.py civiccast/captions/settings.py civiccast/captions/settings_router.py civiccast/captions/vod_job.py civiccast/publish/router.py civiccast/cli.py tests/captions/test_offline_caption_job.py tests/captions/test_recorded_caption_settings.py tests/captions/test_doctor_translation_check.py tests/publish/test_offline_caption_enqueue.py tests/dr/test_station_backup_runtime.py` — 11 files already formatted.
- `git diff --check` — passed; Git reported existing CRLF-to-LF notices for parent-owned manual files `docs/manual/src/22-configuration.md` and `docs/manual/src/30-architecture.md`.

## Correction trail and limits

The first expanded Python run had nine publish-test failures because this machine's `CIVICCAST_STAFF_TOKENS` environment setting shadows the repository's deterministic test token. The publish test module now clears that setting with `monkeypatch` per test; rerun passed. Initial UI test runs exposed an ambiguous Spanish label and React Query's second mutation-context argument; the checkbox now has an explicit accessible label and the focused test assertions account for the context; rerun passed. Initial Ruff formatting check identified five changed Python files; those files were formatted and the final check passed. `npm run typecheck` is not a script in this package; `npx tsc -b --pretty false` is the package's TypeScript check and passed.

Checks were limited to the caption/settings/API, publish enqueue, doctor, backup inventory, Station Profile UI, Python lint/format, and TypeScript compile paths. No broad test suite, service soak, or production config operation was run.

## Focused CDN retry correction

The parent review found that English-first publication could fail its CDN
republish after writing the edited local sidecar, then skip the CDN retry on the
next pass because `published_cue_count` and the now-current sidecar matched.
The worker now marks this specific failure in the existing `last_error` field
and retries the idempotent local attach plus CDN upload while that marker remains.
Successful retry replaces the marker with the normal Spanish-waiting reason; no
database schema changed.

Baseline before adding the regression:

```text
python -m pytest tests/captions/test_offline_caption_job.py::TestCaptionLanguageSettings::test_english_reviewed_attaches_first_and_job_finishes_after_spanish_review tests/captions/test_offline_caption_job.py::TestCdnRepublishGatesCompletion -q
3 passed in 1.27s
```

The new focused regression was observed failing before the fix:

```text
python -m pytest tests/captions/test_offline_caption_job.py::TestCdnRepublishGatesCompletion::test_english_first_cdn_failure_is_retried_after_local_edit_is_written -q
1 failed in 1.73s
```

The failed assertion was `republisher.calls == 3`; the retry made only two
uploads, confirming it skipped the CDN upload after the local sidecar had been
updated.

After the fix, the regression passed:

```text
python -m pytest tests/captions/test_offline_caption_job.py::TestCdnRepublishGatesCompletion::test_english_first_cdn_failure_is_retried_after_local_edit_is_written -q
1 passed in 1.23s
```

The affected CDN and English-first tests passed:

```text
python -m pytest tests/captions/test_offline_caption_job.py::TestCdnRepublishGatesCompletion tests/captions/test_offline_caption_job.py::TestCaptionLanguageSettings::test_english_reviewed_attaches_first_and_job_finishes_after_spanish_review -q
4 passed in 1.50s
```

Focused lint and formatting passed:

```text
python -m ruff check civiccast/captions/vod_job.py tests/captions/test_offline_caption_job.py
All checks passed!

python -m ruff format --check civiccast/captions/vod_job.py tests/captions/test_offline_caption_job.py
2 files already formatted
```



