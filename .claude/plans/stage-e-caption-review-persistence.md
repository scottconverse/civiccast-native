# Stage E — Durable DB-Backed Caption Review Store + Caption-Tap Design Deferral

> Sprint plan stage 5. Capability gap: "`InMemoryCaptionReviewStore` is a real
> but ephemeral component; default even on the durable path; no DB
> model/migration." Caption review decisions are operator work product on the
> public record path — they must survive a restart.

**Goal:** Caption review items persist in the database whenever durable
storage is active (Postgres or managed SQLite), with the in-memory store
remaining the explicit-ephemeral default; plus a recorded design deferral for
the live-audio caption tap (the other half of the caption capability gap),
explicitly NOT implemented this sprint per the sprint plan.

**Architecture:** SA model `CaptionReviewItem` (cue fields flattened) +
migration `0025_caption_review_items` under a new
`civiccast/captions/migrations/versions/` slot (registered in `alembic.ini`);
`PostgresCaptionReviewStore` implementing the existing `CaptionReviewStore`
protocol with identical semantics; both durable wiring blocks in `app.py`
switch the store-bundle factory from the in-memory class to a per-request
Postgres store.

## Tasks (TDD)

### E1: Store + migration (red first)

- Test `tests/captions/test_review_persistence.py`:
  - create/get/list (asset_id + status filters, (created_at, id) ordering),
    approve/edit/reject transitions incl. reviewed_text semantics
    (approve keeps prior edit; reject clears), duplicate-id →
    `CaptionReviewItemAlreadyExistsError`, missing id →
    `CaptionReviewItemNotFoundError` — same contract as the in-memory store.
  - durability: a second store instance over the same engine sees the rows.
  - real-Postgres round-trip via the shared harness (skip-gated).
- Implement: `civiccast/captions/persistence.py` (SA model +
  `PostgresCaptionReviewStore`), migration
  `0025_caption_review_items` (down_revision `0024_finalization_failure_codes`;
  CHECK on status; downgrade drops the table), `alembic.ini`
  version_locations entry. The existing migration-graph guards
  (single head, id ordering) cover the chain automatically.

### E2: Durable wiring (red first)

- Test: app-factory — file SQLite DB migrated to head; POST
  `/api/staff/captions/review-items` through one app instance; a NEW app
  instance over the same DB GETs the item (restart-survival through the
  running app, the exact failure the audit row describes).
- Implement: `_resolve_caption_review_store` in both durable wiring blocks of
  `app.py` (store bundle factory), in-memory store stays the
  ephemeral/no-DB default.

### E3: Caption-tap design deferral (docs only, per sprint plan)

- `docs/design/live-audio-caption-tap-deferral.md`: what exists (worker,
  proof script with synthetic silence), what's missing (live-audio bridge +
  lifecycle), option sketch (egress audio fork / recorder sidecar tap /
  post-hoc-only), what decision Scott owes, and why it is deferred.
- CAPABILITIES: caption review store row → durable-on-DB-path wording;
  caption transcription worker row gains the deferral pointer. CHANGELOG.

### E4: Gate + result file + commit

- Full pytest (Postgres env), ruff/format, mypy scoped, alembic heads == 1,
  OpenAPI artifact check, `git diff --check`; result file; commit
  `feat(captions): durable caption review store refs #98`.
