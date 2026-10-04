# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Concurrency and freshness contracts without real DB or app services."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from civiccast.db.guarded_connect import run_bounded
from civiccast.health_schema import HealthSchemaOwner
from civiccast.schema_check import SchemaStatus


def _wait(predicate) -> None:
    deadline = time.monotonic() + 2
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert predicate()


def test_retains_actual_timed_out_worker_and_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()
    calls = []
    now = [0.0]
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="db")

    def read(source):
        calls.append(source)
        if len(calls) == 1:

            def blocked():
                entered.set()
                try:
                    assert release.wait(2)
                finally:
                    exited.set()

            try:
                run_bounded(blocked, ceiling_seconds=0.02)
            except TimeoutError:
                return SchemaStatus(state="unknown")
        return SchemaStatus(state="current", db_revision="head", expected_head="head")

    monkeypatch.setattr("civiccast.schema_check.check_schema_currency", read)
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: "db", ttl_seconds=1, clock=lambda: now[0]
    )
    try:
        assert owner.request().state == "unknown"
        assert entered.wait(1)
        _wait(lambda: state.schema_status_checked_monotonic is not None)
        now[0] = 2
        for _ in range(10):
            assert owner.request().state == "unknown"
        assert calls == ["db"]
        release.set()
        assert exited.wait(1)
        _wait(lambda: all(f.done() for f in owner._work))
        owner.request()
        _wait(lambda: state.schema_status.state == "current")
        assert owner.request().db_revision == "head"
        assert calls == ["db", "db"]
    finally:
        release.set()
        assert owner.close(2)


@pytest.mark.parametrize("invalidate", ["source", "close", "explicit"])
def test_late_results_never_publish(monkeypatch: pytest.MonkeyPatch, invalidate: str) -> None:
    entered, release = threading.Event(), threading.Event()
    source = ["old"]
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="old")

    def read(_source):
        entered.set()
        assert release.wait(2)
        return SchemaStatus(state="current", db_revision="old", expected_head="old")

    monkeypatch.setattr("civiccast.schema_check.check_schema_currency", read)
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: source[0], ttl_seconds=1
    )
    try:
        owner.request()
        assert entered.wait(1)
        if invalidate == "source":
            source[0] = "new"
            owner.request()
        elif invalidate == "explicit":
            owner.invalidate()
        else:
            assert not owner.close(0.01)
        release.set()
        owner._thread.join(1)
        assert state.schema_status.state == "unknown"
        assert state.schema_status.db_revision is None
        assert state.schema_status_checked_monotonic is None
    finally:
        release.set()
        assert owner.close(2)


def test_failure_is_cached_and_stale_success_not_served(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]
    calls = []
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="db")

    def read(_source):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("private driver detail")
        return SchemaStatus(state="current", db_revision="head", expected_head="head")

    monkeypatch.setattr("civiccast.schema_check.check_schema_currency", read)
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: "db", ttl_seconds=1, clock=lambda: now[0]
    )
    try:
        owner.request()
        _wait(lambda: state.schema_status.state == "current")
        now[0] = 2
        assert owner.request().state == "unknown"
        _wait(lambda: len(calls) == 2 and not owner._thread.is_alive())
        assert owner.request().state == "unknown"
        assert len(calls) == 2
        now[0] = 4
        owner.request()
        _wait(lambda: state.schema_status.state == "current")
        assert len(calls) == 3
    finally:
        assert owner.close(2)


def test_current_schema_for_different_unwired_source_cannot_attest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="old")
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus(state="current", db_revision="head", expected_head="head"),
    )
    owner = HealthSchemaOwner(state, sync_storage=lambda: None, source=lambda: "new", ttl_seconds=1)
    try:
        owner.request()
        _wait(lambda: state.schema_status_checked_monotonic is not None)
        verdict = owner.request()
        assert verdict.state == "unknown"
        assert verdict.db_revision is None and verdict.expected_head is None
    finally:
        assert owner.close(2)


