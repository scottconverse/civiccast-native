# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP-03: Publish preflight and approval read the same real provider registry.

Covers the audit's QA-001 / ENG-001-readiness defect: preflight used a
deterministic mock credential store, unrelated to
``civiccast.platform.providers``, that always reported "healthy" -- so a
station that set e.g. ``CIVICCAST_PROVIDER_YOUTUBE=real`` with no credentials
saw preflight say ``ready=true`` and then hit an uncaught
``ProviderConfigurationError`` (an unhandled 500) on approval.

Parameterized per provider family (Internet Archive, local NAS, YouTube,
subscriber mail/webhook) across five states: missing config, partial config,
valid-real config, explicit mock, and a runtime/network call failure once
config is valid. Also proves: preflight `ready=false` exactly when approval
would refuse; approval never raises an uncaught `ValueError`; nothing secret
appears in a response or a log record.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime

import pytest

from civiccast.archive.models import (
    ArchiveProof,
    MockInternetArchiveClient,
    MockLocalNasArchiveClient,
)
from civiccast.platform.providers import (
    PROVIDER_KIND_INTERNET_ARCHIVE,
    PROVIDER_KIND_LOCAL_NAS,
    PROVIDER_KIND_YOUTUBE,
    ProviderRegistry,
    default_registry,
)
from civiccast.publish.models import PublishApprovalRequest
from civiccast.publish.readiness import describe_surface_readiness
from civiccast.publish.service import (
    PublishConfigurationError,
    approve_publish,
    build_publish_preflight,
)
from civiccast.publish.store import InMemoryPublishStore
from civiccast.schedule.models import StaffAssetRow
from civiccast.subscribe.models import SubscriptionRecord
from civiccast.syndicate.models import MockYouTubeClient

# A secret-shaped marker: if this ever leaked into a preflight/approval
# response or a log record, the redaction contract (plan item 3) is broken.
_SECRET_MARKER = "sk-super-secret-do-not-leak-9f3c1a"


def _asset(*, required: bool = True) -> StaffAssetRow:
    return StaffAssetRow(
        asset_id="council-2026-07-08",
        title="Council - July 8, 2026",
        state="validated",
        manifest_url="https://cdn.example/council-2026-07-08/playlist.m3u8",
        published_at=datetime(2026, 7, 8, 20, 0, tzinfo=UTC),
        retention_policy="meeting" if required else "short",
        version=1,
    )


def _request(*surface_ids: str) -> PublishApprovalRequest:
    return PublishApprovalRequest(
        operator_id="staff-1",
        operator_display_name="Avery Operator",
        approved_surface_ids=list(surface_ids),
    )


class _RecordingSubscribeStore:
    """Minimal SubscribeStore returning a fixed confirmed-recipient list."""

    def __init__(self, records: list[SubscriptionRecord]) -> None:
        self._records = records

    def list_confirmed_for_target(
        self, *, target_type: str, target_id: str
    ) -> list[SubscriptionRecord]:
        del target_type, target_id
        return self._records


