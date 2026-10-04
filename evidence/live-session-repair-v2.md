# Live meeting recovery repair — v2 retry-gate correction

2026-10-03, Mountain Time. This supersedes v1's finalization UI gating claim, not its other evidence or limitations. HEAD remains `588a7ec39ab0722a4273fde64034ecdba1d74b17`; exact current 16-file scope and SHA-256 snapshot is `live-session-source-manifest-v2.json`. No commit/push/deploy/station action.

Independent review correctly found that FinalizationPanel's Retry finalization could remain enabled for read-only staff or after an authoritative meeting read failed. Backend role checks protected the request, but the UI contradicted recovery's read-only/no-stale-mutation promise. The v1 implementation was not complete on this boundary.

FinalizationPanel now receives `canOperateMeeting` from the parent. Its only mutation (retry) requires that permission, an Ending session and successful session/finalization-status reads. The disabled button and mutation-function guard share that predicate. A plain explanation says retry is unavailable until a meeting operator successfully reopens current controls. No auth or transition backend code changed. The reviewer froze findings before this edit; their isolate/tests were not edited.

## RED/GREEN and affected checks

From operator directory `civiccast/apps/portal-operator`:

- `npm run test:unit -- src/screens/LiveRoomScreen.test.tsx -t 'disables finalization retry' 2>&1 | Tee-Object -FilePath C:\Dev\Claude\civiccast-u73\evidence\live-session-retry-gate-red.log`: `Tests  2 failed | 40 skipped (42)`. Both were assertion failures, `expected false to be true`, for records_clerk and failed authoritative session read. Complete raw RED retained.
- `npm run test:unit -- src/screens/LiveRoomScreen.test.tsx 2>&1 | Tee-Object -FilePath C:\Dev\Claude\civiccast-u73\evidence\live-session-retry-gate-green-final.log`: `Test Files  1 passed (1)` / `Tests  42 passed (42)` / `Duration  2.85s (transform 169ms, setup 161ms, import 271ms, tests 1.80s, environment 439ms)`. The read-error fixture initially assumed only one initial session read; the existing parent and FinalizationPanel each read once, so two initial successful reads are supplied before rejection. The initial post-fix fixture failure remains separately captured; it was not counted as product regression.
- `npm run build 2>&1 | Tee-Object -FilePath C:\Dev\Claude\civiccast-u73\evidence\live-session-retry-gate-build.log`: tsc exit 0; `181 modules transformed`, `built in 441ms`; LiveRoomScreen asset `LiveRoomScreen-Cqkpf46M.js`.
- `npx eslint src/screens/LiveRoomScreen.tsx src/screens/LiveRoomScreen.test.tsx`: exit 0, no output.
- `$env:CIVICCAST_PLAYWRIGHT_EXECUTABLE='C:\Program Files\Google\Chrome\Application\chrome.exe'; npx playwright test e2e/live-room.spec.ts --grep '@recovery|Beta B2' --workers=1 2>&1 | Tee-Object -FilePath C:\Dev\Claude\civiccast-u73\evidence\live-session-retry-gate-browser.log`: `4 passed (6.2s)`. Real isolated browser proves recovery, channel race, normal authorized ending retry and finalization retry after explicit click still work. All API calls remain fixture-intercepted, recovery cases assert no browser console/page errors. Node NO_COLOR/FORCE_COLOR warnings retained.

From repo root, canonical chapter and in-app help now describe the retry gate. `ops/docs-sprint/tools/build_manual.py --no-diagrams` and `scripts/render_docsite_manual.py` regenerated the assembled and built-in manual. `scripts/render_docsite_manual.py --check-current`: `render_docsite_manual: PASS - civiccast/docsite/manual.json is current.` Raw output: `live-session-retry-gate-manual.log`. `git diff --check` exit 0 with existing CRLF normalization warning. No OpenAPI contract changed in this correction, so its v1 reproducibility evidence remains applicable.

Changed since v1: LiveRoomScreen.tsx, LiveRoomScreen.test.tsx, canonical live chapter, in-app help/live and their assembled/built-in manual outputs. No new functional file scope. Source SHA-256: `049E14F6CC8557B29193470348115B1FEB1842349DED1F7AD7956B150136EB04`; test SHA-256: `C3AF1DA7BFB2389AE06C0A68925751D6E6FB0F201A5458319550322727433976`.

Full operator 1118-test and 14-browser evidence in v1 predates this correction; do not represent those counts as rerun against v2. Current affected checks are 42 unit and 4 browser tests. Baseline inherited failures, initial raw truncation, dependency-junction qualification, generated drift and station/runtime limitations remain as disclosed in v1. Independent corrected-snapshot rereview is still required; this report is not a self-issued PASS.

proved: retry-gate RED2/GREEN42, affected browser4, build/typecheck/eslint and manual reproducibility passed · lane: Critical.
