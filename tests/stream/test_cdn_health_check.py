# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for CDNAdapter.health_check on the stub and BunnyCDN adapters.

The Cloudflare R2 adapter's health_check is covered (with moto) in
test_cdn_cloudflare_r2.py; this file covers the other two implementations and
protocol conformance of the new method.
"""

from __future__ import annotations

import types
from pathlib import Path

import httpx
import pytest

from civiccast.stream.cdn import CDNAdapter
from civiccast.stream.cdn.bunny import BunnyCDNAdapter
from civiccast.stream.cdn.stub import StubCDNAdapter


def _bunny() -> BunnyCDNAdapter:
    return BunnyCDNAdapter(
        storage_zone_name="civiccast-zone",
        access_key="bunny-key",
        cdn_hostname="civiccast.b-cdn.net",
    )


# --- protocol conformance ----------------------------------------------------


def test_stub_and_bunny_satisfy_the_protocol_including_health_check(tmp_path: Path) -> None:
    assert isinstance(StubCDNAdapter(tmp_path), CDNAdapter)
    assert isinstance(_bunny(), CDNAdapter)


# --- stub --------------------------------------------------------------------


def test_stub_health_check_true_when_root_is_creatable(tmp_path: Path) -> None:
    adapter = StubCDNAdapter(tmp_path / "cdn-root")
    assert adapter.health_check() is True
    assert (tmp_path / "cdn-root").is_dir()


def test_stub_health_check_false_when_root_cannot_be_created(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("i am a file", encoding="utf-8")
    # A root whose parent is a regular file cannot be mkdir'd -> OSError -> False.
    adapter = StubCDNAdapter(blocker / "sub")
    assert adapter.health_check() is False


# --- bunny (httpx.get mocked) ------------------------------------------------


def test_bunny_health_check_true_on_http_200(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, **kwargs: object) -> types.SimpleNamespace:
        assert url == "https://storage.bunnycdn.com/civiccast-zone/"
        assert kwargs["headers"] == {"AccessKey": "bunny-key"}
        return types.SimpleNamespace(status_code=200)

    monkeypatch.setattr(httpx, "get", fake_get)
    assert _bunny().health_check() is True


def test_bunny_health_check_false_on_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda *a, **k: types.SimpleNamespace(status_code=401))
    assert _bunny().health_check() is False


def test_bunny_health_check_false_on_transport_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> types.SimpleNamespace:
        raise httpx.ConnectError("zone unreachable")

    monkeypatch.setattr(httpx, "get", boom)
    assert _bunny().health_check() is False
