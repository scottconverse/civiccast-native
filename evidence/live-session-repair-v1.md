# Live meeting recovery repair — v1

2026-10-03, Mountain Time. Source checkout: `C:\Dev\Claude\civiccast-u73`, HEAD `588a7ec39ab0722a4273fde64034ecdba1d74b17` plus the uncommitted files hashed in `live-session-source-manifest.json`. Independent review is required; this is implementation evidence, not candidate certification. No commit, push, installation, publication, or station broadcast action was performed.

## Operator result

New meetings use unique IDs, including browsers where LAN HTTP has no `crypto.randomUUID` (cryptographic `getRandomValues` UUID fallback). After the selected session is Recorded and there are no unfinished meetings on that channel, Create live session is enabled and styled as an available action. Ending/finalization failure is not mistaken for completion.

After refresh or same-tab navigation, choose the channel and explicitly select the correct Existing meeting by its ID and state. No meeting is silently chosen. Discovery reads only Idle, Pre-flight, On air and Ending rows; completed recordings remain in Assets. Selected state comes from the server GET/query cache and polls every three seconds. Discovery polls every ten seconds and excludes completed history in the store SQL filter. There is no schema/migration change or browser-storage-only recovery.

Recovery never creates, starts, ends, retries finalization or takes over automatically. Choosing another channel clears selection, pending confirmation and preflight results; delayed get/create/action responses cannot repopulate old-channel controls. Recovered Pre-flight requires new confirmation and checklist evaluation. List/read failures offer explicit retry and block replacement creation or stale mutations. Session recovery remains available when source configuration is empty, loading or failed.

The existing global staff bearer middleware protects the new GET list. Read-only staff can inspect meetings but cannot operate them; create/start/end and preflight fences are unchanged. Backend tests use real global middleware and valid generated test bearers, prove missing Authorization receives 401 and records_clerk create receives 403. No auth environment was cleared to make tests pass.

## Scope and trace

Only live screen/client/router/test surfaces, affected canonical manual/help/CHANGELOG and reproducible generated docs changed. The pre-existing oversight ledger was left untouched. Exact 16-file scope and SHA-256 hashes: `live-session-source-manifest.json`.

Callers: App.tsx mounts LiveRoomScreen at `/live`; createLiveSession/getLiveSession are used by the screen and FinalizationPanel; existing e2e fixtures exercise the same client routes. New listLiveSessions is consumed by sessionsQuery. The synchronous FastAPI route calls existing synchronous LiveSessionStore.list_sessions, run through the request threadpool; no lock or async boundary was added. The store already supports SQL channel/state filters and deterministic ordering. Public `/current` was deliberately not reused: it only projects on-air state and chooses newest, which would hide ambiguity.

Data contract: additive staff `GET /api/staff/live/sessions?channel_id=<required>` returns `LiveSessionResponse[]` containing unfinished sessions on that channel. No existing payload, response or state transition changed. Rendering trace: choose Existing meeting → selected ID/query GET → validate ID/channel → session state drives controls/finalization. Errors and recovery/loading/multiple/empty messages are rendered in Session controls. Query keys include channel and session ID; contextVersion fences in-flight mutations.

Rollback is bounded to these source/docs changes and regeneration; no persisted session is rewritten or deleted by discovery. Returning to older UI would lose recovery controls, not roll back existing server sessions. Root owns integration and any rollback execution.

## Verification receipts

Commands below ran from the repo root unless marked operator directory (`civiccast/apps/portal-operator`). Raw logs retain warnings/errors, not just PASS counts.

