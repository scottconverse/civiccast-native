# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the CloudflareR2Adapter CDN backend.

Per ADR 0006: Cloudflare R2 is the documented DDoS-protection alternate
to the BunnyCDN default. The adapter speaks S3 v4, so coverage uses
moto to spin up an in-process mock S3 service — no real Cloudflare
account or network access required.

Closes the Sprint 0.2 next-cleanup item that flagged R2 as ADR-named
but unshipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# moto + boto3 are pulled in via the dev group (and via the
# ``cloudflare-r2`` optional extra for production installs).
boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from moto import mock_aws  # noqa: E402  (after importorskip)

from civiccast.stream.cdn import CDNAdapter  # noqa: E402
from civiccast.stream.cdn.cloudflare_r2 import (  # noqa: E402
    CloudflareR2Adapter,
    CloudflareR2Error,
    _guess_content_type,
)

_ACCOUNT_ID = "abc123" + "0" * 26  # 32-char hex stand-in
_ACCESS_KEY = "ck_test_access_key"
_SECRET_KEY = "ck_test_secret_key_value"
_BUCKET = "civiccast-test-bucket"
_PUBLIC_BASE = "https://cdn.example.org"


@pytest.fixture
def r2_adapter(monkeypatch: pytest.MonkeyPatch):
    """Yield a CloudflareR2Adapter wired to moto's mock S3 service.

    moto patches boto3 globally during ``mock_aws()``, so the adapter's
    boto3 client transparently routes to the in-process mock instead of
    Cloudflare's real endpoint. The mock pre-creates the bucket the
    adapter expects so health_check + upload + delete all hit a real
    S3-shaped state machine.
    """
    with mock_aws():
        # moto's mock S3 ignores endpoint_url; bucket creation goes to
        # the global mock service, then the adapter's client (also
        # patched by moto) sees it.
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=_BUCKET)

        adapter = CloudflareR2Adapter(
            account_id=_ACCOUNT_ID,
            access_key_id=_ACCESS_KEY,
            secret_access_key=_SECRET_KEY,
            bucket=_BUCKET,
            public_base_url=_PUBLIC_BASE,
            _client=s3,
        )
        yield adapter


# ---------------------------------------------------------------------------
# TestProtocolConformance
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """Locks: CloudflareR2Adapter satisfies the @runtime_checkable
    CDNAdapter Protocol used elsewhere in civiccast.stream."""

    def test_satisfies_cdn_adapter_protocol(self, r2_adapter: CloudflareR2Adapter) -> None:
        assert isinstance(r2_adapter, CDNAdapter)
        assert callable(r2_adapter.upload_file)
        assert callable(r2_adapter.delete_file)
        assert callable(r2_adapter.public_url)


# ---------------------------------------------------------------------------
# TestConstructorValidation
# ---------------------------------------------------------------------------


class TestConstructorValidation:
    """Locks: missing or insecure config raises before any network call."""

    def test_missing_account_id_raises(self) -> None:
        with mock_aws(), pytest.raises(ValueError, match="account_id"):
            CloudflareR2Adapter(
                account_id="",
                access_key_id=_ACCESS_KEY,
                secret_access_key=_SECRET_KEY,
                bucket=_BUCKET,
                public_base_url=_PUBLIC_BASE,
            )

    def test_http_public_base_url_rejected(self) -> None:
        with mock_aws(), pytest.raises(ValueError, match="https"):
            CloudflareR2Adapter(
                account_id=_ACCOUNT_ID,
                access_key_id=_ACCESS_KEY,
                secret_access_key=_SECRET_KEY,
                bucket=_BUCKET,
                public_base_url="http://insecure.example.org",
            )


# ---------------------------------------------------------------------------
# TestUploadFile
# ---------------------------------------------------------------------------


