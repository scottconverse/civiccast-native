# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""AgendaImportSettings.from_env() -- plan §7 config, off by default."""

from __future__ import annotations

import pytest

from civiccast.agenda_import.config import AgendaImportSettings, validate_client_code


class TestValidateClientCode:
    """SEC-1: only bare vendor tenant tokens pass; anything that could redirect
    the spliced request host is rejected."""

    @pytest.mark.parametrize("value", ["longmont", "portagemi", "site-01", "a_b", "A" * 64])
    def test_accepts_bare_tenant_tokens(self, value: str) -> None:
        assert validate_client_code(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "169.254.169.254/latest/meta-data/#",  # SSRF path splice
            "evil.com",  # dot -> different host
            "a@b",  # userinfo injection
            "a b",  # whitespace
            "a:b",  # port/scheme injection
            "",  # empty
            "A" * 65,  # too long
        ],
    )
    def test_rejects_unsafe_values(self, value: str) -> None:
        with pytest.raises(ValueError, match="client_code must be"):
            validate_client_code(value)


class TestFromEnv:
    def test_default_is_off_and_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "CIVICCAST_AGENDA_SOURCE",
            "CIVICCAST_AGENDA_SOURCE_CLIENT",
            "CIVICCAST_AGENDA_SOURCE_TOKEN",
            "CIVICCAST_AGENDA_SOURCE_TIMEOUT_S",
        ):
            monkeypatch.delenv(name, raising=False)

        settings = AgendaImportSettings.from_env()

        assert settings.source == "off"
        assert settings.enabled is False
        assert settings.client_code is None
        assert settings.token is None
        assert settings.timeout_seconds == 10.0

    def test_legistar_source_is_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_AGENDA_SOURCE", "legistar")
        settings = AgendaImportSettings.from_env()
        assert settings.enabled is True
        assert settings.source == "legistar"

    def test_unknown_source_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_AGENDA_SOURCE", "bogus-vendor")
        with pytest.raises(ValueError, match="CIVICCAST_AGENDA_SOURCE"):
            AgendaImportSettings.from_env()

    def test_client_and_token_pass_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_AGENDA_SOURCE", "legistar")
        monkeypatch.setenv("CIVICCAST_AGENDA_SOURCE_CLIENT", "seattle")
        monkeypatch.setenv("CIVICCAST_AGENDA_SOURCE_TOKEN", "token-sentinel")
        settings = AgendaImportSettings.from_env()
        assert settings.client_code == "seattle"
        assert settings.token == "token-sentinel"

    def test_timeout_validates_numeric_and_positive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_AGENDA_SOURCE_TIMEOUT_S", "not-a-number")
        with pytest.raises(ValueError, match="CIVICCAST_AGENDA_SOURCE_TIMEOUT_S"):
            AgendaImportSettings.from_env()

        monkeypatch.setenv("CIVICCAST_AGENDA_SOURCE_TIMEOUT_S", "0")
        with pytest.raises(ValueError, match="positive"):
            AgendaImportSettings.from_env()

        monkeypatch.setenv("CIVICCAST_AGENDA_SOURCE_TIMEOUT_S", "5.5")
        assert AgendaImportSettings.from_env().timeout_seconds == 5.5
