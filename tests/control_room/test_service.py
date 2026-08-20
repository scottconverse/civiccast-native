# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S16 build step 9 slice 2b — cue plan/fire service.

Covers civiccast.control_room.service.ControlRoomService: the plan-then-fire
split (plan opens no device socket; fire goes through the injected TsrClient),
session gating, the append-only cue audit, the fail-closed audit-before-raise on
a transport error, and the S18 gap-8 timed DeviceCommand record.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.control_room.models import (
    ControlSurface,
    DeviceProfile,
    ProductionDevice,
    TimelineCue,
)
from civiccast.control_room.service import (
    ControlRoomService,
    CueMaterialStateChangedError,
    CueNotReadyError,
    CuePolicyError,
    CueSurfaceMismatchError,
    OnAirConfirmationRequiredError,
    OnAirReadinessBlockedError,
    OnAirSessionExpiredError,
    RollbackNotAvailableError,
    SafeStateCueRequiredError,
    SessionAlreadyOpenError,
    SessionClosedError,
    SessionLockOverrideForbiddenError,
)
from civiccast.control_room.store import (
    ControlRoomStore,
    DeviceNotFoundError,
    SurfaceNotFoundError,
)
from civiccast.control_room.tsr_client import (
    HttpTsrClient,
    NullTsrClient,
    TsrApplyResult,
    TsrClientError,
    TsrProbeResult,
)
from civiccast.db import Base

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


class _FakeTsr:
    """Records apply_cue/probe calls; configurable outcome."""

    def __init__(
        self, *, ok: bool = True, raises: bool = False, health_reachable: bool = True
    ) -> None:
        self.ok = ok
        self.raises = raises
        self.health_reachable = health_reachable
        self.applied: list[dict[str, Any]] = []
        self.probed: list[str] = []

    def health(self) -> TsrProbeResult:
        return TsrProbeResult(
            reachable=self.health_reachable,
            detail="ok" if self.health_reachable else "TSR sidecar unreachable",
        )

    def apply_cue(self, *, device, profile, action, payload) -> TsrApplyResult:
        self.applied.append({"device": device.device_id, "action": action, "payload": payload})
        if self.raises:
            raise TsrClientError("device unreachable")
        return TsrApplyResult(
            ok=self.ok,
            detail="" if self.ok else "rejected",
            device_state={"scene": payload.get("scene")},
        )

    def probe_device(self, *, device, profile) -> TsrProbeResult:
        self.probed.append(device.device_id)
        return TsrProbeResult(reachable=True, capability_map={"cues": ["scene"]})


@contextmanager
def _factory(eng) -> Iterator[Session]:
    with Session(bind=eng) as session:
        yield session


@pytest.fixture
def store(tmp_path) -> Iterator[ControlRoomStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'cr.sqlite'}", future=True)
    Base.metadata.create_all(eng)
    try:
        yield ControlRoomStore(lambda: _factory(eng))
    finally:
        eng.dispose()


def _service(store: ControlRoomStore, tsr=None) -> ControlRoomService:
    counter = itertools.count(1)
    return ControlRoomService(
        store,
        tsr,
        clock=lambda: _T0,
        id_factory=lambda: f"{next(counter):04d}",
    )


def _open_on_air_session(svc: ControlRoomService) -> str:
    return svc.open_session(
        surface_id="srf",
        operator_id="op",
        mode="on_air",
        safe_state_cue_id="cue_1",
        confirm_on_air=True,
    ).session_id


def _seed(
    store: ControlRoomStore,
    *,
    device_enabled: bool = True,
    device_kind: str = "obs",
    device_transport: str = "websocket",
    device_host: str | None = None,
    action: str = "scene",
    payload: dict | None = None,
    profile_options: dict | None = None,
    confirm: bool = False,
) -> None:
    store.upsert_surface(
        ControlSurface(
            surface_id="srf", label="Chamber", created_by="op", created_at=_T0, updated_at=_T0
        )
    )
    store.upsert_device(
        ProductionDevice(
            device_id="dev_obs",
            label="Studio OBS",
            kind=device_kind,  # type: ignore[arg-type]
            transport=device_transport,  # type: ignore[arg-type]
            host=device_host,
            enabled=device_enabled,
            created_at=_T0,
            updated_at=_T0,
        )
    )
    store.upsert_profile(
        DeviceProfile(
            profile_id="prof",
            device_id="dev_obs",
            tsr_device_type=device_kind.upper(),
            options=profile_options or {},
            take_delay_ms=120,
            post_roll_ms=250,
            created_at=_T0,
            updated_at=_T0,
        )
    )
    store.upsert_cue(
        TimelineCue(
            cue_id="cue_1",
            surface_id="srf",
            label="Take CAM2",
            device_id="dev_obs",
            action=action,
            payload=payload if payload is not None else {"scene": "CAM2"},
            confirm_required=confirm,
            proof_boundary="x",
            created_at=_T0,
        )
    )