class TestUploadFile:
    """Locks: upload_file PUTs to R2 and returns the public URL."""

    def test_uploads_and_returns_public_url(
        self, r2_adapter: CloudflareR2Adapter, tmp_path: Path
    ) -> None:
        local = tmp_path / "playlist.m3u8"
        # write_bytes (not write_text) so Windows checkouts don't translate
        # \n into \r\n and trip the byte-equal assertion below.
        local.write_bytes(b"#EXTM3U\n#EXT-X-VERSION:3\n")

        url = r2_adapter.upload_file(local, "council-2026-05-08/playlist.m3u8")

        assert url == f"{_PUBLIC_BASE}/council-2026-05-08/playlist.m3u8"

        # Confirm the object actually landed in the mock bucket.
        s3 = boto3.client("s3", region_name="us-east-1")
        body = s3.get_object(Bucket=_BUCKET, Key="council-2026-05-08/playlist.m3u8")["Body"].read()
        assert body == b"#EXTM3U\n#EXT-X-VERSION:3\n"

    def test_strips_leading_slash_from_remote_key(
        self, r2_adapter: CloudflareR2Adapter, tmp_path: Path
    ) -> None:
        local = tmp_path / "seg000.ts"
        local.write_bytes(b"\x00\x00")

        url = r2_adapter.upload_file(local, "/foo/bar/seg000.ts")

        assert url == f"{_PUBLIC_BASE}/foo/bar/seg000.ts"
        assert "//foo" not in url

    def test_sets_content_type_for_m3u8(
        self, r2_adapter: CloudflareR2Adapter, tmp_path: Path
    ) -> None:
        local = tmp_path / "playlist.m3u8"
        local.write_text("#EXTM3U\n", encoding="utf-8")
        r2_adapter.upload_file(local, "x/playlist.m3u8")

        s3 = boto3.client("s3", region_name="us-east-1")
        head = s3.head_object(Bucket=_BUCKET, Key="x/playlist.m3u8")
        assert head["ContentType"] == "application/vnd.apple.mpegurl"
        # The churning live playlist must not inherit R2's default TTL.
        assert head["CacheControl"] == "max-age=1"

    def test_sets_immutable_cache_control_for_segments(
        self, r2_adapter: CloudflareR2Adapter, tmp_path: Path
    ) -> None:
        local = tmp_path / "seg000000001.ts"
        local.write_bytes(b"\x00" * 64)
        r2_adapter.upload_file(local, "x/seg000000001.ts")

        s3 = boto3.client("s3", region_name="us-east-1")
        head = s3.head_object(Bucket=_BUCKET, Key="x/seg000000001.ts")
        assert "immutable" in head["CacheControl"]

    def test_raises_on_missing_bucket(self, tmp_path: Path) -> None:
        local = tmp_path / "x.ts"
        local.write_bytes(b"\x00")

        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            # Intentionally do NOT create the bucket — upload_file should fail
            adapter = CloudflareR2Adapter(
                account_id=_ACCOUNT_ID,
                access_key_id=_ACCESS_KEY,
                secret_access_key=_SECRET_KEY,
                bucket="nonexistent-bucket-civiccast",
                public_base_url=_PUBLIC_BASE,
                _client=s3,
            )
            with pytest.raises(CloudflareR2Error):
                adapter.upload_file(local, "x.ts")


# ---------------------------------------------------------------------------
# TestDeleteFile
# ---------------------------------------------------------------------------


class TestDeleteFile:
    """Locks: delete_file removes objects and is silent on missing keys."""

    def test_deletes_existing_object(self, r2_adapter: CloudflareR2Adapter, tmp_path: Path) -> None:
        local = tmp_path / "x.ts"
        local.write_bytes(b"\x00")
        r2_adapter.upload_file(local, "to-delete/x.ts")

        s3 = boto3.client("s3", region_name="us-east-1")
        # Sanity: object exists pre-delete.
        s3.head_object(Bucket=_BUCKET, Key="to-delete/x.ts")

        r2_adapter.delete_file("to-delete/x.ts")

        from botocore.exceptions import ClientError

        with pytest.raises(ClientError):
            s3.head_object(Bucket=_BUCKET, Key="to-delete/x.ts")

    def test_silent_on_nonexistent_key(self, r2_adapter: CloudflareR2Adapter) -> None:
        # moto's S3 actually returns 204 for DELETE of a missing key (S3
        # does the same), so this is a happy-path. The adapter still
        # explicitly traps NoSuchKey for any provider that returns 404.
        r2_adapter.delete_file("never-existed.ts")  # must not raise


# ---------------------------------------------------------------------------
# TestPublicUrl
# ---------------------------------------------------------------------------


class TestPublicUrl:
    """Locks: public_url synthesizes URLs deterministically without any
    network call. Used by the packager to pre-compute manifest URLs."""

    def test_returns_base_plus_key(self, r2_adapter: CloudflareR2Adapter) -> None:
        url = r2_adapter.public_url("council-2026-05-08/playlist.m3u8")
        assert url == f"{_PUBLIC_BASE}/council-2026-05-08/playlist.m3u8"

    def test_strips_leading_slash(self, r2_adapter: CloudflareR2Adapter) -> None:
        url = r2_adapter.public_url("/foo/bar")
        assert url == f"{_PUBLIC_BASE}/foo/bar"


# ---------------------------------------------------------------------------
# TestHealthCheck (doctor connectivity probe)
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Locks: health_check returns True for a reachable bucket and False
    on every error mode (invalid creds, missing bucket, network error)."""

    def test_returns_true_for_reachable_bucket(self, r2_adapter: CloudflareR2Adapter) -> None:
        assert r2_adapter.health_check() is True

    def test_returns_false_for_missing_bucket(self) -> None:
        with mock_aws():
            s3 = boto3.client("s3", region_name="us-east-1")
            adapter = CloudflareR2Adapter(
                account_id=_ACCOUNT_ID,
                access_key_id=_ACCESS_KEY,
                secret_access_key=_SECRET_KEY,
                bucket="this-bucket-was-never-created",
                public_base_url=_PUBLIC_BASE,
                _client=s3,
            )
            assert adapter.health_check() is False


# ---------------------------------------------------------------------------
# TestContentType
# ---------------------------------------------------------------------------


class TestContentType:
    """Locks: _guess_content_type returns the right MIME for HLS."""

    def test_m3u8_is_apple_mpegurl(self) -> None:
        assert _guess_content_type("foo/bar/playlist.m3u8") == "application/vnd.apple.mpegurl"

    def test_ts_is_mp2t(self) -> None:
        assert _guess_content_type("foo/seg001.ts") == "video/mp2t"

    def test_unknown_falls_back_to_octet_stream(self) -> None:
        assert _guess_content_type("foo.unknownext") == "application/octet-stream"

    def test_case_insensitive_extension(self) -> None:
        assert _guess_content_type("FOO.M3U8") == "application/vnd.apple.mpegurl"
