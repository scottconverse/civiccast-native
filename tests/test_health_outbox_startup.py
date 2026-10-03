# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Actual app construction and retained journal preparation under finite gates."""

from __future__ import annotations

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from civiccast.reporting.asrun_outbox import AsRunOutbox
from civiccast.schema_check import SchemaStatus


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("close_held", [False, True])
def test_constructor_defers_owned_outbox_open(monkeypatch, tmp_path, explicit, close_held):
    import civiccast.app as module
    from civiccast.db import reset_engine

    for name in (
        "DATABASE_URL",
        "CIVICCAST_ALLOW_EPHEMERAL_STORES",
        "CIVICCAST_NATIVE_STATION_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    url = "sqlite:///:memory:"
    if explicit:
        monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "off")
    monkeypatch.setattr(module, "load_managed_database_url", lambda: url)
    monkeypatch.setattr(module, "ensure_managed_storage", lambda: SimpleNamespace(database_url=url))
    monkeypatch.setattr(module, "_managed_upload_dir_if_ready", lambda: None)
    monkeypatch.setattr(module, "_ensure_default_local_recording_target", lambda app: None)
    monkeypatch.setattr(module, "_prewarm_native_live_caption_runtime", lambda app: None)
    monkeypatch.setattr(module, "_maybe_start_finalization_worker", lambda app: None)
    monkeypatch.setattr("civiccast.egress.automation.reap_predecessor_relays", lambda **kw: [])
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )
    starts = []
    monkeypatch.setattr(
        "civiccast.platform.worker_runtime.ThreadSupervisor.start",
        lambda self, **kw: starts.append(self),
    )
    entered, release, constructed = threading.Event(), threading.Event(), threading.Event()
    apps, errors, connections = [], [], []
    original = AsRunOutbox._open_connection

    def held(self):
        assert self._db_path.resolve().is_relative_to(tmp_path.resolve())
        entered.set()
        assert release.wait(8)
        conn = original(self)
        connections.append(conn)
        return conn

    monkeypatch.setattr(AsRunOutbox, "_open_connection", held)

    def construct():
        try:
            apps.append(module.create_app())
        except Exception as exc:
            errors.append(exc)
        finally:
            constructed.set()

    thread = threading.Thread(target=construct)
    thread.start()
    try:
        assert constructed.wait(2), "auxiliary journal must not block actual create_app"
        assert not entered.is_set() and not errors
        app = apps[0]
        app.state.durable_storage_backfill = lambda: None
        # Hooks are separately covered; this case isolates journal initialization.
        app.state.startup_condition_hooks = []
        with TestClient(app) as client:
            assert entered.wait(1)
            assert client.get("/health").json()["status"] == "degraded"
            assert not app.state.durable_storage_active and not starts
            owner = app.state.health_schema_owner
            if close_held:
                app.state.lifespan_started = False
                assert not owner.close(0.01)
                assert not app.state.as_run_outbox.close(wait=False)
            release.set()
            if close_held:
                assert owner.close(2)
                assert not app.state.durable_storage_active and not starts
                assert len(connections) == 1
                with pytest.raises(sqlite3.ProgrammingError):
                    connections[0].execute("SELECT 1")
            else:
                deadline = time.monotonic() + 2
                body = client.get("/health").json()
                while body["status"] != "healthy" and time.monotonic() < deadline:
                    time.sleep(0.01)
                    body = client.get("/health").json()
                assert body["status"] == "healthy"
                assert body["schema_db_revision"] == body["schema_expected_head"] == "head"
                assert starts and len(connections) == 1
                app.state.as_run_outbox.initialize()
                assert app.state.as_run_outbox.pending_count() == 0
                assert len(connections) == 1
    finally:
        release.set()
        thread.join(3)
        assert not thread.is_alive()
        for app in apps:
            assert app.state.health_schema_owner.close(2)
            if hasattr(app.state, "as_run_outbox"):
                assert app.state.as_run_outbox.close()
        for conn in connections:
            conn.close()
        reset_engine()


def test_failed_journal_schema_initialization_closes_handle(monkeypatch, tmp_path):
    from civiccast.reporting.asrun_outbox import AsRunOutboxJournalError

    closed = []
    connection = SimpleNamespace(
        execute=lambda statement: None,
        executescript=lambda statement: (_ for _ in ()).throw(
            sqlite3.OperationalError("fake schema failure")
        ),
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: connection)
    outbox = AsRunOutbox(object(), db_path=tmp_path / "failed.sqlite3", defer_open=True)
    try:
        with pytest.raises(AsRunOutboxJournalError):
            outbox.initialize()
        assert closed == [True], "failed initialization must release the opened handle"
    finally:
        outbox.close()


