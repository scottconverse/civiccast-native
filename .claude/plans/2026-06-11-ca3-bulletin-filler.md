# CA-3: Bulletin Filler — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Part of the cable-automation sprint (master: 2026-06-11-cable-automation-sprint-master.md). CA-1 = #141 (program log), CA-2 = channel automation driver.

**Goal:** Gaps between scheduled programs show rotating community bulletin slides (the incumbent PEG platform's "bulletin board" role) instead of the bare slate — operator-managed, per-channel opt-in, honest fallback to slate when there's nothing approved.

**Verified current state (subagent deep-read 2026-06-11):**
- Bulletin lifecycle is fully MODELED (`CgBulletinSubmission`: submitted→needs_changes→accepted/declined→scheduled, approval + moderation metadata, zone targeting) but **contract-only**: `build_bulletin_queue()` returns deterministic mock data per request; there is NO durable bulletin store. CA-3 must make bulletins real before rendering them.
- NO snapshot→video renderer exists anywhere. The only video generation precedent is `SlateSourceGenerator` (lavfi color + drawtext → MPEG-TS, with a no-text retry).
- The `fallback_source_provider` seam (`Callable[[EgressConfig], EgressSourcePlan]`, daemon.py:57) accepts a richer filler with ZERO daemon changes — CA-2's `build_channel_automation` wires it.
- `ChannelBranding` (display_name/short_name/color/logo_text) exists for on-brand slides; not yet consumed by any renderer.

**Design (locked):**
1. **Durable bulletins — migration `0033_cg_bulletins`** (parent 0032): `cg_bulletins` table mirroring `CgBulletinSubmission` (submission_id PK, channel_id, organization, title, message, target_zone_kind, state CHECK, approved_by_operator, moderation_notes, requested_start/end, created_at/updated_at). `PostgresCgBulletinStore` + staff CRUD (`/api/staff/cg/channels/{id}/bulletins` POST/PATCH state transitions enforcing the modeled approval rules); the existing public bulletin-queue endpoint reads durable APPROVED rows when storage is active (deterministic mock stays for ephemeral mode — same posture as every other store).
2. **Renderer — `BulletinFillerSourceGenerator`** (`civiccast/egress/bulletin_filler.py`), Option C from the exploration: pure-ffmpeg slide generation, no new dependencies (no headless browser). Per approved bulletin: one ~10s MPEG-TS slide — channel-branding background color, station short_name bug, drawtext title + body (Python `textwrap` pre-wrapping; drawtext multiline via wrapped literal text; reuse `_escape_drawtext`). Segments concatenate into the rotation `[slide1..slideN]` (the concat encoder already plays segment lists). Content-hash caching: slides regenerate only when the approved set changes (hash in the filename). Zero approved bulletins → delegate to `SlateSourceGenerator` (never a blank or stale board). drawtext-failure retry mirrors the slate generator.
3. **Per-channel opt-in — `fill_policy`** on egress_configs (same migration 0033): `'slate'` (default, today's behavior) | `'bulletins'`. `EgressConfig.fill_policy` flows through the config API like `auto_start` did.
4. **Wiring:** a `FillerSourceProvider` composite used by `build_channel_automation` (and the CLI): receives `EgressConfig`, branches on `fill_policy` — bulletins (with slate delegate inside) or slate. Channel branding resolved from the cable channel profile when available, else from config defaults.

**Tests (TDD):**
- Store: round-trip + state-transition rules (approve requires operator id; decline requires notes) on sqlite; migration head-pin advance to `0033_cg_bulletins`; real-Postgres upgrade covered by the existing head test.
- Renderer: ffmpeg arg construction per slide (branding color, wrapped text, escaping), one segment per approved bulletin in queue order, content-hash cache (same set → no re-render; changed set → new files), zero-approved → slate delegation, drawtext-failure retry, ffmpeg-failure raises. Fake ffmpeg runner exactly like the slate tests.
- Composite provider: fill_policy branching; bulletins policy with no approved rows → slate plan.
- API: CRUD + transition guards + public queue serves durable approved rows.

**Steps:** branch `work/ca3-bulletin-filler` → failing tests → migration+store → staff CRUD + public queue read-through → renderer → composite provider + automation/CLI wiring → OpenAPI regen + docs (background-workers note, USER-MANUAL bulletin section, CAPABILITIES cg row honesty) → full gate → PR → merge.

**Honest boundary:** slides are ffmpeg-rendered text boards (titles/messages on brand colors) — not the full multi-zone template renderer (tickers, feeds, schedule zones). That render engine remains the documented gap in the CG row; this stage ships the PEG automation community bulletin rotation.
