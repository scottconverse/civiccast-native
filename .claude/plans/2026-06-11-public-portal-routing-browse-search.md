# Public Portal Routing/Detail/Browse/Search/Pagination (issue #107) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** Turn the single-page `?manifest=` player into a small multi-view portal: hash routing, a recording detail page with canonical shareable URLs, a browse view with search + date filter + pagination, while keeping every existing empty/loading/error state, the subscribe/contribute flows, analytics posture, and the legacy `?manifest=` path intact.

**Verified current state:** `apps/portal-public/src/App.tsx` (970 lines) renders everything on `/` and only reads `?manifest=`. Backend already serves `GET /api/public/assets` (full list) and `GET /api/public/assets/{asset_id}` (404-safe detail) — no backend change needed. `AssetMetadata` has NO meeting-body/category field, so the issue's "browse by meeting/body/category" facet is **blocked on a product taxonomy decision** (which field, who sets it) — implemented facets are publish-year + free-text search; the gap is reported honestly in the PR, not invented.

**Design:**
- Hash routing (consistent with the operator console; works on any static host with zero rewrite rules), hand-rolled (~40 lines, no new dependency — smaller bundle for residents):
  - `#/` home — live now, coming up, the 6 newest recordings + "Browse all recordings" link, follow + contribute sections (existing content).
  - `#/recordings?q=&year=&page=` browse — search over title+description (client-side; the archive list is already fully fetched), year facet derived from `published_at`, 12-per-page pagination, all state in the hash query so every browse view is a shareable URL.
  - `#/watch/{asset_id}` detail — fetches the single-asset endpoint, HLS player, title/description/published/duration, a copy-canonical-link button, not-found state on 404.
  - Legacy `?manifest=` override keeps its exact current behavior (cleanroom e2e + operator resident-preview depend on it).
- File split (App.tsx is over capacity): `src/types.ts` (shared interfaces), `src/api.ts` (fetchJson/postJson/postForm + formatters), `src/router.ts` (parse/build hash routes + useHashRoute hook), `src/screens/HomeScreen.tsx`, `src/screens/RecordingsScreen.tsx`, `src/screens/WatchScreen.tsx`; `App.tsx` keeps the shell (header/nav/route switch/emergency overlay) plus the subscribe/contribute sections it owns today (rendered on Home).
- Analytics: keep one `schedule_browse` per view load (`portal_home`, `recordings_browse`, `watch_recording`, `watch_manifest_override`) — same fail-silent posture.
- Keep a11y: nav landmarks, focus handling on route change (move focus to the view heading), all new interactive elements ≥44px targets like existing.

**Tests (Playwright, mock-routed like a11y.spec.ts):** new `e2e/routing.spec.ts`:
1. Home shows live/coming-up/recent and nav; "Browse all recordings" navigates to `#/recordings`.
2. Browse lists recordings, search filters (incl. zero-result empty state), year facet filters, pagination pages and is reflected in the URL (deep-link to `#/recordings?q=...&page=2` restores state).
3. Card click → `#/watch/{id}` detail with title/description/player mount; deep-link directly to a watch URL works (canonical/shareable); unknown id shows the not-found state.
4. Legacy `?manifest=` still renders the override player.
5. Existing a11y spec extended: axe pass on browse + watch views.
6. Existing error/empty/loading assertions stay green (a11y.spec.ts untouched behavior).

**Branch:** `work/portal-routing` from `main`.

### Tasks
1. Extract `types.ts` / `api.ts` / `router.ts` (pure refactor, no behavior change) — build green, e2e a11y spec still passes. Commit.
2. Route shell in App.tsx + HomeScreen extraction (home identical to today, plus nav + recent-6 cap + browse link). Playwright: home + legacy manifest tests. Commit.
3. RecordingsScreen (search/year/pagination, URL state, empty states). Playwright browse tests. Commit.
4. WatchScreen (detail fetch, player, share link, 404 state) + card links point at `#/watch/{id}` (replacing `/?manifest=` links) while the manifest override path stays supported. Playwright watch tests. Commit.
5. Axe pass on new views; full portal-public `npm run test:a11y`; operator-console `prepare:public-portal`-dependent specs unaffected (resident preview uses home). Full backend gate (portal dist not part of pytest, but run for repo health). Docs truth: CAPABILITIES.md public-portal row + known-limitations if it mentions the single-page shape. PR `closes #107` with the honest body/category-facet gap note. Merge.
