# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Integration: a live manifest GET feeds the surge switch's load monitor."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from civiccast.common.trusted_proxy import reset_trusted_proxy_cache
from civiccast.egress.router import get_egress_store
from civiccast.live.surge_service import SurgeSwitchService
from civiccast.stream.cdn.stub import StubCDNAdapter
from civiccast.stream.media_router import live_router


class _FixedPeerASGI:
    """ASGI shim that pins ``scope['client']`` to a chosen host so the route's
    ``resolve_client_ip`` sees a *trusted* immediate peer and walks
    ``X-Forwarded-For``. The default TestClient peer (``"testclient"``) is not a
    parseable IP, so without this the CDN-edge case can't be exercised."""

    def __init__(self, app: Any, host: str) -> None:
        self._app = app
        self._host = host

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            scope = {**scope, "client": (self._host, 40000)}
        await self._app(scope, receive, send)


def _app(tmp_path: Path) -> tuple[FastAPI, SurgeSwitchService]:
    live = tmp_path / "live"
    live.mkdir()
    (live / "playlist.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    (live / "seg000000000.ts").write_bytes(b"x" * 32)

    def _get_config(channel_id: str) -> Any:
        if channel_id != "gov-ch12":
            return None
        return SimpleNamespace(sinks=[SimpleNamespace(kind="hls", uri=live.resolve().as_uri())])

    store = SimpleNamespace(get_config=_get_config)
    app = FastAPI()
    app.include_router(live_router)
    app.dependency_overrides[get_egress_store] = lambda: store
    app.state.surge_switch_service = SurgeSwitchService(
        egress_store_provider=lambda: store,
        cdn_adapter_provider=lambda: StubCDNAdapter(tmp_path / "cdn"),
        threshold=1,
        buffer_seconds=0.0,
    )
    return app, app.state.surge_switch_service


def test_manifest_get_feeds_the_surge_monitor(tmp_path: Path) -> None:
    app, svc = _app(tmp_path)
    client = TestClient(app)

    resp = client.get("/media/live/gov-ch12/playlist.m3u8")

    assert resp.status_code == 200
    assert svc.monitor.concurrent("gov-ch12") >= 1  # the poll was recorded


def test_segment_get_does_not_feed_the_monitor(tmp_path: Path) -> None:
    app, svc = _app(tmp_path)
    client = TestClient(app)

    resp = client.get("/media/live/gov-ch12/seg000000000.ts")

    assert resp.status_code == 200
    assert svc.monitor.concurrent("gov-ch12") == 0  # only manifest polls count


def test_two_viewers_behind_one_cdn_edge_count_as_two(tmp_path: Path, monkeypatch: Any) -> None:
    """Regression for the surge-switch undercount: the manifest route must count
    the real client from X-Forwarded-For, not the shared CDN edge IP. With the
    pre-fix ``request.client.host`` both viewers collapse to the one edge IP and
    concurrency reads 1 — so the surge switch would never fire. Proves the route
    resolves distinct clients → 2."""
    # No CDN provider + no explicit CIDRs → the two public XFF client IPs are
    # non-trusted (so they resolve as the real clients). QA-4: private-proxy
    # trust is no longer the default, so this "uvicorn behind a local
    # loopback proxy" scenario now opts in explicitly, same as a real
    # deployment doing the same thing would.
    for var in ("CIVICCAST_CDN_PROVIDER", "CIVICCAST_TRUSTED_PROXY_CIDRS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CIVICCAST_TRUST_PRIVATE_PROXIES", "true")
    reset_trusted_proxy_cache()
    try:
        app, svc = _app(tmp_path)
        client = TestClient(_FixedPeerASGI(app, "127.0.0.1"))

        r1 = client.get(
            "/media/live/gov-ch12/playlist.m3u8",
            headers={"X-Forwarded-For": "203.0.113.10"},
        )
        r2 = client.get(
            "/media/live/gov-ch12/playlist.m3u8",
            headers={"X-Forwarded-For": "203.0.113.20"},
        )

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert svc.monitor.concurrent("gov-ch12") == 2
    finally:
        reset_trusted_proxy_cache()  # don't leak cached env state to other tests