- Baseline `.venv/Scripts/python.exe -m pytest tests/live/test_router.py tests/live/test_store.py -q`: `83 failed, 73 passed in 61.63s (0:01:01)`. First failure: test_router.py:307 expected 201, received 401; existing fixture sent no Authorization. Full output was truncated by the tool and was not retained as a complete raw file. This inherited red baseline is not a green claim. A focused first-failure rerun confirmed `1 failed in 4.44s` and the same 401. The broad inherited red suite was not rerun to manufacture green.
- Baseline operator `npm run test:unit -- src/screens/LiveRoomScreen.test.tsx`: `Tests  27 passed (27)`.
- Primary RED: refresh/remount test could not find Existing meeting; repeated-meeting test observed Create disabled after Recorded. Backend valid-bearer list returned 405 instead of expected 200. These failures are in the tool record; complete raw files for those initial runs were not captured. Do not overstate their raw-evidence completeness.
- Additional assertion RED captured fully: `live-session-empty-source-red-assertion.log` (missing recovery selector with no configured source); `live-session-lan-uuid-red.log` (randomUUID absent, expected create call 1, got 0). Earlier empty-source attempts were invalid fixture REDs and are separately retained, not counted as sensitive bug proofs.
- Final operator `npm run test:unit -- src/screens/LiveRoomScreen.test.tsx`: `Tests  40 passed (40)`; `live-session-ui-lan-green.log`.
- Final operator `npm run test:unit`: `Test Files  93 passed (93)` / `Tests  1118 passed (1118)` / `Duration  13.16s (transform 9.96s, setup 18.29s, import 19.50s, tests 55.93s, environment 65.42s)`; `live-session-full-ui-final.log`. Existing jsdom unsupported navigation stderr remains, fully captured; this is not a console-clean claim for the whole unit suite.
- `.venv/Scripts/python.exe -m pytest tests/live/test_router.py -k TestSessionRecovery -q`: `3 passed, 103 deselected in 6.01s`; `live-session-backend-final.log`. Exercises real middleware, channel isolation, read-only access, no mutation, missing channel, missing Authorization, and ending included/recorded excluded.
- `.venv/Scripts/python.exe -m pytest tests/live/test_store.py -q`: `53 passed in 2.70s`; `live-session-store.log`.
- Operator `npm run build`: tsc exit 0; Vite `181 modules transformed`, `built in 458ms`; `live-session-build-final.log`. LiveRoomScreen built asset `LiveRoomScreen-C7ptowfw.js`. No installed station bundle was rebuilt/deployed.
- Operator `npx eslint src/screens/LiveRoomScreen.tsx src/screens/LiveRoomScreen.test.tsx src/api/client.ts e2e/live-room.spec.ts`: exit 0; `live-session-eslint-final.log`. Python `ruff check civiccast/live/router.py tests/live/test_router.py`: `All checks passed!`; `live-session-ruff-final.log`.
- Final actual browser command (operator directory): `$env:CIVICCAST_PLAYWRIGHT_EXECUTABLE='C:\Program Files\Google\Chrome\Application\chrome.exe'; npx playwright test e2e/live-room.spec.ts --workers=1 2>&1 | Tee-Object -FilePath C:\Dev\Claude\civiccast-u73\evidence\live-session-all-browser-verified.log`: `14 passed (12.7s)`. Chrome `154.0.8037.97`. Recovery cases assert no browser page/console errors and save `recovery.png` in Playwright test-results. Tests intercept all API requests; no station dependency. First managed-browser launch failed because Chromium headless-shell 1217 was absent; the installed Chrome route then passed. Earlier broad fixture runs exposed changed-contract assertions and a typed-list fixture issue; each failure is retained, diagnosed and updated to assert the new intended behavior, not skipped. Some earlier incomplete legacy fixtures attempted reads to an unavailable loopback backend (ECONNREFUSED); none succeeded or issued station mutations. Final consolidated browser run has no such proxy errors. Node NO_COLOR/FORCE_COLOR warnings remain in the raw log.
- `.venv/Scripts/python.exe ops/docs-sprint/tools/build_manual.py --no-diagrams` assembled the canonical chapters; `.venv/Scripts/python.exe scripts/render_docsite_manual.py` regenerated the built-in manual; `--check-current`: `render_docsite_manual: PASS - civiccast/docsite/manual.json is current.` (`live-session-manual-repro-final.log`). Cached diagrams were preserved; PDF/DOCX were not rendered.
- `.venv/Scripts/python.exe scripts/generate-openapi-artifacts.py` regenerated schema/types/API reference; `--check` exit 0 (`live-session-openapi-repro.log`). Generator warnings about ephemeral stores and missing packaged portal paths are retained; they do not prove a station runtime. `git diff --check` exit 0, with Git's manual.render.json CRLF normalization warning.

Dependencies reused the existing node_modules junction to the recorded civiccast-native frontend dependency tree; Vitest reported 4.1.9 and Vite 8.1.0. This is current-source build/test proof (cwd and built artifact are this checkout), not a fresh lockfile npm-ci proof. No dependencies were installed or changed.

## Generated drift, independently classified

Reproducible regeneration also picks up inherited current-source changes: summary review `include_approved` and `approval_required_summary_ids` (summary/router.py:103,125); auto-schedule's published/approval description (schedule/autoschedule_router.py:421-422); canonical summary manual chapter text already present at HEAD but absent from the assembled manual. Those runtime/source chapters were not edited by this task. Root selected keeping full reproducible generator output, rather than hand-editing generated artifacts.

## Review status and limits

Five-lens self-review: engineering traces and channel/race/error/auth tests pass; UX loading/empty/multiple/retry states explicit; tests sensitive REDs recorded as above; canonical/assembled/help/generated docs agree; QA real isolated browser covers recovery, refresh, same-tab return, delayed old channel, finalization retry, absent configuration and existing preflight/role/accessibility cases. Root review identified randomUUID origin support and disabled-action styling; both were repaired with fallback RED/GREEN and named predicate.

Independent review remains required. No clean-machine installer, station refresh/restart, real live broadcast, recorder/file delivery, long soak, PostgreSQL concurrency, public portal feed or deployment claim is made. Discovery filters completed history but intentionally does not cap unfinished rows or silently omit old idle meetings. It does not solve abandoned-session cancellation or simultaneous creation by separate operators. Existing generic action-error advice and misleading start/end feed wording remain documented outside this repair; existing backend fences are unchanged.

proved: focused UI40, full operator1118, backend recovery3, store53, browser14, build/typecheck/lint and generated reproducibility passed; inherited backend auth-fixture failures remain · lane: Critical.
