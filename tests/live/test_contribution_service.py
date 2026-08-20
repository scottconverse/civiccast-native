# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S17 build step 9 slice 3b — VDO.Ninja bridge + orchestration service.

Covers civiccast.live.contribution.bridge (Null + Url URL minting + diagnostics
delegation) and civiccast.live.contribution.service.ContributionService (room
open/close, single-use invite mint + race-safe consume, the waiting-room admit
gate, on-air engine seam, guest state machine, max-guest limit, terms gate).
SQLite-backed store; a FakeBridge stands in for the self-hosted VDO instance.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.live.contribution.bridge import (
    GuestUrls,
    NullVdoNinjaBridge,
    UrlVdoNinjaBridge,
    VdoBridgeError,
    VdoDiagnostics,
)
from civiccast.live.contribution.models import (
    INVITE_TOKEN_MIN_LENGTH,
    ContributionRoom,
    RemoteGuestSession,
)
from civiccast.live.contribution.service import (
    ContributionService,
    GuestNotAdmittedError,
    InvalidGuestTransitionError,
    InviteConsumedError,
    InviteExpiredError,
    InviteNotFoundError,
    RoomClosedError,
    RoomGuestLimitError,
    RoomNotOpenError,
)
from civiccast.live.contribution.store import ContributionStore

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class FakeBridge:
    """A deterministic VDO.Ninja bridge for tests — records calls, mints stable
    URLs, returns an injectable diagnostics snapshot."""

    def __init__(self, diagnostics: VdoDiagnostics | None = None) -> None:
        self.opened: list[str] = []
        self._diag = diagnostics or VdoDiagnostics(turn_reachable=True, vdo_process_up=True)

    def director_url(self, room: ContributionRoom) -> str:
        self.opened.append(room.room_id)
        return f"https://vdo.test/?director={room.vdo_room_name}"

    def guest_urls(self, room: ContributionRoom, *, invite_token: str, role: str) -> GuestUrls:
        return GuestUrls(
            view_url=f"https://vdo.test/?room={room.vdo_room_name}&push={invite_token}",
            push_url=f"https://vdo.test/?view={invite_token}&solo=1",
        )

    def diagnostics(self) -> VdoDiagnostics:
        return self._diag


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ContributionStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'contribution.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield ContributionStore(factory)
    finally:
        eng.dispose()


def _make_service(store: ContributionStore, **kw: object):
    """Service with deterministic ids/tokens and a mutable clock holder."""
    now = [_T0]
    counter = {"n": 0}

    def _id() -> str:
        counter["n"] += 1
        return f"{counter['n']:04d}"

    def _token() -> str:
        counter["n"] += 1
        return f"token-{counter['n']:0>{INVITE_TOKEN_MIN_LENGTH}}"

    svc = ContributionService(
        store,
        bridge=kw.pop("bridge", FakeBridge()),
        clock=lambda: now[0],
        id_factory=_id,
        token_factory=_token,
        **kw,  # type: ignore[arg-type]
    )
    return svc, now


# --- bridge ------------------------------------------------------------------


def test_url_bridge_mints_deterministic_urls() -> None:
    bridge = UrlVdoNinjaBridge("https://vdo.station.example/")
    room = ContributionRoom(
        room_id="r1",
        channel_id="ch",
        name="Chamber",
        vdo_room_name="vdoabc",
        created_at=_T0,
        updated_at=_T0,
    )
    assert "director=vdoabc" in bridge.director_url(room)
    urls = bridge.guest_urls(room, invite_token="tok123", role="council_member")
    assert "push=tok123" in urls.view_url and "room=vdoabc" in urls.view_url
    assert "view=tok123" in urls.push_url and "solo=1" in urls.push_url


def test_url_bridge_rejects_empty_base() -> None:
    with pytest.raises(VdoBridgeError):
        UrlVdoNinjaBridge("   ")


def test_url_bridge_diagnostics_unwired_is_honest() -> None:
    bridge = UrlVdoNinjaBridge("https://vdo.test")
    diag = bridge.diagnostics()
    assert diag.turn_reachable is False
    assert "not wired" in diag.detail
    # With a probe wired it returns the probe's snapshot.
    wired = UrlVdoNinjaBridge(
        "https://vdo.test", diagnostics_probe=lambda: VdoDiagnostics(turn_reachable=True)
    )
    assert wired.diagnostics().turn_reachable is True


