# Stage 3 (build step 3) — S9 Reliability & Process Identity

**Branch:** `work/3.0-gstreamer-engine` · **Spec:** `docs/spec/3.0/sections/S9-reliability-and-process-identity.md`
(mirror `Desktop\Code\civiccast-3.0-spec\sections\S9-...md`). **Started 2026-06-14** after Stage 1 (engine) +
Stage 2 (4h soak) closed.

## Goal
Make the persistent GStreamer channel survive unattended: supervise the pipeline (bus-error + stall watchdog +
clean restart to a known state), reap device-holding **co-processes** TOCTOU-safely on boot, durably track their
pids, unify pacing, surface schema-currency on /health, and cap proof-event churn. Engine alignment (S9 §0): the
in-process GStreamer pipeline dissolves the per-segment ffmpeg-orphan class — reliability re-targets to (a)
supervising the persistent pipeline and (b) the optional co-processes (CasparCG/SDI → DeckLink, NDI runtime →
NDI name) that still spawn as OS processes and can lock hardware.

## Grounding (verified in repo, 2026-06-14)
- `EgressStateRow` = `models.py:345` (has `pid`; add `*_coproc_pid`/`*_coproc_created_at`).
- Co-process machinery EXISTS: `egress/sdi_relay.py`, `egress/ndi_relay.py`, `automation.reap_predecessor_relays`
  (called in a try/except at startup but its result is **not acted on** — the load-bearing gap).
- Pacing latches EXIST inline: `automation._start_retry_at` (132), `_replan_retry_at` (135) → migrate to a class.
- Process-identity TOCTOU primitive EXISTS: `daemon.OrphanInfo` + `_default_orphan_probe`/`_terminator` (re-verify
  `create_time` at kill) → extract a shared `_verify_and_kill_process`.
- Engine reload watchdog/abort (Stage-1 ENG-001 fix) is the in-process analogue; S9 adds the **pipeline-level**
  bus-error + stall supervision around it.

