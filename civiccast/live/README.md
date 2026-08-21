# civiccast.live -- Live-Broadcast Spine

Owns the live broadcast lifecycle: the session state machine, the configured
source descriptors (RTMP / RTSP / NDI / SRT), the recording targets, optional
outbound relay configs, the pre-flight checklist evaluator, the staff
`/api/staff/live/*` API surface plus the public now-playing endpoint, and the
recording-finalization worker + handler that land a finalized broadcast as an
asset row at state `recorded`.

## Architecture

The live module composes its persistence aggregates (sessions, sources,
recording targets, relay configs, finalization jobs), a read-only preflight
evaluator, the HTTP surface, and the finalization worker + handler:

```
                                                                  +---------+
        +---------------+        +-----------------+              | router  |
        | LiveSession   |        | LiveSource      |              |---------|
        |---------------|        |-----------------|              | staff   |
        | state machine |<-------| (per channel)   |<-------------| API at  |
        | idle/preflight|        +-----------------+              | /api/   |
        | on_air/ending |        +-----------------+              | staff/  |
        | recorded      |<-------| RecordingTarget |<-------------| live/*  |
        +-------+-------+        +-----------------+              +----+----+
                ^                                                      |
                |  read-only inputs to                                  |
                |                                                      v
        +-------+----------+                                  +--------+--------+
        | preflight        |                                  | Finalization    |
        | evaluator        |---------- 9 checks ------------->| worker         |
        | (9-check         |   PASS / FAIL / NOT_CONFIGURED   | settle/retry    |
        |  contract)       |                                  +--------+--------+
        +------------------+                                           |
                                                                       v
                                  +-----------------+         +--------+--------+
                                  | live_session_   |<--------| Finalizer      |
                                  | events          |         | one DB txn     |
                                  | (idempotency)   |         +--------+--------+
                                  +-----------------+                  |
                                                                       v
                                                              +--------+--------+
                                                              | assets row at   |
                                                              | state=recorded  |
                                                              | manifest_url    |
                                                              | only if served  |
                                                              +-----------------+
```

Architectural decisions live in:

- [ADR 0010](../../docs/adr/0010-live-session-state-machine.md) -- live session state machine: forward-only transitions via conditional UPDATE.
- [ADR 0011](../../docs/adr/0011-recording-finalization-transactional-event.md) -- recording finalization: idempotent transactional event + asset insert.

Design rationale for the rest of the slice (preflight checklist contract,
staff API endpoint shapes, source-type enumeration, QA-005 + QA-007 backend
correctness fixes) lives at
[`docs/research/v04-slice1-broadcast-spine-design.md`](../../docs/research/v04-slice1-broadcast-spine-design.md).

## Public API

The authoritative export list is `civiccast/live/__init__.py` (`__all__`); this
section highlights the main entry points rather than mirroring the full list
(hand-maintained mirrors of `__all__` rot).

```python
from civiccast.live import (
    # Lifecycle + finalization state constants
    LIVE_SESSION_STATE_IDLE,        # ... PREFLIGHT / ON_AIR / ENDING / RECORDED
    FINALIZATION_STATE_PENDING,     # ... RUNNING / FAILED / COMPLETED

    # SA mapped classes
    LiveSession, LiveSource, LiveSessionEvent, RecordingTarget,
    LiveRelayConfig, LiveFinalizationJob,

    # Pydantic peers (create/response shapes, preflight, finalization status)
    LiveSessionCreate, LiveSessionResponse,
    LiveFinalizationStatusResponse,
    RecordingTargetCreate, RecordingTargetResponse,
    LiveRelayConfigCreate, LiveRelayConfigResponse,

    # Stores, evaluator, finalizer, worker
    LiveSessionStore, LiveSourceStore, RecordingTargetStore,
    LiveRelayConfigStore, PreflightEvaluator,
    LiveRecordingFinalizer, LiveFinalizationWorker,
)
```

## State machine

Forward-only. See ADR 0010 for the rationale.

