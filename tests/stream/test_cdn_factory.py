# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Config-driven CDN selector tests (Stage C).

ADR 0006 promised "the active adapter is selected by the cdn.provider config
key"; until this stage nothing read any such key and the CLI hard-instantiated
the R2 adapter. The factory reads ``CIVICCAST_CDN_PROVIDER`` and constructs
the selected adapter from its provider-specific credential variables, failing
fast with actionable errors.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.stream.cdn.factory import (
    CDN_PROVIDERS,
    CdnSettings,
    build_cdn_adapter,
)
from civiccast.stream.cdn.stub import StubCDNAdapter

_ALL_CDN_ENV = (
    "CIVICCAST_CDN_PROVIDER",
    "CIVICCAST_CDN_STUB_ROOT",
    "CIVICCAST_BUNNY_STORAGE_ZONE",
    "CIVICCAST_BUNNY_ACCESS_KEY",
    "CIVICCAST_BUNNY_CDN_HOSTNAME",
    "CIVICCAST_R2_ACCOUNT_ID",
    "CIVICCAST_R2_ACCESS_KEY_ID",
    "CIVICCAST_R2_SECRET_ACCESS_KEY",
    "CIVICCAST_R2_BUCKET",
    "CIVICCAST_R2_PUBLIC_BASE_URL",
    "CIVICCAST_FASTLY_REGION",
    "CIVICCAST_FASTLY_ACCESS_KEY_ID",
    "CIVICCAST_FASTLY_SECRET_ACCESS_KEY",
    "CIVICCAST_FASTLY_BUCKET",
    "CIVICCAST_FASTLY_PUBLIC_BASE_URL",
    "CIVICCAST_AKAMAI_REGION",
    "CIVICCAST_AKAMAI_ACCESS_KEY_ID",
    "CIVICCAST_AKAMAI_SECRET_ACCESS_KEY",
    "CIVICCAST_AKAMAI_BUCKET",
    "CIVICCAST_AKAMAI_PUBLIC_BASE_URL",
)


@pytest.fixture(autouse=True)
def _clean_cdn_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _ALL_CDN_ENV:
        monkeypatch.delenv(name, raising=False)


class TestCdnSettings:
    def test_default_is_off(self) -> None:
        settings = CdnSettings.from_env()
        assert settings.provider == "off"

    def test_explicit_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "off")
        assert CdnSettings.from_env().provider == "off"

    def test_invalid_provider_fails_fast_listing_valid_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "banana")
        with pytest.raises(ValueError, match="CIVICCAST_CDN_PROVIDER") as excinfo:
            CdnSettings.from_env()
        for provider in CDN_PROVIDERS:
            assert provider in str(excinfo.value)

    def test_direct_construction_with_invalid_provider_fails(self) -> None:
        # __post_init__ guards every construction path, not just from_env().
        with pytest.raises(ValueError, match="CIVICCAST_CDN_PROVIDER"):
            CdnSettings(provider="banana")