@pytest.mark.parametrize("feature", ["captions", "translation"])
def test_inline_model_selection_is_not_constructor_io(monkeypatch, tmp_path, feature):
    import civiccast.app as module
    from civiccast.db import reset_engine

    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path / "tap"))
    monkeypatch.setattr(module, "_ensure_default_local_recording_target", lambda app: None)
    monkeypatch.setattr("civiccast.egress.automation.reap_predecessor_relays", lambda **kw: [])
    monkeypatch.setattr(module, "_maybe_start_finalization_worker", lambda app: None)
    monkeypatch.setattr(module, "_maybe_start_background_supervisors", lambda app: None)
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )
    entered, release, constructed = threading.Event(), threading.Event(), threading.Event()
    apps = []
    calls = []
    runtime, translator = object(), object()

    def caption(service, **kwargs):
        calls.append("captions")
        if feature == "captions":
            entered.set()
            assert release.wait(8)
        return runtime

    def translation(service):
        calls.append("translation")
        if feature == "translation":
            entered.set()
            assert release.wait(8)
        return translator

    monkeypatch.setattr(module, "build_caption_runtime", caption)
    monkeypatch.setattr(module, "build_translator", translation)
    monkeypatch.setattr(
        module,
        "build_tap_worker",
        lambda *args, **kw: SimpleNamespace(
            _runtime=kw["runtime"],
            _translation_provider=kw["translation_provider"],
            run_forever=lambda **kw: None,
        ),
    )

    def construct():
        apps.append(module.create_app())
        constructed.set()

    thread = threading.Thread(target=construct)
    thread.start()
    try:
        assert constructed.wait(2), "inline model selection must not block construction"
        assert not entered.is_set() and not calls
        app = apps[0]
        app.state.durable_storage_backfill = lambda: None
        app.state.startup_condition_hooks = []
        with TestClient(app) as client:
            assert entered.wait(1)
            assert client.get("/health").json()["status"] == "degraded"
            release.set()
            deadline = time.monotonic() + 2
            body = client.get("/health").json()
            while body["status"] != "healthy" and time.monotonic() < deadline:
                time.sleep(0.01)
                body = client.get("/health").json()
            assert body["status"] == "healthy"
            assert body["schema_db_revision"] == body["schema_expected_head"] == "head"
            assert calls == ["captions", "translation"]
            assert app.state.caption_tap_worker._runtime is runtime
            assert app.state.caption_tap_worker._translation_provider is translator
    finally:
        release.set()
        thread.join(3)
        assert not thread.is_alive()
        for app in apps:
            assert app.state.health_schema_owner.close(2)
            assert app.state.as_run_outbox.close()
        reset_engine()


@pytest.mark.parametrize("explicit", [False, True])
def test_full_constructor_database_barrier_with_inline_captions(monkeypatch, tmp_path, explicit):
    from sqlalchemy.engine import Engine

    import civiccast.app as module
    from civiccast.db import reset_engine

    url = "sqlite:///:memory:"
    for name in (
        "DATABASE_URL",
        "CIVICCAST_ALLOW_EPHEMERAL_STORES",
        "CIVICCAST_NATIVE_STATION_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)
    if explicit:
        monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path / "tap"))
    monkeypatch.setenv("CIVICCAST_EGRESS_DEGRADED_REASON", "finite fake degraded reason")
    monkeypatch.setattr(module, "load_managed_database_url", lambda: url)
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("constructor entered deferred DB/preparation boundary")

    monkeypatch.setattr(Engine, "connect", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(module, "ensure_managed_storage", forbidden)
    monkeypatch.setattr(module, "build_caption_runtime", forbidden)
    monkeypatch.setattr(module, "build_translator", forbidden)
    monkeypatch.setattr("civiccast.egress.automation.reap_predecessor_relays", forbidden)
    monkeypatch.setattr("civiccast.egress.automation._raise_egress_degraded_alert", forbidden)
    app = module.create_app()
    try:
        assert calls == []
        assert not app.state.durable_storage_active
        assert not hasattr(app.state, "caption_tap_worker")
    finally:
        assert app.state.health_schema_owner.close(1)
        assert app.state.as_run_outbox.close()
        reset_engine()