# --- plan opens no socket ----------------------------------------------------


def test_plan_cue_opens_no_socket_and_carries_profile_timing(store: ControlRoomStore) -> None:
    _seed(store, confirm=True)
    tsr = _FakeTsr()
    svc = _service(store, tsr)
    session = svc.open_session(surface_id="srf", operator_id="op")
    plan = svc.plan_cue(session_id=session.session_id, cue_id="cue_1")
    assert tsr.applied == []  # planning NEVER touches the device
    assert plan.ready_to_send is True
    assert plan.confirm_required is True
    assert plan.take_delay_ms == 120 and plan.post_roll_ms == 250
    assert "CAM2" in plan.command_preview
    assert "no device socket is opened" in plan.proof_boundary
    assert len(plan.material_state_fingerprint) == 64


def test_plan_cue_not_ready_when_device_disabled(store: ControlRoomStore) -> None:
    _seed(store, device_enabled=False)
    svc = _service(store, _FakeTsr())
    session = svc.open_session(surface_id="srf", operator_id="op")
    plan = svc.plan_cue(session_id=session.session_id, cue_id="cue_1")
    assert plan.ready_to_send is False
    assert "Enable" in plan.operator_action


# --- session gating ----------------------------------------------------------


def test_open_session_rejects_unknown_surface_and_double_open(store: ControlRoomStore) -> None:
    svc = _service(store, _FakeTsr())
    with pytest.raises(SurfaceNotFoundError):
        svc.open_session(surface_id="nope", operator_id="op")
    _seed(store)
    svc.open_session(surface_id="srf", operator_id="op")
    with pytest.raises(SessionAlreadyOpenError):
        svc.open_session(surface_id="srf", operator_id="op")


def test_session_already_open_error_carries_the_lock_holder(store: ControlRoomStore) -> None:
    _seed(store)
    svc = _service(store, _FakeTsr())
    opened = svc.open_session(surface_id="srf", operator_id="op_dana", operator_name="Dana")
    with pytest.raises(SessionAlreadyOpenError) as excinfo:
        svc.open_session(surface_id="srf", operator_id="op_other")
    assert excinfo.value.existing_session.session_id == opened.session_id
    assert excinfo.value.existing_session.operator_id == "op_dana"
    assert excinfo.value.existing_session.operator_name == "Dana"


def test_open_session_concurrent_race_loser_gets_clean_conflict_not_a_raw_db_error(
    store: ControlRoomStore,
) -> None:
    """Simulates two operators racing open_session for the same surface: both
    pass the app-level "no existing open session" check before either insert
    lands. The DB-level unique constraint (models.py) lets only one insert
    win; the loser must see the same SessionAlreadyOpenError/lock-holder info
    as the non-racy duplicate-open path, not a raw store IntegrityError."""

    class _RacyStore(ControlRoomStore):
        """The first two "is a session already open" checks report None --
        the exact TOCTOU window two concurrent requests both observe, even
        though the second call happens after the first operator's session
        has actually committed. Every later check (the service's own
        post-conflict re-fetch) sees real DB state, matching how a real
        race resolves: by the time the loser's insert fails, the winner's
        commit is already visible."""

        def __init__(self, session_factory) -> None:
            super().__init__(session_factory)
            self._checks = 0

        def get_open_session_for_surface(self, surface_id: str) -> Any:
            self._checks += 1
            if self._checks <= 2:
                return None
            return super().get_open_session_for_surface(surface_id)

    _seed(store)
    racy = _RacyStore(store._session_factory)
    svc = _service(racy, _FakeTsr())
    winner = svc.open_session(surface_id="srf", operator_id="op_dana", operator_name="Dana")
    with pytest.raises(SessionAlreadyOpenError) as excinfo:
        svc.open_session(surface_id="srf", operator_id="op_other")
    assert excinfo.value.existing_session.session_id == winner.session_id
    assert excinfo.value.existing_session.operator_id == "op_dana"