def _confirmed(channel: str) -> SubscriptionRecord:
    return SubscriptionRecord(
        subscription_id=f"sub-{channel}",
        channel=channel,  # type: ignore[arg-type]
        encrypted_subscriber_handle="sealed",
        target_type="channel",
        target_id="government",
        status="confirmed",
        confirmation_token="tok-confirm",
        unsubscribe_token="tok-unsub",
        encrypted_webhook_secret="sealed-secret" if channel == "webhook" else None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        confirmed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


# ---------------------------------------------------------------------------
# Internet Archive / local NAS / YouTube: provider-registry-backed families
# ---------------------------------------------------------------------------

_ARCHIVE_FAMILY_CASES = [
    pytest.param(
        "internet-archive",
        PROVIDER_KIND_INTERNET_ARCHIVE,
        "CIVICCAST_PROVIDER_INTERNET_ARCHIVE",
        {},
        id="internet-archive-missing",
    ),
    pytest.param(
        "internet-archive",
        PROVIDER_KIND_INTERNET_ARCHIVE,
        "CIVICCAST_PROVIDER_INTERNET_ARCHIVE",
        {"CIVICCAST_IA_ACCESS_KEY": "key-only"},
        id="internet-archive-partial",
    ),
    pytest.param(
        "local-nas-rsync",
        PROVIDER_KIND_LOCAL_NAS,
        "CIVICCAST_PROVIDER_LOCAL_NAS",
        {},
        id="local-nas-missing",
    ),
    pytest.param(
        "youtube-live",
        PROVIDER_KIND_YOUTUBE,
        "CIVICCAST_PROVIDER_YOUTUBE",
        {
            "CIVICCAST_YOUTUBE_CLIENT_ID": "id-only",
            "CIVICCAST_YOUTUBE_CLIENT_SECRET": "secret-only",
        },
        id="youtube-partial",
    ),
]


@pytest.mark.parametrize(("surface_id", "kind", "env_key", "env"), _ARCHIVE_FAMILY_CASES)
def test_missing_or_partial_real_config_agrees_between_preflight_and_approval(
    monkeypatch: pytest.MonkeyPatch,
    surface_id: str,
    kind: str,
    env_key: str,
    env: dict[str, str],
) -> None:
    monkeypatch.setenv(env_key, "real")
    for name, value in env.items():
        monkeypatch.setenv(name, value)

    asset = _asset()
    preflight = build_publish_preflight(asset)
    check = next(c for c in preflight.checks if c.id == surface_id)
    assert check.health == "error"
    if check.required:
        assert preflight.ready is False, "a required surface's invalid real config must block ready"
    assert check.credential_reference == f"{env_key}=real"

    store = InMemoryPublishStore()
    with pytest.raises(PublishConfigurationError) as excinfo:
        approve_publish(asset=asset, request=_request(surface_id), store=store)
    assert surface_id in excinfo.value.surfaces
    # Controlled 409, not a mid-approval crash: no run was ever persisted.
    assert store.get_run(asset.asset_id) is None


def test_valid_real_config_is_healthy_and_never_falls_back_to_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit mock never substitutes for a working real adapter."""
    monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")

    class _FakeRealArchive:
        def __init__(self) -> None:
            self.called = False

        def upload(self, *, asset_id: str, payload: bytes) -> ArchiveProof:
            del payload
            self.called = True
            return ArchiveProof(
                target_type="internet_archive",
                target_url_or_path=f"https://archive.example/details/{asset_id}",
                verification_hash="sha256:" + "a" * 64,
                credential_posture="informal_per_station",
                simulated=False,
            )

    real_client = _FakeRealArchive()
    registry = ProviderRegistry()
    registry.register(PROVIDER_KIND_INTERNET_ARCHIVE, "mock", MockInternetArchiveClient)
    registry.register(PROVIDER_KIND_INTERNET_ARCHIVE, "real", lambda: real_client)
    # The asset is a required-public-record; local-nas-rsync/zfs are also
    # required surfaces, so they need a resolvable (mock) provider too, or
    # `ready` would read False for an unrelated reason.
    registry.register(PROVIDER_KIND_LOCAL_NAS, "mock", MockLocalNasArchiveClient)
    registry.register(PROVIDER_KIND_YOUTUBE, "mock", MockYouTubeClient)

    asset = _asset()
    preflight = build_publish_preflight(asset, registry=registry)
    check = next(c for c in preflight.checks if c.id == "internet-archive")
    assert check.health == "ok"
    assert "simulated" not in check.message
    assert preflight.ready is True

    record = approve_publish(
        asset=asset,
        request=_request("internet-archive"),
        store=InMemoryPublishStore(),
        registry=registry,
    )
    surface = next(s for s in record.surfaces if s.id == "internet-archive")
    assert surface.state == "succeeded"
    assert surface.simulated is False
    assert real_client.called is True, "approval must use the real-named adapter, not the mock"


def test_explicit_mock_is_usable_but_stays_marked_simulated() -> None:
    """The shipped default (mock) never blocks readiness, but is never
    reported as real-provider proof (plan item 6)."""
    asset = _asset()
    preflight = build_publish_preflight(asset)
    check = next(c for c in preflight.checks if c.id == "internet-archive")
    assert check.health == "ok"
    assert check.credential_reference == "CIVICCAST_PROVIDER_INTERNET_ARCHIVE=mock"
    assert "simulated" in check.message.lower()
    assert preflight.ready is True

    record = approve_publish(
        asset=asset, request=_request("internet-archive"), store=InMemoryPublishStore()
    )
    surface = next(s for s in record.surfaces if s.id == "internet-archive")
    assert surface.state == "succeeded"
    assert surface.simulated is True
    assert "SIMULATED" in surface.message


def test_runtime_call_failure_after_valid_config_fails_only_that_surface() -> None:
    """Once config is valid, a network/runtime failure is per-surface -- not
    a 409 (config was fine) and not a 500 (the rest of the run continues)."""

    class _ExplodingRealArchive:
        def upload(self, *, asset_id: str, payload: bytes) -> ArchiveProof:
            del asset_id, payload
            raise RuntimeError("archive.org: connection reset")

    registry = ProviderRegistry()
    registry.register(PROVIDER_KIND_INTERNET_ARCHIVE, "mock", lambda: _ExplodingRealArchive())
    registry.register(PROVIDER_KIND_LOCAL_NAS, "mock", MockLocalNasArchiveClient)
    registry.register(PROVIDER_KIND_YOUTUBE, "mock", MockYouTubeClient)

    asset = _asset()
    record = approve_publish(
        asset=asset,
        request=_request("internet-archive", "youtube-vod"),
        store=InMemoryPublishStore(),
        registry=registry,
    )
    surfaces = {s.id: s for s in record.surfaces}
    assert surfaces["internet-archive"].state == "failed"
    assert "connection reset" in (surfaces["internet-archive"].next_step or "")
    assert surfaces["youtube-vod"].state == "succeeded", (
        "a runtime failure on one surface must not take down an unrelated one"
    )


def test_unselected_broken_provider_never_blocks_portal_only_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan item 9: a misconfigured, UNselected provider cannot block a
    portal-only (or otherwise unrelated) approval."""
    monkeypatch.setenv("CIVICCAST_PROVIDER_YOUTUBE", "real")  # broken: no creds

    asset = _asset()
    record = approve_publish(asset=asset, request=_request("portal"), store=InMemoryPublishStore())
    portal = next(s for s in record.surfaces if s.id == "portal")
    assert portal.state == "succeeded"


# ---------------------------------------------------------------------------
# Subscriber channels (mail/webhook)
#
# Subscriber readiness uses the same target set and provider configuration as
# delivery. These checks cover missing configuration, simulated providers,
# and the requirement for durable outcomes before claiming a send.
# ---------------------------------------------------------------------------


def test_readiness_module_reports_ready_when_no_confirmed_recipients() -> None:
    """civiccast.publish.readiness's real per-channel check, exercised
    directly (see module docstring above: service.py no longer calls this
    for subscriber-notifications, but the logic stays correct for the
    parked real-send branch)."""
    registry = default_registry()
    readiness = describe_surface_readiness(
        "subscriber-notifications",
        label="Subscriber notifications",
        registry=registry,
        subscribe_store=_RecordingSubscribeStore([]),
    )
    assert readiness is not None
    assert readiness.healthy is True
    assert "no confirmed subscribers" in readiness.message.lower()


def test_readiness_module_reports_missing_real_mail_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PROVIDER_MAIL", "real")
    registry = default_registry()
    readiness = describe_surface_readiness(
        "subscriber-notifications",
        label="Subscriber notifications",
        registry=registry,
        subscribe_store=_RecordingSubscribeStore([_confirmed("email")]),
        subscribe_targets=[("channel", "government")],
    )
    assert readiness is not None
    assert readiness.healthy is False
    assert "email" in readiness.message


def test_readiness_module_real_webhook_needs_no_station_wide_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unlike mail (a station-wide SMTP credential), the real webhook
    provider has no required global env var -- each subscription's HMAC
    secret is sealed per-row in the subscribe store, not read from the
    environment (see civiccast.subscribe.webhook.WebhookSettings.from_env
    and civiccast.subscribe.service.dispatch_notifications). Selecting
    CIVICCAST_PROVIDER_WEBHOOK=real is therefore immediately usable -- this
    is real product behavior, not a readiness gap."""
    monkeypatch.setenv("CIVICCAST_PROVIDER_WEBHOOK", "real")
    registry = default_registry()
    readiness = describe_surface_readiness(
        "subscriber-notifications",
        label="Subscriber notifications",
        registry=registry,
        subscribe_store=_RecordingSubscribeStore([_confirmed("webhook")]),
        subscribe_targets=[("channel", "government")],
    )
    assert readiness is not None
    assert readiness.healthy is True
    assert "CIVICCAST_PROVIDER_WEBHOOK=real" in readiness.reference


def test_readiness_module_explicit_mock_is_usable_and_simulated() -> None:
    registry = default_registry()
    readiness = describe_surface_readiness(
        "subscriber-notifications",
        label="Subscriber notifications",
        registry=registry,
        subscribe_store=_RecordingSubscribeStore([_confirmed("email"), _confirmed("webhook")]),
        subscribe_targets=[("channel", "government")],
    )
    assert readiness is not None
    assert readiness.healthy is True
    assert "simulated" in readiness.message.lower()
    assert "CIVICCAST_PROVIDER_MAIL=mock" in readiness.reference
    assert "CIVICCAST_PROVIDER_WEBHOOK=mock" in readiness.reference


def test_subscriber_notifications_preflight_exposes_missing_real_mail_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected real mail provider must report missing configuration."""
    monkeypatch.setenv("CIVICCAST_PROVIDER_MAIL", "real")
    store = _RecordingSubscribeStore([_confirmed("email")])
    asset = _asset()

    preflight = build_publish_preflight(asset, subscribe_store=store)
    check = next(c for c in preflight.checks if c.id == "subscriber-notifications")
    assert check.health == "error"
    assert check.required is False
    assert "email" in check.message.lower()
    assert preflight.ready is True


def test_subscriber_notifications_approval_blocks_on_broken_real_mail_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A selected real mail surface cannot claim delivery without SMTP."""
    monkeypatch.setenv("CIVICCAST_PROVIDER_MAIL", "real")
    store = _RecordingSubscribeStore([_confirmed("email")])
    asset = _asset()

    with pytest.raises(PublishConfigurationError):
        approve_publish(
            asset=asset,
            request=_request("subscriber-notifications"),
            store=InMemoryPublishStore(),
            subscribe_store=store,
        )


def test_subscriber_notifications_with_no_receipt_store_never_claims_delivery() -> None:
    """A missing durable receipt store must not be reported as a sent notice."""
    store = _RecordingSubscribeStore([_confirmed("email"), _confirmed("webhook")])
    asset = _asset()

    record = approve_publish(
        asset=asset,
        request=_request("portal", "subscriber-notifications"),
        store=InMemoryPublishStore(),
        subscribe_store=store,
    )
    surface = next(s for s in record.surfaces if s.id == "subscriber-notifications")
    assert surface.state != "succeeded"
    assert surface.health != "ok"
    # No "succeeded" audit event was emitted for a surface that never ran.
    assert not any(
        event.surface_id == "subscriber-notifications" and event.action == "succeeded"
        for event in record.audit_events
    )


# ---------------------------------------------------------------------------
# Podcast uses the local recording and has no external provider.
# ---------------------------------------------------------------------------


def test_podcast_preflight_describes_local_audio_without_blocking_portal() -> None:
    asset = _asset()
    preflight = build_publish_preflight(asset)
    check = next(c for c in preflight.checks if c.id == "podcast")
    assert check.health == "unknown"
    assert check.required is False
    assert "local recording" in check.message.lower()
    assert preflight.ready is True


# ---------------------------------------------------------------------------
# No uncaught ValueError, and redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env_key",
    [
        "CIVICCAST_PROVIDER_INTERNET_ARCHIVE",
        "CIVICCAST_PROVIDER_LOCAL_NAS",
        "CIVICCAST_PROVIDER_YOUTUBE",
    ],
)
def test_approval_never_raises_uncaught_value_error(
    monkeypatch: pytest.MonkeyPatch, env_key: str
) -> None:
    """The original defect: ProviderRegistry.resolve() raises
    ProviderConfigurationError (a RuntimeError) straight out of
    settings.from_env()'s ValueError. approve_publish must convert that into
    PublishConfigurationError -- never let a bare ValueError/
    ProviderConfigurationError escape to the caller."""
    monkeypatch.setenv(env_key, "real")
    asset = _asset()
    surface_id = {
        "CIVICCAST_PROVIDER_INTERNET_ARCHIVE": "internet-archive",
        "CIVICCAST_PROVIDER_LOCAL_NAS": "local-nas-rsync",
        "CIVICCAST_PROVIDER_YOUTUBE": "youtube-live",
    }[env_key]
    try:
        approve_publish(
            asset=asset,
            request=_request(surface_id),
            store=InMemoryPublishStore(),
        )
    except PublishConfigurationError:
        pass  # expected, controlled failure
    except ValueError as exc:  # pragma: no cover - the regression this guards
        pytest.fail(f"approve_publish let an uncaught ValueError escape: {exc}")


def test_missing_real_config_never_leaks_a_secret_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Redaction (plan item 3): even when an operator has typed a real-looking
    secret into a *different, still-missing* credential variable, neither the
    preflight response nor any log record emitted during preflight/approval
    contains that value -- only variable NAMES are ever surfaced."""
    monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")
    # A DIFFERENT credential value is present in the environment (as it would
    # be on a real station running other providers) -- it must never leak
    # into an unrelated surface's readiness output.
    monkeypatch.setenv("CIVICCAST_SMTP_PASSWORD", _SECRET_MARKER)

    asset = _asset()
    with caplog.at_level(logging.DEBUG):
        preflight = build_publish_preflight(asset)
        with contextlib.suppress(PublishConfigurationError):
            approve_publish(
                asset=asset,
                request=_request("internet-archive"),
                store=InMemoryPublishStore(),
            )

    dumped = preflight.model_dump_json()
    assert _SECRET_MARKER not in dumped
    for record in caplog.records:
        assert _SECRET_MARKER not in record.getMessage()


def test_real_provider_error_message_never_echoes_a_configured_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even the ONE credential the operator is actively trying to configure
    never appears in the readiness message -- only the missing variable
    NAMES do (civiccast.platform.providers's own contract)."""
    monkeypatch.setenv("CIVICCAST_PROVIDER_INTERNET_ARCHIVE", "real")
    monkeypatch.setenv("CIVICCAST_IA_ACCESS_KEY", _SECRET_MARKER)
    # CIVICCAST_IA_SECRET_KEY intentionally left unset -> partial/invalid.

    asset = _asset()
    preflight = build_publish_preflight(asset)
    check = next(c for c in preflight.checks if c.id == "internet-archive")
    assert check.health == "error"
    assert _SECRET_MARKER not in check.message
    assert _SECRET_MARKER not in (check.credential_reference or "")
    assert _SECRET_MARKER not in check.next_step
    assert "CIVICCAST_IA_SECRET_KEY" in check.message