def test_diagnostics_identify_held_refresh_phase_without_private_source(monkeypatch, caplog):
    import json
    import logging

    from civiccast import health_provenance

    monkeypatch.setattr(health_provenance, "ENABLED", True)
    entered, release = threading.Event(), threading.Event()
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="PRIVATE_URL")
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )

    def held_storage():
        entered.set()
        assert release.wait(2)

    owner = HealthSchemaOwner(
        state, sync_storage=held_storage, source=lambda: "PRIVATE_URL", ttl_seconds=5
    )
    try:
        assert callable(getattr(owner, "diagnostic_snapshot", None)), "phase snapshot is missing"
        with caplog.at_level(logging.INFO, logger="civiccast.health_provenance"):
            assert owner.request().state == "unknown"
            assert entered.wait(1)
            snapshot = owner.diagnostic_snapshot()
            assert snapshot["phase"] == "sync_storage"
            assert snapshot["attempt"] == 1 and snapshot["epoch"] == 0
            assert snapshot["elapsed_ms"] >= 0
            assert snapshot["queued_ms"] >= 0
            before = owner._thread
            for _ in range(20):
                assert owner.request().state == "unknown"
            assert owner._thread is before
            snapshot["phase"] = "PRIVATE_EXCEPTION"
            owner._diagnostic_phase("PRIVATE_URL")
            assert owner.diagnostic_snapshot()["phase"] == "sync_storage"
            release.set()
            owner._thread.join(1)
        records = [r.message for r in caplog.records if "Health schema refresh phase " in r.message]
        assert records, "opt-in existing proof logger must expose the active worker phase"
        assert all("PRIVATE_" not in r for r in records)
        payloads = [json.loads(r.split("phase ", 1)[1]) for r in records]
        assert {p["phase"] for p in payloads} >= {"started", "sync_storage", "complete"}
        assert len(owner.diagnostic_snapshot()) <= 12
    finally:
        release.set()
        assert owner.close(2)


def test_diagnostics_distinguish_head_read_graph_and_retained_work(monkeypatch):
    import civiccast.schema_check as checks
    from civiccast import health_provenance

    monkeypatch.setattr(health_provenance, "ENABLED", True)
    entered, release = threading.Event(), threading.Event()
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="PRIVATE_URL")
    monkeypatch.setattr(checks, "expected_migration_head", lambda: "head")
    monkeypatch.setattr(checks, "known_revisions", lambda: frozenset({"head"}))

    def held_read(source):
        def actual():
            entered.set()
            assert release.wait(2)
            return "head"

        return run_bounded(actual, ceiling_seconds=0.03)

    monkeypatch.setattr(checks, "read_db_revision", held_read)
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: "PRIVATE_URL", ttl_seconds=5
    )
    try:
        assert callable(getattr(owner, "diagnostic_snapshot", None)), "phase snapshot is missing"
        owner.request()
        assert entered.wait(1)
        assert owner.diagnostic_snapshot()["phase"] == "read"
        owner._thread.join(1)
        snapshot = owner.diagnostic_snapshot()
        assert snapshot["phase"] == "retained_work" and snapshot["retained_work"] == 1
        assert snapshot["state"] == "unknown"
        owner.request(invalidate=True)
        assert owner.diagnostic_snapshot()["attempt"] == 1
        release.set()
    finally:
        release.set()
        _wait(lambda: all(future.done() for future in owner._work))
        assert owner.close(2)


@pytest.mark.parametrize("phase", ["head", "read", "graph"])
def test_diagnostic_real_schema_check_phase_is_not_guessed(monkeypatch, phase):
    import civiccast.schema_check as checks
    from civiccast import health_provenance

    monkeypatch.setattr(health_provenance, "ENABLED", True)
    entered, release = threading.Event(), threading.Event()
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="PRIVATE_URL")

    def held(value):
        entered.set()
        assert release.wait(2)
        return value

    monkeypatch.setattr(
        checks, "expected_migration_head", lambda: held("head") if phase == "head" else "head"
    )
    monkeypatch.setattr(
        checks, "read_db_revision", lambda source: held("head") if phase == "read" else "head"
    )
    monkeypatch.setattr(
        checks,
        "known_revisions",
        lambda: held(frozenset({"head"})) if phase == "graph" else frozenset({"head"}),
    )
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: "PRIVATE_URL", ttl_seconds=5
    )
    try:
        owner.request()
        assert entered.wait(1)
        assert owner.diagnostic_snapshot()["phase"] == phase
        assert owner.request().state == "unknown"
        release.set()
        owner._thread.join(1)
        assert owner.request().state == "current"
        assert owner.diagnostic_snapshot()["phase"] == "complete"
    finally:
        release.set()
        assert owner.close(2)