def test_close_session_by_owning_operator_succeeds(store: ControlRoomStore) -> None:
    _seed(store)
    svc = _service(store, _FakeTsr())
    opened = svc.open_session(surface_id="srf", operator_id="op_dana")
    closed = svc.close_session(session_id=opened.session_id, requested_by="op_dana")
    assert closed.state == "closed"


def test_close_session_by_another_operator_is_forbidden_without_override(
    store: ControlRoomStore,
) -> None:
    _seed(store)
    svc = _service(store, _FakeTsr())
    opened = svc.open_session(surface_id="srf", operator_id="op_dana")
    with pytest.raises(SessionLockOverrideForbiddenError):
        svc.close_session(session_id=opened.session_id, requested_by="op_other")
    assert store.get_open_session_for_surface("srf") is not None


def test_close_session_lock_override_releases_another_operators_session(
    store: ControlRoomStore,
) -> None:
    _seed(store)
    svc = _service(store, _FakeTsr())
    opened = svc.open_session(surface_id="srf", operator_id="op_dana")
    closed = svc.close_session(
        session_id=opened.session_id, requested_by="op_support", is_lock_override=True
    )
    assert closed.state == "closed"
    assert store.get_open_session_for_surface("srf") is None


def test_open_session_defaults_to_test_mode(store: ControlRoomStore) -> None:
    _seed(store)
    svc = _service(store, _FakeTsr())
    session = svc.open_session(surface_id="srf", operator_id="op")
    assert session.mode == "test"
    assert session.safe_state_cue_id is None
    assert session.on_air_expires_at is None


def test_open_on_air_session_requires_confirm_and_safe_state(store: ControlRoomStore) -> None:
    _seed(store, confirm=True)
    svc = _service(store, _FakeTsr())
    with pytest.raises(OnAirConfirmationRequiredError):
        svc.open_session(
            surface_id="srf",
            operator_id="op",
            mode="on_air",
            safe_state_cue_id="cue_1",
        )
    with pytest.raises(SafeStateCueRequiredError):
        svc.open_session(
            surface_id="srf",
            operator_id="op",
            mode="on_air",
            confirm_on_air=True,
        )
    session = svc.open_session(
        surface_id="srf",
        operator_id="op",
        mode="on_air",
        safe_state_cue_id="cue_1",
        confirm_on_air=True,
    )
    assert session.mode == "on_air"
    assert session.safe_state_cue_id == "cue_1"
    assert session.on_air_expires_at == _T0 + timedelta(minutes=30)


def test_open_on_air_session_rejects_readiness_blockers(store: ControlRoomStore) -> None:
    _seed(store, confirm=True, device_enabled=False)
    svc = _service(store, _FakeTsr())
    with pytest.raises(OnAirReadinessBlockedError, match="Enabled devices"):
        svc.open_session(
            surface_id="srf",
            operator_id="op",
            mode="on_air",
            safe_state_cue_id="cue_1",
            confirm_on_air=True,
        )
    assert store.get_open_session_for_surface("srf") is None


def test_open_on_air_session_requires_confirm_required_safe_state(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=False)
    svc = _service(store, _FakeTsr())
    with pytest.raises(SafeStateCueRequiredError, match="confirm-required"):
        svc.open_session(
            surface_id="srf",
            operator_id="op",
            mode="on_air",
            safe_state_cue_id="cue_1",
            confirm_on_air=True,
        )


def test_plan_on_closed_session_is_rejected(store: ControlRoomStore) -> None:
    _seed(store)
    svc = _service(store, _FakeTsr())
    session = svc.open_session(surface_id="srf", operator_id="op")
    svc.close_session(session_id=session.session_id)
    with pytest.raises(SessionClosedError):
        svc.plan_cue(session_id=session.session_id, cue_id="cue_1")


def test_cue_on_wrong_surface_is_rejected(store: ControlRoomStore) -> None:
    _seed(store)
    # a second surface + a session on it; cue_1 belongs to "srf", not "srf2"
    store.upsert_surface(
        ControlSurface(
            surface_id="srf2", label="B", created_by="op", created_at=_T0, updated_at=_T0
        )
    )
    svc = _service(store, _FakeTsr())
    session = svc.open_session(surface_id="srf2", operator_id="op")
    with pytest.raises(CueSurfaceMismatchError):
        svc.plan_cue(session_id=session.session_id, cue_id="cue_1")


