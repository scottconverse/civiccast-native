# ADR 0008 — Database session pattern: sync SQLAlchemy 2.0, psycopg v3, per-module Alembic migrations under one env

**Status:** Accepted
**Date:** 2026-05-09
**Deciders:** Scott Converse (human director)
**Related rung:** 0.3 — Schedule module (task 1a, DB foundation)
**Related spec section:** §5.1 Backend stack (FastAPI / SQLAlchemy / Alembic), §5.4 Liveness + readiness, CLAUDE.md "Tooling" (Database: PostgreSQL 17 + pgvector; Migrations: Alembic, both directions tested) and "Closed architectural decisions" (Schema: `civiccast.*`; Repository layout: per-module migration directories)
**Supersedes:** N/A
**Superseded by:** N/A

---

## Context

Sprint 0.3's first task is to land the project's first-time database scaffolding: a SQLAlchemy declarative base, an engine factory + FastAPI session dependency, and an initialized Alembic environment with reversible up/down semantics. Every later module (the schedule module at this rung, the `PostgresAssetStore` in task 1b that replaces `civiccast.vod.store.InMemoryAssetStore`, every persistence-touching module through 1.0) imports from this foundation. The contract has to be right on the first pass — there are no callers to break today, but every future caller will be locked to this shape.

Three implementation questions need to resolve before code lands:

1. **Sync vs async SQLAlchemy.** FastAPI is async-first by default, which makes async SQLAlchemy + asyncpg the textbook answer. But the actual repo state contradicts the textbook: every existing route handler is `def`, not `async def` (`civiccast/app.py:42`, `civiccast/vod/router.py:66`); every test uses `fastapi.testclient.TestClient` (sync); `grep -rn 'async def\|await ' civiccast/` returns zero matches. The Sprint 0.2 `AssetStore` Protocol declares sync methods. Choosing async now would force either an `asyncio.run(...)` wrapper inside the future `PostgresAssetStore` (anti-pattern: one event loop per call), or a breaking change to the rung 0.2 sync `AssetStore` Protocol (forbidden by this rung's `forbidden_paths`), or a forked codebase convention (every Sprint 0.3+ route `async def`, every Sprint 0.1/0.2 route `def`).

2. **Driver choice.** Once sync is on the table, the driver options are psycopg v3 (the third-generation Postgres driver with full SQLAlchemy 2.0 support and good ergonomics), psycopg2-binary (the legacy driver), and asyncpg (async-only, ruled out by question 1). `psycopg[binary]` ships a pre-built wheel that does not require system Postgres dev headers, removing a contributor-machine install hazard.

3. **Alembic layout.** CLAUDE.md's "Closed architectural decisions" says "Each module has its own subdirectory with its own README.md, CHANGELOG.md, test suite, and Alembic migration directory." Read literally, that means N independent Alembic environments (one per module), N `alembic_version` tables, N CI commands, N upgrade orderings — operationally untenable at the project's planned ~19-module v1.0 scope. The manifest's `expected_outputs` for this task name a single repo-root `alembic.ini` and `alembic/env.py`. These two readings disagree on the surface; the question is whether to honor CLAUDE.md's per-module *envs* literally or honor it as per-module *files* under one shared env.

Independently, CLAUDE.md's closed schema decision says CivicCast's tables live in the `civiccast.*` Postgres namespace. The session foundation has to set that namespace at the metadata level so every future model lands in the right place automatically.

## Decision

`civiccast.db` ships as **sync SQLAlchemy 2.0 with the typed `DeclarativeBase` API**, configured against `MetaData(schema="civiccast")` so every future ORM model lands in the project's reserved Postgres namespace by default. The Postgres driver is **`psycopg[binary]>=3.2`** — the third-generation driver, installed via the binary wheel extra. The session dependency is a generator (`def get_session() -> Iterator[Session]`) that yields a per-request `Session` and closes it in `finally`, so FastAPI's `Depends`-with-override pattern that already proves itself in `civiccast/vod/router.py` extends to the database layer unchanged.

The Alembic environment is **one `alembic.ini` + one `alembic/env.py` at the repo root**, with **per-module migration directories under `civiccast/<module>/migrations/versions/`** discovered at runtime. CLAUDE.md's "each module has its own Alembic migration directory" is honored as per-module *files* feeding into a single shared migration runner — the spirit (per-module file ownership) without the operational cost (N independent runners). The repo-root `alembic/versions/` slot is reserved-not-in-use; a migration accidentally dropped there is still picked up rather than silently ignored.

Both `alembic upgrade head` and `alembic downgrade base` are exercised in CI against an ephemeral SQLite database. Task 1b's first real migration hooks into the same harness; the harness shape is proven before any real schema lands, which is what the manifest's "the wiring is proven before any real schema lands" demands.

## Alternatives considered

### Sync vs async SQLAlchemy

**Option A — Sync SQLAlchemy 2.0 + psycopg v3.** Consistent with the existing sync route handlers, the existing sync `AssetStore` Protocol, and the existing sync `TestClient`-based test suite. SQLAlchemy 2.0's typed `Session` + `DeclarativeBase` + `Mapped[...]` give mypy-strict ergonomics at parity with the async API. FastAPI's threadpool handles the blocking I/O without a single line of `async`/`await` anywhere in `civiccast/db/`. **Selected.**

**Option B — Async SQLAlchemy + asyncpg.** The textbook FastAPI answer. Rejected for this rung *not because async is wrong* but because the rest of the codebase is sync, and forcing async here either (a) creates an `asyncio.run(...)` wrapper inside the future `PostgresAssetStore` (anti-pattern: new event loop per call, blocks the request thread, undoes every benefit of the async driver), (b) requires a breaking change to the rung 0.2 sync `AssetStore` Protocol (forbidden by this rung's `forbidden_paths`), or (c) forks the codebase convention so half the routes are `async def` and half are `def`. The release plan does not name a flip-the-handlers-to-async rung through 1.0. Async is *deferred*, not *ruled out* — a future ADR alongside the work that converts the route handlers can reverse this decision.

### Driver choice

**Option A — `psycopg[binary]>=3.2`.** Third-generation psycopg, full SQLAlchemy 2.0 support, the binary wheel ships pre-built so no system `libpq` headers are required at install time on contributor machines or CI runners. Cross-platform: wheels exist for Linux, macOS, and Windows on Python 3.12+. **Selected.**

**Option B — `psycopg2-binary`.** The legacy driver. Rejected because (a) it is the previous generation; psycopg v3 has cleaner async support (relevant for the future async-flip ADR) and better SQLAlchemy 2.0 integration; (b) `psycopg2-binary` is in maintenance-only mode upstream; (c) no functional advantage at this rung's scope.

**Option C — `asyncpg`.** Async-only. Tied to async SQLAlchemy, which Option B above rules out for this rung.

### Alembic layout

**Option A — One `alembic.ini` + one `alembic/env.py`, per-module version directories under `civiccast/<module>/migrations/versions/`, discovered at startup.** CLAUDE.md's "each module owns its own migration directory" is honored as per-module *files* under a single shared runner. One `alembic upgrade head` walks every module's graph; one `alembic downgrade base` walks them all back. The repo-root `alembic/versions/` slot stays reserved-not-in-use — included in the discovery set so an accidentally-dropped migration is not silently ignored, but the convention is to keep migrations next to their owning module's code. **Selected.**

**Option B — N independent Alembic envs (one per module), one `alembic.ini` and `alembic/env.py` per module.** A literal reading of CLAUDE.md's closed decision. Rejected because (a) at v1.0's planned ~19 modules, this means N migration runners, N CI commands, N `alembic_version` tables, and N upgrade orderings for operators to manage; (b) the operational cost has no compensating benefit when the modules all live in one Postgres schema (per CLAUDE.md's other closed decision); (c) the manifest's `expected_outputs` for this task name a single repo-root layout, which the planner read as the binding interpretation of CLAUDE.md.

**Option C — One `alembic.ini`, one `alembic/env.py`, all migrations under the repo-root `alembic/versions/` (no per-module directories).** Operationally simplest, but loses per-module file ownership entirely. Rejected because CLAUDE.md's "each module has its own migration directory" is a real ownership statement — when a module is refactored, retired, or split, its migrations should move with it. The Option A split lets module-owners curate their own version directory while preserving the single-runner ergonomics.

## Consequences

### Positive

- **Single-language stack and single convention.** Every existing route handler stays `def`; every existing test keeps using sync `TestClient`; the future `PostgresAssetStore` plugs into the existing sync `AssetStore` Protocol without an event-loop wrapper.
- **Typed mypy-strict ergonomics.** SQLAlchemy 2.0's `DeclarativeBase` + `Mapped[T]` give full type information without the legacy `declarative_base()` API's `Any`-ish return type. The strict-mypy posture in `[tool.mypy]` survives unchanged.
- **Clean test-injection seam.** `app.dependency_overrides[get_session]` mirrors the existing override pattern used by `tests/vod/test_router.py` for `get_store`. New tests for DB-backed routes do not need a new pattern to learn.
- **Lazy engine factory survives unset `DATABASE_URL` at import time.** `import civiccast.db` does not crash when `DATABASE_URL` is unset, so the umbrella app's `app = create_app()` at module-import time keeps working in unit-test contexts that never touch the database.
- **One `alembic upgrade head` walks every module's graph.** Operators see one migration UI; CI runs one command; the per-module file ownership is preserved.
- **No system Postgres dev headers required.** `psycopg[binary]` ships a pre-built wheel; contributor onboarding does not require `apt install libpq-dev` or the macOS Postgres-developer-files install.

### Negative

- **Async migration debt deferred.** When the rest of the codebase converts to `async def` route handlers, `civiccast/db/` will need to ship an async `Session` factory + `get_async_session` dependency, and the synchronous `Session` may need to coexist or migrate. The cost of the conversion is bounded — the public API is small (5 callables) — but it is real.
- **One `alembic.ini` interpolation gap.** ConfigParser's `BasicInterpolation` does not pull from `os.environ`, and the `alembic` CLI does not import the project's compat shim before reading the ini. The shim in `civiccast/db/_alembic_compat.py` patches `alembic.config.Config.__init__` to fill `sqlalchemy.url` from `DATABASE_URL` post-init; the patch installs on import of `civiccast.db`, which `alembic/env.py` triggers. This adds one indirection layer that contributors need to understand if they trace the URL resolution path.
- **`alembic/versions/` reserved-not-in-use.** New contributors may put a migration there by mistake. The discovery code picks it up regardless (so the mistake does not silently no-op), but the convention is documented in `alembic/README.md` and ADR Compliance below; expect occasional review-time corrections.

### Risks

- **SQLite-vs-Postgres divergence in tests (research.md §5.3).** `tests/db/` runs against ephemeral SQLite for wiring proof. SQLite ignores the `civiccast` schema qualifier; the `MetaData(schema="civiccast")` decision survives the test but is not actually exercised at DDL-time on SQLite. Postgres-only features (jsonb columns, pgvector, schema enforcement) will need a real-Postgres test pass at task 1b. *Mitigation:* the wiring test asserts `Base.metadata.schema == "civiccast"` at the metadata level (not at runtime DDL), which locks the contract; task 1b's planner is bound by this ADR's Compliance to add a real-Postgres test pass; `alembic/env.py` suppresses the schema kwargs when the dialect is SQLite so the ephemeral test does not crash on `civiccast.alembic_version` table creation.

- **CI cwd drift breaking Alembic discovery.** `Path("civiccast").glob("*/migrations")` evaluated against a non-repo-root cwd returns `[]` and silently turns `alembic upgrade head` into a no-op for every module. *Mitigation:* `alembic/env.py` resolves the discovery root relative to `Path(__file__).parent.parent / "civiccast"` — not relative to cwd. The wiring test `test_discovery_walks_civiccast_module_migrations` exercises the absolute-path resolution.

- **Future async migration adds two-API friction.** If the codebase eventually adopts `async def` route handlers, `civiccast/db/` will host both `Session` (sync) and `AsyncSession` (async) for some transition period. *Mitigation:* this is a deferred decision for a future ADR. The decision lands alongside the work that converts the route handlers, not before it.

- **`psycopg[binary]` wheel availability on unsupported platforms.** The binary wheel is published for Python 3.12+ on the OSes the project supports per ADR 0003 (WSL2 Ubuntu, native Linux, macOS). A contributor on a platform without a published wheel would fall through to a source build, which requires `libpq-dev`. *Mitigation:* `civiccast doctor` (Sprint 0.1) reports the failure with a clear remediation hint; the source-build fallback path is documented in `psycopg`'s upstream docs.

## Compliance

- **`civiccast/db/` public API is the contract every later module imports unchanged.** `from civiccast.db import Base, get_engine, get_session, bind_engine, reset_engine` — these five names are stable across the project. A change to any of their signatures requires a superseding ADR.

- **`Base.metadata.schema == "civiccast"` at the metadata level.** Locked by `tests/db/test_session.py::TestSchemaNamespace::test_base_metadata_default_schema_is_civiccast`. Every model that inherits from `Base` lands in the `civiccast` namespace by default; explicit `__table_args__ = {"schema": ...}` overrides are an ADR-level change.

- **Per-module migration directories under `civiccast/<module>/migrations/versions/`.** Documented in `alembic/README.md`. The `alembic revision -m ... --version-path civiccast/<module>/migrations/versions` invocation is the contributor-facing convention. A lint script that flags new migrations created at the reserved repo-root `alembic/versions/` slot is deferred to `next-cleanup.md` per the planner's decision; the convention is documented in this ADR and in `alembic/README.md` regardless.

- **Both `alembic upgrade head` and `alembic downgrade base` are exercised against an ephemeral SQLite database** in CI. Locked by `tests/db/test_alembic_env.py::TestAlembicReversibility::test_upgrade_head_on_empty_graph_succeeds` and `test_downgrade_base_on_empty_graph_succeeds`. Task 1b's first real migration hooks into the same harness; the migration's `downgrade()` body MUST be implemented and tested per CLAUDE.md's Tooling clause.

- **`version_table_schema="civiccast"` on dialects that support schemas.** `alembic/env.py` passes the kwarg when the dialect is not SQLite; the migration metadata table lives in the same namespace as the data tables. Locked by `tests/db/test_alembic_env.py::TestAlembicReversibility::test_version_table_schema_is_civiccast_on_postgres_dialect`.

- **Real-Postgres schema test at task 1b.** This ADR binds task 1b's planner to add at least one test pass that runs against a real Postgres instance (CI sidecar or local container) so the `civiccast` schema is exercised at DDL time, not just at the metadata level. The SQLite-for-wiring split is acceptable for task 1a per the manifest; task 1b cannot rely on it alone.

- **Lint posture for generated migration files** is deferred to task 1b. `alembic/versions/` ships empty in this rung; the ruff configuration for generated files (long lines, autogenerated imports) is task 1b's call once a real migration template is in use. Tracked in `next-cleanup.md`.

## References

- CivicCastUnifiedSpec-v2.md §5.1 Backend stack
- CivicCastUnifiedSpec-v2.md §5.4 Liveness + readiness
- CivicCast-ReleasePlan-0.1-to-1.0.md — rung 0.3 Schedule module scope
- CLAUDE.md — Tooling (Database, Migrations); Closed architectural decisions (Schema: `civiccast.*`; Repository layout)
- ADR 0001 — Messaging substrate (NATS JetStream; rules out Postgres LISTEN/NOTIFY as broadcast bus, but allows it for low-volume row-change notifications — relevant context for future use of the Postgres connection ADR 0008 establishes)
- ADR 0003 — Project hardware (CI runs on Ubuntu; cross-platform requirement for the driver choice)
- ADR 0004 — uv as workspace tool (`uv.lock` is committed and updated by `uv lock` after any dependency change; CI runs `uv sync --frozen`)
- ADR 0005 — Sprint 0.1 framework stack (FastAPI + Typer + Pydantic; main-deps inline-comment convention this ADR follows)
- [SQLAlchemy 2.0 typed declarative base](https://docs.sqlalchemy.org/en/20/orm/declarative_styles.html#using-a-late-defined-typed-declarative-base)
- [psycopg v3 documentation](https://www.psycopg.org/psycopg3/docs/)
- [Alembic per-module `version_locations`](https://alembic.sqlalchemy.org/en/latest/branches.html#working-with-explicit-branches)
- Plan: `.agent-runs/2026-05-08-db-foundation/plan.md`
- Director decisions: `.agent-runs/2026-05-08-db-foundation/director-decisions.md`
- Research: `.agent-runs/2026-05-08-db-foundation/research.md`

---

*ADRs are immutable once Accepted. Reversing or superseding requires a new ADR that references this one. Do not edit the substance of an Accepted ADR — only its Status field and a one-line note pointing to the superseding ADR.*
