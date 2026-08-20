# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S16 build step 9 slice 2c — control-room staff API.

A minimal FastAPI app mounts the real router, sets the operator identity via
middleware (so the real require_any_role gate runs), and overrides the DI seams
with a SQLite-backed store + service + a fake TsrClient. Covers role-gating
(positive / 403 / 401), the write-only device secret (never returned, persisted
to the injected writer), plan-opens-no-socket at the API, fire + the fail-closed
502, and 503-when-unwired.
"""

from __future__ import annotations

import contextlib
import itertools
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.control_room.models import (
    ControlSurface,
    DeviceProfile,
    ProductionDevice,
    TimelineCue,
)
from civiccast.control_room.router import (
    get_control_room_service,
    get_control_room_store,
    get_device_secret_writer,
    staff_router,
)
from civiccast.control_room.service import ControlRoomService
from civiccast.control_room.store import ControlRoomStore
from civiccast.control_room.tsr_client import TsrApplyResult, TsrClientError, TsrProbeResult
from civiccast.db import Base

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

# _build() below creates a real SQLAlchemy Engine (StaticPool + one persistent
# SQLite DBAPI connection) per call and has no fixture scope to tear down in.
# Undisposed engines/connections only get released whenever the cyclic GC
# happens to collect them — a point that varies run to run and can coincide
# with an unrelated later test, which is exactly the kind of inter-test
# pollution this file was flaking on. Every engine _build() creates is
# registered here and disposed by the autouse fixture immediately after each
# test, so cleanup is deterministic instead of GC-timing-dependent.
_ENGINES_TO_DISPOSE: list[Any] = []


def _dispose_registered_engines() -> None:
    while _ENGINES_TO_DISPOSE:
        _ENGINES_TO_DISPOSE.pop().dispose()


@pytest.fixture(autouse=True)
def _dispose_engines_after_test() -> Iterator[None]:
    yield
    _dispose_registered_engines()


class _FakeTsr:
    def __init__(self, *, raises: bool = False) -> None:
        self.raises = raises
        self.applied: list[dict[str, Any]] = []

    def apply_cue(self, *, device, profile, action, payload) -> TsrApplyResult:
        self.applied.append({"action": action})
        if self.raises:
            raise TsrClientError("unreachable")
        return TsrApplyResult(ok=True, device_state={"scene": payload.get("scene")})

    def probe_device(self, *, device, profile) -> TsrProbeResult:
        return TsrProbeResult(reachable=True, capability_map={"cues": ["scene"]})

    def health(self) -> TsrProbeResult:
        return TsrProbeResult(reachable=True, detail="ok")


def _build(
    scopes: tuple[str, ...] | None = ("setup_admin",),
    *,
    wire: bool = True,
    tsr=None,
    operator_id: str = "dana",
    operator_name: str = "Dana",
    store: ControlRoomStore | None = None,
    service: ControlRoomService | None = None,
):
    if store is None:
        engine = create_engine(
            "sqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        _ENGINES_TO_DISPOSE.append(engine)
        with engine.connect() as conn:
            with contextlib.suppress(Exception):
                conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
            Base.metadata.create_all(conn)
            conn.commit()

        @contextmanager
        def factory() -> Iterator[Session]:
            sess = Session(bind=engine)
            try:
                yield sess
            finally:
                sess.close()

        store = ControlRoomStore(factory)
    fake = tsr or _FakeTsr()
    if service is None:
        counter = itertools.count(1)
        service = ControlRoomService(
            store, fake, clock=lambda: _T0, id_factory=lambda: f"{next(counter):04d}"
        )
    secrets: dict[str, str] = {}

    app = FastAPI()

    @app.middleware("http")
    async def _ident(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id=operator_id, operator_display_name=operator_name, scopes=scopes
            )
        return await call_next(request)

    app.include_router(staff_router)
    if wire:
        app.dependency_overrides[get_control_room_store] = lambda: store
        app.dependency_overrides[get_control_room_service] = lambda: service
        app.dependency_overrides[get_device_secret_writer] = lambda: (
            lambda h, s: secrets.__setitem__(h, s)
        )
    return app, store, fake, secrets


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


def _seed(
    store: ControlRoomStore,
    *,
    action="scene",
    enabled=True,
    confirm: bool = False,
    with_profile: bool = True,
) -> None:
    store.upsert_device(
        ProductionDevice(
            device_id="dev_obs",
            label="OBS",
            kind="obs",
            transport="websocket",
            enabled=enabled,
            created_at=_T0,
            updated_at=_T0,
        )
    )
    store.upsert_surface(
        ControlSurface(
            surface_id="srf", label="Chamber", created_by="op", created_at=_T0, updated_at=_T0
        )
    )
    if with_profile:
        store.upsert_profile(
            DeviceProfile(
                profile_id="prof_dev_obs",
                device_id="dev_obs",
                tsr_device_type="OBS",
                options={},
                capability_map={},
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
            payload={"scene": "CAM2"},
            confirm_required=confirm,
            proof_boundary="x",
            created_at=_T0,
        )
    )


# --- role gate ---------------------------------------------------------------


def test_device_read_forbidden_for_records_clerk() -> None:
    assert (
        _client(scopes=("records_clerk",)).get("/api/staff/control-room/devices").status_code == 403
    )


def test_no_identity_is_unauthorized() -> None:
    assert _client(scopes=None).get("/api/staff/control-room/devices").status_code == 401


def test_device_write_forbidden_for_meeting_operator() -> None:
    r = _client(scopes=("meeting_operator",)).post(
        "/api/staff/control-room/devices",
        json={"label": "OBS", "kind": "obs", "transport": "websocket"},
    )
    assert r.status_code == 403


def test_device_read_allowed_for_support_admin() -> None:
    app, store, _fake, _ = _build(scopes=("support_admin",))
    store.upsert_device(
        ProductionDevice(
            device_id="dev_secret_test",
            label="Secret Test",
            kind="obs",
            transport="websocket",
            secret_ref="crsecret_dev_secret_test",
            enabled=True,
            created_at=_T0,
            updated_at=_T0,
        )
    )
    from fastapi.testclient import TestClient

    r = TestClient(app).get("/api/staff/control-room/devices")
    assert r.status_code == 200
    for device in r.json():
        assert "secret" not in device, f"Device GET must never serialize the secret; got {device!r}"


# --- device create + write-only secret --------------------------------------


def test_create_device_persists_secret_and_never_returns_it() -> None:
    app, store, _fake, secrets = _build(scopes=("setup_admin",))
    client = TestClient(app)
    r = client.post(
        "/api/staff/control-room/devices",
        json={
            "label": "OBS",
            "kind": "obs",
            "transport": "websocket",
            "host": "127.0.0.1",
            "port": 4455,
            "secret": "hunter2",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert "secret" not in body  # write-only — never serialized back
    assert body["secret_ref"] is not None  # a keyring handle was stored instead
    assert secrets[body["secret_ref"]] == "hunter2"  # secret went to the writer
    # and it is persisted on the device row
    assert store.get_device(body["device_id"]).secret_ref == body["secret_ref"]


# --- plan opens no socket; fire goes through Tsr -----------------------------


def _open_session(client: TestClient) -> str:
    r = client.post("/api/staff/control-room/sessions", json={"surface_id": "srf"})
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def _open_on_air_session(client: TestClient) -> str:
    r = client.post(
        "/api/staff/control-room/sessions",
        json={
            "surface_id": "srf",
            "mode": "on_air",
            "safe_state_cue_id": "cue_1",
            "confirm_on_air": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["session_id"]


def test_plan_opens_no_socket_at_the_api() -> None:
    app, store, fake, _ = _build(scopes=("meeting_operator",))
    _seed(store)
    client = TestClient(app)
    sid = _open_session(client)
    r = client.post(f"/api/staff/control-room/sessions/{sid}/cues/cue_1/plan")
    assert r.status_code == 200, r.text
    assert "no device socket is opened" in r.json()["proof_boundary"]
    assert fake.applied == []  # planning never touched the device


def test_open_session_defaults_to_test_mode() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",))
    _seed(store)
    client = TestClient(app)
    r = client.post("/api/staff/control-room/sessions", json={"surface_id": "srf"})
    assert r.status_code == 201, r.text
    assert r.json()["mode"] == "test"
    assert r.json()["safe_state_cue_id"] is None
    assert r.json()["on_air_expires_at"] is None


def test_open_on_air_session_requires_confirm_and_safe_state() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",))
    _seed(store)
    client = TestClient(app)
    no_confirm = client.post(
        "/api/staff/control-room/sessions",
        json={"surface_id": "srf", "mode": "on_air", "safe_state_cue_id": "cue_1"},
    )
    assert no_confirm.status_code == 409
    no_safe = client.post(
        "/api/staff/control-room/sessions",
        json={"surface_id": "srf", "mode": "on_air", "confirm_on_air": True},
    )
    assert no_safe.status_code == 409


def test_open_on_air_session_rejects_readiness_blockers() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",))
    _seed(store, confirm=True, with_profile=False)
    client = TestClient(app)
    r = client.post(
        "/api/staff/control-room/sessions",
        json={
            "surface_id": "srf",
            "mode": "on_air",
            "safe_state_cue_id": "cue_1",
            "confirm_on_air": True,
        },
    )
    assert r.status_code == 409
    assert "readiness" in r.text
    assert "Device profiles" in r.text


def test_fire_succeeds_and_audits() -> None:
    app, store, fake, _ = _build(scopes=("meeting_operator",))
    _seed(store, confirm=True)
    client = TestClient(app)
    sid = _open_on_air_session(client)
    r = client.post(f"/api/staff/control-room/sessions/{sid}/cues/cue_1/fire")
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "fired"
    assert len(fake.applied) == 1
    audit = client.get(f"/api/staff/control-room/sessions/{sid}/audit")
    assert audit.status_code == 200 and audit.json()[0]["result"] == "fired"


def test_fire_in_test_mode_audits_planned_without_sending() -> None:
    app, store, fake, _ = _build(scopes=("meeting_operator",))
    _seed(store)
    client = TestClient(app)
    sid = _open_session(client)
    r = client.post(f"/api/staff/control-room/sessions/{sid}/cues/cue_1/fire")
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "planned"
    assert r.json()["detail"]["test_mode"] is True
    assert fake.applied == []


def test_fire_with_stale_material_state_fingerprint_is_409_and_not_sent() -> None:
    app, store, fake, _ = _build(scopes=("meeting_operator",))
    _seed(store)
    client = TestClient(app)
    sid = _open_session(client)
    plan = client.post(f"/api/staff/control-room/sessions/{sid}/cues/cue_1/plan")
    assert plan.status_code == 200, plan.text
    assert plan.json()["material_state_fingerprint"]
    r = client.post(
        f"/api/staff/control-room/sessions/{sid}/cues/cue_1/fire",
        json={"material_state_fingerprint": "stale"},
    )
    assert r.status_code == 409
    assert "Dry Run" in r.text
    assert fake.applied == []


def test_fire_transport_error_is_502_and_audited_failed() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",), tsr=_FakeTsr(raises=True))
    _seed(store, confirm=True)
    client = TestClient(app)
    sid = _open_on_air_session(client)
    r = client.post(f"/api/staff/control-room/sessions/{sid}/cues/cue_1/fire")
    assert r.status_code == 502
    assert "hunter2" not in r.text  # no secret leak; type-only detail
    audit = client.get(f"/api/staff/control-room/sessions/{sid}/audit").json()
    assert audit and audit[0]["result"] == "failed"


def test_fire_forbidden_for_support_admin() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",))
    _seed(store)
    client = TestClient(app)
    sid = _open_session(client)
    # support_admin can read but not fire — rebuild client with that scope, same session id won't exist;
    # simplest: a fresh support_admin client hitting fire on any path is 403 before service runs.
    sa = _client(scopes=("support_admin",))
    assert sa.post(f"/api/staff/control-room/sessions/{sid}/cues/cue_1/fire").status_code == 403


# --- unwired -> 503 ----------------------------------------------------------


def test_unwired_returns_503() -> None:
    app, *_ = _build(scopes=("setup_admin",), wire=False)
    assert TestClient(app).get("/api/staff/control-room/devices").status_code == 503
    assert TestClient(app).get("/api/staff/control-room/readiness").status_code == 503


def test_readiness_report_allowed_for_support_admin_and_keeps_station_device_ready_false() -> None:
    app, store, _fake, _ = _build(scopes=("support_admin",))
    _seed(store, with_profile=False)
    client = TestClient(app)
    r = client.get("/api/staff/control-room/readiness")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ready_for_on_air"] is False  # seeded device has no profile in this router helper
    assert body["station_device_ready"] is False
    assert body["devices_configured"] == 1
    assert body["surfaces_configured"] == 1
    assert body["lpm_profiles"]
    assert "Station-device evidence" in {check["label"] for check in body["checks"]}


def test_station_device_evidence_check_speaks_to_the_operator() -> None:
    """Assert the operator-visible text, not just the label.

    F-RC4-3 replaced release-engineering vocabulary on this check with words an
    operator can act on. The suite passed with that fix fully reverted -- only
    ``label`` was ever asserted -- so the green count proved nothing about the
    change it was cited to verify. These assertions go red on a revert.
    """
    app, store, _fake, _ = _build(scopes=("support_admin",))
    _seed(store, with_profile=False)
    body = TestClient(app).get("/api/staff/control-room/readiness").json()
    check = next(c for c in body["checks"] if c["check_id"] == "station-device-evidence")
    assert check["detail"] == (
        "This control room has not been verified against your station's real equipment yet."
    )
    assert check["operator_action"] == (
        "Run a check against the room's actual devices before relying on it for a live broadcast."
    )


def test_no_readiness_check_fronts_release_engineering_vocabulary() -> None:
    """The root-cause guard behind F-RC4-3.

    The finding was not "this one string is wrong" -- it was that internal
    release-engineering vocabulary reached an operator screen. Guard every
    check's operator-visible text, so the next check added to this list cannot
    reintroduce the same class of defect. ``lpm_profiles`` stays a payload field
    name; only human-facing strings are scanned.
    """
    jargon = (
        "contract-lab",
        "check-catalog",
        "LPM profile",
        "fixture, simulator",
        "station-device readiness",
        "Stage 0",
        "evidence only",
    )
    app, store, _fake, _ = _build(scopes=("support_admin",))
    _seed(store, with_profile=False)
    body = TestClient(app).get("/api/staff/control-room/readiness").json()
    offenders = [
        f"{check['check_id']}.{field}: {check[field]!r}"
        for check in body["checks"]
        for field in ("label", "detail", "operator_action")
        for token in jargon
        if token.lower() in str(check[field]).lower()
    ]
    assert not offenders, "release-engineering words on an operator screen:\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("role", ["setup_admin", "support_admin", "meeting_operator"])
def test_readiness_report_allowed_role_matrix(role: str) -> None:
    app, store, _fake, _ = _build(scopes=(role,))
    _seed(store)
    r = TestClient(app).get("/api/staff/control-room/readiness")
    assert r.status_code == 200, r.text


def test_readiness_report_unauthorized_without_staff_identity() -> None:
    r = _client(scopes=None).get("/api/staff/control-room/readiness")
    assert r.status_code == 401


def test_readiness_report_forbidden_for_records_clerk() -> None:
    r = _client(scopes=("records_clerk",)).get("/api/staff/control-room/readiness")
    assert r.status_code == 403


def test_create_vmix_input_cue_rejects_rename_payload() -> None:
    app, store, _fake, _ = _build(scopes=("setup_admin",))
    store.upsert_device(
        ProductionDevice(
            device_id="dev_vmix",
            label="vMix Streaming PC",
            kind="vmix",
            transport="http",
            host="127.0.0.1",
            port=8088,
            enabled=True,
            created_at=_T0,
            updated_at=_T0,
        )
    )
    store.upsert_surface(
        ControlSurface(
            surface_id="srf",
            label="Chamber",
            created_by="op",
            created_at=_T0,
            updated_at=_T0,
        )
    )
    r = TestClient(app).post(
        "/api/staff/control-room/surfaces/srf/cues",
        json={
            "label": "Rename is not allowed",
            "device_id": "dev_vmix",
            "action": "input",
            "payload": {"input": 2, "rename": "Bad idea"},
        },
    )
    assert r.status_code == 422


# --- cue versioning / immutability -------------------------------------------


def test_fired_cue_cannot_be_deleted_at_the_api() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",))
    _seed(store, confirm=True)
    client = TestClient(app)
    sid = _open_on_air_session(client)
    fire = client.post(f"/api/staff/control-room/sessions/{sid}/cues/cue_1/fire")
    assert fire.status_code == 200, fire.text

    app2, _store2, _fake2, _ = _build(scopes=("setup_admin",), store=store)
    r = TestClient(app2).delete("/api/staff/control-room/cues/cue_1")
    assert r.status_code == 409
    assert "already fired" in r.text


def test_cue_version_increments_on_edit() -> None:
    app, store, _fake, _ = _build(scopes=("setup_admin",))
    store.upsert_surface(
        ControlSurface(
            surface_id="srf", label="Chamber", created_by="op", created_at=_T0, updated_at=_T0
        )
    )
    store.upsert_device(
        ProductionDevice(
            device_id="dev_obs",
            label="OBS",
            kind="obs",
            transport="websocket",
            created_at=_T0,
            updated_at=_T0,
        )
    )
    client = TestClient(app)
    created = client.post(
        "/api/staff/control-room/surfaces/srf/cues",
        json={
            "label": "Take CAM2",
            "device_id": "dev_obs",
            "action": "scene",
            "payload": {"scene": "CAM2"},
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["version"] == 1


# --- device health + freshness -----------------------------------------------


def test_probe_endpoint_updates_device_health_visible_on_next_read() -> None:
    app, store, _fake, _ = _build(scopes=("setup_admin",))
    _seed(store)
    client = TestClient(app)
    before = client.get("/api/staff/control-room/devices").json()[0]
    assert before["last_probed_at"] is None
    assert before["last_reachable"] is None

    probe = client.post("/api/staff/control-room/devices/dev_obs/probe")
    assert probe.status_code == 200, probe.text

    after = client.get("/api/staff/control-room/devices").json()[0]
    assert after["last_reachable"] is True
    assert after["last_probed_at"] is not None


# --- operator locks + rollback ------------------------------------------------


def test_open_session_conflict_names_the_lock_holder() -> None:
    app, store, _fake, _ = _build(
        scopes=("meeting_operator",), operator_id="op_dana", operator_name="Dana"
    )
    _seed(store)
    client = TestClient(app)
    _open_session(client)

    app2, _store2, _fake2, _ = _build(
        scopes=("meeting_operator",), store=store, operator_id="op_other", operator_name="Otis"
    )
    r = TestClient(app2).post("/api/staff/control-room/sessions", json={"surface_id": "srf"})
    assert r.status_code == 409
    assert "Dana" in r.text
    assert "force-close" in r.text


def test_close_session_forbidden_for_another_operator_without_admin_role() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",), operator_id="op_dana")
    _seed(store)
    client = TestClient(app)
    sid = _open_session(client)

    app2, _store2, _fake2, _ = _build(
        scopes=("meeting_operator",), store=store, operator_id="op_other"
    )
    r = TestClient(app2).delete(f"/api/staff/control-room/sessions/{sid}")
    assert r.status_code == 403


def test_close_session_lock_override_by_setup_admin_succeeds() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",), operator_id="op_dana")
    _seed(store)
    client = TestClient(app)
    sid = _open_session(client)

    app2, _store2, _fake2, _ = _build(scopes=("setup_admin",), store=store, operator_id="op_setup")
    r = TestClient(app2).delete(f"/api/staff/control-room/sessions/{sid}")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "closed"


def test_rollback_fires_the_safe_state_cue() -> None:
    app, store, fake, _ = _build(scopes=("meeting_operator",))
    _seed(store, confirm=True)
    client = TestClient(app)
    sid = _open_on_air_session(client)
    r = client.post(f"/api/staff/control-room/sessions/{sid}/rollback")
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "fired"
    assert r.json()["cue_id"] == "cue_1"
    assert len(fake.applied) == 1


def test_rollback_without_safe_state_cue_is_409() -> None:
    app, store, _fake, _ = _build(scopes=("meeting_operator",))
    _seed(store)
    client = TestClient(app)
    sid = _open_session(client)  # test mode, no safe-state cue configured
    r = client.post(f"/api/staff/control-room/sessions/{sid}/rollback")
    assert r.status_code == 409
    assert "no configured safe-state cue" in r.text


def test_rollback_forbidden_for_support_admin() -> None:
    r = _client(scopes=("support_admin",)).post("/api/staff/control-room/sessions/sess_x/rollback")
    assert r.status_code == 403
    assert "meeting_operator" in r.text


# --- test isolation: _build()'s engine must not leak past the test ----------


def test_build_registers_its_sqlite_engine_for_disposal() -> None:
    """``_build()`` must hand its Engine to the autouse cleanup registry.

    Without this, nothing ever calls ``engine.dispose()`` and the SQLite
    DBAPI connection stays open until the cyclic GC happens to collect it --
    at an unpredictable point that can land inside a later, unrelated test.
    """

    before = len(_ENGINES_TO_DISPOSE)
    _build(scopes=("setup_admin",))
    assert len(_ENGINES_TO_DISPOSE) == before + 1


def test_autouse_fixture_disposes_the_engine_after_the_test() -> None:
    """Regression test for inter-test pollution (predates this change; reproduced
    on a clean main checkout as "a different subset of tests fails on each run").

    ``_build()`` creates a real SQLAlchemy Engine (StaticPool + one persistent
    SQLite DBAPI connection) with no fixture scope of its own to tear down in.
    Left undisposed, these engines and their open DBAPI connections only get
    released whenever the cyclic GC happens to collect them -- a point that
    varies from run to run and can land in the middle of a later, unrelated
    test. That is the actual root cause of the flake: not application state
    leaking between tests, but real OS-level resources (SQLite connections)
    accumulating and being finalized at unpredictable times.

    This drives ``_dispose_registered_engines`` -- the exact teardown logic
    the `_dispose_engines_after_test` autouse fixture runs after every test --
    directly, and asserts it genuinely closes the SQLite DBAPI connection
    (not just drops a Python reference to it).
    """

    _build(scopes=("setup_admin",))
    connection_record = _ENGINES_TO_DISPOSE[-1].pool.connection
    assert connection_record.dbapi_connection is not None  # sanity: really opened

    _dispose_registered_engines()

    assert connection_record.dbapi_connection is None, (
        "the autouse fixture must close _build()'s SQLite DBAPI connection "
        f"once the test ends; found a still-open one: {connection_record.dbapi_connection!r}"
    )