## MIGRATION — RESOLVED (investigated 2026-06-14, 3 parallel agents + verified)
**It is ONE migration chain, not three trees** (ADR 0008): a single root `alembic.ini` + `alembic/env.py`
discovers ~14 per-module `civiccast/<module>/migrations/versions/` dirs via `version_locations`.
`civiccast/alembic/` is a **packaged-wheel duplicate** of the root config (kept in sync by
`tests/test_alembic_ini_sync.py`). `civiccast/egress/migrations/` is the **egress module's slot** in that one
chain (no standalone config).
- **Owner of the target tables:** `civiccast/egress/migrations/versions/` — both tables created in
  `0020_egress_control_plane.py`; every egress schema change (CA-2…CA-7, 0020–0036) lives there. **Table names:
  `egress_states` (singular — NOT `egress_state_rows`; that's the Pydantic class name) and `egress_health_samples`.**
- **Real chain HEAD = `0037_asset_meeting_body`** (verified: highest on-disk migration; nothing lists it as a
  `down_revision`). The spec's `0042`/`0043` are **unbuilt planning numbers** — 0038–0057 don't exist on disk.
- **DECISION:** new file `civiccast/egress/migrations/versions/0038_reliability_fields.py`, `revision="0038_reliability_fields"`,
  `down_revision="0037_asset_meeting_body"`. Add cols to `egress_states` (coproc pids/created_at) +
  `egress_health_samples` (schema_version, proof_events_appended) via `op.batch_alter_table(..., schema=schema)`
  (matches 0021's pattern; SQLite-compat + multi-schema). **Drop the spec's "after 0042" dependency** — 0042
  doesn't exist and S8 (step 4) is built AFTER S9; chaining on the unbuilt 0042 would branch the chain. S8 later
  takes the next sequential number on top of 0038.

## Slices (TDD; each → audit-lite 0/0/0/0/0 → commit; gi-free first, WSL last)
- **S9-1 — pure primitives (Windows-testable).** `egress/pacing.py` `UniformPacingLatch` (should_run_now/force_reset);
  `egress/coprocess_identity.py` `CoprocessIdentity` dataclass; extract `_verify_and_kill_process(pid, created_at,
  tol=1.0)` shared util (psutil; mockable). Migrate `_start_retry_at`/`_replan_retry_at` to the latch. Unit tests
  per spec §8.1 (latch cooldown/reset, TOCTOU match/recycled-pid).
- **S9-2 — schema-currency + proof-event caps (store-level, gi-free).** `egress/schema_currency.py`
  (`EGRESS_SCHEMA_VERSION`, `current_schema_version`, `is_schema_current`); add `schema_version` +
  `proof_events_appended_since_last_sample` to `EgressHealthSample`; trim policy in BOTH `InMemoryEgressStore` and
  `PostgresEgressStore` (10k/channel, trim 1k oldest on append). Wire `daemon._append_health` to populate the new
  fields. Unit tests §8.1 (trim per-channel isolation, schema version, proof rate count).
- **S9-3 — migration (resolve the numbering above first).** Add the reliability columns to `egress_state_rows`
  (co-process pids/created_at) + `egress_health_samples` (schema_version, proof_events_appended) on the REAL head.
  Test on fresh + existing DB via the portable Postgres (`CIVICCAST_POSTGRES_TEST_URL`).
- **S9-4 — co-process durability + boot reap wiring.** On co-process spawn/stop, write/clear
  `EgressStateRow.{sdi,ndi}_coproc_pid/created_at`; sync the in-memory `_RELAY_STATUSES`. Act on
  `reap_predecessor_relays()` at boot: append a `civiccast-egress-coprocess-lifecycle` proof event per reaped pid,
  clear stale state. Integration tests §8.2 (reap-on-boot, skip-live-process, TOCTOU skip).
- **S9-5 — pipeline supervision (gi/WSL).** Engine bus handler for `GST_MESSAGE_ERROR`/`EOS` (already partly there
  from the Stage-1 reload containment) + a **stall watchdog** (output running-time not advancing for
  `PIPELINE_STALL_TIMEOUT`=10s while on-air) → **clean restart to known state** on the committed source,
  **latch-gated** (reuse `UniformPacingLatch`), proof event + S8-escalation hook on repeated restarts. WSL harness
  test: inject an element error / kill the sink target → bus handler fires, restart returns to PLAYING on the
  committed source, **0 CC across the supervised restart**. (This is the S9 analogue of the Stage-1 reload
  watchdog, at the pipeline level.)
- **S9-6 — readiness latch + /health endpoint + UI badge.** Latch-gate the active health/co-process readiness
  poll (30s/channel); add schema_version to the `/health` payload; SystemHealthScreen badge (🟢 Schema OK /
  🔴 Schema Drift + proof-churn line). NOTE: this slice HAS a UI surface → `/walkthrough` applies at stage close.

## Stage close
Full egress suite green (Windows) + WSL harness green (incl. the new pipeline-restart test) → `/walkthrough`
(S9-6 has UI) → `/audit-team` to 0/0/0/0/0 → push. The 72h soak with failure-injection is **build step 13**
(end of build, per Scott), not mid-build; the Stage-2 4h soak already gives first machine-confidence.

## Open decisions for Scott (from spec §10.3 — non-blocking, defaults chosen)
1. TOCTOU create_time tolerance: keep **1.0s** (escalate to 5.0s only if soak shows false positives).
2. Proof-event trim threshold: **fixed 10k/channel** for 3.0 (configurable in 3.1 if needed).
3. Schema-version bump discipline: bump `EGRESS_SCHEMA_VERSION` on any breaking entity change; document in the module.
4. Windows Job Objects / POSIX process groups for co-process lifetime coupling: **defer to 3.1** (engine is
   in-process; no per-segment child to leak).

## S9-4 design (de-risked 2026-06-14 — implement next)
Relays are supervised per-channel in `ChannelAutomationService._sync_sdi_relay(config)` /
`_sync_ndi_relay(config)` (automation.py ~212-290), keyed by `channel_id` in `self._sdi_relays`/`self._ndi_relays`;
the service has `self._store`. So the durable-pid approach is feasible WITHOUT relay-module surgery:
- **Spawn write:** when `_sync_{sdi,ndi}_relay` starts a relay, read its pid + `psutil.create_time()`, write to
  `EgressStateRow.{sdi,ndi}_coproc_pid/created_at` via `store.write_state` (fields landed in S9-2b/3). On
  stop/clear (the `.pop()` path), null them. (TODO recon: confirm the relay supervisor object exposes `.pid` — check
  `sdi_relay.py` SdiRelayStatus/supervisor; the Popen is at sdi_relay.py:274 / ndi_relay.py:163.)
- **Boot reap (channel-attributed):** new `reap_stale_coprocesses(store, channel_ids)` — for each channel state
  row with a non-null coproc pid, `process_identity.verify_and_kill_process(pid, created_at)` (TOCTOU-safe); if it
  reaps a live predecessor, append a per-channel `civiccast-egress-coprocess-lifecycle` proof event + clear the
  fields. Wire at boot AFTER store creation (automation.py ~494). The existing cmdline `reap_predecessor_relays`
  (automation.py:353, already wired at :491) stays as a global safety net.
- **Tests:** spawn writes the pid (fake relay); stop clears it; boot reap kills a stale pid (fake verify_and_kill)
  + emits the proof event + clears; TOCTOU skip (create_time drift). gi-free, Windows-testable.
