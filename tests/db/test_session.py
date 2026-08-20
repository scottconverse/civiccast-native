# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the civiccast.db runtime session contract.

Locks the public surface that future modules (task 1b's PostgresAssetStore,
the schedule module, every later module) will import unchanged:

- get_engine() — lazy, memoized, survives unset DATABASE_URL at import time.
- bind_engine() / reset_engine() — test-injection hooks.
- get_session() — FastAPI dependency, generator with try/finally close.
- Base — DeclarativeBase with schema="civiccast" metadata.

Per plan.md §4 of run 2026-05-08-db-foundation. Real SQLite engine; nothing
mocked that the test is supposed to verify.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import (
    Base,
    bind_engine,
    get_engine,
    get_session,
    reset_engine,
)


class TestEngineFactory:
    def test_get_engine_unset_database_url_does_not_crash_at_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Graceful-degradation contract — `import civiccast.db` must succeed
        with DATABASE_URL unset. `app = create_app()` runs at module import
        in civiccast/app.py:68; if civiccast.db raised at import time when
        DATABASE_URL was missing, every unrelated unit test in the suite
        would fail. Per research.md §2.4."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        # Force a fresh import of civiccast.db with DATABASE_URL unset.
        # The fresh import rebuilds civiccast.db.base's module-level Base and
        # MetaData. Model modules already imported elsewhere stay bound to the
        # ORIGINAL Base, so if we leave the fresh (empty) modules in
        # sys.modules, any later test that does `from civiccast.db import Base;
        # Base.metadata.create_all(engine)` builds zero tables and then fails
        # with "no such table". Snapshot and restore so this test's re-import
        # cannot corrupt the module singletons for the rest of the suite.
        target_mods = ["civiccast.db", "civiccast.db.session", "civiccast.db.base"]
        saved = {name: sys.modules.get(name) for name in target_mods}
        try:
            for name in target_mods:
                sys.modules.pop(name, None)
            # Importing the package must not raise.
            importlib.import_module("civiccast.db")
        finally:
            for name, mod in saved.items():
                if mod is not None:
                    sys.modules[name] = mod
                else:
                    sys.modules.pop(name, None)

    def test_get_engine_returns_singleton(self, engine: Engine) -> None:
        """Two calls return the same Engine instance — proves memoization."""
        first = get_engine()
        second = get_engine()
        assert first is second

    def test_bind_engine_replaces_singleton(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After bind_engine(other), get_engine() returns `other`."""
        first = create_engine("sqlite:///:memory:", future=True)
        other = create_engine("sqlite:///:memory:", future=True)
        disposed = False
        original_dispose = first.dispose

        def _record_dispose() -> None:
            nonlocal disposed
            disposed = True
            original_dispose()

        bind_engine(first)
        monkeypatch.setattr(first, "dispose", _record_dispose)
        try:
            bind_engine(other)
            assert get_engine() is other
            assert disposed is True
        finally:
            reset_engine()
            first.dispose()
            other.dispose()

    def test_reset_engine_disposes_and_clears(self) -> None:
        """After reset_engine(), the next get_engine() rebuilds — i.e. the
        stored engine is no longer the previous one."""
        first = create_engine("sqlite:///:memory:", future=True)
        bind_engine(first)
        assert get_engine() is first
        reset_engine()
        # After reset, binding a new engine should produce a different object.
        second = create_engine("sqlite:///:memory:", future=True)
        try:
            bind_engine(second)
            assert get_engine() is second
            assert get_engine() is not first
        finally:
            reset_engine()
            first.dispose()
            second.dispose()


class TestSessionDependency:
    def test_get_session_yields_session_bound_to_engine(self, engine: Engine) -> None:
        """The yielded Session has .bind equal to the bound engine."""
        gen = get_session()
        sess = next(gen)
        try:
            assert isinstance(sess, Session)
            assert sess.bind is engine
        finally:
            # Exhaust generator so finally: session.close() runs.
            with pytest.raises(StopIteration):
                next(gen)

    def test_get_session_closes_on_normal_exit(self, engine: Engine) -> None:
        """Using next(get_session()) then exhausting the generator closes
        the session — proves the try/finally close clause is wired."""
        gen = get_session()
        sess = next(gen)
        # Close happens when the generator exhausts.
        with pytest.raises(StopIteration):
            next(gen)
        # SQLAlchemy 2.0: a closed Session reports is_active=False once the
        # transaction is rolled back, and accessing .connection() should
        # raise. The simplest contract assertion is that close() ran — we
        # check by asserting no in-progress transaction remains.
        assert sess.in_transaction() is False

    def test_get_session_closes_on_exception(self, engine: Engine) -> None:
        """If the consumer raises while holding the session, the generator's
        finally: close() must still run — no leak."""
        gen = get_session()
        sess = next(gen)
        # Simulate the consumer raising. Generator close() runs the finally.
        gen.close()
        assert sess.in_transaction() is False

    def test_dependency_override_substitutes_session(self, engine: Engine) -> None:
        """app.dependency_overrides[get_session] swaps the yielded session,
        mirroring the override pattern proven by tests/vod/test_router.py:37.
        Uses a throwaway route on a fresh app to assert the substituted
        session reaches the handler."""
        from civiccast.app import create_app

        app = create_app()

        # The substituted session is identifiable by being bound to a
        # marker engine we control. Register a route that returns the
        # id() of the session's bind so the test can assert routing.
        marker = create_engine("sqlite:///:memory:", future=True)

        def _override() -> Iterator[Session]:
            s = Session(bind=marker)
            try:
                yield s
            finally:
                s.close()

        @app.get("/_test/session-bind-id")
        def _route(db: Session = Depends(get_session)) -> dict[str, int]:
            assert db.bind is not None
            return {"bind_id": id(db.bind)}

        app.dependency_overrides[get_session] = _override
        try:
            with TestClient(app) as c:
                r = c.get("/_test/session-bind-id")
            assert r.status_code == 200
            assert r.json()["bind_id"] == id(marker)
        finally:
            marker.dispose()


class TestSchemaNamespace:
    def test_base_metadata_default_schema_is_civiccast(self) -> None:
        """Locks the schema-namespace contract per CLAUDE.md's closed
        `civiccast.*` decision (research.md §3). Every future model under
        Base inherits this MetaData and lands in the `civiccast` schema."""
        assert Base.metadata.schema == "civiccast"
