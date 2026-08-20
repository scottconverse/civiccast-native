<!-- SPDX-License-Identifier: CC-BY-4.0 -->
<!-- Copyright (c) The CivicCast Authors -->

# Alembic — CivicCast monorepo migrations

This directory holds the *single* Alembic environment for the entire
CivicCast monorepo. Per [ADR 0008](../docs/adr/0008-database-session-pattern.md)
and director-decisions §2 of run 2026-05-08-db-foundation:

- One `alembic.ini` at the repo root.
- One `env.py` here.
- Per-module migration directories live under
  `civiccast/<module>/migrations/versions/`.
- `env.py` walks the `civiccast/` tree at startup and tells Alembic
  about every per-module version directory it finds.

## Where do I put a new migration?

Inside the owning module:

```
civiccast/
  vod/
    migrations/
      versions/
        20260512_initial_assets.py
  schedule/
    migrations/
      versions/
        20260520_initial_channels.py
```

The repo-root `alembic/versions/` slot is **reserved-not-in-use**.
A migration dropped here is still picked up by the runner (so a
mistake does not silently no-op) but the convention is to keep
migrations next to their owning module's code.

## Running migrations

The connection URL is resolved from the `DATABASE_URL` environment
variable. Set it once for your shell and Alembic + the runtime
`civiccast.db` engine factory both pick it up.

```bash
export DATABASE_URL="postgresql+psycopg://civiccast:civiccast@localhost:5432/civiccast"

# Apply every pending migration across every module.
alembic upgrade head

# Roll all the way back (CI tests both directions).
alembic downgrade base

# Generate a new migration in the owning module's directory.
alembic revision -m "add channel slug index" \
    --version-path civiccast/schedule/migrations/versions
```

`--version-path` is required at `revision` time because Alembic does
not know which module a new migration belongs to.

## Why one env.py instead of one per module?

CivicCast plans ~19 modules at v1.0. A separate Alembic env per
module would mean N migration runners, N CI commands, and N upgrade
orderings for operators to manage. The single-env-with-per-module
versions layout reconciles CLAUDE.md's "each module owns its own
migration directory" rule with the operational simplicity of one
`alembic upgrade head`. See ADR 0008 for the full decision trail.
