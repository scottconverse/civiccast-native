# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S22 custom-metadata staff + public API — role gating, typed validation, exposure boundary.

A minimal FastAPI app mounts the real metadata routers, sets the operator identity via
middleware (so the real ``require_any_role`` gate runs), and overrides the DI seam with a
SQLite-backed ``CustomFieldStore`` + ``CustomFieldService``. Covers:

* role gating (READ / def-WRITE setup_admin-only / value-WRITE meeting_operator+records_clerk;
  403 / 401), for both staff surfaces;
* def CRUD (create / get / patch label / delete), key-immutability on PATCH (409),
  DELETE blocked when values exist unless ``?confirm=true`` (409 -> 204);
* asset values GET / PUT with typed validation (list-not-an-option / required-missing -> 422,
  asset_ref must resolve -> 422);
* public ``/api/public/search?cf.<key>=<value>``: exposes ONLY searchable+api_exposed fields,
  a non-exposed field never leaks and cannot be used as a working filter (DC-5), numeric/date
  range via ``cf.<key>_gte`` / ``_lte`` against value_num/value_date;
* 503 when the service is unwired.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.metadata.models import AssetMetadata
from civiccast.metadata.router import (
    get_custom_field_service,
    public_router,
    staff_router,
)
from civiccast.metadata.service import CustomFieldService
from civiccast.metadata.store import CustomFieldStore

_STATION = "civiccast-station"

# A small known universe so asset_ref/producer_ref resolution is deterministic.
_KNOWN_ASSETS = {"council-2025-01", "council-2025-02", "planning-2025-01", "library-asset"}
_KNOWN_PRODUCERS = {"city-tv", "public-access"}

# Packaged public assets the public-search endpoint filters over (asset_id + title only
# need to be real for the projection; the cf values drive the match).
_PUBLIC_ASSETS = [
    AssetMetadata(
        asset_id="council-2025-01",
        title="City Council — January",
        manifest_url="https://cdn.example.org/council-2025-01/index.m3u8",
    ),
    AssetMetadata(
        asset_id="council-2025-02",
        title="City Council — February",
        manifest_url="https://cdn.example.org/council-2025-02/index.m3u8",
    ),
    AssetMetadata(
        asset_id="planning-2025-01",
        title="Planning Commission — January",
        manifest_url="https://cdn.example.org/planning-2025-01/index.m3u8",
    ),
]


def _build(
    scopes: tuple[str, ...] | None = ("setup_admin",),
    *,
    wire: bool = True,
):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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

    store = CustomFieldStore(factory)
    service = CustomFieldService(
        store,
        asset_exists=lambda aid: aid in _KNOWN_ASSETS,
        producer_exists=lambda pid: pid in _KNOWN_PRODUCERS,
        public_asset_lister=lambda: list(_PUBLIC_ASSETS),
    )

    app = FastAPI()

    @app.middleware("http")
    async def _ident(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(staff_router)
    app.include_router(public_router)
    if wire:
        app.dependency_overrides[get_custom_field_service] = lambda: service
    return app, store, service


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


def _def_payload(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "field_id": "fld_meeting_type",
        "station_id": _STATION,
        "key": "meeting_type",
        "label": "Meeting Type",
        "type": "list",
        "options": ["Regular", "Special"],
        "required": False,
        "searchable": True,
        "api_exposed": True,
        "order": 0,
    }
    base.update(kw)
    return base


def _seed_def(client: TestClient, **kw: object) -> dict:
    r = client.post("/api/staff/custom-fields", json=_def_payload(**kw))
    assert r.status_code == 201, r.text
    return r.json()


# --- def CRUD role gating ----------------------------------------------------


def test_list_defs_allowed_for_read_roles() -> None:
    for scope in ("setup_admin", "meeting_operator", "records_clerk"):
        r = _client(scopes=(scope,)).get("/api/staff/custom-fields")
        assert r.status_code == 200, (scope, r.text)


def test_list_defs_unauthorized_without_identity() -> None:
    assert _client(scopes=None).get("/api/staff/custom-fields").status_code == 401


def test_create_def_allowed_for_setup_admin() -> None:
    r = _client(scopes=("setup_admin",)).post("/api/staff/custom-fields", json=_def_payload())
    assert r.status_code == 201, r.text
    assert r.json()["key"] == "meeting_type"


def test_create_def_forbidden_for_meeting_operator() -> None:
    r = _client(scopes=("meeting_operator",)).post("/api/staff/custom-fields", json=_def_payload())
    assert r.status_code == 403


def test_create_def_forbidden_for_records_clerk() -> None:
    r = _client(scopes=("records_clerk",)).post("/api/staff/custom-fields", json=_def_payload())
    assert r.status_code == 403


# --- def CRUD behavior -------------------------------------------------------


def test_get_def_roundtrip_and_404() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client)
    got = client.get("/api/staff/custom-fields/fld_meeting_type")
    assert got.status_code == 200, got.text
    assert got.json()["label"] == "Meeting Type"
    assert client.get("/api/staff/custom-fields/fld_nope").status_code == 404


