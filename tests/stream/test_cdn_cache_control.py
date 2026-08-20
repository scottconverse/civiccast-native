# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The CDN cache-control policy: manifests must not be cached like segments.

A live HLS playlist is rewritten every ~2s; a CDN edge caching it with its
default TTL (minutes to hours) would serve a stale manifest pointing at a
segment the origin has already evicted -- stalling every CDN viewer. Segments,
by contrast, are immutable and should cache for the whole broadcast.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from civiccast.stream.cdn import cache_control
from civiccast.stream.cdn.bunny import BunnyCDNAdapter


def test_manifest_gets_a_tiny_max_age() -> None:
    assert cache_control("live/gov-ch12/playlist.m3u8") == "max-age=1"


def test_segment_gets_a_long_immutable_max_age() -> None:
    value = cache_control("live/gov-ch12/seg000000001.ts")
    assert "immutable" in value
    assert "31536000" in value


def test_unknown_extension_defaults_to_immutable() -> None:
    # Anything that is not a playlist is treated as an immutable asset.
    assert "immutable" in cache_control("live/gov-ch12/init.mp4")


def test_bunny_upload_sets_cache_control_per_key(tmp_path: Path) -> None:
    adapter = BunnyCDNAdapter(
        storage_zone_name="myzone", access_key="secret", cdn_hostname="myzone.b-cdn.net"
    )
    payload = tmp_path / "f"
    payload.write_bytes(b"\x00" * 16)
    ok = MagicMock(status_code=201)

    with patch("civiccast.stream.cdn.bunny.httpx.put", return_value=ok) as put:
        adapter.upload_file(payload, "live/ch/playlist.m3u8")
        assert put.call_args.kwargs["headers"]["Cache-Control"] == "max-age=1"

        adapter.upload_file(payload, "live/ch/seg000000001.ts")
        assert "immutable" in put.call_args.kwargs["headers"]["Cache-Control"]