# --- fire --------------------------------------------------------------------


def test_fire_cue_success_audits_fired(store: ControlRoomStore) -> None:
    _seed(store, confirm=True)
    tsr = _FakeTsr(ok=True)
    svc = _service(store, tsr)
    session_id = _open_on_air_session(svc)
    event = svc.fire_cue(session_id=session_id, cue_id="cue_1", operator_id="op")
    assert event.result == "fired"
    assert len(tsr.applied) == 1
    audit = store.list_cue_events(session_id)
    assert len(audit) == 1 and audit[0].result == "fired"
    assert audit[0].detail.get("scene") == "CAM2"
    assert len(str(audit[0].detail.get("material_state_fingerprint"))) == 64


def test_rollback_session_fires_the_configured_safe_state_cue(store: ControlRoomStore) -> None:
    _seed(store, confirm=True)
    tsr = _FakeTsr(ok=True)
    svc = _service(store, tsr)
    session_id = _open_on_air_session(svc)
    event = svc.rollback_session(session_id=session_id, operator_id="op")
    assert event.result == "fired"
    assert event.cue_id == "cue_1"  # the fixture's safe-state cue
    assert len(tsr.applied) == 1


def test_rollback_session_without_safe_state_cue_configured_raises(
    store: ControlRoomStore,
) -> None:
    _seed(store)
    svc = _service(store, _FakeTsr())
    session = svc.open_session(surface_id="srf", operator_id="op")  # test mode, no safe-state cue
    with pytest.raises(RollbackNotAvailableError):
        svc.rollback_session(session_id=session.session_id, operator_id="op")


def test_rollback_session_on_closed_session_raises(store: ControlRoomStore) -> None:
    _seed(store, confirm=True)
    svc = _service(store, _FakeTsr())
    session_id = _open_on_air_session(svc)
    svc.close_session(session_id=session_id)
    with pytest.raises(SessionClosedError):
        svc.rollback_session(session_id=session_id, operator_id="op")


def test_fire_cue_in_test_mode_audits_planned_and_does_not_call_tsr(
    store: ControlRoomStore,
) -> None:
    _seed(store)
    tsr = _FakeTsr(ok=True)
    svc = _service(store, tsr)
    session = svc.open_session(surface_id="srf", operator_id="op")
    event = svc.fire_cue(session_id=session.session_id, cue_id="cue_1", operator_id="op")
    assert event.result == "planned"
    assert event.detail["test_mode"] is True
    assert event.detail["device_command_blocked"] is True
    assert tsr.applied == []
    assert store.list_cue_events(session.session_id)[0].result == "planned"


def test_fire_with_stale_material_state_fingerprint_refuses_without_device_call(
    store: ControlRoomStore,
) -> None:
    _seed(store)
    tsr = _FakeTsr(ok=True)
    svc = _service(store, tsr)
    session = svc.open_session(surface_id="srf", operator_id="op")
    plan = svc.plan_cue(session_id=session.session_id, cue_id="cue_1")
    assert plan.material_state_fingerprint
    with pytest.raises(CueMaterialStateChangedError):
        svc.fire_cue(
            session_id=session.session_id,
            cue_id="cue_1",
            operator_id="op",
            expected_material_state_fingerprint="stale",
        )
    assert tsr.applied == []


def test_fire_cue_on_disabled_device_refuses_without_calling_tsr(store: ControlRoomStore) -> None:
    _seed(store, device_enabled=False)
    tsr = _FakeTsr()
    svc = _service(store, tsr)
    session = svc.open_session(surface_id="srf", operator_id="op")
    with pytest.raises(CueNotReadyError):
        svc.fire_cue(session_id=session.session_id, cue_id="cue_1", operator_id="op")
    assert tsr.applied == []  # never reached the device
    assert store.list_cue_events(session.session_id) == []


def test_fire_cue_transport_error_audits_failed_then_raises(store: ControlRoomStore) -> None:
    _seed(store, confirm=True)
    tsr = _FakeTsr(raises=True)
    svc = _service(store, tsr)
    session_id = _open_on_air_session(svc)
    with pytest.raises(TsrClientError):
        svc.fire_cue(session_id=session_id, cue_id="cue_1", operator_id="op")
    # the failed attempt is audited BEFORE the error propagates (no silent drop)
    audit = store.list_cue_events(session_id)
    assert len(audit) == 1 and audit[0].result == "failed"
    assert "unreachable" in audit[0].detail.get("detail", "")


