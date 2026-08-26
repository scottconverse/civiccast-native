# civiccast.schedule — Schedule Module

Sprint 0.3 module. Owns the asset metadata model, the `PostgresAssetStore`
implementation of the `AssetStore` Protocol (defined in `civiccast.vod`),
the upload + ffprobe ingest pipeline, and the schedule API endpoints.

## Architecture

See [ADR 0008](../../docs/adr/0008-database-session-pattern.md) for the
sync-SA + per-module Alembic posture this module follows.

The asset state machine — `pending_ingest → ingesting → validated | rejected`
— is enforced at the database level via a CHECK constraint (Postgres) and at
the SA model level via `__table_args__ CheckConstraint` (SQLite test paths).

## Public API

```python
from civiccast.schedule.models import (
    Asset,                 # SQLAlchemy 2.0 mapped class
    AssetMetadata,         # Pydantic v2 peer of vod.models.AssetMetadata
    AssetMetadataUpdate,   # PATCH /api/staff/assets/{id} request body (with optimistic-concurrency expected_version)
    UploadedAssetResponse, # POST /api/staff/assets/upload response
    StaffAssetRow,         # GET /api/staff/assets row (operator library)
    ScheduleItem,          # SQLAlchemy 2.0 mapped class for schedule_items
    ScheduleItemCreate,    # Pydantic request body for POST /api/staff/schedule
    ScheduleItemResponse,  # Pydantic row for GET /api/staff/schedule
    ScheduleConflictDetail,
    ASSET_STATE_PENDING, ASSET_STATE_INGESTING,
    ASSET_STATE_VALIDATED, ASSET_STATE_REJECTED,
    SCHEDULE_MODE_PREMIERE, SCHEDULE_MODE_EMBARGO,
    SCHEDULE_STATE_SCHEDULED, SCHEDULE_STATE_CANCELLED, SCHEDULE_STATE_PUBLISHED,
)
from civiccast.schedule.store import (
    PostgresAssetStore,
    PostgresScheduleStore,
    AssetNotFoundError,
    AssetVersionConflictError,
    ScheduleConflictError,
)
from civiccast.schedule.ingest import (
    run_ffprobe, validate_ingest, check_ffprobe,
    FfprobeResult, UnsupportedFormatError, FfprobeError, FfprobeNotFoundError,
)
from civiccast.schedule.router import (
    public_router, staff_router,
    get_asset_store, get_postgres_store, get_schedule_store,
)
```

## Endpoints

Public (no auth, mounted at `/api/public`):

- `GET /assets` — list every packaged asset (`manifest_url IS NOT NULL`).
- `GET /assets/{asset_id}` — get one packaged asset, 404 if absent or unpackaged.

Staff (no auth at this rung — see [docs/ops/staff-route-protection.md](../../docs/ops/staff-route-protection.md);
bearer-token auth lands at v0.4):

- `GET /assets` — operator library; returns every asset regardless of state.
- `GET /assets/{asset_id}` — get one operator-side asset row.
- `PATCH /assets/{asset_id}` — update title / description / trim / chapters / retention.
  Optimistic-concurrency via the `expected_version` request field; 409 on stale write.
- `POST /assets` — create one asset directly (no file upload).
- `POST /assets/upload` — multipart upload + ffprobe ingest + validation gate.
- `POST /schedule` — create a scheduled item (premiere | embargo).
  Returns 409 with the conflicting item under `detail.conflicting_item` when the EXCLUDE
  constraint rejects an overlapping premiere on the same channel.
- `GET /schedule` — list scheduled items, filterable by `channel_id`, `mode`, `state`,
  date range. Each row carries a denormalized `asset_title` from a LEFT JOIN.
- `GET /schedule/{id}` — read one scheduled item.
- `POST /schedule/{id}/cancel` — transition `scheduled → cancelled`. Frees the channel slot.

## ffprobe ingest pipeline

`run_ffprobe(path)` shells out to `ffprobe -print_format json -show_streams
-show_format` and returns a typed `FfprobeResult`. `validate_ingest(result)`
applies the validation gate:

- Codec must be in the supported set (h264, hevc, vp9, vp8, av1, prores).
- Audio codec, if present, must be in the supported set.
- Container format must contain a supported token (mp4, mov, matroska,
  webm, avi, mpegts).

Rejections raise `UnsupportedFormatError` with operator-readable copy. The
upload endpoint translates this to HTTP 422.

## Migrations

Per-module migrations live under `civiccast/schedule/migrations/versions/`:

- `0001_create_assets_table.py` — Sprint 0.3 task 1a baseline.
- `0002_add_asset_ingest_fields.py` — Sprint 0.3 task 3: `manifest_url`
  becomes nullable; nine ffprobe columns; state machine + CHECK constraint.
