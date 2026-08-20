# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the generic S3-compatible CDN adapter (Fastly / Akamai origins).

Uses moto's in-process mock S3 -- no real Fastly/Akamai account or network.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

boto3 = pytest.importorskip("boto3")
moto = pytest.importorskip("moto")

from moto import mock_aws  # noqa: E402

from civiccast.stream.cdn import CDNAdapter  # noqa: E402
from civiccast.stream.cdn.s3_compatible import (  # noqa: E402
    S3CompatibleCDNAdapter,
    _guess_content_type,
)

_ENDPOINT = "https://us-east.object.fastlystorage.app"
_ACCESS_KEY = "s3_test_access_key"
_SECRET_KEY = "s3_test_secret_key_value"
_BUCKET = "civiccast-test-bucket"
_PUBLIC_BASE = "https://cdn.example.org"


@pytest.fixture
def s3_adapter() -> Iterator[S3CompatibleCDNAdapter]:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=_BUCKET)
        yield S3CompatibleCDNAdapter(
            endpoint_url=_ENDPOINT,
            access_key_id=_ACCESS_KEY,
            secret_access_key=_SECRET_KEY,
            bucket=_BUCKET,
            public_base_url=_PUBLIC_BASE,
            _client=s3,
        )


# --- protocol conformance ----------------------------------------------------


def test_satisfies_the_cdn_adapter_protocol(s3_adapter: S3CompatibleCDNAdapter) -> None:
    assert isinstance(s3_adapter, CDNAdapter)


# --- upload / public_url / delete --------------------------------------------


def test_upload_returns_public_url_and_stores_the_object(
    s3_adapter: S3CompatibleCDNAdapter, tmp_path: Path
) -> None:
    seg = tmp_path / "seg000000001.ts"
    seg.write_bytes(b"x" * 2048)

    url = s3_adapter.upload_file(seg, "live/gov-ch12/seg000000001.ts")

    assert url == "https://cdn.example.org/live/gov-ch12/seg000000001.ts"
    body = s3_adapter._client.get_object(Bucket=_BUCKET, Key="live/gov-ch12/seg000000001.ts")
    assert body["Body"].read() == b"x" * 2048
    assert body["ContentType"] == "video/mp2t"
    assert "immutable" in body["CacheControl"]  # segments cache long


def test_upload_sets_short_cache_control_on_the_manifest(
    s3_adapter: S3CompatibleCDNAdapter, tmp_path: Path
) -> None:
    # The churning live playlist must not inherit the edge's default (long) TTL.
    manifest = tmp_path / "playlist.m3u8"
    manifest.write_text("#EXTM3U\n", encoding="utf-8")

    s3_adapter.upload_file(manifest, "live/gov-ch12/playlist.m3u8")

    stored = s3_adapter._client.get_object(Bucket=_BUCKET, Key="live/gov-ch12/playlist.m3u8")
    assert stored["CacheControl"] == "max-age=1"


def test_public_url_does_not_require_upload(s3_adapter: S3CompatibleCDNAdapter) -> None:
    assert s3_adapter.public_url("/a/b.m3u8") == "https://cdn.example.org/a/b.m3u8"


def test_delete_is_a_silent_noop_when_absent(s3_adapter: S3CompatibleCDNAdapter) -> None:
    s3_adapter.delete_file("never/written.ts")  # must not raise


def test_delete_removes_an_existing_object(
    s3_adapter: S3CompatibleCDNAdapter, tmp_path: Path
) -> None:
    from botocore.exceptions import ClientError

    seg = tmp_path / "s.ts"
    seg.write_bytes(b"y" * 16)
    s3_adapter.upload_file(seg, "k.ts")
    s3_adapter.delete_file("k.ts")
    with pytest.raises(ClientError):
        # Upload succeeded then delete removed it; a fresh get now 404s.
        s3_adapter._client.get_object(Bucket=_BUCKET, Key="k.ts")


# --- health_check ------------------------------------------------------------


def test_health_check_true_when_bucket_reachable(s3_adapter: S3CompatibleCDNAdapter) -> None:
    assert s3_adapter.health_check() is True


def test_health_check_false_when_bucket_missing(s3_adapter: S3CompatibleCDNAdapter) -> None:
    missing = S3CompatibleCDNAdapter(
        endpoint_url=_ENDPOINT,
        access_key_id=_ACCESS_KEY,
        secret_access_key=_SECRET_KEY,
        bucket="no-such-bucket",
        public_base_url=_PUBLIC_BASE,
        _client=s3_adapter._client,
    )
    assert missing.health_check() is False


# --- validation --------------------------------------------------------------


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="requires endpoint_url"):
        S3CompatibleCDNAdapter(
            endpoint_url=_ENDPOINT,
            access_key_id="",
            secret_access_key=_SECRET_KEY,
            bucket=_BUCKET,
            public_base_url=_PUBLIC_BASE,
            _client=object(),
        )


def test_non_https_endpoint_is_rejected() -> None:
    with pytest.raises(ValueError, match="endpoint_url must start with https"):
        S3CompatibleCDNAdapter(
            endpoint_url="http://insecure.example",
            access_key_id=_ACCESS_KEY,
            secret_access_key=_SECRET_KEY,
            bucket=_BUCKET,
            public_base_url=_PUBLIC_BASE,
            _client=object(),
        )


def test_non_https_public_base_url_is_rejected() -> None:
    with pytest.raises(ValueError, match="public_base_url must start with https"):
        S3CompatibleCDNAdapter(
            endpoint_url=_ENDPOINT,
            access_key_id=_ACCESS_KEY,
            secret_access_key=_SECRET_KEY,
            bucket=_BUCKET,
            public_base_url="http://cdn.example.org",
            _client=object(),
        )


def test_guess_content_type_covers_hls() -> None:
    assert _guess_content_type("x/seg.ts") == "video/mp2t"
    assert _guess_content_type("x/playlist.m3u8") == "application/vnd.apple.mpegurl"
    assert _guess_content_type("x/thing.bin") == "application/octet-stream"
