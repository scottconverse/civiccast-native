# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""D4 (rc17): optional-provider credential readiness must be fail-honest.

Before this fix, ``build_provider_readiness_report`` decided "credentials are
present" for Internet Archive / YouTube / subscriber notices by checking
presence of env-var *names* (``_INSTALLER_PROVIDER_ENV_NAMES``) that do not
match what the real provider adapters actually read via ``.from_env()``
(``docs/ops/cdn-and-providers.md`` is the canonical variable list). An
operator could set an unrelated, never-consumed env var, record a live-proof
evidence string, and the readiness card would claim ``ready`` while the real
adapter would immediately raise ``ValueError`` for missing credentials.

These tests exercise the real (fake-provider-backed, no network) settings
validation path at the service level: readiness must report the real
provider's own actionable error, never a false "configured"/"ready".
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def provider_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CIVICCAST_STATION_STATE_PATH", str(tmp_path / "station-state.json"))
    monkeypatch.setenv(
        "CIVICCAST_PROVIDER_CREDENTIALS_FILE", str(tmp_path / "provider-credentials.json")
    )
    monkeypatch.setenv("CIVICCAST_PROVIDER_PROOFS_FILE", str(tmp_path / "provider-proofs.json"))
    return tmp_path


def _item(report: object, provider_id: str) -> object:
    return next(item for item in report.items if item.id == provider_id)  # type: ignore[attr-defined]


