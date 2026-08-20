# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S17 build step 9 slice 3e — guest on-air → channel live seam.

Covers civiccast.live.contribution.on_air.build_contribution_on_air_hook: it
fires the channel live-takeover on guest-on-air, is a safe no-op when no engine
is wired, and never raises a takeover failure into the operator's action (a guest
going on-air must not 500). The real takeover (S5 content-reload) + compositing
are proven elsewhere; this is the wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from civiccast.live.contribution.models import ContributionRoom, RemoteGuestSession
from civiccast.live.contribution.on_air import build_contribution_on_air_hook

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _room(channel_id: str = "ch_gov") -> ContributionRoom:
    return ContributionRoom(
        room_id="room_1",
        channel_id=channel_id,
        name="Chamber",
        vdo_room_name="vdo_1",
        created_at=_T0,
        updated_at=_T0,
    )


def _session() -> RemoteGuestSession:
    return RemoteGuestSession(
        session_id="gs_1",
        room_id="room_1",
        invite_id="inv_1",
        guest_display_name="Jane",
        proof_boundary="lab",
    )


def test_hook_fires_channel_takeover() -> None:
    taken: list[str] = []
    hook = build_contribution_on_air_hook(taken.append)
    hook(_session(), _room("ch_school"))
    assert taken == ["ch_school"]


def test_hook_suppresses_already_live_error() -> None:
    from civiccast.egress.takeover_service import AlreadyLiveError

    def _already_live(_channel_id: str) -> None:
        raise AlreadyLiveError("channel already live")

    # AlreadyLiveError is swallowed — idempotent: a second guest in an already-live room.
    build_contribution_on_air_hook(_already_live)(_session(), _room())


def test_hook_is_safe_no_op_without_engine() -> None:
    # No take_live wired (operator airs the composited feed) — must not raise.
    build_contribution_on_air_hook(None)(_session(), _room())


def test_takeover_non_ready_error_propagates_from_hook() -> None:
    from civiccast.egress.takeover_service import TakeoverNotReadyError

    def _not_ready(_channel_id: str) -> None:
        raise TakeoverNotReadyError("engine not ready")

    # Non-AlreadyLiveError exceptions propagate — the service reverts state and returns 503.
    with pytest.raises(TakeoverNotReadyError):
        build_contribution_on_air_hook(_not_ready)(_session(), _room())
