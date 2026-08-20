# CA-5: Program Guide Editor + Resident Schedule — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Part of the cable-automation sprint (master: 2026-06-11-cable-automation-sprint-master.md). CA-1=#141, CA-2=#142, CA-3=#143, CA-4=#144.

**Goal:** The clerk-facing heart of the PEG automation system: place recordings on a channel's recurring weekly guide from the operator console, flip a channel to 24/7 with filler policy, moderate community bulletins — and residents see the channel schedule on the portal. After CA-5, the whole cable lane is operable without touching an API.

**Decisions on the exploration's open questions:**
1. Residents see ONLY airable programming (status=scheduled), never skips/internal detail → new sanitized public endpoint.
2. Recurrence UI = radio (once/daily/weekly/weekdays) + datetime-local first start + optional repeat-until — mirrors the backend model exactly.
3. auto_start/fill_policy edit lands on ChannelOpsScreen next to the existing EgressControlPanel (config PUT is already setup_admin-gated; consistent).
4. Bulletin moderation UI IS in scope (CgBoardScreen panel) — without it, fill_policy=bulletins is API-only and fails Scott's "coherent, easy to operate" bar.

**Pieces (exploration-verified integration points):**
- **Backend:** `public_router` in `civiccast/programlog/router.py`: `GET /api/public/programlog/channels/{channel_id}/guide?hours=` → sanitized entries (display title = title_override or asset title joined server-side, start, duration; scheduled-only; no skip details/ids). TDD in tests/programlog/test_router.py.
- **Operator console** (template: ScheduleScreen + ScheduleDrawer patterns; route registration App.tsx ROUTE_PATHS + Sidebar RouteId/NAV_SECTIONS "Run Meeting"):
  - New `ProgramGuideScreen` (`/guide`): channel selector, 7-day merged log (incl. skip rows with reasons styled as warnings + the materialize "Refresh guide" button), slot list with disable, create-slot drawer (asset picker, recurrence radio, datetime-local w/ the existing local↔UTC helpers, repeat-until).
  - `ChannelOpsScreen`: new Egress Configuration panel — auto_start toggle + fill_policy radio (+ slate message edit), GET/PUT config client functions.
  - `CgBoardScreen`: Community Bulletins panel — list (all states), add, approve (operator id from staff identity), request-changes/decline with notes.
  - New client functions in api/client.ts (slot CRUD, channel log, materialize, egress config get/put, bulletins CRUD) — generated types already present after the CA-1..4 OpenAPI regens.
- **Public portal:** `#/schedule` view (channel guide from the public endpoint, channel tabs from /api/public/... — use the existing coming-up channel default 'public' + a simple channel param), nav link; extend router union + routing.spec.ts.
- **e2e:** new `e2e/program-guide.spec.ts` (mock-routed: slot create incl. recurrence, log rendering incl. skip warning, refresh trigger), ChannelOps config panel assertions, CgBoard bulletin moderation flow, portal-public schedule view test. Template: schedule.spec.ts.
- **Docs:** USER-MANUAL admin/operator sections gain "Program guide" + "Community bulletins" + "Run a channel 24/7" walkthroughs; CAPABILITIES channel-automation row updated (operable end-to-end from the console).

**Steps:** branch `work/ca5-program-guide` → backend public endpoint (TDD) → client fns → ProgramGuideScreen → ChannelOps config panel → CgBoard bulletins panel → portal #/schedule → e2e all four → OpenAPI regen + docs → builds + Playwright suites + full backend gate → PR → merge.
