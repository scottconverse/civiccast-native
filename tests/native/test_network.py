# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Network exposure configuration contracts for the native station."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from civiccast.native.network import (
    NetworkSettings,
    NetworkSettingsStore,
    default_network_settings_path,
    render_caddyfile,
)


def caddy_settings(**overrides: object) -> NetworkSettings:
    values: dict[str, object] = {
        "mode": "caddy",
        "public_base_url": "https://watch.example.gov",
        "staff_hostname": "staff.example.gov",
        "staff_allowed_cidrs": ["192.168.50.0/24", "2001:db8:10::/64"],
        "upstream_host": "127.0.0.1",
        "upstream_port": 8123,
    }
    values.update(overrides)
    return NetworkSettings.model_validate(values)


def test_default_is_loopback_only_and_has_no_public_proxy_config() -> None:
    settings = NetworkSettings()

    assert settings.mode == "loopback"
    assert settings.upstream_host == "127.0.0.1"
    assert settings.upstream_port == 8000
    assert settings.public_base_url is None
    assert render_caddyfile(settings) == ""
    assert settings.runtime_values().trusted_proxy_cidrs == ()
    assert settings.runtime_values().caddy_bind_addresses == ()


def test_network_settings_path_override_is_honored(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    override = tmp_path / "settings.json"
    monkeypatch.setenv("CIVICCAST_NETWORK_SETTINGS_PATH", str(override))

    assert default_network_settings_path() == override


@pytest.mark.parametrize(
    "override",
    [
        {"upstream_host": "0.0.0.0"},
        {"upstream_host": "192.168.1.4"},
        {"upstream_host": "localhost"},
        {"upstream_port": 443},
        {"public_base_url": "https://watch.example.gov"},
        {"public_base_url": "http://watch.example.gov"},
        {"public_base_url": "https://watch.example.gov/path"},
    ],
)
def test_rejects_unsafe_or_ambiguous_listener_and_public_url(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        NetworkSettings.model_validate(override)


@pytest.mark.parametrize(
    "override",
    [
        {"public_base_url": "http://watch.example.gov"},
        {"public_base_url": "https://watch.example.gov:8443"},
        {"staff_hostname": "watch.example.gov"},
        {"staff_hostname": "staff.example.gov/path"},
        {"staff_allowed_cidrs": []},
        {"staff_allowed_cidrs": ["0.0.0.0/0"]},
        {"staff_allowed_cidrs": ["not-a-network"]},
        {"caddy_bind_addresses": ["0.0.0.0"]},
        {"caddy_bind_addresses": ["127.0.0.1"]},
        {"caddy_bind_addresses": ["not-an-ip"]},
        {"upstream_host": "0.0.0.0"},
    ],
)
def test_caddy_mode_rejects_incomplete_or_exposed_configuration(
    override: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        caddy_settings(**override)


def test_generated_caddyfile_separates_public_routes_and_restricts_staff() -> None:
    settings = caddy_settings()
    generated = render_caddyfile(settings)
    public_site, staff_site = generated.split("https://staff.example.gov", maxsplit=1)

    assert "admin off" in generated
    assert "https://watch.example.gov" in public_site
    assert "path / /assets/* /favicon.svg /api/public/* /media/vod/* /media/live/*" in public_site
    assert 'respond "Not found" 404' in public_site
    assert "/api/staff/*" not in public_site
    assert "/operator/*" not in public_site
    assert "path /api/setup /api/setup/*" in staff_site
    assert (
        'respond @first_setup "First setup is available only on the station computer." 403'
        in staff_site
    )
    assert "remote_ip 192.168.50.0/24 2001:db8:10::/64" in staff_site
    assert "reverse_proxy @staff_access 127.0.0.1:8123" in staff_site
    assert "header_up X-Forwarded-For {http.request.remote.host}" in generated
    assert "header_up X-Real-IP {http.request.remote.host}" in generated
    assert "header_up -Forwarded" in generated
    assert 'respond "Staff access is limited to approved networks." 403' in staff_site


def test_store_round_trips_settings_and_refuses_corrupt_state(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "network-settings.json"
    store = NetworkSettingsStore(path)

    assert store.load() == NetworkSettings()
    assert store.save(caddy_settings()) is True
    assert store.save(caddy_settings()) is False
    assert store.load() == caddy_settings()
    assert json.loads(path.read_text(encoding="utf-8"))["mode"] == "caddy"

    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Network settings file is invalid"):
        store.load()


def test_caddy_runtime_trusts_only_the_loopback_upstream() -> None:
    settings = caddy_settings(
        upstream_host="::1",
        caddy_bind_addresses=["192.168.50.8", "2001:db8:50::8"],
    )

    assert settings.runtime_values().trusted_proxy_cidrs == ("::1/128",)
    assert settings.runtime_values().public_base_url == "https://watch.example.gov"
    assert settings.runtime_values().caddy_bind_addresses == ("192.168.50.8", "2001:db8:50::8")
    generated = render_caddyfile(settings)
    assert "bind 192.168.50.8 [2001:db8:50::8]" in generated
    assert generated.count("bind 192.168.50.8 [2001:db8:50::8]") == 3
    assert "http://watch.example.gov, http://staff.example.gov" in generated


def test_public_url_is_active_only_with_complete_caddy_mode() -> None:
    settings = caddy_settings()

    assert settings.runtime_values().public_base_url == "https://watch.example.gov"
