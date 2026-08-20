# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Community bulletin CRUD + moderation API tests (cable automation CA-3)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, suppress

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.schedule.models  # noqa: F401 -- ATTACH ':memory:' AS civiccast on SQLite connect
from civiccast.app import create_app
from civiccast.cg.bulletin_store import PostgresCgBulletinStore
from civiccast.cg.router import get_cg_bulletin_store
from civiccast.db import Base, bind_engine, reset_engine

_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}


@contextmanager
def _client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    bind_engine(engine)
    with engine.connect() as conn:
        with suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        Base.metadata.create_all(conn)
        conn.commit()
    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            sess = Session(bind=engine)
            try:
                yield sess
            finally:
                sess.close()

        app = create_app()
        app.dependency_overrides[get_cg_bulletin_store] = lambda: PostgresCgBulletinStore(
            session_factory
        )
        yield TestClient(app, headers=_STAFF_HEADERS)
    finally:
        reset_engine()
        engine.dispose()


def _create_payload(**overrides):  # type: ignore[no-untyped-def]
    payload = {
        "organization": "Pinegrove Garden Club",
        "submitter_label": "Garden Club coordinator",
        "title": "Spring plant sale",
        "message": "Saturday 9am at the community center.",
        "target_zone_kind": "primary",
    }
    payload.update(overrides)
    return payload


def test_create_moderate_and_serve_public_rotation() -> None:
    with _client() as client:
        created = client.post("/api/staff/cg/channels/public/bulletins", json=_create_payload())
        assert created.status_code == 200
        submission = created.json()
        assert submission["state"] == "submitted"
        submission_id = submission["submission_id"]

        # Not approved yet: the public rotation is empty.
        public = client.get("/api/public/cg/channels/public/bulletins")
        assert public.status_code == 200
        assert public.json()["submissions"] == []

        approved = client.patch(
            f"/api/staff/cg/channels/public/bulletins/{submission_id}",
            json={"state": "accepted", "approved_by_operator": "op-hash-1"},
        )
        assert approved.status_code == 200
        assert approved.json()["state"] == "accepted"

        public = client.get("/api/public/cg/channels/public/bulletins").json()
        assert [item["submission_id"] for item in public["submissions"]] == [submission_id]
        assert public["approved_zone_items"][0]["content"]["submission_id"] == submission_id

        staff = client.get("/api/staff/cg/channels/public/bulletins").json()
        assert len(staff["submissions"]) == 1


def test_moderation_rules_are_enforced_over_the_api() -> None:
    with _client() as client:
        submission_id = client.post(
            "/api/staff/cg/channels/public/bulletins", json=_create_payload()
        ).json()["submission_id"]

        # Approving without an operator id violates the model's rule.
        rejected = client.patch(
            f"/api/staff/cg/channels/public/bulletins/{submission_id}",
            json={"state": "accepted"},
        )
        assert rejected.status_code == 422
        assert "approved_by_operator" in rejected.json()["detail"]

        # Declining requires moderation notes.
        rejected = client.patch(
            f"/api/staff/cg/channels/public/bulletins/{submission_id}",
            json={"state": "declined"},
        )
        assert rejected.status_code == 422

        ok = client.patch(
            f"/api/staff/cg/channels/public/bulletins/{submission_id}",
            json={"state": "declined", "moderation_notes": "Duplicate of an existing post."},
        )
        assert ok.status_code == 200


def test_unknown_bulletin_and_wrong_channel_are_404() -> None:
    with _client() as client:
        assert (
            client.patch(
                "/api/staff/cg/channels/public/bulletins/cgb_nope",
                json={"title": "x"},
            ).status_code
            == 404
        )
        submission_id = client.post(
            "/api/staff/cg/channels/public/bulletins", json=_create_payload()
        ).json()["submission_id"]
        assert (
            client.patch(
                f"/api/staff/cg/channels/education/bulletins/{submission_id}",
                json={"title": "x"},
            ).status_code
            == 404
        )


def test_mutations_503_without_durable_storage() -> None:
    client = TestClient(create_app(), headers=_STAFF_HEADERS)
    response = client.post("/api/staff/cg/channels/public/bulletins", json=_create_payload())
    assert response.status_code == 503
    # The read endpoints keep the deterministic mock in ephemeral mode.
    assert client.get("/api/public/cg/channels/public/bulletins").status_code == 200
