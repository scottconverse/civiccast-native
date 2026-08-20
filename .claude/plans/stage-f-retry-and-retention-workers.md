# Stage F — ActivityPub Retry Worker + Retention Enforcement Worker

> Sprint plan stage 6. Capability gaps: ActivityPub delivery is
> `production-wired` but "no retry/backoff/dead-letter worker" — a follower
> inbox that is down at publish time never hears about the recording; and
> nothing anywhere acts on `assets.retention_until`, so retention schedules
> are decorative.

**Goal:** (1) Failed ActivityPub deliveries are queued durably and retried
with bounded exponential backoff until delivered or dead-lettered. (2) A
retention worker makes expiry *visible and auditable*: expired assets are
flagged into a durable disposition-review queue surfaced to records clerks —
**no automatic destruction of public records** (judgment call recorded below).

**Key judgment call (for Scott's review):** the sprint plan says "retention
enforcement worker". CivicCast is a public-records product; the asset UI's
"Records officer review required" note and the preset disclaimers
("not legal advice... confirm before enabling automatic purges") argue
against silent auto-deletion. This stage enforces the *schedule* — expiry is
detected, recorded append-only, and surfaced — while automatic purge remains
an explicit follow-up product decision. CAPABILITIES says exactly this.

**Architecture:** Generic `ThreadSupervisor` in
`civiccast/platform/worker_runtime.py` (start/stop/running, daemon thread,
mirrors the proven finalization-supervisor shape). Both workers follow the
Stage B+D hardening pattern from day one: env settings with fail-fast
validation, injected `now`, survive-and-log loop, terminal states excluded
from scans, stable failure semantics.

- **AP retry:** `ActivityPubStore` protocol grows queue methods
  (`enqueue_delivery_retry`, `due_delivery_retries`, `record_delivery_retry_result`,
  `list_delivery_retries`) implemented by both InMemory and Postgres stores;
  new `activitypub_delivery_retries` table (migration 0026, activitypub
  module). `deliver_publish_activity` enqueues on failed results (status 0 or
  >= 400). Worker re-delivers due rows; success → `delivered` (+ delivery
  attempt recorded as usual), failure → backoff, `dead_letter` at max.
  Env: `CIVICCAST_ACTIVITYPUB_RETRY_WORKER=inline|off` (default inline),
  `CIVICCAST_ACTIVITYPUB_RETRY_{POLL_SECONDS,BACKOFF_SECONDS,MAX_ATTEMPTS}`
  (defaults 60 / 120 / 8).
- **Retention:** new `asset_disposition_reviews` table (migration 0027,
  schedule module: asset_id PK, retention_policy, retention_until,
  flagged_at, status `pending_review`) + `RetentionEnforcementWorker`
  (`civiccast/schedule/retention_worker.py`) flagging expired,
  non-permanent assets exactly once. Staff read surface:
  `GET /api/staff/records/disposition-queue` (records module router,
  records_clerk-readable) so flags are operator-visible, not silent.
  Env: `CIVICCAST_RETENTION_WORKER=inline|off` (default inline — it only
  flags), `CIVICCAST_RETENTION_POLL_SECONDS` (default 3600).
- **Lifespan:** `app.state.background_supervisors` list; both durable wiring
  blocks register the two supervisors; `_app_lifespan` starts/stops them with
  the finalization supervisor.

## Tasks (TDD, red first)

1. `tests/activitypub/test_retry_worker.py`: failed delivery enqueues
   (success does not); due-row retry succeeds → `delivered` + delivery
   recorded; repeated failure → backoff growth → `dead_letter` at max with
   last error; loop survives a scan exception; off-mode never starts.
2. `tests/schedule/test_retention_worker.py`: expired non-permanent asset
   flagged once (idempotent rescans); `permanent`, future, and null
   `retention_until` never flagged; router test for the disposition queue
   endpoint (200 + rows, 401 unauthenticated, role gating).
3. Implement models + migrations 0026/0027 (single-head guards cover the
   chain; update the head tripwire), workers, store methods, service enqueue,
   supervisor runtime, app wiring, doctor no-op.
4. Docs: `docs/ops/background-workers.md` (or extend the finalization
   runbook) for both workers' envs and semantics; records-clerk guide note;
   CAPABILITIES rows (AP delivery row gains retry/dead-letter truth;
   retention row added honestly); CHANGELOG; regenerate OpenAPI artifacts
   (new staff endpoint).
5. Gate + result file + commit
   `feat(platform): activitypub retry and retention review workers refs #98`.
