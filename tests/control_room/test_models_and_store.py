# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S16 build step 9 slice 2a — production control-room data layer.

Covers civiccast.control_room.models (ProductionDevice / DeviceProfile /
ControlSurface / TimelineCue / ControlRoomSession / CueFiredEvent /
DeviceCommand validators + ORM peers) and
civiccast.control_room.store.ControlRoomStore (device/profile/surface/cue CRUD,
session open/close, append-only cue + device-command audit). SQLite-backed; the
live-Postgres head + namespace checks live in tests/live/test_real_postgres.py.
The 0047 migration's up/down reversibility is asserted by
TestProductionControlMigration via the real Alembic chain on ephemeral SQLite.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from civiccast.control_room.models import (
    ControlRoomSession,
    ControlSurface,
    CueFiredEvent,
    DeviceCommand,
    DeviceProfile,
    ProductionDevice,
    TimelineCue,
)
from civiccast.control_room.store import (
    ControlRoomStore,
    CueImmutableError,
    DeviceNotFoundError,
    SessionNotFoundError,
    SessionSurfaceConflictError,
)
from civiccast.db import Base

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ControlRoomStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'control_room.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield ControlRoomStore(factory)
    finally:
        eng.dispose()


def _device(device_id: str = "dev_obs", **kw: object) -> ProductionDevice:
    base: dict[str, object] = {
        "device_id": device_id,
        "label": "Studio OBS",
        "kind": "obs",
        "transport": "websocket",
        "host": "127.0.0.1",
        "port": 4455,
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kw)
    return ProductionDevice(**base)  # type: ignore[arg-type]


def _surface(surface_id: str = "srf_chamber", **kw: object) -> ControlSurface:
    base: dict[str, object] = {
        "surface_id": surface_id,
        "label": "Council Chamber A/B/C",
        "created_by": "op_dana",
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kw)
    return ControlSurface(**base)  # type: ignore[arg-type]


def _cue(cue_id: str, *, bank: int = 0, position: int = 0, **kw: object) -> TimelineCue:
    base: dict[str, object] = {
        "cue_id": cue_id,
        "surface_id": "srf_chamber",
        "label": "Take CAM2",
        "device_id": "dev_obs",
        "action": "scene",
        "payload": {"scene": "CAM2"},
        "bank": bank,
        "position": position,
        "proof_boundary": "Cue plan preview only; no device socket is opened by this API.",
        "created_at": _T0,
    }
    base.update(kw)
    return TimelineCue(**base)  # type: ignore[arg-type]


# --- model validation --------------------------------------------------------


def test_device_secret_ref_defaults_none_and_no_cleartext_field() -> None:
    dev = _device()
    assert dev.secret_ref is None
    # extra="forbid": a cleartext password field can never sneak into the model.
    with pytest.raises(ValidationError):
        ProductionDevice(**{**dev.model_dump(), "password": "hunter2"})  # type: ignore[arg-type]


def test_device_port_range_enforced() -> None:
    with pytest.raises(ValidationError):
        _device(port=70000)


def test_profile_timing_bounds() -> None:
    prof = DeviceProfile(
        profile_id="prof_obs",
        device_id="dev_obs",
        tsr_device_type="OBS",
        take_delay_ms=250,
        post_roll_ms=500,
        created_at=_T0,
        updated_at=_T0,
    )
    assert prof.version == 1
    with pytest.raises(ValidationError):
        DeviceProfile(
            profile_id="p",
            device_id="d",
            tsr_device_type="OBS",
            take_delay_ms=-1,
            created_at=_T0,
            updated_at=_T0,
        )


def test_cue_unknown_action_rejected() -> None:
    with pytest.raises(ValidationError):
        _cue("cue_x", action="explode")


# --- device CRUD -------------------------------------------------------------


def test_device_upsert_get_list_delete(store: ControlRoomStore) -> None:
    store.upsert_device(_device("dev_obs"))
    store.upsert_device(_device("dev_atem", label="ATEM Mini", kind="atem", transport="tcp"))
    got = store.get_device("dev_obs")
    assert got is not None and got.kind == "obs" and got.port == 4455
    labels = [d.label for d in store.list_devices()]
    assert labels == ["ATEM Mini", "Studio OBS"]  # ordered by label

    # upsert updates in place, no duplicate row
    store.upsert_device(_device("dev_obs", label="Studio OBS (relocated)", secret_ref="kr:obs"))
    again = store.get_device("dev_obs")
    assert again is not None
    assert again.label == "Studio OBS (relocated)" and again.secret_ref == "kr:obs"
    assert len(store.list_devices()) == 2

    store.delete_device("dev_obs")
    assert store.get_device("dev_obs") is None
    with pytest.raises(DeviceNotFoundError):
        store.delete_device("dev_obs")