def test_null_bridge_fails_closed() -> None:
    bridge = NullVdoNinjaBridge()
    room = ContributionRoom(
        room_id="r1", channel_id="ch", name="x", vdo_room_name="v", created_at=_T0, updated_at=_T0
    )
    with pytest.raises(VdoBridgeError):
        bridge.director_url(room)
    with pytest.raises(VdoBridgeError):
        bridge.guest_urls(room, invite_token="t", role="presenter")
    assert bridge.diagnostics().turn_reachable is False


# --- rooms -------------------------------------------------------------------


def test_create_room_idle_with_fresh_vdo_token(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    a = svc.create_room(channel_id="ch", name="Room A")
    b = svc.create_room(channel_id="ch", name="Room B")
    assert a.state == "idle"
    assert a.vdo_room_name != b.vdo_room_name  # never reused across rooms


def test_open_room_requires_configured_bridge(store: ContributionStore) -> None:
    svc, _ = _make_service(store, bridge=NullVdoNinjaBridge())
    room = svc.create_room(channel_id="ch", name="Room A")
    with pytest.raises(VdoBridgeError):
        svc.open_room(room.room_id)


def test_open_room_sets_open_and_is_idempotent(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    room = svc.create_room(channel_id="ch", name="Room A")
    opened, director_url = svc.open_room(room.room_id)
    assert opened.state == "open"
    assert "director=" in director_url
    again, _u = svc.open_room(room.room_id)
    assert again.state == "open"


# --- invites + single-use resolve -------------------------------------------


def _open_room(svc) -> ContributionRoom:
    room = svc.create_room(channel_id="ch", name="Chamber")
    svc.open_room(room.room_id)
    return svc.get_room(room.room_id)


def test_mint_invite_then_resolve_creates_held_session(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    room = _open_room(svc)
    invite = svc.mint_invite(room_id=room.room_id, guest_display_name="Jane", role="council_member")
    assert len(invite.invite_token) >= INVITE_TOKEN_MIN_LENGTH
    assert invite.view_url and "push=" in invite.view_url

    view = svc.resolve_invite(invite.invite_token)
    assert view.needs_terms is False
    assert view.session_id is not None
    gs = svc.get_session(view.session_id)
    assert gs.state == "connected"
    assert gs.admitted_at is None  # HELD in the waiting room

    # Single-use: a second resolve of the same token is gone.
    with pytest.raises(InviteConsumedError):
        svc.resolve_invite(invite.invite_token)


def test_mint_invite_refused_on_closed_room(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    room = _open_room(svc)
    svc.close_room(room.room_id)
    with pytest.raises(RoomClosedError):
        svc.mint_invite(room_id=room.room_id, guest_display_name="Jane", role="presenter")


def test_resolve_unknown_expired_and_room_not_open(store: ContributionStore) -> None:
    svc, now = _make_service(store)
    with pytest.raises(InviteNotFoundError):
        svc.resolve_invite("nope-" + "x" * INVITE_TOKEN_MIN_LENGTH)

    # Room must be open to accept guests.
    idle = svc.create_room(channel_id="ch", name="Idle")
    # mint allowed against idle, but resolve refuses until opened.
    inv_idle = svc.mint_invite(room_id=idle.room_id, guest_display_name="Bob", role="presenter")
    with pytest.raises(RoomNotOpenError):
        svc.resolve_invite(inv_idle.invite_token)

    # Expiry.
    room = _open_room(svc)
    inv = svc.mint_invite(
        room_id=room.room_id,
        guest_display_name="Ann",
        role="presenter",
        ttl=timedelta(minutes=30),
    )
    now[0] = _T0 + timedelta(hours=1)  # advance past expiry
    with pytest.raises(InviteExpiredError):
        svc.resolve_invite(inv.invite_token)


def test_public_comment_must_accept_terms_before_join(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    room = _open_room(svc)
    inv = svc.mint_invite(
        room_id=room.room_id, guest_display_name="Resident", role="public_comment"
    )
    # First resolve: terms required, token NOT consumed (a re-resolve still asks).
    view = svc.resolve_invite(inv.invite_token)
    assert view.needs_terms is True
    assert view.session_id is None
    assert view.terms_version is not None
    assert svc.resolve_invite(inv.invite_token).needs_terms is True  # still not consumed

    # Accept terms, then resolve succeeds + consumes (proves it was unconsumed).
    svc.accept_terms(inv.invite_token)
    view2 = svc.resolve_invite(inv.invite_token)
    assert view2.needs_terms is False
    assert view2.session_id is not None


def test_max_guests_limit_enforced(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    room = svc.create_room(channel_id="ch", name="Solo", max_guests=1)
    svc.open_room(room.room_id)
    i1 = svc.mint_invite(room_id=room.room_id, guest_display_name="A", role="presenter")
    i2 = svc.mint_invite(room_id=room.room_id, guest_display_name="B", role="presenter")
    svc.resolve_invite(i1.invite_token)  # fills the single slot
    with pytest.raises(RoomGuestLimitError):
        svc.resolve_invite(i2.invite_token)


# --- guest-session operator actions -----------------------------------------


def _join(svc, room) -> str:
    inv = svc.mint_invite(room_id=room.room_id, guest_display_name="Guest", role="council_member")
    return svc.resolve_invite(inv.invite_token).session_id


def test_on_air_requires_admit_then_fires_hook_and_room_goes_live(store: ContributionStore) -> None:
    fired: list[tuple[str, str]] = []
    svc, _ = _make_service(
        store, on_air_hook=lambda gs, room: fired.append((gs.session_id, room.room_id))
    )
    room = _open_room(svc)
    sid = _join(svc, room)

    # Cannot go on-air before admit (waiting-room gate).
    with pytest.raises(GuestNotAdmittedError):
        svc.put_on_air(sid)

    admitted = svc.admit_guest(sid)
    assert admitted.admitted_at is not None
    assert svc.admit_guest(sid).admitted_at == admitted.admitted_at  # idempotent

    on_air = svc.put_on_air(sid)
    assert on_air.state == "on_air" and on_air.on_air_at is not None
    assert svc.get_room(room.room_id).state == "live"
    assert fired == [(sid, room.room_id)]


def test_mute_off_air_and_drop_transitions(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    room = _open_room(svc)
    sid = _join(svc, room)
    svc.admit_guest(sid)
    svc.put_on_air(sid)

    assert svc.mute_guest(sid).state == "muted"
    assert svc.take_off_air(sid).state == "connected"  # admitted retained
    dropped = svc.drop_guest(sid)
    assert dropped.state == "dropped" and dropped.ended_at is not None
    # Terminal: no further operator action is legal.
    with pytest.raises(InvalidGuestTransitionError):
        svc.admit_guest(sid)


def test_close_room_ends_active_guests(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    room = _open_room(svc)
    sid = _join(svc, room)
    svc.admit_guest(sid)
    svc.put_on_air(sid)
    svc.close_room(room.room_id)
    assert svc.get_room(room.room_id).state == "closed"
    assert svc.get_session(sid).state == "ended"


def test_update_connection_quality_is_advisory(store: ContributionStore) -> None:
    svc, _ = _make_service(store)
    room = _open_room(svc)
    sid = _join(svc, room)
    updated = svc.update_connection_quality(sid, "degraded")
    assert updated.connection_quality == "degraded"
    assert updated.state == "connected"  # quality never changes the state


def test_diagnostics_delegates_to_bridge(store: ContributionStore) -> None:
    bridge = FakeBridge(diagnostics=VdoDiagnostics(turn_reachable=True, ice_summary="ok"))
    svc, _ = _make_service(store, bridge=bridge)
    diag = svc.diagnostics()
    assert diag.turn_reachable is True and diag.ice_summary == "ok"


def test_dropping_on_air_guest_emits_alert_but_waiting_guest_does_not(
    store: ContributionStore,
) -> None:
    alerts: list[tuple[str, str]] = []
    svc, _ = _make_service(store, alert_hook=lambda k, d: alerts.append((k, d)))
    room = _open_room(svc)

    # A still-waiting guest dropped before air → no alert (nothing aired).
    waiting = _join(svc, room)
    svc.drop_guest(waiting)
    assert alerts == []

    # An on-air guest dropped → one guest-drop alert.
    live = _join(svc, room)
    svc.admit_guest(live)
    svc.put_on_air(live)
    svc.drop_guest(live)
    assert [k for k, _ in alerts] == ["remote-contribution-guest-drop"]


def test_drop_never_implies_offair_of_others(store: ContributionStore) -> None:
    """A dropped guest is independent — dropping one leaves another on-air."""
    svc, _ = _make_service(store)
    room = _open_room(svc)
    s1 = _join(svc, room)
    s2 = _join(svc, room)
    for sid in (s1, s2):
        svc.admit_guest(sid)
        svc.put_on_air(sid)
    svc.drop_guest(s1)
    assert isinstance(svc.get_session(s2), RemoteGuestSession)
    assert svc.get_session(s2).state == "on_air"
