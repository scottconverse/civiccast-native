# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the CDN credential bridge (stored setup-wizard creds -> live adapter)."""

from __future__ import annotations

import json
import types
from pathlib import Path

import httpx
import pytest

from civiccast.installer.cdn_bridge import check_provider_connection, resolve_stored_cdn_adapter
from civiccast.stream.cdn.bunny import BunnyCDNAdapter

_BUNNY = {
    "storage_zone_name": "civiccast-zone",
    "access_key": "bunny-secret-key",
    "cdn_hostname": "civiccast.b-cdn.net",
}


def _store_creds(path: Path, provider_id: str, fields: dict[str, str]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "providers": {
                    provider_id: {"saved_at": "2026-01-01T00:00:00+00:00", "fields": fields}
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def creds_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "provider-credentials.json"
    monkeypatch.setenv("CIVICCAST_PROVIDER_CREDENTIALS_FILE", str(path))
    return path


# --- resolve_stored_cdn_adapter ----------------------------------------------


def test_resolve_returns_none_when_nothing_is_stored(creds_file: Path) -> None:
    assert resolve_stored_cdn_adapter() is None


def test_resolve_builds_adapter_from_stored_bunny_credentials(creds_file: Path) -> None:
    _store_creds(creds_file, "bunny", _BUNNY)
    assert isinstance(resolve_stored_cdn_adapter(), BunnyCDNAdapter)


# --- check_provider_connection ------------------------------------------------


def test_connection_test_requires_saved_credentials(creds_file: Path) -> None:
    with pytest.raises(ValueError, match="Save the provider credentials"):
        check_provider_connection("bunny")


def test_connection_test_rejects_a_non_cdn_provider(creds_file: Path) -> None:
    with pytest.raises(ValueError, match="not a CDN provider"):
        check_provider_connection("youtube")


def test_connection_test_ok_when_provider_is_reachable(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store_creds(creds_file, "bunny", _BUNNY)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: types.SimpleNamespace(status_code=200))
    result = check_provider_connection("bunny")
    assert result.provider_id == "bunny"
    assert result.status == "ok"
    assert _BUNNY["access_key"] not in result.message  # never echoes the secret


def test_connection_test_failed_when_provider_unreachable(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store_creds(creds_file, "bunny", _BUNNY)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: types.SimpleNamespace(status_code=401))
    result = check_provider_connection("bunny")
    assert result.status == "failed"
    assert _BUNNY["access_key"] not in result.message


def test_connection_test_failed_when_saved_credentials_incomplete(creds_file: Path) -> None:
    _store_creds(creds_file, "cloudflare-r2", {"account_id": "only-one-field"})
    result = check_provider_connection("cloudflare-r2")
    assert result.status == "failed"
    assert "incomplete" in result.message.lower()


def test_connection_test_reports_missing_s3_extra_gracefully(
    creds_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # When boto3/the s3-cdn extra is absent, the S3 adapter raises
    # S3CDNNotInstalledError (a RuntimeError, not ValueError). The connection
    # test must render that as a safe "failed" response, not a raw 500.
    import civiccast.installer.cdn_bridge as bridge
    from civiccast.stream.cdn.s3_compatible import S3CDNNotInstalledError

    _store_creds(
        creds_file,
        "fastly",
        {
            "region": "us-east",
            "access_key_id": "k",
            "secret_access_key": "s",
            "bucket": "b",
            "public_base_url": "https://cdn.example.org",
        },
    )

    def _raise(*_a: object, **_k: object) -> object:
        raise S3CDNNotInstalledError("boto3 missing")

    monkeypatch.setattr(bridge, "build_cdn_adapter_from_credentials", _raise)
    result = check_provider_connection("fastly")
    assert result.status == "failed"
    assert "s3-cdn" in result.message


# --- all four CDNs are portal-enterable + resolvable --------------------------


def test_readiness_report_includes_every_cdn_provider_card(creds_file: Path) -> None:
    from civiccast.installer.service import build_provider_readiness_report

    report = build_provider_readiness_report()
    ids = {item.id for item in report.items}
    assert {"cloudflare-r2", "bunny", "fastly", "akamai"} <= ids

    fastly = next(item for item in report.items if item.id == "fastly")
    assert {f.id for f in fastly.credential_fields} == {
        "region",
        "access_key_id",
        "secret_access_key",
        "bucket",
        "public_base_url",
    }


def test_save_then_resolve_fastly_credentials(creds_file: Path) -> None:
    pytest.importorskip("boto3")
    from civiccast.installer.models import ProviderCredentialSetupRequest
    from civiccast.installer.service import save_provider_credentials
    from civiccast.stream.cdn.s3_compatible import S3CompatibleCDNAdapter

    save_provider_credentials(
        ProviderCredentialSetupRequest(
            provider_id="fastly",
            values={
                "region": "us-east",
                "access_key_id": "k",
                "secret_access_key": "s",
                "bucket": "b",
                "public_base_url": "https://cdn.example.org",
            },
        )
    )
    assert isinstance(resolve_stored_cdn_adapter(), S3CompatibleCDNAdapter)