def test_open_on_air_with_null_tsr_refuses_before_session_creation(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)
    svc = _service(store, NullTsrClient())
    with pytest.raises(OnAirReadinessBlockedError, match="TSR control service"):
        _open_on_air_session(svc)
    assert store.get_open_session_for_surface("srf") is None


def test_fire_gap8_router_take_records_device_command_with_timing(store: ControlRoomStore) -> None:
    _seed(
        store,
        device_kind="tcp",
        device_transport="tcp",
        action="router_take",
        payload={"source": "3", "destination": "1"},
        confirm=True,
    )
    tsr = _FakeTsr(ok=True)
    svc = _service(store, tsr)
    session_id = _open_on_air_session(svc)
    event = svc.fire_cue(session_id=session_id, cue_id="cue_1", operator_id="op")
    assert event.result == "fired"
    # a timed DeviceCommand audit row was written for the gap-8 facility action
    cmds = store.list_device_commands("dev_obs")
    assert len(cmds) == 1
    assert cmds[0].command_kind == "router_take"
    assert cmds[0].take_delay_ms == 120 and cmds[0].post_roll_ms == 250
    assert cmds[0].result == "fired"


def test_fire_gap8_router_take_transport_failure_records_device_command_failed(
    store: ControlRoomStore,
) -> None:
    _seed(
        store,
        device_kind="tcp",
        device_transport="tcp",
        action="router_take",
        payload={"source": "3", "destination": "1"},
        confirm=True,
    )
    tsr = _FakeTsr(raises=True)
    svc = _service(store, tsr)
    session_id = _open_on_air_session(svc)
    with pytest.raises(TsrClientError):
        svc.fire_cue(session_id=session_id, cue_id="cue_1", operator_id="op")
    cmds = store.list_device_commands("dev_obs")
    assert len(cmds) == 1
    assert cmds[0].command_kind == "router_take"
    assert cmds[0].result == "failed"
    assert cmds[0].issued_at is not None


def test_expired_on_air_session_closes_and_refuses_before_device_call(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)
    tsr = _FakeTsr(ok=True)
    now = _T0
    svc = ControlRoomService(
        store,
        tsr,
        clock=lambda: now,
        id_factory=lambda: "fixed",
    )
    session = svc.open_session(
        surface_id="srf",
        operator_id="op",
        mode="on_air",
        safe_state_cue_id="cue_1",
        confirm_on_air=True,
    )
    now = _T0 + timedelta(minutes=31)
    with pytest.raises(OnAirSessionExpiredError):
        svc.fire_cue(session_id=session.session_id, cue_id="cue_1", operator_id="op")
    assert tsr.applied == []
    assert store.get_session(session.session_id).state == "closed"  # type: ignore[union-attr]


def test_rollback_session_bypasses_on_air_expiry_and_still_fires_safe_state_cue(
    store: ControlRoomStore,
) -> None:
    """rollback_session (the panic/safe-state cue) must still reach the
    device on an expired on-air session -- that is precisely when it is
    needed most. A normal fire_cue on the same expired session must still
    be refused (see test_expired_on_air_session_closes_and_refuses_before_device_call)."""
    _seed(store, confirm=True)
    tsr = _FakeTsr(ok=True)
    now = _T0
    svc = ControlRoomService(
        store,
        tsr,
        clock=lambda: now,
        id_factory=lambda: "fixed",
    )
    session = svc.open_session(
        surface_id="srf",
        operator_id="op",
        mode="on_air",
        safe_state_cue_id="cue_1",
        confirm_on_air=True,
    )
    now = _T0 + timedelta(minutes=31)
    event = svc.rollback_session(session_id=session.session_id, operator_id="op")
    assert event.result == "fired"
    assert tsr.applied  # the safe-state cue actually reached the device
    assert store.get_session(session.session_id).state == "open"  # type: ignore[union-attr]


def test_probe_device_uses_tsr_and_rejects_unknown(store: ControlRoomStore) -> None:
    _seed(store)
    tsr = _FakeTsr()
    svc = _service(store, tsr)
    result = svc.probe_device(device_id="dev_obs")
    assert result.reachable is True and tsr.probed == ["dev_obs"]
    with pytest.raises(DeviceNotFoundError):
        svc.probe_device(device_id="ghost")


