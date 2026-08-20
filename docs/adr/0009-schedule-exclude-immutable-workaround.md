# ADR 0009 — Schedule conflict detection: `scheduled_at_end` denormalization to satisfy Postgres EXCLUDE/IMMUTABLE

**Status:** Accepted
**Date:** 2026-05-10
**Deciders:** Scott Converse (human director)
**Related rung:** 0.3 — Schedule module (task 4, premiere/embargo scheduling)
**Related spec section:** Schedule lifecycle (premiere / embargo semantics, channel conflict rules); CLAUDE.md "Closed architectural decisions" (Schema: `civiccast.*`; per-module Alembic migrations under one env per ADR 0008)
**Supersedes:** N/A
**Superseded by:** N/A
**Closes:** DOC-008 in `audit-civiccast-v0.3.0-2026-05-10/03-documentation-deepdive.md`

---

## Context

Sprint 0.3 task 4 ships premiere/embargo scheduling. The headline correctness contract is: **two premieres on the same channel cannot occupy overlapping time ranges.** A user-space check at the FastAPI layer is not enough — concurrent writers (two operators in two browser tabs) would race. The contract has to land at the Postgres layer.

Postgres provides exactly the right tool: **`EXCLUDE` constraints with the `btree_gist` extension.** An EXCLUDE constraint can be expressed as

```
EXCLUDE USING gist (
    channel_id WITH =,
    tstzrange(scheduled_at, scheduled_at + duration_seconds * interval '1 second', '[)') WITH &&
)
WHERE (mode IN ('live', 'premiere') AND state = 'scheduled')
```

— "for any two rows that share `channel_id` and have overlapping (`&&`) time ranges, the `WHERE` predicate determines which subset participates in the check." On paper this is exactly what we want.

In practice it does not work. Postgres requires every expression inside an EXCLUDE index's column list to be **IMMUTABLE**. `tstzrange(scheduled_at, scheduled_at + duration_seconds * interval '1 second', '[)')` involves arithmetic with `interval '1 second'`, which Postgres marks as **STABLE** (not IMMUTABLE) because `interval` arithmetic depends on session timezone settings. Postgres rejects the constraint at migration time:

```
ERROR:  functions in index expression must be marked IMMUTABLE
```

Wrapping the whole expression in a SQL function and tagging the function `IMMUTABLE` is *technically* allowed but semantically wrong: the function would lie about its volatility, and a future Postgres release that tightens IMMUTABLE detection (or a `pg_dump` / `pg_upgrade` revalidation pass) could surface the lie at the worst possible moment.

The audit-team v0.3.0 pass (DOC-008) flagged this as an architectural decision that lived only in the migration's docstring and the SA model's column comments. Future maintainers who read those notes would understand the constraint exists; future maintainers who *don't* see those notes might "clean up" the apparently-redundant `scheduled_at_end` column and immediately break the conflict-detection contract that v0.3 is built on.

## Decision

**Denormalize a `scheduled_at_end` column on `schedule_items`** that holds `scheduled_at + duration_seconds * interval '1 second'` precomputed at write time. The EXCLUDE constraint then operates on `(channel_id, tstzrange(scheduled_at, scheduled_at_end, '[)'))`, which contains only IMMUTABLE expressions.