- `0003_create_schedule_items_table.py` — Sprint 0.3 task 4: schedule_items
  table with btree_gist EXCLUDE conflict detection on
  `(channel_id, tstzrange(scheduled_at, scheduled_at_end))`. The
  `scheduled_at_end` column is **denormalized** because Postgres requires
  IMMUTABLE expressions in EXCLUDE indexes — see ADR 0009.
- `0004_asset_trim_chapters_meta.py` — Sprint 0.3 task 5: `trim_in_seconds`,
  `trim_out_seconds`, `chapters` (JSONB), `retention_policy`,
  `retention_until` columns on `assets`; `version` column for optimistic
  concurrency; `assets_trim_out_positive` CHECK.
- `0005_schema_hardening_audit_v030.py` — v0.3.0 audit-team / Scott
  independent-audit closure: drops `live` from the `mode` CHECK + EXCLUDE
  WHERE clauses (ENG-004), adds the Postgres trigger that maintains
  `scheduled_at_end` via a STABLE function, raises the schedule duration
  upper bound to 14 days, and idempotently re-imposes the
  `assets_trim_out_positive` CHECK + `assets.version` column for
  environments that bootstrapped before 0004 was tightened.
- `0010_fractional_asset_trim.py` — Sprint 0.4 Slice 4: widens
  `trim_in_seconds` and `trim_out_seconds` to `Numeric(10,3)` so the API,
  operator trim editor, and packager preserve sub-second trim points.

All schedule migrations implement `upgrade()` and `downgrade()`; reversibility is exercised
by `tests/schedule/test_real_postgres.py` against postgres:17 via
testcontainers.

## Tests

Asset-side:

- `tests/schedule/test_store_conformance.py` — both `InMemoryAssetStore`
  and `PostgresAssetStore` round-trip identically under the `AssetStore`
  Protocol.
- `tests/schedule/test_router.py` — public + staff asset endpoint behaviour
  + schedule endpoint coverage (16 schedule tests + asset coverage).
- `tests/schedule/test_upload_router.py` — 12 tests across no-DB, form
  validation, ffprobe gate, path-traversal hardening, and happy path.
- `tests/schedule/test_ingest.py` — 22 tests: parser, validator, doctor,
  real-ffprobe integration (skipped when binary absent).
- `tests/schedule/test_staff_list_router.py` — 7 tests for the operator
  library endpoint.
- `tests/schedule/test_metadata_update_router.py` — PATCH endpoint:
  optimistic-concurrency 409 path, retention placeholder, trim/chapter
  round-trip.

Schedule + DB-engine contract:

- `tests/schedule/test_schedule_models.py` — Pydantic shape locks; mode
  + state enum unions stay in sync with FE types.
- `tests/schedule/test_schedule_store_properties.py` — hypothesis
  property-based conflict-detection tests.
- `tests/schedule/test_real_postgres.py` — testcontainers + real
  Postgres 17. Locks the schema namespace, the Alembic version table
  location, downgrade-to-base cleanup, store round-trip, and the five
  EXCLUDE-conflict scenarios. It also proves fractional trim columns are
  `numeric(10,3)`, round-trip fractional values, and downgrade/re-upgrade
  cleanly. The `CIVICCAST_RUN_POSTGRES_TESTS=1` env
  var converts the docker-unavailable skip into a hard failure for CI
  + cleanroom (TEST-001 / TEST-002).
- `tests/schedule/test_app_wiring.py` — DI contract for `create_app()`
  with and without `DATABASE_URL` set (ADR 0008 §Director Decisions).

## S7 media lifecycle worker (`media_lifecycle_worker.py`)

Readiness computation, ingest-time transcode seeding/dispatch, and the
archival verification gate (CLAUDE.md §4.6). Env-gated
`MediaLifecycleWorkerSettings` (same per-station config pattern as
`retention_worker.py` / `media_integrity_worker.py`); see its docstring for
the full `CIVICCAST_MEDIA_LIFECYCLE_*` / `CIVICCAST_TRANSCODE_*` env vars.

**Transcode defaults and resource posture (ADR 0007 amendment,
2026-08-24):** the default seed set is a single web-friendly, resolution-
aware H.264 rendition (`DEFAULT_TRANSCODE_FORMATS`) — no GPL encoder, and
never upscales past the source's own probed resolution. Dispatched jobs run
at Windows `BELOW_NORMAL_PRIORITY_CLASS` under a per-minute-of-source
timeout budget (10 min floor, 10x-realtime, 2h ceiling) rather than
ffmpeg's flat 6h default, and `transcode_seeding_enabled` lets a station
turn ingest-time transcoding off entirely. See ADR 0007 for the full
rationale (a real GPL-license defect plus a resource-posture defect, found
together in one audit) and `tests/policy/test_ffmpeg_h264_encoder.py` for
the widened GPL-encoder-literal sweep this closed.
