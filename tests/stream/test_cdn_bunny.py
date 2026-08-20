# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.stream.cdn.bunny — BunnyCDN adapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from civiccast.stream.cdn import CDNAdapter
from civiccast.stream.cdn.bunny import BunnyCDNAdapter, BunnyCDNError
from civiccast.stream.cdn.stub import StubCDNAdapter


class TestBunnyCDNAdapterInit:
    def test_raises_on_missing_credentials(self) -> None:
        with pytest.raises(ValueError, match="storage_zone_name"):
            BunnyCDNAdapter(storage_zone_name="", access_key="key", cdn_hostname="host")

    def test_accepts_valid_credentials(self) -> None:
        adapter = BunnyCDNAdapter(
            storage_zone_name="myzone",
            access_key="abc123",
            cdn_hostname="myzone.b-cdn.net",
        )
        assert isinstance(adapter, BunnyCDNAdapter)

    def test_implements_cdn_adapter_protocol(self) -> None:
        adapter = BunnyCDNAdapter(
            storage_zone_name="myzone",
            access_key="abc123",
            cdn_hostname="myzone.b-cdn.net",
        )
        assert isinstance(adapter, CDNAdapter)


class TestBunnyCDNPublicUrl:
    def setup_method(self) -> None:
        self.adapter = BunnyCDNAdapter(
            storage_zone_name="myzone",
            access_key="abc123",
            cdn_hostname="myzone.b-cdn.net",
        )

    def test_builds_https_url(self) -> None:
        url = self.adapter.public_url("assets/video/playlist.m3u8")
        assert url == "https://myzone.b-cdn.net/assets/video/playlist.m3u8"

    def test_strips_trailing_slash_from_hostname(self) -> None:
        adapter = BunnyCDNAdapter(
            storage_zone_name="myzone",
            access_key="abc123",
            cdn_hostname="myzone.b-cdn.net/",
        )
        url = adapter.public_url("test.ts")
        assert not url.startswith("https://myzone.b-cdn.net//")

    def test_strips_leading_slash_from_remote_key(self) -> None:
        # Defensive: a caller passing "/assets/seg.ts" must not produce
        # "https://myzone.b-cdn.net//assets/seg.ts" (double slash, which
        # some CDN edges treat as a different cache key than the slash-
        # normalized variant).
        url = self.adapter.public_url("/assets/seg.ts")
        assert url == "https://myzone.b-cdn.net/assets/seg.ts"


class TestBunnyCDNUploadFile:
    def setup_method(self) -> None:
        self.adapter = BunnyCDNAdapter(
            storage_zone_name="myzone",
            access_key="secret",
            cdn_hostname="myzone.b-cdn.net",
        )

    def test_upload_returns_public_url(self, tmp_path: Path) -> None:
        test_file = tmp_path / "seg000.ts"
        test_file.write_bytes(b"\x00" * 16)

        mock_response = MagicMock()
        mock_response.status_code = 201

        with patch("civiccast.stream.cdn.bunny.httpx.put", return_value=mock_response):
            url = self.adapter.upload_file(test_file, "assets/seg000.ts")

        assert url == "https://myzone.b-cdn.net/assets/seg000.ts"

    def test_upload_raises_on_http_error(self, tmp_path: Path) -> None:
        test_file = tmp_path / "seg000.ts"
        test_file.write_bytes(b"\x00" * 16)

        mock_response = MagicMock()
        mock_response.status_code = 403

        with (
            patch("civiccast.stream.cdn.bunny.httpx.put", return_value=mock_response),
            pytest.raises(BunnyCDNError, match="HTTP 403"),
        ):
            self.adapter.upload_file(test_file, "assets/seg000.ts")

    def test_upload_raises_on_network_error(self, tmp_path: Path) -> None:
        import httpx

        test_file = tmp_path / "seg000.ts"
        test_file.write_bytes(b"\x00" * 16)

        with (
            patch(
                "civiccast.stream.cdn.bunny.httpx.put",
                side_effect=httpx.TransportError("connection reset"),
            ),
            pytest.raises(BunnyCDNError, match="Network error"),
        ):
            self.adapter.upload_file(test_file, "assets/seg000.ts")


class TestBunnyCDNDeleteFile:
    def setup_method(self) -> None:
        self.adapter = BunnyCDNAdapter(
            storage_zone_name="myzone",
            access_key="secret",
            cdn_hostname="myzone.b-cdn.net",
        )

    def test_delete_succeeds_on_204(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 204
        with patch("civiccast.stream.cdn.bunny.httpx.delete", return_value=mock_response):
            self.adapter.delete_file("assets/old.ts")  # no raise

    def test_delete_silent_on_404(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 404
        with patch("civiccast.stream.cdn.bunny.httpx.delete", return_value=mock_response):
            self.adapter.delete_file("assets/missing.ts")  # no raise

    def test_delete_raises_on_unexpected_status(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        with (
            patch("civiccast.stream.cdn.bunny.httpx.delete", return_value=mock_response),
            pytest.raises(BunnyCDNError, match="HTTP 500"),
        ):
            self.adapter.delete_file("assets/bad.ts")


class TestStubCDNAdapter:
    """StubCDNAdapter is used in all non-integration tests instead of real CDN."""

    def test_implements_cdn_adapter_protocol(self, tmp_path: Path) -> None:
        stub = StubCDNAdapter(tmp_path / "cdn_root")
        assert isinstance(stub, CDNAdapter)

    def test_upload_copies_file_to_root(self, tmp_path: Path) -> None:
        root = tmp_path / "cdn"
        stub = StubCDNAdapter(root)
        src = tmp_path / "test.ts"
        src.write_bytes(b"abc")
        stub.upload_file(src, "video/test.ts")
        assert (root / "video" / "test.ts").read_bytes() == b"abc"

    def test_upload_returns_file_uri(self, tmp_path: Path) -> None:
        stub = StubCDNAdapter(tmp_path / "cdn")
        src = tmp_path / "test.ts"
        src.write_bytes(b"abc")
        url = stub.upload_file(src, "video/test.ts")
        assert url.startswith("file://")

    def test_delete_removes_file(self, tmp_path: Path) -> None:
        root = tmp_path / "cdn"
        stub = StubCDNAdapter(root)
        src = tmp_path / "test.ts"
        src.write_bytes(b"x")
        stub.upload_file(src, "video/test.ts")
        assert (root / "video" / "test.ts").exists()
        stub.delete_file("video/test.ts")
        assert not (root / "video" / "test.ts").exists()

    def test_delete_silent_for_nonexistent(self, tmp_path: Path) -> None:
        stub = StubCDNAdapter(tmp_path / "cdn")
        stub.delete_file("does/not/exist.ts")  # no raise

    def test_public_url_returns_file_uri(self, tmp_path: Path) -> None:
        stub = StubCDNAdapter(tmp_path / "cdn")
        url = stub.public_url("video/playlist.m3u8")
        assert url.startswith("file://")
        assert "playlist.m3u8" in url
