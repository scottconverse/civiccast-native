# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S17 build step 9 slice 3a — remote-contribution data layer.

Covers civiccast.live.contribution.models (ContributionRoom / GuestInvite /
RemoteGuestSession validators + ORM peers) and
civiccast.live.contribution.store.ContributionStore (room CRUD, single-use
invite consume, terms recording, guest-session state machine). SQLite-backed;
the live-Postgres head + namespace checks live in tests/live/test_real_postgres.py.
The 0048 migration's up/down reversibility is asserted by
TestRemoteContributionMigration via the real Alembic chain on ephemeral SQLite.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.live.contribution.models import (
    INVITE_TOKEN_MIN_LENGTH,
    ContributionRoom,
    GuestInvite,
    RemoteGuestSession,
)
from civiccast.live.contribution.store import (
    ContributionStore,
    RoomNotFoundError,
)

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
_TOKEN = "tok_" + "a" * INVITE_TOKEN_MIN_LENGTH


def _naive(dt: datetime | None) -> datetime | None:
    # SQLite (test backend) drops tzinfo on round-trip; production Postgres keeps
    # it. Compare wall-clock values regardless of which backend answered.
    return dt.replace(tzinfo=None) if dt is not None else None


REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


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


def _room(room_id: str = "room_chamber", **kw: object) -> ContributionRoom:
    base: dict[str, object] = {
        "room_id": room_id,
        "channel_id": "ch_gov",
        "name": "Council Chamber Guests",
        "vdo_room_name": "vdo_" + room_id,
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kw)
    return ContributionRoom(**base)  # type: ignore[arg-type]


def _invite(invite_id: str = "inv_jane", *, token: str = _TOKEN, **kw: object) -> GuestInvite:
    base: dict[str, object] = {
        "invite_id": invite_id,
        "room_id": "room_chamber",
        "guest_display_name": "Jane (remote)",
        "role": "council_member",
        "invite_token": token,
        "expires_at": _T0 + timedelta(hours=2),
        "created_at": _T0,
    }
    base.update(kw)
    return GuestInvite(**base)  # type: ignore[arg-type]


def _session(session_id: str = "gs_jane", **kw: object) -> RemoteGuestSession:
    base: dict[str, object] = {
        "session_id": session_id,
        "room_id": "room_chamber",
        "invite_id": "inv_jane",
        "guest_display_name": "Jane (remote)",
        "proof_boundary": "LAN loopback; no internet NAT traversal proven.",
    }
    base.update(kw)
    return RemoteGuestSession(**base)  # type: ignore[arg-type]


# --- model validation --------------------------------------------------------


def test_room_defaults_idle_and_gst_compositor() -> None:
    room = _room()
    assert room.state == "idle"
    assert room.compositor_target == "gst_compositor"
    assert room.max_guests == 6


def test_room_max_guests_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        _room(max_guests=0)
    with pytest.raises(ValidationError):
        _room(max_guests=51)


def test_room_unknown_state_and_compositor_rejected() -> None:
    with pytest.raises(ValidationError):
        _room(state="paused")  # not in RoomState
    with pytest.raises(ValidationError):
        _room(compositor_target="ffmpeg")  # not in CompositorTarget


def test_invite_token_minimum_length_enforced() -> None:
    with pytest.raises(ValidationError):
        _invite(token="tooshort")
    # Exactly the floor is accepted.
    ok = _invite(token="z" * INVITE_TOKEN_MIN_LENGTH)
    assert len(ok.invite_token) == INVITE_TOKEN_MIN_LENGTH


def test_invite_unknown_contribution_role_rejected() -> None:
    with pytest.raises(ValidationError):
        _invite(role="setup_admin")  # an auth role, not a contribution role


def test_guest_session_defaults_held_in_waiting_room() -> None:
    gs = _session()
    assert gs.state == "invited"
    assert gs.connection_quality == "unknown"
    assert gs.admitted_at is None  # held until the operator admits
    assert gs.on_air_at is None


# --- room store --------------------------------------------------------------


def test_room_upsert_get_list_by_channel_set_state_delete(store: ContributionStore) -> None:
    store.upsert_room(_room("room_a", channel_id="ch_gov"))
    store.upsert_room(_room("room_b", channel_id="ch_school", name="School Board Guests"))

    assert store.get_room("room_a") is not None
    gov = store.list_rooms(channel_id="ch_gov")
    assert [r.room_id for r in gov] == ["room_a"]
    assert len(store.list_rooms()) == 2

    opened = store.set_room_state("room_a", "open", updated_at=_T0 + timedelta(minutes=1))
    assert opened.state == "open"
    assert _naive(opened.updated_at) == _naive(_T0 + timedelta(minutes=1))

    store.delete_room("room_b")
    assert store.get_room("room_b") is None
    with pytest.raises(RoomNotFoundError):
        store.delete_room("room_b")


def test_room_upsert_updates_existing(store: ContributionStore) -> None:
    store.upsert_room(_room("room_a", name="Original"))
    updated = store.upsert_room(_room("room_a", name="Renamed", max_guests=10))
    assert updated.name == "Renamed"
    assert updated.max_guests == 10
    assert len(store.list_rooms()) == 1


# --- invite store + single-use consume --------------------------------------


def test_invite_create_get_by_token_and_list(store: ContributionStore) -> None:
    store.upsert_room(_room())
    store.create_invite(_invite("inv_1", token=_TOKEN))
    store.create_invite(_invite("inv_2", token="tok_" + "b" * INVITE_TOKEN_MIN_LENGTH))

    by_token = store.get_invite_by_token(_TOKEN)
    assert by_token is not None and by_token.invite_id == "inv_1"
    assert store.get_invite_by_token("nope") is None
    assert {i.invite_id for i in store.list_invites_for_room("room_chamber")} == {"inv_1", "inv_2"}


