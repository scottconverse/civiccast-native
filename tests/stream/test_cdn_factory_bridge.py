# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for build_cdn_adapter_from_credentials (setup-wizard creds -> adapter)."""

from __future__ import annotations

import pytest

from civiccast.stream.cdn import CDNAdapter
from civiccast.stream.cdn.bunny import BunnyCDNAdapter
from civiccast.stream.cdn.factory import (
    CDN_CREDENTIAL_PROVIDER_IDS,
    build_cdn_adapter_from_credentials,
)

_BUNNY_FIELDS = {
    "storage_zone_name": "civiccast-zone",
    "access_key": "bunny-secret-key",
    "cdn_hostname": "civiccast.b-cdn.net",
}
_R2_FIELDS = {
    "account_id": "abc123" + "0" * 26,
    "access_key_id": "r2-access",
    "secret_access_key": "r2-secret",
    "bucket": "civiccast-media",
    "public_base_url": "https://cdn.example.org",
}


def test_cdn_credential_provider_ids_are_the_hyphenated_wizard_ids() -> None:
    assert CDN_CREDENTIAL_PROVIDER_IDS == ("cloudflare-r2", "bunny", "fastly", "akamai")


def test_builds_a_bunny_adapter_from_wizard_fields() -> None:
    adapter = build_cdn_adapter_from_credentials("bunny", _BUNNY_FIELDS)
    assert isinstance(adapter, BunnyCDNAdapter)
    assert isinstance(adapter, CDNAdapter)
    assert adapter.public_url("live/seg0.ts") == "https://civiccast.b-cdn.net/live/seg0.ts"


def test_builds_an_r2_adapter_from_wizard_fields() -> None:
    pytest.importorskip("boto3")  # R2 adapter constructs a boto3 client
    from civiccast.stream.cdn.cloudflare_r2 import CloudflareR2Adapter

    adapter = build_cdn_adapter_from_credentials("cloudflare-r2", _R2_FIELDS)
    assert isinstance(adapter, CloudflareR2Adapter)
    assert adapter.public_url("live/seg0.ts") == "https://cdn.example.org/live/seg0.ts"


_FASTLY_FIELDS = {
    "region": "us-east",
    "access_key_id": "fastly-access",
    "secret_access_key": "fastly-secret",
    "bucket": "civiccast-media",
    "public_base_url": "https://cdn.example.org",
}
_AKAMAI_FIELDS = {
    "region": "us-east-1",
    "access_key_id": "akamai-access",
    "secret_access_key": "akamai-secret",
    "bucket": "civiccast-media",
    "public_base_url": "https://cdn.example.org",
}


def test_builds_a_fastly_s3_adapter_from_wizard_fields() -> None:
    pytest.importorskip("boto3")
    from civiccast.stream.cdn.s3_compatible import S3CompatibleCDNAdapter

    adapter = build_cdn_adapter_from_credentials("fastly", _FASTLY_FIELDS)
    assert isinstance(adapter, S3CompatibleCDNAdapter)
    assert adapter.public_url("live/seg0.ts") == "https://cdn.example.org/live/seg0.ts"


def test_builds_an_akamai_s3_adapter_from_wizard_fields() -> None:
    pytest.importorskip("boto3")
    from civiccast.stream.cdn.s3_compatible import S3CompatibleCDNAdapter

    adapter = build_cdn_adapter_from_credentials("akamai", _AKAMAI_FIELDS)
    assert isinstance(adapter, S3CompatibleCDNAdapter)


def test_incomplete_fastly_fields_raise_valueerror_from_the_adapter() -> None:
    # No region -> empty endpoint -> the adapter's incomplete-credentials guard.
    with pytest.raises(ValueError):
        build_cdn_adapter_from_credentials("fastly", {"bucket": "only-one"})


def test_malformed_region_is_rejected_to_prevent_host_injection() -> None:
    # A region with '/' would redirect the endpoint host; must be rejected, not
    # formatted into "https://us-east/evil.example.com.object.fastlystorage.app".
    with pytest.raises(ValueError, match="region must match"):
        build_cdn_adapter_from_credentials(
            "fastly", {**_FASTLY_FIELDS, "region": "us-east/evil.example.com"}
        )


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError, match="CDN credential provider"):
        build_cdn_adapter_from_credentials("youtube", {"client_id": "x"})


def test_incomplete_bunny_fields_raise_valueerror_from_the_adapter() -> None:
    with pytest.raises(ValueError):
        build_cdn_adapter_from_credentials("bunny", {"storage_zone_name": "only-one"})
