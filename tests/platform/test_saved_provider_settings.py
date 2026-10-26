# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Setup values configure real adapters without environment mutation or live claims."""

import os
from pathlib import Path

import pytest

from civiccast.installer.models import ProviderCredentialSetupRequest
from civiccast.installer.service import build_provider_readiness_report, save_provider_credentials
from civiccast.platform.providers import default_registry, describe_provider


@pytest.mark.parametrize(
    "provider_id,kind,values",
    [
        (
            "internet-archive",
            "internet_archive",
            {"access_key": "test-access", "secret_key": "test-secret"},
        ),
        (
            "youtube",
            "youtube",
            {
                "client_id": "test-client",
                "client_secret": "test-secret",
                "refresh_token": "test-refresh",
            },
        ),
        ("local-nas", "local_nas", {}),
        (
            "subscriber-notifications",
            "mail",
            {"smtp_host": "smtp.example.test", "smtp_from": "station@example.test"},
        ),
    ],
)
def test_setup_values_reach_real_adapter_without_env_or_live_proof(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider_id: str,
    kind: str,
    values: dict[str, str],
) -> None:
    for name in list(os.environ):
        if name.startswith("CIVICCAST_PROVIDER_") or name.startswith(
            ("CIVICCAST_YOUTUBE_", "CIVICCAST_IA_", "CIVICCAST_NAS_", "CIVICCAST_SMTP_")
        ):
            monkeypatch.delenv(name)
    monkeypatch.setenv("CIVICCAST_PROVIDER_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    if provider_id == "local-nas":
        values = {"archive_path": str(tmp_path)}
    before = dict(os.environ)
    response = save_provider_credentials(
        ProviderCredentialSetupRequest(provider_id=provider_id, values=values)
    )
    assert os.environ == before
    assert "test-secret" not in response.model_dump_json()
    assert "test-refresh" not in response.model_dump_json()
    registry = default_registry()
    posture = describe_provider(kind, registry)
    assert posture.selected_name == "real" and posture.usable and not posture.simulated
    client = registry.resolve(kind)
    settings = client._settings
    expected_field = {
        "internet_archive": "access_key",
        "youtube": "refresh_token",
        "local_nas": "archive_root",
        "mail": "host",
    }[kind]
    assert (
        getattr(settings, expected_field)
        == (
            {
                "internet_archive": "test-access",
                "youtube": "test-refresh",
                "local_nas": tmp_path,
                "mail": "smtp.example.test",
            }[kind]
        )
    )
    assert os.environ == before
    item = next(item for item in build_provider_readiness_report().items if item.id == provider_id)
    assert item.status == "needs_live_proof"


def test_explicit_mock_selection_is_honest_even_with_saved_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_PROVIDER_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    save_provider_credentials(
        ProviderCredentialSetupRequest(
            provider_id="youtube",
            values={"client_id": "client", "client_secret": "secret", "refresh_token": "refresh"},
        )
    )
    monkeypatch.setenv("CIVICCAST_PROVIDER_YOUTUBE", "mock")
    posture = describe_provider("youtube")
    assert posture.simulated and posture.selected_name == "mock"
    proof = default_registry().resolve("youtube").publish_live(asset_id="meeting")
    assert proof.delivery_state == "simulated" and not proof.confirmed_live


def test_webhook_only_setup_does_not_select_smtp(monkeypatch, tmp_path):
    monkeypatch.delenv("CIVICCAST_PROVIDER_MAIL", raising=False)
    monkeypatch.setenv("CIVICCAST_PROVIDER_CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    save_provider_credentials(
        ProviderCredentialSetupRequest(
            provider_id="subscriber-notifications",
            values={"webhook_secret": "webhook-only-secret", "smtp_host": "", "smtp_from": ""},
        )
    )
    assert describe_provider("mail").selected_name == "mock"
