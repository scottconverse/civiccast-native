# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Storage that is CONFIGURED BUT UNREACHABLE must degrade, not 500.

GauntletGate rc18 PE-2026-07-22-1 (Critical). The rc17-era QA-1 fix added
``get_optional_session``, which rescues ``RuntimeError`` -- and
``civiccast.db.get_engine`` raises ``RuntimeError`` in exactly one case: the
``DATABASE_URL`` is unset. Engine construction is lazy and opens no socket, so
when ``DATABASE_URL`` IS set and Postgres is merely unreachable -- restarting,
a network blip, pool exhaustion -- ``get_session()`` succeeds and yields a real
Session. The failure surfaces later, at ``session.execute()`` inside the
handler, as ``sqlalchemy.exc.OperationalError``. Nothing caught that, so it
reached FastAPI as a bare 500.

The gap mattered because the shipped test for the original fix
(``test_media_router_storage_absent.py``) named "any brief Postgres outage,
restart, network blip, pool exhaustion" in its rationale while only ever
exercising ``monkeypatch.delenv("DATABASE_URL")``. It tested the unconfigured
case and claimed the unreachable one. This file covers what that one asserted.

Both are the same thing to a resident: the recording will not play. Both must
answer 503 with the same message, not a hang and a stack trace.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from civiccast.db import reset_engine

# A port nothing listens on: the engine builds fine, the connection does not.
UNREACHABLE_URL = "postgresql+psycopg://civiccast:civiccast@127.0.0.1:59999/civiccast"


@pytest.fixture
def unreachable_storage(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)
    reset_engine()
    try:
        yield
    finally:
        reset_engine()
        os.environ.pop("DATABASE_URL", None)


def test_get_session_does_not_raise_runtime_error_when_merely_unreachable() -> None:
    """The premise of the bug, pinned so the reasoning cannot rot.

    If this ever starts raising RuntimeError, the original narrow guard would
    have been sufficient after all and this whole file can be revisited.
    """

    from civiccast import db

    os.environ["DATABASE_URL"] = UNREACHABLE_URL
    reset_engine()
    try:
        session = next(db.get_session())
        # Engine construction is lazy: no socket has been opened yet.
        with pytest.raises(OperationalError):
            session.execute(__import__("sqlalchemy").text("SELECT 1"))
    finally:
        reset_engine()
        os.environ.pop("DATABASE_URL", None)


def test_vod_playback_degrades_when_postgres_is_unreachable(
    unreachable_storage: None,
) -> None:
    from civiccast.app import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.get("/media/vod/some-asset/playlist.m3u8")

    assert response.status_code == 503, (
        f"VOD playback returned {response.status_code} with Postgres unreachable. "
        "A resident hitting a published meeting during a database restart must "
        "get the documented 503, not a bare 500."
    )
    assert response.json()["detail"] == "Durable storage is not ready yet."


def test_live_playback_degrades_when_postgres_is_unreachable(
    unreachable_storage: None,
) -> None:
    """The live sibling reads the egress store, which has the same exposure."""

    from civiccast.app import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    response = client.get("/media/live/some-channel/playlist.m3u8")

    assert response.status_code in (404, 503), (
        f"Live playback returned {response.status_code} with Postgres "
        "unreachable; expected a clean 404/503 degrade, not a 500."
    )


def test_unconfigured_storage_still_degrades_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The original case must keep working -- this fix widens, never replaces."""

    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_engine()
    try:
        from civiccast.app import create_app

        client = TestClient(create_app(), raise_server_exceptions=False)
        response = client.get("/media/vod/some-asset/playlist.m3u8")
        assert response.status_code == 503
        assert response.json()["detail"] == "Durable storage is not ready yet."
    finally:
        reset_engine()
