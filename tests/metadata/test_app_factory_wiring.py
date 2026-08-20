# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S22 app-factory wiring — ``create_app()`` registers + wires the custom-field service.

``test_router.py`` exercises the routers with a hand-built SQLite service. Nothing there
asserts that ``create_app()`` actually registers ``get_custom_field_service`` and mounts both
routers, or that the public search filters the SAME packaged corpus the portal shows. A
refactor dropping the override (reverting every endpoint to a 503) would have passed the
router suite. These tests close that gap end-to-end against a real migrated DB:

* the override is registered + both routers are mounted (no 503 on the live path);
* a full round-trip: setup_admin defines a field, a value is set on a packaged asset, and the
  public search surfaces ONLY the exposed field (the non-exposed one never leaks — DC-5);
* numeric range search via the denormalized value_num column resolves the right asset.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.metadata.router import get_custom_field_service

# A real configured staff token granting the def-write + value-write roles, so the staff
# calls below go through the REAL auth middleware (not an injected identity) — proving the
# routers are mounted on the live, authenticated path.
_ADMIN_TOKEN = "cf-wiring-admin"  # deterministic local test token
_STAFF_TOKENS = f"{_ADMIN_TOKEN}:dana:Dana:setup_admin,meeting_operator"
_ADMIN_HEADERS = {"Authorization": f"Bearer {_ADMIN_TOKEN}"}


def _migrate(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _store_over_db() -> object:
    """A schedule asset store over the same SQLite DB the app uses (to seed a packaged asset)."""
    import os

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from civiccast.schedule.store import PostgresAssetStore

    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, future=True)
    if database_url.startswith("sqlite"):
        engine = engine.execution_options(schema_translate_map={"civiccast": None})

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return PostgresAssetStore(factory)


@pytest.fixture
def durable_app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "cf-wiring.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS", _STAFF_TOKENS)
    # The DB token store is consulted first; allow the configured env token as a fallback so
    # this fixture can authenticate without seeding a DB-issued token.
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
    # Point the durable contributor (producer-identity) store at a temp path so a producer_ref
    # round-trip resolves against the SAME durable source the app binds (M1/M2).
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_STORE_PATH", str(tmp_path / "contributors.json"))
    # QA-3: store.create_submission now requires media.upload_ref to resolve to a
    # real file inside the configured contributor upload directory, so _seed_producer
    # below needs one isolated to this test rather than the real machine's default.
    monkeypatch.setenv("CIVICCAST_CONTRIBUTOR_UPLOAD_DIR", str(tmp_path / "contributor-uploads"))
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    _migrate(db_path)
    yield tmp_path


def _seed_producer(account_id: str) -> None:
    """Persist a producer (contributor account) into the durable contributor store, then move
    its submission OUT of the pending review queue — proving producer_ref resolves against
    durable identity, not "has a queued submission" (M2)."""
    import hashlib
    from datetime import UTC, datetime

    from civiccast.contribute.models import (
        BrokenMediaGateResult,
        ContributorAccount,
        ContributorReviewRequest,
        ContributorSubmissionCreate,
        ScheduleHandoff,
        SubmissionAgreementAcceptance,
        SubmissionMediaReference,
        SubmissionNotificationPreference,
    )
    from civiccast.contribute.store import (
        ContributorSubmissionStore,
        default_contributor_store_path,
        default_contributor_upload_dir,
    )

    now = datetime(2026, 5, 31, 18, 0, tzinfo=UTC)
    # QA-3: upload_ref must resolve to a real file inside the configured
    # contributor upload directory; the durable_app_env fixture points that
    # directory at this test's isolated tmp_path.
    upload_dir = default_contributor_upload_dir()
    upload_dir.mkdir(parents=True, exist_ok=True)
    show_path = upload_dir / "show.mov"
    show_content = b"seeded-producer-program-bytes"
    show_path.write_bytes(show_content)

    store = ContributorSubmissionStore(default_contributor_store_path())
    receipt = store.create_submission(
        ContributorSubmissionCreate(
            contributor=ContributorAccount(
                account_id=account_id,
                display_name="City TV",
                contact_email="producer@example.test",
            ),
            channel_id="public",
            title="Producer Program",
            description="A program from a known producer.",
            tags=["civic"],
            producer_name="City TV",
            media=SubmissionMediaReference(
                upload_ref=str(show_path),
                filename="show.mov",
                content_type="video/quicktime",
                size_bytes=len(show_content),
                sha256=hashlib.sha256(show_content).hexdigest(),
            ),
            agreements=[
                SubmissionAgreementAcceptance(
                    agreement_id="community-media-submission",
                    version="2026-05-31",
                    accepted_at=now,
                    accepted_by_name="City TV",
                )
            ],
            notifications=[
                SubmissionNotificationPreference(kind="email", target="producer@example.test")
            ],
        )
    )
    store.review_submission(
        receipt.submission_id,
        ContributorReviewRequest(
            action="schedule",
            broken_media_gate=BrokenMediaGateResult(
                state="passed", checked_at=now, summary="probes passed"
            ),
            schedule_handoff=ScheduleHandoff(
                channel_id="public", requested_start=now, duration_seconds=1800
            ),
        ),
    )


