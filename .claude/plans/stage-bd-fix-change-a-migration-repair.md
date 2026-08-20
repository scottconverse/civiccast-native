# Change A — Migration Graph Repair + BigInteger Byte Columns

> Part of the Stage B+D fix sprint (see `.claude/plans/audit-sprint-1.md`).
> Findings closed: ENG-001 (Blocker), TEST-001 (Blocker), QA-006 (Blocker), W-1,
> ENG-003 / TEST-005 / W-3 (Critical), ENG-012 (Minor), ENG-015 (Nit, default-drift half).
> Decision basis (Scott, final): re-parent + renumber 0011 → 0023 onto
> `0022_egress_proof_source_ref`. Branch unreleased; only disposable audit SQLite
> DBs ever applied 0011.

**Goal:** One linear alembic graph (`alembic heads` → exactly 1) with 64-bit byte
columns, proven by the 11 currently-red tests passing **unmodified** plus new
everywhere-runnable guards.

**Architecture:** Rename/re-parent the migration file; widen
`recording_size_bytes` / `last_observed_size_bytes` to `sa.BigInteger` in both the
corrected migration and the SQLAlchemy model; align the `created_at` server
default (`CURRENT_TIMESTAMP` works on both SQLite and Postgres) so autogenerate
drift disappears.

**Precondition check (decision flip-trigger):** confirm no real DB applied 0011.
Evidence: branch never pushed beyond `work/audit-sprint-1`, installer never run,
only `C:\CivicCastTester\tools\audit-walkthrough\*.db` (disposable per handoff)
ran `upgrade heads`. If contrary evidence appears → STOP, report to Scott
(merge-revision path instead).

## Tasks

### Task A1: Failing guards first (TDD)

**Files:**
- Create: `tests/db/test_migration_graph_guards.py`

Two tests:

```python
def test_alembic_graph_has_exactly_one_head() -> None:
    cfg = Config(str(ALEMBIC_INI))
    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1, f"alembic graph is forked: {heads}"


def test_finalization_job_byte_columns_are_64_bit() -> None:
    from sqlalchemy import BigInteger
    from civiccast.live.models import LiveFinalizationJob
    for col in ("recording_size_bytes", "last_observed_size_bytes"):
        column_type = LiveFinalizationJob.__table__.c[col].type
        assert isinstance(column_type, BigInteger), (
            f"{col} must be BigInteger (Postgres INTEGER caps at ~2 GiB); got {column_type!r}"
        )
```

Also add a revision-ordering guard (ENG-012 / watchlist #14 cheap insurance):

```python
def test_new_revision_ids_sort_after_their_down_revision() -> None:
    # walks ScriptDirectory; numeric-prefixed revision must sort >= its parent's
```

- Run: `pytest tests/db/test_migration_graph_guards.py -q` → expect 2-3 failures
  (two heads; Integer columns).

### Task A2: Re-parent + renumber + widen the migration

**Files:**
- Rename (git mv): `civiccast/live/migrations/versions/0011_live_finalization_jobs.py`
  → `civiccast/live/migrations/versions/0023_live_finalization_jobs.py`
- Edit in the renamed file:
  - `revision = "0023_live_finalization_jobs"`
  - `down_revision = "0022_egress_proof_source_ref"`
  - `sa.Column("recording_size_bytes", sa.BigInteger(), nullable=True)` (and
    `last_observed_size_bytes`)
  - Replace `_server_default_now()` with `sa.text("CURRENT_TIMESTAMP")` (valid on
    both dialects; kills ENG-015 autogenerate drift)
  - Update downgrade guard message to say `0023_live_finalization_jobs`
  - Docstring: note the 0011→0023 renumber and why (repo-global revision chain)

### Task A3: Widen the model columns

**Files:**
- Modify: `civiccast/live/models.py:344-345` — `mapped_column(BigInteger, nullable=True)`,
  import `BigInteger` from sqlalchemy.

### Task A4: >2 GiB round-trip in the Postgres-gated suite

**Files:**
- Modify: `tests/live/test_real_postgres.py` — add a Docker-gated test inserting a
  `LiveFinalizationJob` with `recording_size_bytes = 3 * 2**31` and reading it
  back; runs in the clean-room pass (Docker unavailable locally — declared gap).

### Task A5: Update the one doc reference

- `civiccast/live/README.md` migrations tree: `0011_…` → `0023_…` (full README
  accuracy pass lands in Change B; this keeps the filename truthful in the same
  commit as the rename).

### Task A6: Verify

- `python -m alembic heads` → exactly one head: `0023_live_finalization_jobs`.
- `python -m alembic upgrade head` then `downgrade base` on a temp SQLite DB.
- The 11 previously-red tests **unmodified**:
  `pytest tests/db/test_alembic_env.py tests/schedule/test_migration_reversibility.py tests/installer/test_installer_api.py tests/installer/test_storage.py tests/auth/test_staff_token_lifecycle.py tests/activitypub/test_activitypub_persistence.py -q` → 0 failures.
- New guards pass: `pytest tests/db/test_migration_graph_guards.py -q`.
- Full suite (minus documented exclusions: `tests/platform/test_nats_broker_real.py`,
  `tests/schedule/test_schedule_conflict_properties.py` — venv lacks
  testcontainers/hypothesis) → 0 failures.
- `ruff check .`, `ruff format --check` on touched files, `git diff --check`.

### Task A7: Result file + commit

- Result file: `tester-handoff/v2.0.1/test-results/windows/<ts>-local-change-a-migration-repair.md`
  (DONE vs NOT, verbatim commands/outputs, full-suite count, safety confirmations,
  clean-room Postgres acceptance criteria restated).
- Commit (signed-off): `fix(live): repair finalization migration graph and widen byte columns refs #98`