def test_patch_label_is_editable() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client)
    r = client.patch("/api/staff/custom-fields/fld_meeting_type", json={"label": "Session Type"})
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "Session Type"
    assert r.json()["key"] == "meeting_type"  # unchanged


def test_patch_key_is_immutable() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client)
    r = client.patch("/api/staff/custom-fields/fld_meeting_type", json={"key": "renamed_key"})
    assert r.status_code == 409, r.text


def test_patch_forbidden_for_meeting_operator() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client)
    forbidden = _client(scopes=("meeting_operator",)).patch(
        "/api/staff/custom-fields/fld_meeting_type", json={"label": "X"}
    )
    assert forbidden.status_code == 403


def test_delete_def_without_values_succeeds() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client)
    r = client.delete("/api/staff/custom-fields/fld_meeting_type")
    assert r.status_code == 204, r.text
    assert client.get("/api/staff/custom-fields/fld_meeting_type").status_code == 404


def test_delete_def_blocked_when_values_exist_then_confirm() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client)
    # set a value so the def now has dependents
    put = client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={"values": [{"field_id": "fld_meeting_type", "value": "Regular"}]},
    )
    assert put.status_code == 200, put.text
    blocked = client.delete("/api/staff/custom-fields/fld_meeting_type")
    assert blocked.status_code == 409, blocked.text
    confirmed = client.delete("/api/staff/custom-fields/fld_meeting_type?confirm=true")
    assert confirmed.status_code == 204, confirmed.text


def test_delete_def_forbidden_for_records_clerk() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client)
    forbidden = _client(scopes=("records_clerk",)).delete(
        "/api/staff/custom-fields/fld_meeting_type"
    )
    assert forbidden.status_code == 403


# --- asset values role gating ------------------------------------------------


def test_get_values_allowed_for_value_roles() -> None:
    setup = _client(scopes=("setup_admin",))
    _seed_def(setup)
    for scope in ("setup_admin", "meeting_operator", "records_clerk"):
        r = _client(scopes=(scope,)).get("/api/staff/assets/council-2025-01/custom-fields")
        assert r.status_code == 200, (scope, r.text)
        assert r.json() == []  # zero-state


def test_put_values_allowed_for_meeting_operator() -> None:
    setup = _client(scopes=("setup_admin",))
    _seed_def(setup)
    # share the same backing store via a single app
    app, _store, service = _build(scopes=("meeting_operator",))
    client = TestClient(app)
    # seed a def directly through the service (the meeting_operator cannot create defs)
    from civiccast.metadata.models import CustomFieldDef

    service.create_field(CustomFieldDef(**_def_payload()))  # type: ignore[arg-type]
    r = client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={"values": [{"field_id": "fld_meeting_type", "value": "Special"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()[0]["value"] == "Special"


def test_put_values_forbidden_without_value_role() -> None:
    # support_admin is NOT an S22 role (spec §4): neither a def-read nor a value-write role.
    app, _store, service = _build(scopes=("support_admin",))
    client = TestClient(app)
    from civiccast.metadata.models import CustomFieldDef

    service.create_field(CustomFieldDef(**_def_payload()))  # type: ignore[arg-type]
    r = client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={"values": [{"field_id": "fld_meeting_type", "value": "Regular"}]},
    )
    assert r.status_code == 403, r.text


def test_list_defs_forbidden_for_support_admin() -> None:
    # N1: field-definition reads are scoped to the spec §4 roles only; support_admin (a real
    # role, but not an S22 role) must NOT read field definitions.
    r = _client(scopes=("support_admin",)).get("/api/staff/custom-fields")
    assert r.status_code == 403, r.text


# --- asset values typed validation -------------------------------------------


def test_put_value_not_an_option_is_422() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client)
    r = client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={"values": [{"field_id": "fld_meeting_type", "value": "NotAnOption"}]},
    )
    assert r.status_code == 422, r.text


def test_put_required_missing_is_422() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client, required=True)
    r = client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={"values": []},
    )
    assert r.status_code == 422, r.text


def test_put_asset_ref_must_resolve_is_422() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client, field_id="fld_related", key="related", type="asset_ref", options=[])
    bad = client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={"values": [{"field_id": "fld_related", "value": "no-such-asset"}]},
    )
    assert bad.status_code == 422, bad.text
    ok = client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={"values": [{"field_id": "fld_related", "value": "library-asset"}]},
    )
    assert ok.status_code == 200, ok.text