def test_app_factory_registers_custom_field_service(durable_app_env: Path) -> None:
    from civiccast.app import create_app

    app = create_app()
    assert get_custom_field_service in app.dependency_overrides
    # The override resolves to a real service (not None), so the live path never 503s.
    assert app.dependency_overrides[get_custom_field_service]() is not None


def test_full_roundtrip_define_set_and_public_search(durable_app_env: Path) -> None:
    from civiccast.app import create_app
    from civiccast.vod.models import AssetMetadata

    # Seed a packaged public asset directly so /api/public/search has a corpus.
    _store_over_db().create(  # type: ignore[attr-defined]
        AssetMetadata(
            asset_id="council-jan",
            title="City Council — January",
            manifest_url="https://cdn.example.org/council-jan/index.m3u8",
            published_at=datetime(2026, 5, 8, 20, 15, tzinfo=UTC),
        )
    )

    app = create_app()
    client = TestClient(app, headers=_ADMIN_HEADERS)

    # 1) setup_admin defines two fields: one exposed list facet + one HIDDEN field.
    assert (
        client.post(
            "/api/staff/custom-fields",
            json={
                "field_id": "fld_meeting_type",
                "station_id": "civiccast-station",
                "key": "meeting_type",
                "label": "Meeting Type",
                "type": "list",
                "options": ["Regular", "Special"],
                "searchable": True,
                "api_exposed": True,
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/staff/custom-fields",
            json={
                "field_id": "fld_secret",
                "station_id": "civiccast-station",
                "key": "secret",
                "label": "Internal Note",
                "type": "text",
                "searchable": True,
                "api_exposed": False,
            },
        ).status_code
        == 201
    )

    # 2) set values on the packaged asset (the meeting_operator role is granted too).
    put = client.put(
        "/api/staff/assets/council-jan/custom-fields",
        json={
            "values": [
                {"field_id": "fld_meeting_type", "value": "Regular"},
                {"field_id": "fld_secret", "value": "classified"},
            ]
        },
    )
    assert put.status_code == 200, put.text

    # 3) public search (unauthenticated) surfaces the asset with ONLY the exposed field.
    pub = TestClient(app).get("/api/public/search?cf.meeting_type=Regular")
    assert pub.status_code == 200, pub.text
    body = pub.json()
    assert [row["asset_id"] for row in body] == ["council-jan"]
    keys = {cf["key"] for cf in body[0]["custom_fields"]}
    assert keys == {"meeting_type"}  # the hidden 'secret' field never leaks


def test_public_search_number_range_via_value_num(durable_app_env: Path) -> None:
    from civiccast.app import create_app
    from civiccast.vod.models import AssetMetadata

    store = _store_over_db()
    for aid in ("ep-10", "ep-20"):
        store.create(  # type: ignore[attr-defined]
            AssetMetadata(
                asset_id=aid,
                title=aid,
                manifest_url=f"https://cdn.example.org/{aid}/index.m3u8",
                published_at=datetime(2026, 5, 8, 20, 15, tzinfo=UTC),
            )
        )

    app = create_app()
    client = TestClient(app, headers=_ADMIN_HEADERS)
    client.post(
        "/api/staff/custom-fields",
        json={
            "field_id": "fld_eps",
            "station_id": "civiccast-station",
            "key": "episode",
            "label": "Episode",
            "type": "number",
            "searchable": True,
            "api_exposed": True,
        },
    )
    client.put(
        "/api/staff/assets/ep-10/custom-fields",
        json={"values": [{"field_id": "fld_eps", "value": "10"}]},
    )
    client.put(
        "/api/staff/assets/ep-20/custom-fields",
        json={"values": [{"field_id": "fld_eps", "value": "20"}]},
    )

    pub = TestClient(app).get("/api/public/search?cf.episode_gte=15")
    assert pub.status_code == 200, pub.text
    assert [row["asset_id"] for row in pub.json()] == ["ep-20"]


def test_app_factory_resolves_asset_ref_and_producer_ref_through_live_path(
    durable_app_env: Path,
) -> None:
    # M1/T2/T3: PUT both an asset_ref AND a producer_ref through create_app() so the live
    # resolver bindings (asset_exists -> app session factory; producer_exists -> app
    # contributor identity source) are exercised, not just injected lambdas. A dangling ref of
    # each kind is a 422; a resolvable ref of each kind is a 200.
    from civiccast.app import create_app
    from civiccast.vod.models import AssetMetadata

    # Seed a library asset (the asset_ref target) and a durable producer identity.
    _store_over_db().create(  # type: ignore[attr-defined]
        AssetMetadata(
            asset_id="library-clip",
            title="Library Clip",
            manifest_url="https://cdn.example.org/library-clip/index.m3u8",
        )
    )
    _seed_producer("city-tv")

    app = create_app()
    client = TestClient(app, headers=_ADMIN_HEADERS)

    # Define an asset_ref field and a producer_ref field.
    for field_id, key, label, ftype in (
        ("fld_related", "related", "Related Asset", "asset_ref"),
        ("fld_producer", "producer", "Producer", "producer_ref"),
    ):
        assert (
            client.post(
                "/api/staff/custom-fields",
                json={
                    "field_id": field_id,
                    "station_id": "civiccast-station",
                    "key": key,
                    "label": label,
                    "type": ftype,
                },
            ).status_code
            == 201
        )

    # A target asset to attach the values to.
    _store_over_db().create(  # type: ignore[attr-defined]
        AssetMetadata(
            asset_id="host-asset",
            title="Host Asset",
            manifest_url="https://cdn.example.org/host-asset/index.m3u8",
        )
    )

    # Dangling asset_ref -> 422 (asset_exists is bound to the app DB, not the module global).
    bad_asset = client.put(
        "/api/staff/assets/host-asset/custom-fields",
        json={"values": [{"field_id": "fld_related", "value": "no-such-asset"}]},
    )
    assert bad_asset.status_code == 422, bad_asset.text

    # Dangling producer_ref -> 422 (producer_exists is bound to the app contributor identity).
    bad_producer = client.put(
        "/api/staff/assets/host-asset/custom-fields",
        json={"values": [{"field_id": "fld_producer", "value": "ghost-producer"}]},
    )
    assert bad_producer.status_code == 422, bad_producer.text

    # Both resolvable refs together -> 200 (the engine-leak guard: the app-bound resolvers
    # query the app's data planes, never the module-global default engine / empty store).
    ok = client.put(
        "/api/staff/assets/host-asset/custom-fields",
        json={
            "values": [
                {"field_id": "fld_related", "value": "library-clip"},
                {"field_id": "fld_producer", "value": "city-tv"},
            ]
        },
    )
    assert ok.status_code == 200, ok.text
    stored = {row["field_id"]: row["value"] for row in ok.json()}
    assert stored == {"fld_related": "library-clip", "fld_producer": "city-tv"}


def test_app_factory_producer_resolver_is_bound_not_module_global(durable_app_env: Path) -> None:
    # T3: a regression that reverted producer_exists to the module-global default (a path-less,
    # empty ContributorSubmissionStore that resolves nobody) would make a valid producer_ref
    # fail. Assert the override's service resolves the seeded producer AND rejects an unknown
    # one through the app-bound resolver — pinning the binding to the app identity source.
    from civiccast.app import create_app
    from civiccast.metadata.router import get_custom_field_service

    _seed_producer("city-tv")
    app = create_app()
    service = app.dependency_overrides[get_custom_field_service]()
    # The bound resolver sees the durable producer; an unknown id does not resolve.
    assert service._producer_exists("city-tv") is True
    assert service._producer_exists("ghost-producer") is False


def test_public_search_op_documents_cf_params(durable_app_env: Path) -> None:
    # W-1: the public-search route reads raw request.query_params, so FastAPI emits no params;
    # openapi_extra must document the cf.<key> family so the published contract is not "none".
    from civiccast.app import create_app

    schema = create_app().openapi()
    params = schema["paths"]["/api/public/search"]["get"].get("parameters", [])
    names = {p["name"] for p in params}
    assert {"cf.<key>", "cf.<key>_gte", "cf.<key>_lte"} <= names
    # The exposure semantics (DC-5: exposed-only, silently ignored) are documented.
    joined = " ".join(p.get("description", "") for p in params)
    assert "api_exposed" in joined
    assert "silently ignored" in joined.lower()