class TestBuildCdnAdapter:
    def test_off_builds_none(self) -> None:
        assert build_cdn_adapter(CdnSettings.from_env()) is None

    def test_stub_requires_root(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "stub")
        with pytest.raises(ValueError, match="CIVICCAST_CDN_STUB_ROOT"):
            build_cdn_adapter(CdnSettings.from_env())

    def test_stub_builds_stub_adapter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "stub")
        monkeypatch.setenv("CIVICCAST_CDN_STUB_ROOT", str(tmp_path))
        adapter = build_cdn_adapter(CdnSettings.from_env())
        assert isinstance(adapter, StubCDNAdapter)
        assert adapter.public_url("a/b.m3u8") == (tmp_path / "a/b.m3u8").as_uri()

    def test_bunny_builds_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.stream.cdn.bunny import BunnyCDNAdapter

        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "bunny")
        monkeypatch.setenv("CIVICCAST_BUNNY_STORAGE_ZONE", "test-zone")
        monkeypatch.setenv("CIVICCAST_BUNNY_ACCESS_KEY", "test-access-key")
        monkeypatch.setenv("CIVICCAST_BUNNY_CDN_HOSTNAME", "test.b-cdn.net")
        adapter = build_cdn_adapter(CdnSettings.from_env())
        assert isinstance(adapter, BunnyCDNAdapter)
        assert adapter.public_url("x/y.m3u8") == "https://test.b-cdn.net/x/y.m3u8"

    def test_bunny_missing_credentials_fails_naming_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "bunny")
        monkeypatch.setenv("CIVICCAST_BUNNY_STORAGE_ZONE", "test-zone")
        with pytest.raises(ValueError) as excinfo:
            build_cdn_adapter(CdnSettings.from_env())
        assert "CIVICCAST_BUNNY_ACCESS_KEY" in str(excinfo.value)
        assert "CIVICCAST_BUNNY_CDN_HOSTNAME" in str(excinfo.value)

    def test_cloudflare_r2_missing_credentials_fails_naming_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "cloudflare_r2")
        monkeypatch.setenv("CIVICCAST_R2_BUCKET", "civic-bucket")
        with pytest.raises(ValueError) as excinfo:
            build_cdn_adapter(CdnSettings.from_env())
        assert "CIVICCAST_R2_ACCOUNT_ID" in str(excinfo.value)

    def test_cloudflare_r2_builds_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        boto3 = pytest.importorskip("boto3", reason="cloudflare-r2 extra not installed")
        assert boto3 is not None
        from civiccast.stream.cdn.cloudflare_r2 import CloudflareR2Adapter

        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "cloudflare_r2")
        monkeypatch.setenv("CIVICCAST_R2_ACCOUNT_ID", "a" * 32)
        monkeypatch.setenv("CIVICCAST_R2_ACCESS_KEY_ID", "key-id")
        monkeypatch.setenv("CIVICCAST_R2_SECRET_ACCESS_KEY", "key-secret")
        monkeypatch.setenv("CIVICCAST_R2_BUCKET", "civic-bucket")
        monkeypatch.setenv("CIVICCAST_R2_PUBLIC_BASE_URL", "https://media.example.org")
        adapter = build_cdn_adapter(CdnSettings.from_env())
        assert isinstance(adapter, CloudflareR2Adapter)

    def test_fastly_builds_s3_adapter_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("boto3", reason="s3-cdn extra not installed")
        from civiccast.stream.cdn.s3_compatible import S3CompatibleCDNAdapter

        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "fastly")
        monkeypatch.setenv("CIVICCAST_FASTLY_REGION", "us-east")
        monkeypatch.setenv("CIVICCAST_FASTLY_ACCESS_KEY_ID", "key-id")
        monkeypatch.setenv("CIVICCAST_FASTLY_SECRET_ACCESS_KEY", "key-secret")
        monkeypatch.setenv("CIVICCAST_FASTLY_BUCKET", "civic-bucket")
        monkeypatch.setenv("CIVICCAST_FASTLY_PUBLIC_BASE_URL", "https://media.example.org")
        adapter = build_cdn_adapter(CdnSettings.from_env())
        assert isinstance(adapter, S3CompatibleCDNAdapter)
        assert adapter.public_url("x/y.ts") == "https://media.example.org/x/y.ts"

    def test_akamai_builds_s3_adapter_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("boto3", reason="s3-cdn extra not installed")
        from civiccast.stream.cdn.s3_compatible import S3CompatibleCDNAdapter

        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "akamai")
        monkeypatch.setenv("CIVICCAST_AKAMAI_REGION", "us-east-1")
        monkeypatch.setenv("CIVICCAST_AKAMAI_ACCESS_KEY_ID", "key-id")
        monkeypatch.setenv("CIVICCAST_AKAMAI_SECRET_ACCESS_KEY", "key-secret")
        monkeypatch.setenv("CIVICCAST_AKAMAI_BUCKET", "civic-bucket")
        monkeypatch.setenv("CIVICCAST_AKAMAI_PUBLIC_BASE_URL", "https://media.example.org")
        adapter = build_cdn_adapter(CdnSettings.from_env())
        assert isinstance(adapter, S3CompatibleCDNAdapter)

    def test_fastly_missing_credentials_fails_naming_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "fastly")
        monkeypatch.setenv("CIVICCAST_FASTLY_BUCKET", "civic-bucket")
        with pytest.raises(ValueError) as excinfo:
            build_cdn_adapter(CdnSettings.from_env())
        assert "CIVICCAST_FASTLY_REGION" in str(excinfo.value)
        assert "CIVICCAST_FASTLY_ACCESS_KEY_ID" in str(excinfo.value)

    def test_s3_endpoint_templates_match_provider_formats(self) -> None:
        from civiccast.stream.cdn.factory import _AKAMAI_ENDPOINT, _FASTLY_ENDPOINT

        assert (
            _FASTLY_ENDPOINT.format(region="us-east") == "https://us-east.object.fastlystorage.app"
        )
        assert _AKAMAI_ENDPOINT.format(region="us-east-1") == "https://us-east-1.linodeobjects.com"

    def test_fastly_malformed_region_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "fastly")
        monkeypatch.setenv("CIVICCAST_FASTLY_REGION", "us-east/evil.example.com")
        monkeypatch.setenv("CIVICCAST_FASTLY_ACCESS_KEY_ID", "k")
        monkeypatch.setenv("CIVICCAST_FASTLY_SECRET_ACCESS_KEY", "s")
        monkeypatch.setenv("CIVICCAST_FASTLY_BUCKET", "b")
        monkeypatch.setenv("CIVICCAST_FASTLY_PUBLIC_BASE_URL", "https://cdn.example.org")
        with pytest.raises(ValueError, match="region must match"):
            build_cdn_adapter(CdnSettings.from_env())


class TestAppWiring:
    def test_invalid_cdn_provider_fails_app_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.app import create_app

        monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "banana")
        with pytest.raises(ValueError, match="CIVICCAST_CDN_PROVIDER"):
            create_app()

    def test_selected_provider_with_missing_credentials_fails_app_startup(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from civiccast.app import create_app

        monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "bunny")
        with pytest.raises(ValueError, match="CIVICCAST_BUNNY_"):
            create_app()

    def test_app_exposes_resolver_for_selected_adapter(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from civiccast.app import create_app

        monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "stub")
        monkeypatch.setenv("CIVICCAST_CDN_STUB_ROOT", str(tmp_path))
        app = create_app()
        adapter = app.state.resolve_cdn_adapter()
        assert isinstance(adapter, StubCDNAdapter)

    def test_app_resolver_returns_none_when_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.app import create_app

        monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
        app = create_app()
        assert app.state.resolve_cdn_adapter() is None