```
        idle
          |
          | start_preflight  (POST /sessions/{id}/start-preflight)
          v
       preflight
          |
          | go_on_air        (POST /sessions/{id}/go-on-air, stamps started_at)
          v
        on_air
          |
          | end_broadcast    (POST /sessions/{id}/end-broadcast, stamps ended_at)
          v
        ending
          |
          | mark_recorded    (internal, called by LiveRecordingFinalizer
          |                   inside the same transaction as the
          |                   event INSERT + asset INSERT)
          v
       recorded
```

Each transition is a conditional UPDATE filtered by the expected source
state. Concurrent writers race the UPDATE; exactly one wins
(`rowcount == 1`), the other raises `LiveSessionStateError` with the
observed current state. The pre-flight evaluator runs against
`/sessions/{id}/preflight` and does NOT mutate state -- it can be
re-invoked freely during the `preflight` window as the operator's
checklist inputs change.

## HTTP surface

The staff endpoints under `/api/staff/live/`, mounted by the umbrella FastAPI
app at `civiccast/app.py` (see `docs/API-REFERENCE.md` for the authoritative,
generated list):

| Method | Path | Purpose |
|:-------|:-----|:--------|
| POST | `/sessions` | Create at state `idle` |
| GET | `/sessions/{id}` | Read one |
| POST | `/sessions/{id}/start-preflight` | Transition `idle -> preflight` |
| POST | `/sessions/{id}/preflight` | Run pre-flight evaluator (non-mutating) |
| POST | `/sessions/{id}/go-on-air` | Transition `preflight -> on_air` |
| POST | `/sessions/{id}/end-broadcast` | Transition `on_air -> ending` |
| GET | `/finalizations` | List finalization worker status rows |
| GET | `/sessions/{id}/finalization` | Read one finalization status row |
| POST | `/sources` | Create LiveSource |
| GET | `/sources` (with `?channel_id=`) | List LiveSources |
| GET | `/sources/{id}` | Get one |
| POST | `/recording-targets` | Create RecordingTarget |
| GET | `/recording-targets` | List |
| GET | `/recording-targets/{id}` | Get one |
| POST | `/relay-configs` | Create optional outbound relay config |
| GET | `/relay-configs` | List relay configs |
| GET | `/relay-configs/{id}` | Get one |
| POST | `/relay-configs/{id}/health` | Record relay health observation |
| GET | `/ingest-plan` | Resolve the channel ingest plan |

Public surface: `GET /api/public/live/current` returns the now-playing live
session for the resident portal (no auth).

Auth posture: every `/api/staff/live/*` route requires staff bearer-token
authentication (enforced by the umbrella app's middleware; see
`docs/ops/staff-route-protection.md`), and deployments should additionally
keep the API on loopback or behind an authenticating reverse proxy for
network/TLS policy.

Status codes:

- `200` -- successful read or state transition.
- `201` -- created.
- `404` -- session / source / target not found.
- `409` -- state-machine mismatch (current_state in detail body) or
  duplicate-id collision.
- `422` -- Pydantic validation failure or path-vs-body id mismatch on
  the preflight evaluator endpoint.
- `503` -- DB not configured (`DATABASE_URL` unset at app startup).

## Pre-flight checklist

Nine checks in canonical order, defined at `civiccast/live/preflight.py`:

1. `network` -- caller-supplied probe.
2. `storage` -- caller-supplied probe; minimum default 50 GiB free.
3. `ai_runtime` -- caller-supplied probe; optional in Slice 1.
4. `live_source` -- DB lookup: any `LiveSource` for the session's
   `channel_id`, then a real server-side media probe
   (`civiccast/live/source_probe.py`'s `probe_live_source`, ffprobe-backed,
   bounded by `CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS`, default 8s)
   confirming the source is actually delivering video or audio before
   go-on-air is allowed. No probe configured -> fails closed
   (`live_source.not_probed`), never a silent pass.