def test_probe_device_records_health_and_freshness(store: ControlRoomStore) -> None:
    _seed(store)
    svc = _service(store, _FakeTsr())
    svc.probe_device(device_id="dev_obs")
    probed = store.get_device("dev_obs")
    assert probed is not None
    assert probed.last_reachable is True
    assert probed.last_probed_at == _T0


def test_probe_device_records_unhealthy_on_transport_failure(store: ControlRoomStore) -> None:
    class _FailingProbe(_FakeTsr):
        def probe_device(self, *, device, profile):
            raise TsrClientError("device unreachable")

    _seed(store)
    svc = _service(store, _FailingProbe())
    with pytest.raises(TsrClientError):
        svc.probe_device(device_id="dev_obs")
    probed = store.get_device("dev_obs")
    assert probed is not None
    assert probed.last_reachable is False
    assert probed.last_probed_at == _T0


def test_readiness_report_flags_stale_and_unhealthy_devices_as_warning_not_blocker(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)
    svc = _service(store, _FakeTsr())
    checks = {check.check_id: check for check in svc.readiness_report().checks}
    assert checks["device-health"].status == "warning"
    assert "No devices exist" not in checks["device-health"].detail

    svc.probe_device(device_id="dev_obs")
    fresh_checks = {check.check_id: check for check in svc.readiness_report().checks}
    assert fresh_checks["device-health"].status == "passed"

    # ready_for_on_air only counts "blocked" checks; a warning never blocks it.
    assert svc.readiness_report().ready_for_on_air is True


def test_vmix_input_rename_payload_is_not_exposed_in_civiccast_31(
    store: ControlRoomStore,
) -> None:
    _seed(
        store,
        device_kind="vmix",
        device_transport="http",
        action="input",
        payload={"input": 2, "rename": "Do Not Rename The Operator Console"},
    )
    svc = _service(store, _FakeTsr())
    session = svc.open_session(surface_id="srf", operator_id="op")
    with pytest.raises(CuePolicyError, match="configuration mutation"):
        svc.plan_cue(session_id=session.session_id, cue_id="cue_1")


def test_public_device_host_requires_explicit_profile_override(store: ControlRoomStore) -> None:
    _seed(store, device_host="8.8.8.8")
    tsr = _FakeTsr()
    svc = _service(store, tsr)
    with pytest.raises(CuePolicyError, match="public IP"):
        svc.probe_device(device_id="dev_obs")
    assert tsr.probed == []


def test_single_label_lan_device_host_is_allowed_without_public_override(
    store: ControlRoomStore,
) -> None:
    _seed(store, device_host="vmix-studio")
    tsr = _FakeTsr()
    svc = _service(store, tsr)
    assert svc.probe_device(device_id="dev_obs").reachable is True
    assert tsr.probed == ["dev_obs"]


def test_public_device_host_override_requires_reason_and_allows_probe(
    store: ControlRoomStore,
) -> None:
    _seed(
        store,
        device_host="8.8.8.8",
        profile_options={
            "allow_public_host_override": True,
            "public_host_override_reason": "Lab VPN NAT proof endpoint",
        },
    )
    tsr = _FakeTsr()
    svc = _service(store, tsr)
    assert svc.probe_device(device_id="dev_obs").reachable is True
    assert tsr.probed == ["dev_obs"]


def test_readiness_report_blocks_empty_control_room_and_keeps_lpm_contract_only(
    store: ControlRoomStore,
) -> None:
    svc = _service(store, _FakeTsr())
    report = svc.readiness_report()
    assert report.ready_for_on_air is False
    assert report.station_device_ready is False
    assert report.devices_configured == 0
    assert report.surfaces_configured == 0
    assert {check.check_id for check in report.checks if check.status == "blocked"} == {
        "device-inventory",
        "device-profiles",
        "surface-inventory",
        "cue-inventory",
    }
    assert report.lpm_profiles
    assert all(
        profile.proof_status == "contract_only_not_station_device_evidence"
        for profile in report.lpm_profiles
    )
    assert "not clean Windows install evidence" in report.proof_boundary


