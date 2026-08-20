# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CLI tests for `civiccast live-takeover` (S5 operator scripting surface).

The service build is monkeypatched to a fake so the commands exercise their
argument handling, success formatting, and error-exit mapping without a DB.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

import civiccast.cli as cli_module
from civiccast.cli import app
from civiccast.egress.models import ManualRouteState, TakeoverSession
from civiccast.egress.takeover_service import (
    AlreadyLiveError,
    NotInTakeoverError,
    TakeoverNotReadyError,
)

_SESSION = TakeoverSession(
    session_id="takeover-abc",
    channel_id="public",
    source_ref="srt://ingest",
    source_label="Council Chamber",
    operator_id="dana",
    operator_name="Dana",
    reason="meeting",
    took_over_at=datetime(2026, 6, 15, 12, 0, tzinfo=UTC),
    returned_at=None,
    source_plan_json="{}",
    notes=None,
)


class _FakeTakeover:
    def __init__(self, *, take_exc=None, handback_exc=None, state=None):  # type: ignore[no-untyped-def]
        self._take_exc = take_exc
        self._handback_exc = handback_exc
        self._state = state
        self.take_calls: list[dict] = []  # type: ignore[type-arg]
        self.handback_calls: list[dict] = []  # type: ignore[type-arg]

    def take(self, **kwargs):  # type: ignore[no-untyped-def]
        self.take_calls.append(kwargs)
        if self._take_exc is not None:
            raise self._take_exc
        return _SESSION

    def handback(self, **kwargs):  # type: ignore[no-untyped-def]
        self.handback_calls.append(kwargs)
        if self._handback_exc is not None:
            raise self._handback_exc
        return _SESSION

    def state(self, channel_id: str) -> ManualRouteState:
        return self._state  # type: ignore[return-value]


def _patch(monkeypatch: pytest.MonkeyPatch, fake: _FakeTakeover) -> None:
    monkeypatch.setattr(cli_module, "_build_takeover_service", lambda: fake)


def test_take_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTakeover()
    _patch(monkeypatch, fake)
    result = CliRunner().invoke(
        app,
        ["live-takeover", "take", "--channel-id", "public", "--operator-id", "dana"],
    )
    assert result.exit_code == 0
    assert "Live takeover started on public" in result.stdout
    assert "Council Chamber" in result.stdout
    assert fake.take_calls[0]["channel_id"] == "public"
    assert fake.take_calls[0]["operator_id"] == "dana"


def test_take_already_live_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeTakeover(take_exc=AlreadyLiveError("already live")))
    result = CliRunner().invoke(
        app, ["live-takeover", "take", "--channel-id", "public", "--operator-id", "dana"]
    )
    assert result.exit_code == 1
    assert "already under live takeover" in result.stdout


def test_take_not_ready_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeTakeover(take_exc=TakeoverNotReadyError("no source")))
    result = CliRunner().invoke(
        app, ["live-takeover", "take", "--channel-id", "public", "--operator-id", "dana"]
    )
    assert result.exit_code == 1
    assert "No ready live source" in result.stdout


def test_return_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeTakeover()
    _patch(monkeypatch, fake)
    result = CliRunner().invoke(
        app, ["live-takeover", "return", "--channel-id", "public", "--operator-id", "dana"]
    )
    assert result.exit_code == 0
    assert "Returned public to scheduled playout" in result.stdout
    assert fake.handback_calls[0]["channel_id"] == "public"


def test_return_not_live_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _FakeTakeover(handback_exc=NotInTakeoverError("not live")))
    result = CliRunner().invoke(
        app, ["live-takeover", "return", "--channel-id", "public", "--operator-id", "dana"]
    )
    assert result.exit_code == 1
    assert "not under live takeover" in result.stdout


def test_state_reports_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    state = ManualRouteState(
        channel_id="public", active_session=None, can_takeover=True, can_return=False
    )
    _patch(monkeypatch, _FakeTakeover(state=state))
    result = CliRunner().invoke(app, ["live-takeover", "state", "--channel-id", "public"])
    assert result.exit_code == 0
    assert "scheduled playout" in result.stdout
    assert "Can take live: yes" in result.stdout
    assert "Can return: no" in result.stdout