5. `recording_target` -- DB lookup: any `RecordingTarget` exists.
6. `operator_confirm` -- caller-supplied boolean.
7. `syndication` -- placeholder (always `not_configured` in Slice 1).
8. `internet_archive` -- placeholder.
9. `nas` -- placeholder.

Readiness rule: required checks (network, storage, live_source,
recording_target, operator_confirm) must be `pass`. AI runtime can be
`pass` or `not_configured`; `fail` blocks readiness. Placeholders never
block.

Each non-pass check carries a stable machine-readable `reason_code` so the
operator UI can map directly to per-failure copy without re-mapping
human-readable strings. The reason codes are dot-notation identifiers
(e.g., `network.unreachable`, `storage.insufficient_free_space`,
`live_source.none_configured_for_channel`).

## Recording finalization

The production path (runtime-verified by the app-factory integration test at
`tests/live/test_finalization_worker_app_wiring.py` and the stage runtime
walkthrough) is:

1. Operator calls `POST /api/staff/live/sessions/{id}/end-broadcast`.
2. The session moves from `on_air` to `ending` and stamps `ended_at`.
3. The worker loop — started by the app lifespan as a background thread when
   durable storage is active (default `CIVICCAST_FINALIZATION_WORKER=inline`),
   or run as a separate process via
   `python -m civiccast.live.finalization_worker` (`external` mode) — observes
   the `ending` session and resolves a local file recording at
   `<recording-target>/<live_session_id>.mp4`.
4. The worker waits for the file to settle.
5. The worker calls `LiveRecordingFinalizer.finalize_recording(...)`.
6. After that transaction commits, the worker packages the local recording to
   HLS and persists package status on `live_finalization_jobs`.
7. Publish readiness remains blocked unless a real servable package URL is
   configured (`CIVICCAST_LIVE_MANIFEST_BASE_URL`) and written to
   `assets.manifest_url`.

Operating the worker — start modes, configuration knobs, status reading, and
failure handling — is documented in
[`docs/ops/finalization-worker-runbook.md`](../../docs/ops/finalization-worker-runbook.md).

### Settle rule

For file recording targets, the worker considers a recording settled only after
the file exists and its byte size is unchanged across two scans at least
`settle_seconds` apart. Until then the job remains `pending`.

### Retry policy

Worker status states are `pending`, `running`, `failed`, and `completed`.
Failures persist `failure_reason`, increment `attempts`, and set
`next_attempt_at` using bounded exponential backoff. The worker retries failed
jobs until `max_attempts`; after that, the job is terminal `failed`. There is
no operator retry endpoint yet — the runbook
(`docs/ops/finalization-worker-runbook.md`) documents what a terminal failure
means and the current recovery procedure; an operator repair surface is a
tracked follow-up.

### Finalizer transaction

Internal handler at `civiccast/live/finalization.py`. It composes three writes
inside one transaction:

1. INSERT `live_session_events` row (event_type=`session.finalized`,
   event_seq=1, payload_json=`{recording_uri, duration_seconds, finalized_at}`).
2. INSERT `assets` row at state `recorded` with
   `source_live_session_id = live_session_id`.
3. Conditional UPDATE `live_sessions` SET state=`recorded` WHERE
   live_session_id=? AND state=`ending`.

Idempotency is structural: the event table's composite PK
`(live_session_id, event_type, event_seq)` rejects duplicate inserts
with `IntegrityError`. The finalizer catches that, re-queries the
existing event + asset, and returns
`FinalizationResult(idempotent=True)` referencing them.

The finalizer does not run the packager inside this transaction. Packaging is a
worker step after commit. That keeps long FFmpeg work outside the DB
transaction while preserving the event/asset/session idempotency guard.

### Packaging and manifest URLs

The worker writes local HLS output to `<recording-parent>/<live_session_id>-hls`
and stores the local manifest path on the finalization job. It does not write
`file://` URLs into `assets.manifest_url`. `manifest_url` is set only when the
worker is configured with a servable public manifest base URL
(`CIVICCAST_LIVE_MANIFEST_BASE_URL`; serving story in the runbook); otherwise
the recorded asset remains visible to operators but does not pass publish
readiness.

