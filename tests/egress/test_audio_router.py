# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11 SAP/descriptive audio — staff API role-gating + public web-toggle endpoint."""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager

from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.egress.audio_router import (
    get_audio_track_store,
    public_router,
    staff_router,
)
from civiccast.egress.audio_tracks import AudioProgramTrack, AudioTrackStore


def _build(scopes: tuple[str, ...] | None = ("setup_admin",), *, wire: bool = True):
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

    store = AudioTrackStore(factory)
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
        app.dependency_overrides[get_audio_track_store] = lambda: store
    return app, store


def _client(**kw) -> TestClient:
    return TestClient(_build(**kw)[0])


_BODY = {
    "track_id": "t_sap",
    "scope": "channel",
    "target_id": "gov",
    "kind": "sap",
    "language": "es",
    "label": "Spanish SAP",
    "source_uri": "file:///m/es.aac",
}


def test_write_forbidden_for_meeting_operator() -> None:
    r = _client(scopes=("meeting_operator",)).put("/api/staff/audio-tracks/t_sap", json=_BODY)
    assert r.status_code == 403


def test_read_allowed_for_support_admin() -> None:
    assert _client(scopes=("support_admin",)).get("/api/staff/audio-tracks").status_code == 200


def test_crud_roundtrip() -> None:
    client = _client()
    assert client.put("/api/staff/audio-tracks/t_sap", json=_BODY).status_code == 200
    rows = client.get("/api/staff/audio-tracks?target_id=gov").json()
    assert [t["track_id"] for t in rows] == ["t_sap"]
    assert client.delete("/api/staff/audio-tracks/t_sap").status_code == 204


def test_track_id_mismatch_rejected() -> None:
    assert _client().put("/api/staff/audio-tracks/other", json=_BODY).status_code == 400


def _seed_two_tracks(store: AudioTrackStore) -> None:
    store.upsert_track(
        AudioProgramTrack(
            track_id="t_sap",
            scope="channel",
            target_id="gov",
            kind="sap",
            language="es",
            label="Spanish SAP",
            source_uri="file:///m/es.aac",
        )
    )
    store.upsert_track(
        AudioProgramTrack(
            track_id="t_off",
            scope="channel",
            target_id="gov",
            kind="descriptive",
            language="en",
            label="Audio description",
            enabled=False,
        )
    )


def test_public_audio_tracks_for_web_toggle_on_gst_engine(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_ENGINE", "gstreamer")
    app, store = _build()
    _seed_two_tracks(store)
    body = TestClient(app).get("/api/public/channels/gov/audio-tracks").json()
    # only enabled tracks; no internal fields (source_uri) leaked
    assert [t["track_id"] for t in body] == ["t_sap"]
    assert "source_uri" not in body[0]
    assert body[0]["kind"] == "sap"


def test_public_audio_tracks_present_by_default(monkeypatch) -> None:
    # GStreamer is the default engine (S15) -- an unset CIVICCAST_EGRESS_ENGINE
    # must behave identically to an explicit "gstreamer", including advertising
    # secondary audio tracks on the web toggle.
    monkeypatch.delenv("CIVICCAST_EGRESS_ENGINE", raising=False)
    app, store = _build()
    _seed_two_tracks(store)
    body = TestClient(app).get("/api/public/channels/gov/audio-tracks").json()
    assert [t["track_id"] for t in body] == ["t_sap"]


def test_public_audio_tracks_empty_on_legacy_ffmpeg_engine(monkeypatch) -> None:
    # The legacy ffmpeg-concat engine emits a single audio PID, so the player
    # toggle must NOT advertise secondary tracks it cannot select.
    monkeypatch.setenv("CIVICCAST_EGRESS_ENGINE", "ffmpeg-concat")
    app, store = _build()
    _seed_two_tracks(store)
    assert TestClient(app).get("/api/public/channels/gov/audio-tracks").json() == []


def test_staff_list_503_when_unwired() -> None:
    assert _client(wire=False).get("/api/staff/audio-tracks").status_code == 503
