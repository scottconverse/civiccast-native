# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""PlayoutSupervisor consumes takeover/handback commands (S5 daemon slice).

Proves the supervisor turns a queued ``takeover`` command into a
``request_live_takeover`` of the open session's plan (and ``handback`` into a
handback), without a live GStreamer engine — a stub strategy captures the
source swap. The actual on-air swap + as-aired proof are the WSL/tester lanes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiccast.egress.models import (
    EgressCommand,
    EgressSourcePlan,
    EgressSourceSegment,
    TakeoverSession,
)
from civiccast.egress.store import InMemoryEgressStore
from civiccast.egress.supervisor import PlayoutSupervisor

_NOW = datetime(2026, 6, 20, 18, 0, 0, tzinfo=UTC)


class _SwapStrategy:
    """Stub encoder strategy that records live-swap requests instead of running
    a real engine (PlayoutSupervisor._reload_or_swap uses supports_live_swap)."""

    supports_live_swap = True

    def __init__(self) -> None:
        self.swaps: list[tuple[str, str]] = []

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:
        self.swaps.append((channel_id, role))


class _FakeReader:
    def __init__(self, session: TakeoverSession | None) -> None:
        self._session = session

    def get_active(self, channel_id: str) -> TakeoverSession | None:
        return self._session


def _live_plan(channel_id: str = "public") -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label="Live: Council chamber",
                path="rtmp://127.0.0.1/live/public",
                duration_seconds=3600.0,
                kind="live",
                source_ref="public:local",
            )
        ],
    )


def _session(channel_id: str = "public") -> TakeoverSession:
    return TakeoverSession(
        session_id="takeover-tok",
        channel_id=channel_id,
        source_ref="public:local",
        source_label="Live: Council chamber",
        operator_id="dana",
        operator_name="Dana",
        reason=None,
        took_over_at=_NOW,
        returned_at=None,
        source_plan_json=_live_plan(channel_id).model_dump_json(),
        notes=None,
    )


def _command(action: str, channel_id: str = "public") -> EgressCommand:
    return EgressCommand(
        channel_id=channel_id,
        action=action,  # type: ignore[arg-type]
        issued_at=_NOW,
        issued_by="dana",
        command_id=f"{action}-1",
    )


def _supervisor(
    reader: object | None, strategy: _SwapStrategy, tmp_path: Path
) -> PlayoutSupervisor:
    kwargs: dict[str, object] = {
        "work_dir": tmp_path,
        "source_plan_provider": lambda channel_id: None,
        "encoder_strategy": strategy,
    }
    if reader is not None:
        kwargs["takeover_audit_store"] = reader
    return PlayoutSupervisor(InMemoryEgressStore(), **kwargs)  # type: ignore[arg-type]


def test_takeover_command_drives_a_seamless_content_reload(tmp_path: Path) -> None:
    # A live takeover changes the PROGRAM-LEG CONTENT (scheduled -> live), so the
    # supervisor drives a content-reload (which rebuilds the program leg from
    # _next_source_plan -> the live plan, 0-CC), NOT a phantom 'live' pad swap.
    strategy = _SwapStrategy()
    sup = _supervisor(_FakeReader(_session()), strategy, tmp_path)
    reloads: list[str] = []
    sup._request_reload = lambda channel_id: reloads.append(channel_id)  # type: ignore[method-assign]
    sup._process_command(_command("takeover"))
    # The supervisor recorded the live plan and routed it to a content-reload.
    assert "public" in sup._live_takeover_plans
    assert sup._live_takeover_plans["public"].segments[0].kind == "live"
    # _next_source_plan now resolves the live plan (what the reload will rebuild to).
    assert sup._next_source_plan("public").segments[0].kind == "live"
    assert reloads == ["public"]
    assert strategy.swaps == []  # live is not a selector pad


def test_handback_command_clears_takeover_and_reloads_scheduled(tmp_path: Path) -> None:
    strategy = _SwapStrategy()
    sup = _supervisor(_FakeReader(_session()), strategy, tmp_path)
    reloads: list[str] = []
    sup._request_reload = lambda channel_id: reloads.append(channel_id)  # type: ignore[method-assign]
    sup._process_command(_command("takeover"))
    sup._process_command(_command("handback"))
    assert "public" not in sup._live_takeover_plans
    # Both takeover and handback are content-reloads of the program leg; neither is
    # a pad swap (the always-hot slate pad is untouched throughout).
    assert reloads == ["public", "public"]
    assert strategy.swaps == []


def test_takeover_with_no_active_session_is_a_noop(tmp_path: Path) -> None:
    strategy = _SwapStrategy()
    sup = _supervisor(_FakeReader(None), strategy, tmp_path)
    sup._process_command(_command("takeover"))
    assert "public" not in sup._live_takeover_plans
    assert strategy.swaps == []


def test_takeover_with_no_store_is_a_noop(tmp_path: Path) -> None:
    strategy = _SwapStrategy()
    sup = _supervisor(None, strategy, tmp_path)  # no takeover_audit_store wired
    sup._process_command(_command("takeover"))
    assert "public" not in sup._live_takeover_plans
    assert strategy.swaps == []


def test_non_takeover_commands_delegate_to_the_daemon(tmp_path: Path) -> None:
    # A 'stop' command flows to the base daemon's handler and writes STOPPED.
    strategy = _SwapStrategy()
    sup = _supervisor(_FakeReader(_session()), strategy, tmp_path)
    sup._process_command(_command("stop"))
    state = sup._store.read_state("public")
    assert state is not None
    assert state.state == "STOPPED"


def test_base_daemon_rejects_takeover_action(tmp_path: Path) -> None:
    # The non-takeover-capable base daemon raises on a takeover action (loud,
    # not silent) — the supervisor is the only engine that consumes it.
    from civiccast.egress.daemon import EgressDaemon
    from civiccast.egress.errors import ConfigInvalidError

    daemon = EgressDaemon(
        InMemoryEgressStore(),
        work_dir=tmp_path,
        source_plan_provider=lambda channel_id: None,
    )
    with pytest.raises(ConfigInvalidError):
        daemon._process_command(_command("takeover"))