def test_readiness_report_passes_configured_local_control_but_not_station_device_ready(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)
    svc = _service(store, _FakeTsr())
    session = svc.open_session(surface_id="srf", operator_id="op")
    report = svc.readiness_report()
    assert report.ready_for_on_air is True
    assert report.station_device_ready is False
    assert report.devices_configured == 1
    assert report.devices_enabled == 1
    assert report.devices_missing_profile == []
    assert report.surfaces_configured == 1
    assert report.cues_configured == 1
    assert report.open_sessions == 1
    assert report.open_on_air_sessions == 0
    assert session.session_id.startswith("crs_")
    checks = {check.check_id: check for check in report.checks}
    assert checks["device-profiles"].status == "passed"
    assert checks["safe-state-candidate"].status == "passed"
    assert checks["station-device-evidence"].status == "warning"


def test_readiness_report_blocks_when_tsr_control_service_is_not_configured(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)
    svc = _service(store, NullTsrClient())

    report = svc.readiness_report()

    assert report.ready_for_on_air is False
    checks = {check.check_id: check for check in report.checks}
    assert checks["tsr-control-service"].status == "blocked"
    assert "not configured" in checks["tsr-control-service"].detail


def test_readiness_report_surfaces_invalid_tsr_url_detail(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)
    svc = _service(
        store,
        NullTsrClient("Invalid CIVICAST_CONTROL_ROOM_TSR_URL: TSR sidecar URL must use localhost"),
    )

    report = svc.readiness_report()

    assert report.ready_for_on_air is False
    checks = {check.check_id: check for check in report.checks}
    assert checks["tsr-control-service"].status == "blocked"
    assert "Invalid CIVICAST_CONTROL_ROOM_TSR_URL" in checks["tsr-control-service"].detail


def test_readiness_report_blocks_configured_but_unreachable_tsr_sidecar(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)
    svc = _service(store, _FakeTsr(health_reachable=False))

    report = svc.readiness_report()

    assert report.ready_for_on_air is False
    checks = {check.check_id: check for check in report.checks}
    assert checks["tsr-control-service"].status == "blocked"
    assert "configured but not reachable" in checks["tsr-control-service"].detail
    assert "Start or restart" in checks["tsr-control-service"].operator_action


def test_readiness_report_converts_real_tsr_transport_failure_to_blocker(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    svc = _service(store, HttpTsrClient("http://127.0.0.1:7717", client=client))

    report = svc.readiness_report()

    assert report.ready_for_on_air is False
    checks = {check.check_id: check for check in report.checks}
    assert checks["tsr-control-service"].status == "blocked"
    assert "configured but not reachable" in checks["tsr-control-service"].detail
    assert "TSR sidecar unreachable" in checks["tsr-control-service"].detail


def test_open_on_air_converts_real_tsr_transport_failure_to_readiness_block(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=True)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    svc = _service(store, HttpTsrClient("http://127.0.0.1:7717", client=client))

    with pytest.raises(OnAirReadinessBlockedError, match="TSR control service"):
        _open_on_air_session(svc)
    assert store.get_open_session_for_surface("srf") is None


def test_readiness_report_blocks_unsafe_device_targets(
    store: ControlRoomStore,
) -> None:
    _seed(store, device_host="8.8.8.8", confirm=True)
    svc = _service(store, _FakeTsr())

    report = svc.readiness_report()

    assert report.ready_for_on_air is False
    checks = {check.check_id: check for check in report.checks}
    assert checks["device-target-policy"].status == "blocked"
    assert "public IP" in checks["device-target-policy"].detail


def test_readiness_report_blocks_unsafe_cue_payloads(
    store: ControlRoomStore,
) -> None:
    _seed(
        store,
        device_kind="vmix",
        device_transport="http",
        action="input",
        payload={"input": 2, "rename": "Do Not Rename"},
        confirm=True,
    )
    svc = _service(store, _FakeTsr())

    report = svc.readiness_report()

    assert report.ready_for_on_air is False
    checks = {check.check_id: check for check in report.checks}
    assert checks["cue-policy"].status == "blocked"
    assert "configuration mutation" in checks["cue-policy"].detail


def test_readiness_report_blocks_cue_surfaces_without_safe_state_candidate(
    store: ControlRoomStore,
) -> None:
    _seed(store, confirm=False)
    svc = _service(store, _FakeTsr())

    report = svc.readiness_report()

    assert report.ready_for_on_air is False
    checks = {check.check_id: check for check in report.checks}
    assert checks["safe-state-candidate"].status == "blocked"
    assert "confirm-required safe-state candidate" in checks["safe-state-candidate"].detail
