# Build Step 7 — CG Bulletin-Board Designer (S6 V1) + CG depth (S18 gap 6)

**Branch:** `work/3.0-gstreamer-engine`. **Parity gap:** 6 (CG / CasparCG).
**Spec:** `civiccast-3.0-spec/sections/S6-cg-bulletin-board-designer.md` (+ its "CG depth" parity addendum).
**Migration head (verified 2026-06-16):** `0043_scheduling_automation` (nothing parents it → single head).

## Reality check (trust the code, not the spec)
Verified by reading `civiccast/cg/`:
- **Exists (contract + bulletin persistence):** `cg/models.py` (IdlePage, EmergencyOverlay, CgTemplate,
  CgZone, CgFeedAdapter/Item/Catalog, CgBulletinSubmission/Queue, MultiZoneCgSnapshot, CgPortalDisplay,
  render-plan/overlay contracts); `cg/bulletin_store.py` (`CgBulletinDb` + `PostgresCgBulletinStore`
  create/get/update/list/list_approved); `cg/migrations/versions/0033_cg_bulletins.py`; `cg/router.py`
  (public render endpoints + staff bulletin CRUD via `get_cg_bulletin_store` DI seam); `cg/service.py`
  (deterministic builders); `egress/bulletin_filler.py`, `egress/cg_bridge.py`, `egress/cg_source.py`,
  `egress/branding.py`; `EgressConfig.fill_policy` ("slate"|"bulletins"); `CgBoardScreen.tsx`.
- **NET-NEW (this step):** the board-designer durable layer + CG depth. `CgBoard`, `CgZoneConfig`,
  `CgFeedSource`, `CgBoardAuditEvent`, `cg_feed_item_approvals`; board CRUD APIs; board→snapshot resolver;
  on-demand feed fetcher; filler time-window + expiration; 5 operator screens; then CG depth
  (BulletinMedia/BulletinAudio/ZoneTag + program-aware interstitials).

## Scope discipline
- On-channel COMPOSITING is **S15 (GStreamer engine, already built)**. S6 produces the
  `MultiZoneCgSnapshot` and hands it to the engine via the `cg_bridge` contract. We build the
  authoring/management layer + engine-bridge wiring to **code-complete + machine-verified at unit/contract
  level**; live composite proofs (DC-CG1 live-video, DC-CG2 bg-audio-under-loudness) are **lab/WSL-tier**
  → routed to the WSL/tester lane (not claimed inline), consistent with prior engine proofs.
- CasparCG = optional GPLv3 premium co-process bridged via NDI/SDI — **not required**; the
  compositor/WPE path is primary. (S9-4 deferred durable co-process pid tracking "to step 7 / CasparCG"
  — only build it if a real CasparCG co-process consumer lands here; otherwise carry the named deferral.)
- Custom operator-uploaded templates (JSON/WPE bundles) = OUT of V1 (spec open-decision 3).

## Slices (per-slice cadence each: build → verify (ruff+pytest/vitest, fail-closed) → audit-lite 0/0/0/0/0
##  → commit → update cursor → re-arm watchdog. OpenAPI --check when router/types change.)

1. **Board-designer DATA LAYER** — models (CgBoard, CgZoneConfig, CgFeedSource, CgBoardAuditEvent +
   feed-item-approval) + `...Db` ORM + stores (`PostgresCgBoardStore` etc.) in `cg/board_store.py`;
   **migration `0044_cg_board_designer`** (parent `0043_scheduling_automation`; tables cg_boards,
   cg_zone_configs, cg_feed_sources, cg_board_audit, cg_feed_item_approvals; both head-pins → 0044).
   No hard FKs (soft string refs, app-layer integrity — matches the schedule/cg convention). Unit tests:
   store CRUD round-trip, validators, migration up/down reversibility (SQLite reflection).

2. **Board resolution + feed fetcher** — `cg/board_resolver.py`: load active board → zones → feed sources
   → build `MultiZoneCgSnapshot`. `cg/feed_fetcher.py`: on-demand fetch rss/ical/caldav/weather/social
   with cache + `last_fetch_error` capture (open-decision 1 = on-demand+cache). Bulletin time-window
   enforcement helper. Pure/read-only. Unit tests (mock feeds; window filter; resolver missing-board).

3. **Staff CRUD APIs** — `cg/board_router.py` (or extend `cg/router.py`): board GET/POST/PATCH; zones
   POST/PATCH/DELETE; feeds GET/POST/PATCH/DELETE; zone-override PATCH; preview GET; audit GET. Role gate
   `require_any_role("setup_admin","publish_operator")` (+ support_admin on reads). DI seams returning None
   at import + app `dependency_overrides` (lifespan + `_install_durable_store_wiring` hot-wire BOTH, per
   the step-6 ENG-001 lesson). OpenAPI regen + --check. Router tests (real role-gate + service).

4. **Filler integration + expiration + approval gate** — board-config-aware `bulletin_filler` (time-window:
   show accepted/scheduled within [start,end); skip expired); daily expiration cleanup job; feed-item
   approval gate (zones with approval_required hide unapproved items). Filler tests + empty→slate fallback.

5. **Operator UI (5 phone-first screens)** — Bulletin Moderation Queue, Board Layout Designer, Feed Manager,
   Live Preview, Board Settings & History. API client methods + `cg-board-format.ts` helpers + nav. Role-gate
   FAIL-CLOSED. vitest + lint + tsc + build. (Preview not browser-driveable in-harness → verify at toolchain.)

6. **CG depth backend (S18 gap 6)** — BulletinMedia (uploaded_image/fullscreen_slide/live_video),
   BulletinAudio (bulletin|channel bg bed, loudness_regime), ZoneTag + CgZoneConfig.allowed_tags;
   program-aware interstitial feed-kind reading the program log (S4) for "Coming Up Next". **migration
   `0045_cg_depth`** (parent 0044; bulletin_media, bulletin_audio, zone_tags; both head-pins → 0045). Tests:
   DC-CG3 (allowed_tags filter — contract), DC-CG4 (coming-up-next interstitial — contract). DC-CG1/DC-CG2
   (live composite / bg-audio loudness) = engine-bridge contract here, live proof = WSL/tester lane.

7. **CG depth UI + engine-bridge wiring** — surface media/audio/tags in the designer; wire snapshot→engine
   compositor path (cg_bridge) for the new kinds; live-video zone source binding. vitest + lint + build.

**Step-7 CLOSE:** stage report → /walkthrough (wiring cross-check) + /audit-team (capped ≤10 agents,
balanced) → fix every finding to 0/0/0/0/0 → re-run full backend suite (audit-sprint-1 venv) +
portal test:unit/lint/build → push → step 7 CLOSED → build step 8 (OTT apps S12, code-only).

## Runner / verify notes
- Backend: `C:\CivicCastTester\tools\venvs\audit-sprint-1\Scripts\python.exe -m pytest` (pytest 9.0.3,
  starlette 1.2.1 — NOT system Python 3.12, whose newer starlette breaks collection). No `--timeout` (no
  pytest-timeout). ffmpeg absent on this PATH → 4 pre-existing non-step failures (2 captions ffmpeg, 2
  programlog task_cc174c66) are EXCLUDED.
- Frontend: `$env:PATH="C:\CivicCastTester\tools\node-v24.14.0-win-x64;$env:PATH"` then
  `cd civiccast/apps/portal-operator; npm run test:unit; npm run lint; npm run build`.
- Commit: write msg to `.git/CC_COMMIT_MSG.txt` then `git commit -F` (PowerShell mangles here-strings).