def test_device_health_defaults_none_and_is_recorded_by_probe_not_config_write(
    store: ControlRoomStore,
) -> None:
    store.upsert_device(_device("dev_obs"))
    fresh = store.get_device("dev_obs")
    assert fresh is not None
    assert fresh.last_probed_at is None
    assert fresh.last_reachable is None

    probed = store.record_device_probe("dev_obs", reachable=True, probed_at=_T0)
    assert probed.last_reachable is True
    assert probed.last_probed_at == _T0

    # A config-only edit (relabel) must not reset or fabricate a health reading.
    relabeled = store.upsert_device(_device("dev_obs", label="Studio OBS (relocated)"))
    assert relabeled.last_reachable is True
    assert relabeled.last_probed_at == _T0

    with pytest.raises(DeviceNotFoundError):
        store.record_device_probe("dev_missing", reachable=True, probed_at=_T0)


def test_profile_upsert_and_latest_version_for_device(store: ControlRoomStore) -> None:
    store.upsert_profile(
        DeviceProfile(
            profile_id="prof_v1",
            device_id="dev_obs",
            tsr_device_type="OBS",
            options={"port": 4455},
            capability_map={"cues": ["scene", "overlay_push"]},
            version=1,
            created_at=_T0,
            updated_at=_T0,
        )
    )
    store.upsert_profile(
        DeviceProfile(
            profile_id="prof_v2",
            device_id="dev_obs",
            tsr_device_type="OBS",
            take_delay_ms=200,
            version=2,
            created_at=_T0,
            updated_at=_T0,
        )
    )
    latest = store.get_profile_for_device("dev_obs")
    assert latest is not None and latest.version == 2 and latest.take_delay_ms == 200
    assert store.get_profile_for_device("dev_missing") is None


# --- surface + cue CRUD ------------------------------------------------------


def test_surface_and_cue_crud_with_bank_ordering(store: ControlRoomStore) -> None:
    store.upsert_surface(_surface())
    assert store.get_surface("srf_chamber") is not None
    # cues are returned ordered by (bank, position), not insertion order
    store.upsert_cue(_cue("cue_c", bank=1, position=0, label="Roll deck"))
    store.upsert_cue(_cue("cue_a", bank=0, position=0))
    store.upsert_cue(_cue("cue_b", bank=0, position=1, label="Take CAM3"))
    ordered = [c.cue_id for c in store.list_cues_for_surface("srf_chamber")]
    assert ordered == ["cue_a", "cue_b", "cue_c"]

    store.delete_cue("cue_b")
    assert [c.cue_id for c in store.list_cues_for_surface("srf_chamber")] == ["cue_a", "cue_c"]


def test_cue_version_starts_at_one_and_bumps_on_edit(store: ControlRoomStore) -> None:
    store.upsert_surface(_surface())
    created = store.upsert_cue(_cue("cue_a"))
    assert created.version == 1
    edited = store.upsert_cue(_cue("cue_a", label="Take CAM2 wide"))
    assert edited.version == 2
    assert store.get_cue("cue_a").version == 2  # type: ignore[union-attr]


def test_fired_cue_is_immutable_to_edit_and_delete(store: ControlRoomStore) -> None:
    store.upsert_surface(_surface())
    store.upsert_cue(_cue("cue_a"))
    assert store.has_fired_cue_event("cue_a") is False

    store.append_cue_event(
        CueFiredEvent(
            event_id="evt_fired",
            session_id="sess_1",
            cue_id="cue_a",
            operator_id="op_dana",
            device_id="dev_obs",
            action="scene",
            result="fired",
            fired_at=_T0,
            detail={},
        )
    )
    assert store.has_fired_cue_event("cue_a") is True

    with pytest.raises(CueImmutableError):
        store.upsert_cue(_cue("cue_a", label="renamed after firing"))
    with pytest.raises(CueImmutableError):
        store.delete_cue("cue_a")
    # untouched: the cue and its label survive both rejected attempts
    assert store.get_cue("cue_a").label == "Take CAM2"  # type: ignore[union-attr]


def test_planned_only_cue_events_do_not_lock_the_cue(store: ControlRoomStore) -> None:
    """A test-mode 'planned' event must not trip immutability — only a real
    ``fired`` result does (mirrors CueResult's planned/fired/failed split)."""
    store.upsert_surface(_surface())
    store.upsert_cue(_cue("cue_a"))
    store.append_cue_event(
        CueFiredEvent(
            event_id="evt_planned",
            session_id="sess_1",
            cue_id="cue_a",
            operator_id="op_dana",
            device_id="dev_obs",
            action="scene",
            result="planned",
            fired_at=_T0,
            detail={},
        )
    )
    assert store.has_fired_cue_event("cue_a") is False
    edited = store.upsert_cue(_cue("cue_a", label="still editable"))
    assert edited.version == 2
    store.delete_cue("cue_a")  # does not raise


