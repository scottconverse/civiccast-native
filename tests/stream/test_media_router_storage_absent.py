# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Policy: VOD playback must degrade, not 500, when storage is unreachable.

GauntletGate QA-1 (Critical, 2026-07-21, reproduced live by an adversarial
verifier). ``GET /media/vod/{asset_id}/{file_path}`` depends directly on
``Depends(get_session)``. ``civiccast/db/session.py`` raises a bare
``RuntimeError`` when ``DATABASE_URL`` is unset, which FastAPI turns into an
unhandled 500 *before* the handler's own documented promise -- "404s (rather
than 500s) for any asset with no completed finalization job" -- is ever reached.

Its sibling one file away, ``GET /media/live/{channel_id}/{file_path}``, takes a
nullable dependency and returns a clean 404 in the same conditions.

This is not only a first-run artifact: it reproduces on any brief Postgres
outage in production (restart, network blip, pool exhaustion), on the
resident-facing route that plays back published public meetings.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from civiccast.app import create_app


def _client_without_storage(monkeypatch: MonkeyPatch) -> TestClient:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    return TestClient(create_app(), raise_server_exceptions=False)


def test_vod_playback_degrades_instead_of_raising_500(monkeypatch: MonkeyPatch) -> None:
    client = _client_without_storage(monkeypatch)
    response = client.get("/media/vod/any-asset/playlist.m3u8")
    assert response.status_code != 500, (
        "VOD playback returned a bare 500 with storage unreachable. Every other "
        "public route degrades; a resident hitting a published meeting during a "
        "database blip must not get 'Internal Server Error'."
    )
    assert response.status_code in {404, 503}, response.status_code


def test_vod_failure_does_not_leak_internals(monkeypatch: MonkeyPatch) -> None:
    client = _client_without_storage(monkeypatch)
    body = client.get("/media/vod/any-asset/playlist.m3u8").text.lower()
    for leak in ("traceback", "sqlalchemy", "runtimeerror", "database_url"):
        assert leak not in body, f"response leaked internal detail: {leak!r}"


def test_live_sibling_still_degrades_cleanly(monkeypatch: MonkeyPatch) -> None:
    """The sibling that already behaved correctly must not regress."""
    client = _client_without_storage(monkeypatch)
    response = client.get("/media/live/any-channel/playlist.m3u8")
    assert response.status_code == 404, response.status_code
