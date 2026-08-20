# Build Step 9 — S16 Production Control Room + S17 Remote Contribution (+ S5 instant-cut + DI dedupe)

**Branch:** `work/3.0-gstreamer-engine` (head `d859df2` at start).
**Authored:** 2026-06-16. Migration head verified: `0046_cg_feed_source_tags`.

## Scope (Scott-approved resume order)
Step 9 = four coupled pieces. Build ALL the software; only real-device rung-1 proofs go to the single LPM punch list.

### Slice 0 — DI dedupe (foundation)
Two duplicated wiring paths in `app.py`: `create_app()` lifespan (~936–1142) and `_install_durable_store_wiring()` (~1191–1359) define identical `_resolve_*` resolvers + re-register 18+ `dependency_overrides` each. A resolver added to one path but not the other → 503 until restart (ENG-001).
- Extract `_wire_all_services(app, session_factory)` (+ `_wire_store_bundle` if needed) called from BOTH paths.
- Regression: app boot with DATABASE_URL at startup AND at runtime both register every override; full existing suite green.

### Slice 1 — S5 instant-cut live leg (finish the Stage-1 named deferral)
The only stub: `gst/strategy.py:157-165` `swap_role("live")` raises NotImplementedError; `graph_from_config` builds only `(program, slate)`; `engine.swap_source(2)` IndexErrors.
- READ the real supervisor/strategy/engine code first (resolve the content-reload-vs-swap ambiguity agent A reported).
- `graph_from_config`: add a 3rd always-hot live `SourceLeg` at `sources[2]`.
- `engine.py`: build the live leg, connect to input-selector `sink_2`, handle `swap_source(2)`.
- `strategy.py`: remove the NotImplementedError, `send_command('swap 2')`, with a guard that falls back to content-reload if the graph was built with <3 sources.
- WSL harness: instant-cut to live = 0 CC, teardown_clean. Confirm PlayoutSupervisor app-wiring is complete.

### Slice 2 — S16 Production Control Room (`civiccast/control_room/`)
- 2a models + migration `0047_production_control` (down_revision `0046_cg_feed_source_tags`) + store: ProductionDevice, DeviceProfile, ControlSurface, TimelineCue, ControlRoomSession (+ cue_fired audit child). Secrets → keyring (`secret_ref`), never in tables. Advance head pins (`tests/test_schema_check.py`, `tests/live/test_real_postgres.py`) to 0047. Add migrations dir to `alembic.ini` version_locations.
- 2b cue plan/fire service — mirror `facility/router_control.py` plan-then-fire discipline (proof_boundary, requires_confirmation, operator_action). Plan opens no socket; fire goes through the Node TSR contract.
- 2c API router `/api/staff/control-room/*` (role-gated per S16 §4) + DI wiring (single edit via slice 0).
- 2d **real Node TSR sidecar** — vendored TSR (MIT) behind a CivicCast-owned REST/IPC contract, localhost/IPC-bound, Python is the only caller. Mocked TSR in tests. License-hygiene CI guard (no GPL/AGPL source in the Apache tree; OBS/obs-websocket reached arms-length over socket).
- 2e operator Control Room console — device strip, surface grid (large tap targets, two-step confirm on confirm_required), plan-before-fire preview, program-feed banner (S16↔S5 boundary visible), session audit drawer. client.ts + nav/route + regen openapi. Degrades honestly when the Node service is down.
- 2f S18 gap-8 — GPI / serial (RS-232/422) + router/switcher control with Take-Delay/Post-Roll on ProductionDevice/DeviceProfile + a `device_command` audit on 0047.
- audit-lite per slice.

### Slice 3 — S17 Remote Contribution (`civiccast/live/contribution/`)
- 3a models + migration `0048_remote_contribution` (down_revision `0047`) + store: ContributionRoom, GuestInvite (invite_token ≥32, single-use, expiring; terms_agreement_id + terms_version reusing contribute/ pattern), RemoteGuestSession. Reuse ndi/srt LiveSource kind (zero schema change). Advance head pins to 0048.
- 3b IFRAME-API control bridge (VDO.Ninja postMessage, mocked in tests) + room/invite/session service: single-use token consume + expiry, waiting-room admit (decision #6 = yes).
- 3c API router — staff `/api/staff/contribution` (5 roles) + public token-gated `/api/public/contribution` (invite resolve + accept-terms). DI wiring.
- 3d VDO.Ninja + coturn co-process supervisors (NdiRelaySupervisor pattern + ThreadSupervisor + verify_and_kill_process) gated `CIVICCAST_REMOTE_CONTRIBUTION`; S3 turnkey install (pinned VDO version + SHA); S8 alert conditions (guest-drop, TURN-unreachable, co-process-down); S9 supervision.
- 3e compositor seam — gst `wpesrc` browser-source → composited NDI/SRT → registers as LiveSource; guest on-air routes through the existing `go_on_air` lifecycle. ("live overlay compositing")
- 3f operator Remote Contribution console — room panel (embedded VDO director iframe), invite composer, guest tray (on-air/mute/off-air/drop + connection-quality badge), diagnostics drawer (TURN reachability, co-process health, honest no-compositor banner). client.ts + nav/route + regen.
- audit-lite per slice.

### Slice 4 — Feed-approval queue UI (step-7 finisher)
SSRF backend guard already shipped (`062aa96`). Build the operator approval-queue UI for CG feed items.

### Step-9 close
`/walkthrough` + `/audit-team` across S5+S16+S17, fix to 0/0/0/0/0, push.

## LPM punch list (the ONE external endpoint — real-device proofs only, NOT unwritten code)
- S16 rung-1: a real OBS (and one of ATEM/vMix) visibly changes on a fired cue via the Node TSR service.
- S17 rung-1: a real remote guest joins self-hosted VDO.Ninja + coturn over a network, TURN-fallback path, composited → on air.

## Decisions taken (spec recommendations, dev authority)
- S16 V1 lab-prove set: OBS + ATEM + vMix.
- S17 V1 compositor: gst `wpesrc` (OBS = documented premium option).
- S17 public-comment moderation: waiting-room admit = yes.
- DRM=OUT, SCTE-35=OUT (Scott-locked). Build everything else.