def test_diagnostic_queued_delay_is_observed_only_when_existing_worker_starts(monkeypatch, caplog):
    import logging

    from civiccast import health_provenance

    monkeypatch.setattr(health_provenance, "ENABLED", True)
    now = [0.0]
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="PRIVATE_URL")
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )

    class DeferredThread:
        def __init__(self, *, target, **kwargs):
            self.target = target

        def start(self):
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(threading, "Thread", DeferredThread)
    owner = HealthSchemaOwner(
        state,
        sync_storage=lambda: None,
        source=lambda: "PRIVATE_URL",
        ttl_seconds=5,
        clock=lambda: now[0],
    )
    with caplog.at_level(logging.INFO, logger="civiccast.health_provenance"):
        owner.request()
        assert owner.diagnostic_snapshot()["phase"] == "queued"
        assert not caplog.records, "HTTP queue publication must not emit logging IO"
        now[0] = 6
        owner._thread.target()
    assert owner.diagnostic_snapshot()["queued_ms"] == 6000
    slow = [
        r.message for r in caplog.records if "Health schema refresh slow completion " in r.message
    ]
    assert len(slow) == 1 and "PRIVATE_URL" not in slow[0]
    assert owner.diagnostic_snapshot()["elapsed_ms"] == 6000
    now[0] = 12
    assert owner.diagnostic_snapshot()["elapsed_ms"] == 6000, "completed duration must not age"


def test_diagnostics_default_off_has_no_phase_log_or_private_export(monkeypatch, caplog):
    from civiccast import health_provenance

    monkeypatch.setattr(health_provenance, "ENABLED", False)
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="PRIVATE_URL")
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: "PRIVATE_URL", ttl_seconds=5
    )
    try:
        owner.request()
        owner._thread.join(1)
        assert owner.diagnostic_snapshot() == {}
        assert not any("Health schema refresh" in r.message for r in caplog.records)
    finally:
        assert owner.close(2)


def test_diagnostic_logging_failure_cannot_change_readiness(monkeypatch):
    from civiccast import health_provenance

    monkeypatch.setattr(health_provenance, "ENABLED", True)

    def broken_logger(*args, **kwargs):
        raise RuntimeError("PRIVATE_LOGGER_EXCEPTION")

    monkeypatch.setattr(health_provenance._LOG, "info", broken_logger)
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="PRIVATE_URL")
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: "PRIVATE_URL", ttl_seconds=5
    )
    try:
        owner.request()
        owner._thread.join(1)
        assert owner.request().state == "current"
        assert "PRIVATE" not in str(owner.diagnostic_snapshot())
    finally:
        assert owner.close(2)


def test_schema_phase_observer_is_scoped_and_failure_is_non_semantic(monkeypatch):
    import civiccast.schema_check as checks

    monkeypatch.setattr(checks, "expected_migration_head", lambda: "head")
    monkeypatch.setattr(checks, "read_db_revision", lambda source: "head")
    monkeypatch.setattr(checks, "known_revisions", lambda: frozenset({"head"}))
    calls = []

    def observer(phase):
        calls.append(phase)
        raise RuntimeError("PRIVATE_OBSERVER_EXCEPTION")

    with checks.observe_schema_phases(observer):
        assert checks.check_schema_currency("PRIVATE_URL").state == "current"
    assert calls == ["head", "read", "graph"]
    checks.check_schema_currency("PRIVATE_URL")
    assert calls == ["head", "read", "graph"], "phase observer leaked beyond its scope"


@pytest.mark.parametrize("diagnostic_operation", ["replace", "_RefreshDiagnostic"])
def test_diagnostic_snapshot_update_failure_cannot_abort_refresh(monkeypatch, diagnostic_operation):
    import civiccast.health_schema as module
    from civiccast import health_provenance

    monkeypatch.setattr(health_provenance, "ENABLED", True)
    calls = []

    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_DIAGNOSTIC_UPDATE")

    monkeypatch.setattr(module, diagnostic_operation, fail)
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: calls.append(source) or SchemaStatus("current", "head", "head"),
    )
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="PRIVATE_URL")
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: None, source=lambda: "PRIVATE_URL", ttl_seconds=5
    )
    try:
        owner.request()
        owner._thread.join(1)
        assert calls == ["PRIVATE_URL"], "diagnostic update prevented real schema work"
        assert owner.request().state == "current"
    finally:
        assert owner.close(2)


def test_diagnostic_epoch_tracks_legitimate_storage_invalidation(monkeypatch):
    from civiccast import health_provenance

    monkeypatch.setattr(health_provenance, "ENABLED", True)
    monkeypatch.setattr(
        "civiccast.schema_check.check_schema_currency",
        lambda source: SchemaStatus("current", "head", "head"),
    )
    state = SimpleNamespace(durable_storage_active=True, durable_storage_url="PRIVATE_URL")
    owner = HealthSchemaOwner(
        state, sync_storage=lambda: owner.invalidate(), source=lambda: "PRIVATE_URL", ttl_seconds=5
    )
    try:
        owner.request()
        owner._thread.join(1)
        assert owner.request().state == "current"
        assert owner._epoch == 1
        assert owner.diagnostic_snapshot()["epoch"] == 1
        assert owner.diagnostic_snapshot()["attempt"] == 1
    finally:
        assert owner.close(2)