def test_put_number_denormalizes_value_num() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_def(client, field_id="fld_eps", key="episode", type="number", options=[])
    r = client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={"values": [{"field_id": "fld_eps", "value": "42"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()[0]["value_num"] == 42.0


# --- public search exposure boundary + facets --------------------------------


def _seed_search_corpus(client: TestClient) -> None:
    """Two exposed defs (a list facet + a number range) and one HIDDEN def, with values."""
    _seed_def(
        client,
        field_id="fld_meeting_type",
        key="meeting_type",
        type="list",
        options=["Regular", "Special"],
        searchable=True,
        api_exposed=True,
    )
    _seed_def(
        client,
        field_id="fld_eps",
        key="episode",
        type="number",
        options=[],
        searchable=True,
        api_exposed=True,
    )
    _seed_def(
        client,
        field_id="fld_secret",
        key="secret",
        type="text",
        options=[],
        searchable=True,
        api_exposed=False,
    )  # NOT exposed
    client.put(
        "/api/staff/assets/council-2025-01/custom-fields",
        json={
            "values": [
                {"field_id": "fld_meeting_type", "value": "Regular"},
                {"field_id": "fld_eps", "value": "10"},
                {"field_id": "fld_secret", "value": "classified"},
            ]
        },
    )
    client.put(
        "/api/staff/assets/council-2025-02/custom-fields",
        json={
            "values": [
                {"field_id": "fld_meeting_type", "value": "Special"},
                {"field_id": "fld_eps", "value": "20"},
            ]
        },
    )


def test_public_search_no_params_returns_all_with_exposed_fields_only() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_search_corpus(client)
    # the public endpoint is unauthenticated, but the staff client's identity is simply
    # ignored on the public router — same backing store, so we reuse the same client.
    pub = client.get("/api/public/search")
    assert pub.status_code == 200, pub.text
    body = pub.json()
    ids = {row["asset_id"] for row in body}
    assert {"council-2025-01", "council-2025-02"} <= ids
    # the hidden field never appears in any public custom_fields map
    for row in body:
        keys = {cf["key"] for cf in row.get("custom_fields", [])}
        assert "secret" not in keys


def test_public_search_eq_facet_filters() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_search_corpus(client)
    pub = client.get("/api/public/search?cf.meeting_type=Regular")
    assert pub.status_code == 200, pub.text
    ids = {row["asset_id"] for row in pub.json()}
    assert ids == {"council-2025-01"}


def test_public_search_hidden_field_filter_is_noop_not_leak() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_search_corpus(client)
    # filtering on a non-exposed field must NOT work as a filter (DC-5: no inference leak).
    pub = client.get("/api/public/search?cf.secret=classified")
    assert pub.status_code == 200, pub.text
    ids = {row["asset_id"] for row in pub.json()}
    # the hidden key is ignored -> behaves like no filter (both assets present)
    assert {"council-2025-01", "council-2025-02"} <= ids


def test_public_search_number_range() -> None:
    client = _client(scopes=("setup_admin",))
    _seed_search_corpus(client)
    pub = client.get("/api/public/search?cf.episode_gte=15&cf.episode_lte=25")
    assert pub.status_code == 200, pub.text
    ids = {row["asset_id"] for row in pub.json()}
    assert ids == {"council-2025-02"}


def test_public_search_is_unauthenticated() -> None:
    # No operator identity at all -> public endpoint must still answer 200.
    app, _store, service = _build(scopes=None)
    from civiccast.metadata.models import CustomFieldDef

    service.create_field(CustomFieldDef(**_def_payload()))  # type: ignore[arg-type]
    r = TestClient(app).get("/api/public/search")
    assert r.status_code == 200, r.text


# --- 503 when unwired --------------------------------------------------------


def test_staff_list_503_when_unwired() -> None:
    r = _client(scopes=("setup_admin",), wire=False).get("/api/staff/custom-fields")
    assert r.status_code == 503, r.text


def test_public_search_503_when_unwired() -> None:
    r = _client(scopes=None, wire=False).get("/api/public/search")
    assert r.status_code == 503, r.text


@pytest.mark.parametrize("scope", ["setup_admin", "meeting_operator", "records_clerk"])
def test_value_read_roles_matrix(scope: str) -> None:
    setup = _client(scopes=("setup_admin",))
    _seed_def(setup)
    r = _client(scopes=(scope,)).get("/api/staff/assets/council-2025-01/custom-fields")
    assert r.status_code == 200