def test_invite_token_is_unique(store: ContributionStore) -> None:
    store.create_invite(_invite("inv_1", token=_TOKEN))
    with pytest.raises(IntegrityError):
        store.create_invite(_invite("inv_2", token=_TOKEN))


def test_single_use_consume_wins_once(store: ContributionStore) -> None:
    # Future expiry so the consume (which uses real now() and now enforces
    # expiry atomically — ENG-009) tests the single-use RACE, not expiry.
    store.create_invite(
        _invite("inv_1", token=_TOKEN, expires_at=datetime.now(UTC) + timedelta(hours=2))
    )
    assert store.consume_invite_token(_TOKEN) is True
    # A second consume of the same token loses the guarded UPDATE race.
    assert store.consume_invite_token(_TOKEN) is False
    # consumed_at is now stamped.
    assert store.get_invite("inv_1").consumed_at is not None
    # An unknown token never consumes.
    assert store.consume_invite_token("ghost-token-value-aaaaaaaaaaaaaaaa") is False


def test_consume_rejects_expired_token_atomically(store: ContributionStore) -> None:
    # ENG-009: expiry is enforced INSIDE the guarded UPDATE, so a token that
    # has expired (even in the microsecond window between a caller's pre-check
    # and this consume) is never granted a single-use session.
    store.create_invite(_invite("inv_exp", token=_TOKEN, expires_at=_T0 + timedelta(hours=1)))
    # Consume `when` = 2h after _T0, i.e. AFTER the 1h expiry → must lose.
    assert store.consume_invite_token(_TOKEN, consumed_at=_T0 + timedelta(hours=2)) is False
    # Rejected for expiry, not consumed — consumed_at stays NULL.
    assert store.get_invite("inv_exp").consumed_at is None
    # A still-valid token at the same `when` consumes fine (proves it's the
    # expiry guard, not a blanket reject).
    _ok = "tok_" + "b" * INVITE_TOKEN_MIN_LENGTH
    store.create_invite(_invite("inv_ok", token=_ok, expires_at=_T0 + timedelta(hours=3)))
    assert store.consume_invite_token(_ok, consumed_at=_T0 + timedelta(hours=2)) is True


def test_record_invite_terms(store: ContributionStore) -> None:
    store.create_invite(_invite("inv_1"))
    updated = store.record_invite_terms(
        "inv_1", terms_agreement_id="agr_42", terms_version="2026-06"
    )
    assert updated.terms_agreement_id == "agr_42"
    assert updated.terms_version == "2026-06"


# --- guest-session store + state machine ------------------------------------


def test_session_create_get_for_invite_and_save_transition(store: ContributionStore) -> None:
    store.create_session(_session("gs_1", invite_id="inv_jane"))
    assert store.get_session("gs_1") is not None
    assert store.get_session_for_invite("inv_jane").session_id == "gs_1"

    gs = store.get_session("gs_1")
    admitted = gs.model_copy(update={"state": "connected", "admitted_at": _T0, "joined_at": _T0})
    saved = store.save_session(admitted)
    assert saved.state == "connected"
    assert _naive(saved.admitted_at) == _naive(_T0)


def test_session_list_room_filter_and_active_only(store: ContributionStore) -> None:
    store.create_session(_session("gs_live", room_id="room_a", state="on_air"))
    store.create_session(_session("gs_done", room_id="room_a", state="ended"))
    store.create_session(_session("gs_other", room_id="room_b", state="connected"))

    room_a = store.list_sessions(room_id="room_a")
    assert {s.session_id for s in room_a} == {"gs_live", "gs_done"}
    active_a = store.list_sessions(room_id="room_a", active_only=True)
    assert {s.session_id for s in active_a} == {"gs_live"}  # ended is terminal


def test_delete_room_does_not_cascade_sessions(store: ContributionStore) -> None:
    """Soft string refs: an on-air guest's audit row outlives its room."""
    store.upsert_room(_room("room_a"))
    store.create_session(_session("gs_1", room_id="room_a", state="ended"))
    store.delete_room("room_a")
    assert store.get_room("room_a") is None
    assert store.get_session("gs_1") is not None  # session survives the room delete


# --- migration reversibility -------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestRemoteContributionMigration:
    """0048_remote_contribution creates the three S17 tables on upgrade and
    drops exactly those on a single-step downgrade to 0047 — the rest of the
    schema (S16 control-room, cg, auto-schedule tables) survives."""

    _TABLES = ("contribution_rooms", "guest_invites", "remote_guest_sessions")

    def test_upgrade_head_creates_the_three_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table), table
            room_idx = {ix["name"] for ix in insp.get_indexes("remote_guest_sessions")}
            assert "ix_remote_guest_sessions_room" in room_idx
            assert "ix_remote_guest_sessions_invite" in room_idx
            # invite_token is uniquely constrained (single-use capability).
            uniq_cols = {
                tuple(uc["column_names"]) for uc in insp.get_unique_constraints("guest_invites")
            }
            assert ("invite_token",) in uniq_cols
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_three_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0047_production_control")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table), table
            assert insp.has_table("control_room_sessions")  # S16 table survives
            assert insp.has_table("cg_feed_sources")  # S6 table survives
            assert insp.has_table("auto_schedule_rules")  # S18 table survives
        finally:
            eng.dispose()
