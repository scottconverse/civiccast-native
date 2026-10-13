# Scheduling verification (provisional; cutoff-date fix pending)

Focused regression sensitivity:

- `uv run pytest tests/schedule/test_autoschedule_materializer.py::test_compile_window_starts_on_station_local_date -q` — RED before the fix: 1 failed on the expected local date assertion. At `2026-01-01 00:30 UTC`, the old UTC anchor produced `2026-01-01 18:00 Pacific/Honolulu`; expected was `2025-12-31 18:00`.

Corrected focused checks (independent re-review pending):

- `python -m pytest tests/programlog/test_materializer.py tests/recording/test_service.py tests/schedule/test_autoschedule_materializer.py tests/schedule/test_autoschedule_worker.py tests/schedule/test_autoschedule_compile.py -q` — `115 passed in 4.64s`.
- `python -m ruff check civiccast/programlog/materializer.py civiccast/recording/service.py civiccast/schedule/autoschedule_materializer.py civiccast/schedule/autoschedule_service.py civiccast/schedule/autoschedule_worker.py tests/programlog/test_materializer.py tests/recording/test_service.py tests/schedule/test_autoschedule_materializer.py` — `All checks passed!`.
- From `civiccast/apps/portal-operator`: `npm run test:unit -- src/components/schedule/ScheduleDrawer.test.tsx` — `Test Files  1 passed (1)`; `Tests  9 passed (9)`.
- From `civiccast/apps/portal-operator`: `npx eslint src/components/schedule/ScheduleDrawer.tsx` — exit 0, no output.