The worker passes persisted trim metadata (`trim_in_seconds`,
`trim_out_seconds`) from the job row to `pack_vod_asset(...)`. Invalid trim
windows fail before an asset row is written. **No production surface currently
writes trim values onto a finalization job** — the propagation is exercised
only by tests; operator-initiated trim that reaches the packaged output
(repackage-on-trim-update) is a tracked follow-up story. The operator trim UI
edits asset metadata after finalization and does not re-render the package.

## Layout

```
civiccast/live/
├── __init__.py                 # public surface re-exports
├── models.py                   # SA classes + Pydantic peers + constants
├── store.py                    # LiveSessionStore + LiveSourceStore + RecordingTargetStore
├── preflight.py                # PreflightEvaluator + PreflightInputs/Evaluation
├── finalization.py             # LiveRecordingFinalizer + FinalizationResult
├── finalization_worker.py      # settle/retry/package worker + status surface
├── router.py                   # FastAPI staff router
├── README.md                   # this file
└── migrations/
    └── versions/
        ├── 0007_live_sessions.py            # creates live_sessions + live_sources + recording_targets
        ├── 0008_finalization_spine.py       # creates live_session_events + assets.source_live_session_id
        ├── 0009_live_sources_index.py       # indexes live_sources.channel_id
        ├── 0010_live_relay_configs.py       # creates live_relay_configs
        ├── 0023_live_finalization_jobs.py   # creates live_finalization_jobs
        └── 0024_finalization_failure_codes.py  # adds failure_code/failure_detail
```

**Migration revision numbers are repo-global, not per-module.** The alembic
chain continues in other modules' `migrations/versions/` directories (schedule,
egress, auth, …) and in the repo-root `alembic/versions/` slot. Before adding a
migration here, run `alembic heads` and parent the new revision on the single
current head — which may live in another module's directory. A guard test
(`tests/db/test_migration_graph_guards.py`) fails the suite if the graph forks
or a new revision id sorts before its parent.

## Test coverage

(Counts intentionally omitted — they rot; run `pytest tests/live -q` for the
current numbers.)

- `tests/live/test_models.py` -- SA model + Pydantic peer + CHECK
  constraint coverage.
- `tests/live/test_store.py` -- SQLite tests covering CRUD + state-
  machine happy + illegal-transition + missing-session paths.
- `tests/live/test_preflight.py` -- tests pinning the nine-check
  contract surface.
- `tests/live/test_router.py` -- HTTP-contract tests across happy +
  404 + 409 + 422 + 503 per endpoint.
- `tests/live/test_finalization.py` -- SQLite tests covering happy +
  idempotent + wrong-state + missing-session + asset-id-collision.
- `tests/live/test_finalization_worker.py` -- worker settle/retry/package
  tests, manifest URL integrity, status reporting, and real-media trim proof.
- `tests/live/test_finalization_worker_app_wiring.py` -- app-factory
  integration proof: end-broadcast over HTTP reaches `completed`/`recorded`
  through the app's own worker wiring; worker mode behavior; external
  entrypoint smoke.
- `tests/live/test_real_postgres.py` -- real-Postgres tests (migration
  upgrade/downgrade + CHECK constraint validation + two-thread state-machine
  concurrency + two-thread finalization idempotency + finalization-jobs
  >2 GiB byte-size round-trip). Skip-gated by Docker availability.

## Current gaps / planned work

- Operator UI for live sessions and finalization status (Slice 2 "Operator
  Live Room") — the status surface is API-only today.
- Operator-reachable trim for live recordings (repackage-on-trim-update) —
  tracked follow-up; see "Packaging and manifest URLs" above.
- Operator retry/repair endpoint for terminal `failed` finalizations —
  tracked follow-up; runbook documents the interim procedure.
- Resident-facing portal display + Coming Up widget (Slice 3); sub-second
  trim precision (Slice 4).