def test_internet_archive_readiness_ignores_a_fictitious_env_var(
    provider_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A var the real IA adapter never reads must never make this 'configured'.

    The real adapter (``civiccast.archive.internet_archive.InternetArchiveSettings``)
    reads ``CIVICCAST_IA_ACCESS_KEY`` / ``CIVICCAST_IA_SECRET_KEY``. Setting only
    the old, disconnected ``CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY`` must leave the
    card honestly "not set up", never claim credentials are present.
    """

    from civiccast.installer.service import build_provider_readiness_report

    monkeypatch.setenv("CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY", "fake-provider-garbage-value")

    report = build_provider_readiness_report()
    item = _item(report, "internet-archive")

    assert item.status == "not_set_up", item.status
    assert "present" not in item.message.lower()


def test_internet_archive_readiness_reaches_needs_live_proof_with_real_credentials(
    provider_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from civiccast.installer.service import build_provider_readiness_report

    monkeypatch.setenv("CIVICCAST_IA_ACCESS_KEY", "fake-access-key")
    monkeypatch.setenv("CIVICCAST_IA_SECRET_KEY", "fake-secret-key")

    report = build_provider_readiness_report()
    item = _item(report, "internet-archive")

    assert item.status == "needs_live_proof", item.status


def test_record_provider_proof_refuses_internet_archive_without_real_credentials(
    provider_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The false-positive reproduction: recording proof must require the real
    credential, not a fictitious env var that happens to share the provider's
    surface name."""

    from civiccast.installer.models import ProviderProofRecordRequest
    from civiccast.installer.service import record_provider_proof

    monkeypatch.setenv("CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY", "fake-provider-garbage-value")

    with pytest.raises(ValueError, match="Save provider credentials"):
        record_provider_proof(
            ProviderProofRecordRequest(
                provider_id="internet_archive",
                evidence_reference="fake-proof-object-key",
                redaction_reviewed=True,
            )
        )


def test_youtube_readiness_requires_the_refresh_token_too(
    provider_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real client (``YouTubeSettings.from_env``) needs client id, client
    secret, AND a refresh token. Two of three must not read as configured."""

    from civiccast.installer.service import build_provider_readiness_report

    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_ID", "fake-client-id")
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "fake-client-secret")

    report = build_provider_readiness_report()
    item = _item(report, "youtube")

    assert item.status != "needs_live_proof", item.status
    assert item.status != "ready", item.status


def test_local_nas_readiness_rejects_a_path_that_is_not_a_real_directory(
    provider_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive validation, not presence: a configured-but-nonexistent archive
    path must not read as "credentials are present"."""

    from civiccast.installer.service import build_provider_readiness_report

    monkeypatch.setenv(
        "CIVICCAST_NAS_ARCHIVE_PATH", str(provider_state / "does-not-exist-anywhere")
    )

    report = build_provider_readiness_report()
    item = _item(report, "local-nas")

    assert item.status != "needs_live_proof", item.status
    assert item.status != "ready", item.status


# --- rc17 D4 round 2 (CC-RC17-001): Setup-STORED credentials must not count
# toward readiness/proof unless they feed the SAME adapter path the real
# production provider constructs. Round 1 fixed the env-var-name-list false
# positive but left a second one: `_provider_credentials_are_valid()` still
# returned True purely because required Setup UI field *names* were stored
# locally, before ever calling the real adapter's own `.from_env()` loader --
# Setup-stored values never reach `os.environ`, so they never actually feed
# the adapter the readiness card claims is satisfied.


def _save_credentials(provider_id: str, values: dict[str, str]) -> None:
    from civiccast.installer.models import ProviderCredentialSetupRequest
    from civiccast.installer.service import save_provider_credentials

    save_provider_credentials(
        ProviderCredentialSetupRequest(provider_id=provider_id, values=values)
    )


def test_internet_archive_setup_stored_credentials_do_not_grant_readiness_without_adapter_env(
    provider_state: Path,
) -> None:
    """(a) Complete Setup-stored IA credentials, zero adapter env: the real
    loader (``CIVICCAST_IA_ACCESS_KEY``/``CIVICCAST_IA_SECRET_KEY``) has
    nothing to read, so this must stay non-ready and refuse proof."""

    from civiccast.installer.models import ProviderProofRecordRequest
    from civiccast.installer.service import build_provider_readiness_report, record_provider_proof

    _save_credentials(
        "internet-archive", {"access_key": "stored-access-key", "secret_key": "stored-secret-key"}
    )

    report = build_provider_readiness_report()
    item = _item(report, "internet-archive")
    assert item.status != "needs_live_proof", item.status
    assert item.status != "ready", item.status

    with pytest.raises(ValueError):
        record_provider_proof(
            ProviderProofRecordRequest(
                provider_id="internet_archive",
                evidence_reference="fake-proof-object-key",
                redaction_reviewed=True,
            )
        )


def test_youtube_setup_stored_credentials_do_not_grant_readiness_without_adapter_env(
    provider_state: Path,
) -> None:
    """(b) Complete Setup-stored YouTube credentials, zero adapter env: the
    real loader (``CIVICCAST_YOUTUBE_CLIENT_ID``/``_CLIENT_SECRET``/
    ``_REFRESH_TOKEN``) has nothing to read, so this must stay non-ready and
    refuse proof."""

    from civiccast.installer.models import ProviderProofRecordRequest
    from civiccast.installer.service import build_provider_readiness_report, record_provider_proof

    _save_credentials(
        "youtube", {"client_id": "stored-client-id", "client_secret": "stored-client-secret"}
    )

    report = build_provider_readiness_report()
    item = _item(report, "youtube")
    assert item.status != "needs_live_proof", item.status
    assert item.status != "ready", item.status

    with pytest.raises(ValueError):
        record_provider_proof(
            ProviderProofRecordRequest(
                provider_id="youtube_live",
                evidence_reference="fake-proof-object-key",
                redaction_reviewed=True,
            )
        )


def test_youtube_readiness_rejects_setup_stored_credentials_without_refresh_token(
    provider_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) Setup-stored client id/secret PLUS the matching real env vars, but
    no refresh token env: the real loader still requires all three, so this
    must stay non-ready and refuse proof even though two of three real
    credentials genuinely exist."""

    from civiccast.installer.models import ProviderProofRecordRequest
    from civiccast.installer.service import build_provider_readiness_report, record_provider_proof

    _save_credentials(
        "youtube", {"client_id": "stored-client-id", "client_secret": "stored-client-secret"}
    )
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_ID", "stored-client-id")
    monkeypatch.setenv("CIVICCAST_YOUTUBE_CLIENT_SECRET", "stored-client-secret")

    report = build_provider_readiness_report()
    item = _item(report, "youtube")
    assert item.status != "needs_live_proof", item.status
    assert item.status != "ready", item.status

    with pytest.raises(ValueError):
        record_provider_proof(
            ProviderProofRecordRequest(
                provider_id="youtube_vod",
                evidence_reference="fake-proof-object-key",
                redaction_reviewed=True,
            )
        )


def test_subscriber_notifications_webhook_only_does_not_satisfy_the_smtp_adapter(
    provider_state: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(d) Subscriber notifications readiness/proof maps to the
    ``email_double_opt_in`` proof provider, whose real production adapter
    (``civiccast.platform.providers._real_mail``) builds
    ``civiccast.subscribe.smtp.SmtpSettings.from_env()``. A webhook secret
    alone -- Setup-stored, and/or as the legacy env var -- must never satisfy
    that SMTP loader; the SMTP loader is the truth."""

    from civiccast.installer.models import ProviderProofRecordRequest
    from civiccast.installer.service import build_provider_readiness_report, record_provider_proof

    _save_credentials("subscriber-notifications", {"webhook_secret": "stored-webhook-secret"})
    monkeypatch.setenv("CIVICCAST_SUBSCRIBER_WEBHOOK_SECRET", "env-webhook-secret")

    report = build_provider_readiness_report()
    item = _item(report, "subscriber-notifications")
    assert item.status != "needs_live_proof", item.status
    assert item.status != "ready", item.status

    with pytest.raises(ValueError):
        record_provider_proof(
            ProviderProofRecordRequest(
                provider_id="email_double_opt_in",
                evidence_reference="fake-proof-object-key",
                redaction_reviewed=True,
            )
        )