def test_surface_assigned_role_defaults_meeting_operator(store: ControlRoomStore) -> None:
    saved = store.upsert_surface(_surface())
    assert saved.assigned_role == "meeting_operator"
    restricted = store.upsert_surface(_surface("srf_admin", assigned_role="setup_admin"))
    assert restricted.assigned_role == "setup_admin"


# --- sessions + audit --------------------------------------------------------


def test_session_lifecycle_and_open_lookup(store: ControlRoomStore) -> None:
    opened = store.open_session(
        ControlRoomSession(
            session_id="sess_1",
            surface_id="srf_chamber",
            operator_id="op_dana",
            operator_name="Dana",
            program_feed_source_ref="public:control-room",
            mode="on_air",
            safe_state_cue_id="safe_cue",
            started_at=_T0,
            on_air_expires_at=_T0,
        )
    )
    assert opened.state == "open"
    assert opened.mode == "on_air"
    assert opened.safe_state_cue_id == "safe_cue"
    assert opened.on_air_expires_at == _T0
    assert store.get_open_session_for_surface("srf_chamber") is not None

    closed = store.close_session("sess_1")
    assert closed.state == "closed" and closed.ended_at is not None
    assert store.get_open_session_for_surface("srf_chamber") is None
    with pytest.raises(SessionNotFoundError):
        store.close_session("sess_missing")


def test_open_session_second_concurrent_open_for_same_surface_is_rejected(
    store: ControlRoomStore,
) -> None:
    """The one-open-session-per-surface lock must hold at the DB level, not
    just via the service's check-then-insert (which two racing callers can
    both pass). Calling store.open_session twice for the same surface_id --
    the exact sequence two concurrent requests race through -- must raise a
    clean conflict on the second insert instead of silently creating two
    open rows."""
    store.open_session(
        ControlRoomSession(
            session_id="sess_a",
            surface_id="srf_race",
            operator_id="op_a",
            started_at=_T0,
        )
    )
    with pytest.raises(SessionSurfaceConflictError):
        store.open_session(
            ControlRoomSession(
                session_id="sess_b",
                surface_id="srf_race",
                operator_id="op_b",
                started_at=_T0,
            )
        )
    # the losing insert must not have left a partial/committed row behind
    assert store.get_session("sess_b") is None


def test_cue_event_audit_is_append_only_and_newest_first(store: ControlRoomStore) -> None:
    for i in range(3):
        store.append_cue_event(
            CueFiredEvent(
                event_id=f"evt_{i}",
                session_id="sess_1",
                cue_id="cue_a",
                operator_id="op_dana",
                device_id="dev_obs",
                action="scene",
                result="fired",
                fired_at=datetime(2026, 1, 1, 12, i, tzinfo=UTC),
                detail={"scene": "CAM2"},
            )
        )
    events = store.list_cue_events("sess_1")
    assert [e.event_id for e in events] == ["evt_2", "evt_1", "evt_0"]  # newest first
    assert all(e.result == "fired" for e in events)


def test_device_command_audit_records_timing(store: ControlRoomStore) -> None:
    saved = store.append_device_command(
        DeviceCommand(
            command_id="cmd_1",
            device_id="dev_router",
            session_id="sess_1",
            command_kind="router_take",
            command_preview="@ TAKE 3 1",
            take_delay_ms=120,
            post_roll_ms=250,
            issued_by="op_dana",
            issued_at=_T0,
            result="fired",
        )
    )
    assert saved.take_delay_ms == 120 and saved.post_roll_ms == 250
    assert saved.command_kind == "router_take"


# --- migration reversibility -------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestProductionControlMigration:
    """0047_production_control creates the seven S16 control-room tables on
    upgrade and drops exactly those on a single-step downgrade to 0046 — the
    rest of the schema (cg_feed_sources, auto-schedule tables) survives."""

    _TABLES = (
        "production_devices",
        "device_profiles",
        "control_surfaces",
        "timeline_cues",
        "control_room_sessions",
        "control_room_cue_events",
        "control_room_device_commands",
    )

    def test_upgrade_head_creates_the_seven_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table), table
            session_cols = {col["name"] for col in insp.get_columns("control_room_sessions")}
            assert {"mode", "safe_state_cue_id", "on_air_expires_at"} <= session_cols
            device_idx = {ix["name"] for ix in insp.get_indexes("timeline_cues")}
            assert "ix_timeline_cues_surface" in device_idx
            assert "ix_timeline_cues_device" in device_idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_seven_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0046_cg_feed_source_tags")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table), table
            assert insp.has_table("cg_feed_sources")  # S6 table survives
            assert insp.has_table("auto_schedule_rules")  # S18 table survives
        finally:
            eng.dispose()
