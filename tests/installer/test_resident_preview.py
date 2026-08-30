# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for ``build_resident_preview`` (bug B4).

Field evidence, native beta candidate #17: the resident preview
unconditionally defaulted to a Vite dev-server URL
(``http://127.0.0.1:5174``) even on a packaged production station -- one
that mounts the real resident portal on its own control-plane origin (see
``civiccast.app._mount_packaged_portals`` / ``CIVICCAST_PUBLIC_PORTAL_DIST``)
-- and simultaneously reported ``status="not_configured"`` even though a
real preview was one click away. These tests pin the packaged-vs-dev split
that mirrors ``operator_console_url()``'s own existing convention.
"""

from __future__ import annotations

import pytest

from civiccast.installer.service import build_resident_preview


@pytest.fixture(autouse=True)
def _clear_resident_preview_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVICCAST_RESIDENT_PORTAL_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_PUBLIC_PORTAL_DIST", raising=False)
    monkeypatch.delenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", raising=False)


def test_explicit_url_always_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_RESIDENT_PORTAL_URL", "https://meetings.example.gov")
    preview = build_resident_preview()
    assert preview.status == "available"
    assert preview.public_url == "https://meetings.example.gov"


def test_packaged_station_without_explicit_url_uses_its_own_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A packaged station (CIVICCAST_PUBLIC_PORTAL_DIST set, matching
    civiccast.app._mount_packaged_portals) serves the real resident portal
    at its own control-plane origin -- never the Vite dev-server port."""

    monkeypatch.setenv("CIVICCAST_PUBLIC_PORTAL_DIST", r"C:\CivicCast\portal-public\dist")
    preview = build_resident_preview()
    assert preview.status == "available"
    assert preview.public_url == "http://127.0.0.1:8000/"
    assert "5174" not in preview.public_url


def test_packaged_station_honors_local_media_base_url_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_PORTAL_DIST", r"C:\CivicCast\portal-public\dist")
    monkeypatch.setenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", "http://127.0.0.1:9000")
    preview = build_resident_preview()
    assert preview.public_url == "http://127.0.0.1:9000/"


def test_unpackaged_station_without_explicit_url_is_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No packaged portal and no explicit URL: honestly not_configured,
    with a dev-only fallback URL that is never claimed as "available"."""

    preview = build_resident_preview()
    assert preview.status == "not_configured"
    assert preview.public_url == "http://127.0.0.1:5174"
    assert "packaged public portal" in preview.message