The column is maintained by a **Postgres trigger** (`schedule_items_scheduled_at_end_trigger`) that recomputes the value on every `INSERT` and on `UPDATE` of `scheduled_at` or `duration_seconds`. The trigger function is marked **STABLE** (not IMMUTABLE — it reads the row's other columns, which is by definition stable, not immutable). A SQLAlchemy event hook performs the same computation at the ORM layer for SQLite test paths that have neither the trigger nor `btree_gist`.

The denormalization is one column wider, costs one trigger fire per write, and cannot drift because the trigger is the only writer. The contract that any future maintainer needs to know is captured in:

- this ADR (the architectural decision);
- the migration `0003_create_schedule_items_table.py` upgrade docstring (the SQL contract);
- the migration `0005_schema_hardening_audit_v030.py` upgrade body (the trigger that audit-team v0.3.0 added so SQLAlchemy's previous-row hook is no longer the sole guarantor on Postgres);
- the `civiccast/schedule/models.py` `scheduled_at_end` column comment (the runtime invariant);
- `civiccast/schedule/README.md` "Migrations" section (the local-context entry point).

Removing the column is **not safe**. Re-deriving it inline would either reintroduce the IMMUTABLE error on Postgres or require a wrapped-function-marked-IMMUTABLE workaround whose semantic correctness is brittle.

## Alternatives rejected

1. **Wrap `tstzrange(scheduled_at, scheduled_at + duration * interval '1 second')` in a SQL function tagged IMMUTABLE.** Rejected. The function would lie about its volatility. Postgres's IMMUTABLE detection has tightened across versions; a future revalidation or `pg_upgrade` pass could expose the lie. The fix-it-once cost is denormalizing a column; the never-fix-it cost is silent constraint failure.

2. **Compute `tstzrange` in application code only and rely on the FastAPI layer to reject conflicts via a transactional `SELECT ... FOR UPDATE` lock.** Rejected. Two operators in two tabs racing to schedule on the same channel would still serialize through the lock, but the contract would live in Python rather than in the database, and a future module (a CivicSuite-side scheduler, an admin script, a one-off SQL migration) bypassing the application layer would silently bypass the conflict check. The whole point of EXCLUDE is to make conflict detection a property of the table, not a property of one calling path.

3. **Materialize `scheduled_at_end` as a `GENERATED ALWAYS AS (...) STORED` column.** Rejected for the same IMMUTABLE reason: Postgres requires generated-column expressions to be IMMUTABLE, and the timezone-arithmetic case fails the same predicate. (Postgres does allow `GENERATED ... AS IDENTITY` and STORED expressions over IMMUTABLE inputs, but not over the STABLE expressions we have here.)

4. **Use the `tsrange` (not `tstzrange`) variant on the assumption that timezone-naive timestamps would be IMMUTABLE.** Rejected. Civic broadcast scheduling is intrinsically across-timezone; storing schedule times without timezone information would either lie about user intent or push a manual "everything is UTC" contract onto every operator, which the spec's UX non-negotiables (§4.1) forbid.

## Consequences

### Positive

- Conflict detection is a property of the `schedule_items` table itself. Any writer — application code, SQL migration, future Mode-B CivicSuite scheduler — gets the constraint enforcement for free.
- The trigger is the only writer, so the denormalized column cannot drift from `(scheduled_at, duration_seconds)`.
- The IMMUTABLE workaround is documented in this ADR + the migration + the model + the schedule README, so a future maintainer cannot accidentally break the contract by tidying.
- The `tests/schedule/test_real_postgres.py` `TestRealPostgresScheduleConflictDetection` suite locks the contract end-to-end against postgres:17 via testcontainers (Sprint 0.3 task 4 + audit-team v0.3.0 TEST-002 closure).

### Negative

- One column wider. The cost is bytes per row, not bytes per query — the column is included in the EXCLUDE index but not in the typical row read.
- One trigger fire per `INSERT`/`UPDATE`. The trigger function is trivial arithmetic; benchmark on `schedule_items` is not measurable next to the EXCLUDE index check itself.
- Tests that bypass the migration (in-memory SQLite paths) need the SQLAlchemy event hook to maintain the column. The hook lives next to the model so the symmetry is visible.

### Neutral

- The denormalization makes the SA model one column more complex. The column comment names the workaround so the reason is visible from the ORM layer too.

## Implementation pointers

- Migration: `civiccast/schedule/migrations/versions/0003_create_schedule_items_table.py`
- Trigger added at audit-team v0.3.0 closure: `civiccast/schedule/migrations/versions/0005_schema_hardening_audit_v030.py`
- Model: `civiccast/schedule/models.py` (`ScheduleItem.scheduled_at_end`)
- Tests: `tests/schedule/test_real_postgres.py::TestRealPostgresScheduleConflictDetection`
- Schedule module README: `civiccast/schedule/README.md` (Migrations section names this ADR)

## Future work

The IMMUTABLE constraint is a Postgres engine quirk; we are not aware of a future Postgres release that lifts it. If one ever does, the trigger + denormalized column can be replaced by a generated-column derivation in a follow-up migration; the constraint would re-bind to the generated column without touching application code. The behavior under that hypothetical future migration is identical, so this ADR survives.
