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
