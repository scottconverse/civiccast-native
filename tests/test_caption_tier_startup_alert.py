# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""PR #80 follow-up: an orphaned-caption-tier degrade must be operator-visible.

The fallback itself works (the station degrades to the proven floor tier and
starts), but on a real box its only trace was a supervisor-process log line no
operator would ever see. These tests prove the startup hook lands a real,
readable ``caption-tier-degraded`` condition in the existing S8 alert hub from
the ``CIVICCAST_CAPTION_TIER_EVENT`` environment station_runtime already emits,
de-dupes across degraded restarts, resolves on a healthy start, and never
writes a spurious audit row on a normal boot.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.alerting.models  # noqa: F401  (registers the SA tables)
from civiccast.alerting.store import get_alert_events
from civiccast.app import _build_caption_tier_startup_condition
from civiccast.db import Base, bind_engine, reset_engine

_ENV = "CIVICCAST_CAPTION_TIER_EVENT"

_DEGRADED_EVENT = {
    "event": "caption-tier-selected",
    "tier": "captions-floor",
    "requested": "captions-large-v3",
    "fallback": True,
    "reason": (
        "caption tier captions-large-v3 is staged but has no valid activation "
        "self-test receipt at its base root (orphaned by an uninstall/reinstall "
        "upgrade); degraded to the proven floor tier"
    ),
}

_HEALTHY_EVENT = {
    "event": "caption-tier-selected",
    "tier": "captions-large-v3",
    "fallback": False,
}


@pytest.fixture
def session_factory() -> Iterator[object]:
    eng: Engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bind_engine(eng)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield factory
    finally:
        reset_engine()
        eng.dispose()


def _events(session_factory: object, state: str | None = None) -> list:
    with session_factory() as session:  # type: ignore[operator]
        return get_alert_events(session, state=state)


def test_degraded_start_raises_an_operator_visible_alert(
    session_factory: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_ENV, json.dumps(_DEGRADED_EVENT))

    _build_caption_tier_startup_condition(session_factory)()

    firing = _events(session_factory, state="firing")
    assert len(firing) == 1
    event = firing[0]
    assert event.condition == "caption-tier-degraded"
    assert event.resource_ref == "caption-tier"
    assert "standard tier" in event.summary
    assert "captions-large-v3" in event.summary
    assert "AI Models" in event.summary
    assert "orphaned by an uninstall/reinstall upgrade" in event.detail


def test_degraded_restarts_dedupe_into_one_firing_event(
    session_factory: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_ENV, json.dumps(_DEGRADED_EVENT))

    _build_caption_tier_startup_condition(session_factory)()
    _build_caption_tier_startup_condition(session_factory)()

    firing = _events(session_factory, state="firing")
    assert len(firing) == 1
    assert firing[0].occurrence_count == 2


def test_healthy_start_resolves_a_previously_firing_alert(
    session_factory: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_ENV, json.dumps(_DEGRADED_EVENT))
    _build_caption_tier_startup_condition(session_factory)()

    monkeypatch.setenv(_ENV, json.dumps(_HEALTHY_EVENT))
    _build_caption_tier_startup_condition(session_factory)()

    assert _events(session_factory, state="firing") == []
    resolved = _events(session_factory, state="resolved")
    # The store's resolve path flips the FIRING row's state in place (its
    # original summary is the audit record of what was degraded).
    assert len(resolved) == 1
    assert resolved[0].condition == "caption-tier-degraded"
    assert resolved[0].resolved_at is not None


def test_healthy_start_with_nothing_firing_writes_no_rows(
    session_factory: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(_ENV, json.dumps(_HEALTHY_EVENT))

    _build_caption_tier_startup_condition(session_factory)()

    assert _events(session_factory) == []


def test_absent_or_garbled_env_never_raises_and_writes_nothing(
    session_factory: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(_ENV, raising=False)
    _build_caption_tier_startup_condition(session_factory)()  # absent -> no-op

    monkeypatch.setenv(_ENV, "{not json")
    _build_caption_tier_startup_condition(session_factory)()  # garbled -> no-op

    monkeypatch.setenv(_ENV, json.dumps(["not", "a", "dict"]))
    _build_caption_tier_startup_condition(session_factory)()  # wrong shape -> no-op

    assert _events(session_factory) == []


def test_alert_sink_failure_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hook must never take down the control plane: a broken session
    factory (schema-less / unreachable DB at that moment) is logged and
    swallowed, matching every other S8 producer."""

    monkeypatch.setenv(_ENV, json.dumps(_DEGRADED_EVENT))

    def broken_factory() -> None:
        raise RuntimeError("db down")

    _build_caption_tier_startup_condition(broken_factory)()  # no exception
