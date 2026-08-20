# civiccast.db — Database Substrate

Sprint 0.3 task 1a module. Owns the SQLAlchemy 2.0 declarative base, the
shared engine binding, and the Alembic root that hosts per-module migration
trees.

## Architecture

See [ADR 0008](../../docs/adr/0008-database-session-pattern.md) — sync
SQLAlchemy 2.0 + psycopg v3 + per-module Alembic migrations under a single
root `env.py`. Sync (not async) was the explicit pick: Celery and the rest of
the platform substrate are sync, and FastAPI handles sync handlers natively
on a thread pool.

## Public API

```python
from civiccast.db import Base, bind_engine, reset_engine, get_session
```

- `Base` — `DeclarativeBase` with the `civiccast.*` PostgreSQL schema
  pre-attached via `metadata.schema = "civiccast"`. Every CivicCast table
  inherits from this.
- `bind_engine(engine)` — install an SA `Engine` for the current process.
  Called once at app boot; subsequent calls replace the binding (used in
  tests).
- `reset_engine()` — clear the binding. Tests use this in fixture teardown.
- `get_session()` — FastAPI-shaped dependency yielding a `Session`. Closes
  the session on generator exit.

## Migrations

Per-module migration trees live under `civiccast/<module>/migrations/`. The
root `alembic/env.py` discovers each tree via `version_locations` declared
in `alembic.ini`. Migrations:

- Use the schema-qualified table form (`civiccast.assets`, not `assets`).
- Implement both `upgrade()` and `downgrade()`. Reversibility is tested in
  `tests/schedule/test_migration_reversibility.py`.
- Guard Postgres-only DDL (CHECK constraints, ALTER COLUMN, btree_gist) with
  `_use_schema()` so SQLite test paths stay green.

## SQLite-vs-Postgres divergence

SQLite ignores schema qualifiers in queries but rejects schema-qualified DDL
(`CREATE TABLE civiccast.assets`). The schedule module ships an
`@event.listens_for(Engine, "connect")` listener that ATTACHes an in-memory
database under the alias `civiccast` for SQLite connections only — Postgres
ignores the hook.

This works for tests (in-memory) and for the cleanroom CI gate (in-memory).
**It does not persist to file-backed SQLite databases**, so `sqlite:///foo.db`
URLs are not a supported dev configuration. Use Postgres for dev, the same as
production. See `apps/portal-operator/README.md` for the dev startup path.

## Tests

- `tests/db/test_alembic_env.py` — root env.py loads, version_locations are
  discovered, upgrade head + downgrade base both succeed.
- `tests/db/test_session.py` — bind/reset/get_session round-trip.
- `tests/schedule/test_real_postgres.py` — testcontainers + real Postgres
  17, run when Docker is available.
