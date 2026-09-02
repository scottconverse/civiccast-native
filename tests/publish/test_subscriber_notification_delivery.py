# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Publish actually delivers subscriber notices, and says only what it observed.

WP-05, the defect: ``approve_publish`` reported the subscriber-notifications
surface ``succeeded`` after building a payload it never dispatched. These tests
drive the real approval path against a loopback SMTP server and a recording
webhook client, then assert on what those sinks OBSERVED -- not on what the
publish record claims.

No live external calls and no real secrets: mail goes to an in-process SMTP
server on a loopback socket, webhooks to an in-process client.
"""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import quote

import pytest

from civiccast.platform.providers import (
    PROVIDER_KIND_MAIL,
    PROVIDER_KIND_WEBHOOK,
    ProviderRegistry,
    default_registry,
)
from civiccast.publish.models import PublishApprovalRequest, PublishRetryRequest
from civiccast.publish.notifications import deliver_publication_notifications
from civiccast.publish.service import (
    approve_publish,
    build_publish_asset_status,
    build_publish_preflight,
    retry_publish_surface,
)
from civiccast.publish.store import InMemoryPublishStore
from civiccast.publish.targets import (
    StaticChannelAssociationLookup,
    resolve_publication_targets,
)
from civiccast.schedule.models import StaffAssetRow
from civiccast.subscribe.delivery import LocalMailbox, LocalWebhookClient
from civiccast.subscribe.models import (
    NotificationPayload,
    SubscriptionPublicResponse,
    SubscriptionSignupRequest,
    SubscriptionWebhookRequest,
)
from civiccast.subscribe.outcome_store import InMemoryNotificationDeliveryStore
from civiccast.subscribe.secrets import load_subscription_secrets
from civiccast.subscribe.service import (
    confirm_subscription,
    create_email_subscription,
    create_webhook_subscription,
)
from civiccast.subscribe.smtp import SmtpMailbox, SmtpSettings
from civiccast.subscribe.store import InMemorySubscribeStore

# Planted markers. If any of these ever reaches a Publish JSON body, a delivery
# outcome row, or a log record, the redaction contract is broken.
RESIDENT_EMAIL = "pii-marker-resident@example.org"
SECOND_EMAIL = "pii-marker-second@example.org"
WEBHOOK_URL = "https://hooks.example/pii-marker-hook"

_PUBLIC_BASE = "https://records.example-city.gov"


class _LoopbackSmtpServer:
    """Minimal in-process SMTP sink that observes every message it is handed."""

    def __init__(self, *, refuse_after: int | None = None) -> None:
        self.recipients: list[str] = []
        self.bodies: list[str] = []
        self._refuse_after = refuse_after
        self._sock = socket.socket()
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self.port = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            with conn:
                try:
                    self._converse(conn)
                except OSError:  # pragma: no cover - client hung up
                    continue

    def _converse(self, conn: socket.socket) -> None:
        conn.sendall(b"220 loopback ESMTP\r\n")
        buffer = b""
        in_data = False
        data_lines: list[str] = []
        recipient: str | None = None
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                return
            buffer += chunk
            while b"\r\n" in buffer:
                line, buffer = buffer.split(b"\r\n", 1)
                text = line.decode("utf-8", "replace")
                if in_data:
                    if text == ".":
                        in_data = False
                        self.bodies.append("\n".join(data_lines))
                        data_lines = []
                        conn.sendall(b"250 OK\r\n")
                        continue
                    data_lines.append(text)
                    continue
                upper = text.upper()
                if upper.startswith("EHLO") or upper.startswith("HELO"):
                    conn.sendall(b"250-loopback\r\n250 OK\r\n")
                elif upper.startswith("RCPT TO"):
                    recipient = text.split(":", 1)[1].strip().strip("<>")
                    if self._refuse_after is not None and len(self.recipients) >= (
                        self._refuse_after
                    ):
                        # Real refusals name the address; that is exactly the
                        # string that must never survive into a stored detail.
                        conn.sendall(f"550 no mailbox for {recipient}\r\n".encode())
                        recipient = None
                    else:
                        self.recipients.append(recipient)
                        conn.sendall(b"250 OK\r\n")
                elif upper.startswith("DATA"):
                    conn.sendall(b"354 End data with <CR><LF>.<CR><LF>\r\n")
                    in_data = True
                elif upper.startswith("QUIT"):
                    conn.sendall(b"221 Bye\r\n")
                    return
                else:
                    conn.sendall(b"250 OK\r\n")

    def close(self) -> None:
        self._stop.set()
        self._sock.close()


@pytest.fixture
def smtp_server() -> Iterator[_LoopbackSmtpServer]:
    server = _LoopbackSmtpServer()
    yield server
    server.close()


@pytest.fixture
def refusing_smtp_server() -> Iterator[_LoopbackSmtpServer]:
    """A relay that refuses every address, naming it in the 550 -- like a real one."""

    server = _LoopbackSmtpServer(refuse_after=0)
    yield server
    server.close()


def _smtp_mailbox(server: _LoopbackSmtpServer) -> SmtpMailbox:
    return SmtpMailbox(
        SmtpSettings(
            host="127.0.0.1",
            port=server.port,
            from_address="notices@station.example",
            use_starttls=False,
        )
    )


@pytest.fixture(autouse=True)
def _configured_public_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_BASE_URL", _PUBLIC_BASE)


def _asset(asset_id: str = "meeting-42", *, meeting_body: str | None = None) -> StaffAssetRow:
    return StaffAssetRow(
        asset_id=asset_id,
        title="Council Meeting 2026-06-10",
        meeting_body=meeting_body,
        state="validated",
        manifest_url=f"https://cdn.example/{asset_id}/playlist.m3u8",
        retention_policy="meeting",
    )


def _confirmed_email(
    store: InMemorySubscribeStore,
    email: str,
    *,
    target_type: str = "channel",
    target_id: str = "government",
) -> SubscriptionPublicResponse:
    mailbox = LocalMailbox()
    created = create_email_subscription(
        SubscriptionSignupRequest(email=email, target_type=target_type, target_id=target_id),
        store=store,
        mailbox=mailbox,
    )
    token = mailbox.messages[-1]["body"].split("token=", 1)[1].strip()
    confirm_subscription(token, store=store)
    return created


def _confirmed_webhook(
    store: InMemorySubscribeStore,
    url: str,
    *,
    target_type: str = "channel",
    target_id: str = "government",
) -> SubscriptionPublicResponse:
    created = create_webhook_subscription(
        SubscriptionWebhookRequest(webhook_url=url, target_type=target_type, target_id=target_id),
        store=store,
    )
    assert created.confirmation_token is not None
    confirm_subscription(created.confirmation_token, store=store)
    return created


def _registry(
    *, mailbox: object | None = None, webhook_client: object | None = None
) -> ProviderRegistry:
    """The app's provider seam, with test adapters registered under "mock".

    Using the registry (rather than patching the service) is the point: it
    proves approval sends through the SAME provider seam preflight reported
    readiness for.
    """

    registry = default_registry()
    if mailbox is not None:
        registry.register(PROVIDER_KIND_MAIL, "mock", lambda: mailbox)
    if webhook_client is not None:
        registry.register(PROVIDER_KIND_WEBHOOK, "mock", lambda: webhook_client)
    return registry


def _approve(
    asset: StaffAssetRow,
    *,
    subscribe_store: InMemorySubscribeStore,
    delivery_store: InMemoryNotificationDeliveryStore,
    publish_store: InMemoryPublishStore,
    mailbox: object | None = None,
    webhook_client: object | None = None,
):  # type: ignore[no-untyped-def]
    """Approve only the subscriber-notifications surface, with test adapters."""

    return approve_publish(
        asset=asset,
        request=PublishApprovalRequest(
            operator_id="staff-1",
            operator_display_name="Avery Operator",
            approved_surface_ids=["subscriber-notifications"],
        ),
        store=publish_store,
        registry=_registry(mailbox=mailbox, webhook_client=webhook_client),
        subscribe_store=subscribe_store,
        delivery_store=delivery_store,
        target_lookup=StaticChannelAssociationLookup(),
    )


def _surface(record):  # type: ignore[no-untyped-def]
    return next(s for s in record.surfaces if s.id == "subscriber-notifications")


class TestRealDeliveryHappens:
    def test_a_real_smtp_sink_observes_the_notice(self, smtp_server: _LoopbackSmtpServer) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)

        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=_smtp_mailbox(smtp_server),
        )

        # The proof is the SINK, not the publish record.
        assert smtp_server.recipients == [RESIDENT_EMAIL]
        assert any("Council Meeting 2026-06-10" in body for body in smtp_server.bodies)
        assert any(f"{_PUBLIC_BASE}/#/watch/meeting-42" in body for body in smtp_server.bodies)

        surface = _surface(record)
        assert surface.state == "succeeded"
        assert surface.notification_summary is not None
        assert surface.notification_summary.sent == 1

    def test_a_webhook_sink_observes_a_signed_post(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_webhook(subscribe_store, WEBHOOK_URL)
        webhooks = LocalWebhookClient()

        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            webhook_client=webhooks,
        )

        assert [request["url"] for request in webhooks.requests] == [WEBHOOK_URL]
        assert webhooks.requests[0]["signature"]
        assert _surface(record).state == "succeeded"

    def test_a_subscription_reached_through_both_targets_is_delivered_once(self) -> None:
        """The dedupe rule: one SUBSCRIPTION, not one per matching target.

        A store that returns the same subscription row for more than one of an
        asset's resolved targets must not produce two deliveries for it -- the
        first target visited binds it, which also keeps its logical delivery key
        stable across runs.
        """

        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        rows = subscribe_store.list_confirmed_for_target(
            target_type="channel", target_id="government"
        )

        class _StoreMatchingEveryTarget(InMemorySubscribeStore):
            def list_confirmed_for_target(self, *, target_type: str, target_id: str):  # type: ignore[no-untyped-def]
                return list(rows)

        greedy = _StoreMatchingEveryTarget()
        mailbox = LocalMailbox()

        record = _approve(
            _asset(meeting_body="planning-commission"),
            subscribe_store=greedy,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=mailbox,
        )

        summary = _surface(record).notification_summary
        assert summary is not None
        assert summary.intended == 1
        assert len(mailbox.messages) == 1
        # Bound to the first target in the resolver's deterministic order.
        assert summary.deliveries[0].target_type == "channel"
        assert sorted(summary.targets) == [
            "channel:government",
            "meeting_body:planning-commission",
        ]

    def test_two_separate_opt_ins_from_one_address_are_two_subscriptions(self) -> None:
        """Not deduplicated, deliberately.

        A resident who confirmed the channel AND the committee made two
        opt-ins, each with its own unsubscribe link. Collapsing them would let
        one unsubscribe silently cancel a subscription the resident still
        wants. The dedupe rule above is about one subscription matching two
        targets, not about one address holding two subscriptions.
        """

        subscribe_store = InMemorySubscribeStore()
        first = _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        second = _confirmed_email(
            subscribe_store,
            RESIDENT_EMAIL,
            target_type="meeting_body",
            target_id="planning-commission",
        )
        assert first.subscription_id != second.subscription_id
        mailbox = LocalMailbox()

        record = _approve(
            _asset(meeting_body="planning-commission"),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=mailbox,
        )

        summary = _surface(record).notification_summary
        assert summary is not None
        assert summary.intended == 2
        assert summary.sent == 2
        assert len(mailbox.messages) == 2


class TestPartialAndQueuedCannotLookSuccessful:
    def test_one_failed_webhook_makes_the_surface_partial(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        _confirmed_webhook(subscribe_store, WEBHOOK_URL)

        class _BrokenWebhooks:
            def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
                raise RuntimeError(f"connection refused talking to {url}")

        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=LocalMailbox(),
            webhook_client=_BrokenWebhooks(),
        )

        surface = _surface(record)
        assert surface.state == "partial"
        assert surface.health == "warning"
        summary = surface.notification_summary
        assert summary is not None
        assert (summary.sent, summary.queued, summary.failed) == (1, 1, 0)
        # The queued row links back to a durable retry-queue row.
        queued = next(row for row in summary.deliveries if row.outcome == "queued")
        assert queued.retry_id is not None
        assert subscribe_store.get_webhook_retry(queued.retry_id) is not None

    def test_a_partial_surface_is_not_reported_as_complete_on_the_dashboard(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        _confirmed_webhook(subscribe_store, WEBHOOK_URL)
        publish_store = InMemoryPublishStore()

        class _BrokenWebhooks:
            def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
                raise RuntimeError("connection refused")

        asset = _asset()
        record = approve_publish(
            asset=asset,
            request=PublishApprovalRequest(
                operator_id="staff-1", operator_display_name="Avery Operator"
            ),
            store=publish_store,
            registry=_registry(webhook_client=_BrokenWebhooks()),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            target_lookup=StaticChannelAssociationLookup(),
        )
        status = build_publish_asset_status(asset, record)

        assert _surface(record).state == "partial"
        # A recording whose notices only half went out is not "Complete".
        assert status.reach_degraded is True
        assert status.dashboard_state != "complete"

    def test_all_webhooks_queued_reads_pending_not_failed(self) -> None:
        """Precedence: a delivery still owned by the retry worker is pending."""

        subscribe_store = InMemorySubscribeStore()
        _confirmed_webhook(subscribe_store, WEBHOOK_URL)

        class _BrokenWebhooks:
            def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
                raise RuntimeError("connection refused")

        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            webhook_client=_BrokenWebhooks(),
        )

        assert _surface(record).state == "pending"

    def test_every_email_refused_reads_failed(
        self, refusing_smtp_server: _LoopbackSmtpServer
    ) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)

        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=_smtp_mailbox(refusing_smtp_server),
        )

        surface = _surface(record)
        assert surface.state == "failed"
        assert surface.notification_summary is not None
        assert surface.notification_summary.failed == 1
        # A real ``SMTPRecipientsRefused`` carries the address dict verbatim;
        # this is the most realistic PII leak path there is.
        assert RESIDENT_EMAIL not in record.model_dump_json()
        assert surface.notification_summary.deliveries[0].error_code.startswith("SMTP")

    def test_no_confirmed_subscribers_claims_no_attempt(self) -> None:
        record = _approve(
            _asset(),
            subscribe_store=InMemorySubscribeStore(),
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=LocalMailbox(),
        )

        surface = _surface(record)
        assert surface.state == "not_configured"
        assert surface.notification_summary is None


class TestFailureIsolation:
    def test_one_exception_neither_erases_earlier_receipts_nor_stops_later_recipients(
        self,
    ) -> None:
        subscribe_store = InMemorySubscribeStore()
        first = _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        second = _confirmed_email(subscribe_store, SECOND_EMAIL)
        delivery_store = InMemoryNotificationDeliveryStore()

        seen: list[str] = []

        class _MailboxThatBlowsUpOnce:
            def send_notification(self, *, email: str, payload: NotificationPayload) -> str:
                seen.append(email)
                if len(seen) == 2:
                    raise RuntimeError(f"relay exploded for {email}")
                return f"mail:{len(seen)}"

        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            publish_store=InMemoryPublishStore(),
            mailbox=_MailboxThatBlowsUpOnce(),
        )

        # Three recipients would be ideal, but two prove both halves: the
        # first receipt survives, and the loop reached the second recipient.
        assert len(seen) == 2
        summary = _surface(record).notification_summary
        assert summary is not None
        assert (summary.sent, summary.failed) == (1, 1)
        outcomes = {row.subscription_id: row.outcome for row in summary.deliveries}
        assert outcomes[first.subscription_id] == "sent"
        assert outcomes[second.subscription_id] == "failed"


class TestIdempotenceAndRetry:
    def test_reapproval_does_not_send_a_second_notice(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        delivery_store = InMemoryNotificationDeliveryStore()
        publish_store = InMemoryPublishStore()
        mailbox = LocalMailbox()

        first = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            publish_store=publish_store,
            mailbox=mailbox,
        )
        second = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            publish_store=publish_store,
            mailbox=mailbox,
        )

        assert len(mailbox.messages) == 1, "re-approval mailed the resident twice"
        # Re-approval returns the EXISTING logical outcome.
        assert _surface(second).state == "succeeded"
        assert _surface(second).notification_summary == _surface(first).notification_summary

    def test_retry_reattempts_only_the_failed_delivery_and_never_the_sent_one(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        _confirmed_email(subscribe_store, SECOND_EMAIL)
        delivery_store = InMemoryNotificationDeliveryStore()
        publish_store = InMemoryPublishStore()

        attempts: list[str] = []

        class _MailboxFailingSecondAddress:
            def __init__(self) -> None:
                self.fail = True

            def send_notification(self, *, email: str, payload: NotificationPayload) -> str:
                attempts.append(email)
                if email == SECOND_EMAIL and self.fail:
                    raise RuntimeError("temporary relay outage")
                return f"mail:{len(attempts)}"

        mailbox = _MailboxFailingSecondAddress()
        asset = _asset()
        _approve(
            asset,
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            publish_store=publish_store,
            mailbox=mailbox,
        )
        assert sorted(attempts) == sorted([RESIDENT_EMAIL, SECOND_EMAIL])

        mailbox.fail = False
        attempts.clear()

        retried = retry_publish_surface(
            asset=asset,
            surface_id="subscriber-notifications",
            request=PublishRetryRequest(
                operator_id="staff-1", operator_display_name="Avery Operator"
            ),
            store=publish_store,
            registry=_registry(mailbox=mailbox),
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            target_lookup=StaticChannelAssociationLookup(),
        )

        # Only the previously failed recipient was contacted again.
        assert attempts == [SECOND_EMAIL]
        surface = _surface(retried)
        assert surface.state == "succeeded"
        assert surface.notification_summary is not None
        assert surface.notification_summary.sent == 2


class TestHistoricalRowsAreNeverGreenEvidence:
    def test_a_succeeded_row_without_a_receipt_reads_unverified(self) -> None:
        """Every subscriber-notification row written before WP-05 looks like this."""

        asset = _asset()
        publish_store = InMemoryPublishStore()
        record = approve_publish(
            asset=asset,
            request=PublishApprovalRequest(
                operator_id="staff-1", operator_display_name="Avery Operator"
            ),
            store=publish_store,
            subscribe_store=InMemorySubscribeStore(),
            delivery_store=InMemoryNotificationDeliveryStore(),
            target_lookup=StaticChannelAssociationLookup(),
        )
        legacy = record.model_copy(
            update={
                "surfaces": [
                    surface.model_copy(
                        update={
                            "state": "succeeded",
                            "health": "ok",
                            "notification_summary": None,
                            "message": "Subscriber notification payload prepared.",
                        }
                    )
                    if surface.id == "subscriber-notifications"
                    else surface
                    for surface in record.surfaces
                ]
            }
        )

        status = build_publish_asset_status(asset, legacy)
        surface = next(s for s in status.surfaces if s.id == "subscriber-notifications")

        assert surface.state == "unverified"
        assert surface.health == "warning"
        assert "cannot show" in surface.message
        assert status.reach_degraded is True


class TestNoPiiEscapes:
    def test_publish_json_outcome_rows_and_logs_carry_no_recipient(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        _confirmed_webhook(subscribe_store, WEBHOOK_URL)
        delivery_store = InMemoryNotificationDeliveryStore()

        class _MailboxNamingTheAddress:
            def send_notification(self, *, email: str, payload: NotificationPayload) -> str:
                raise RuntimeError(f"550 no mailbox for {email}")

        class _WebhooksNamingTheUrl:
            def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
                raise RuntimeError(f"connect failed to {url} using {secret}")

        with caplog.at_level(logging.DEBUG):
            record = _approve(
                _asset(),
                subscribe_store=subscribe_store,
                delivery_store=delivery_store,
                publish_store=InMemoryPublishStore(),
                mailbox=_MailboxNamingTheAddress(),
                webhook_client=_WebhooksNamingTheUrl(),
            )

        publish_json = record.model_dump_json()
        outcome_json = "".join(
            outcome.model_dump_json()
            for outcome in delivery_store.list_for_publication("pub:meeting-42")
        )
        logged = "\n".join(caplog.messages) + "\n".join(
            str(rec.getMessage()) for rec in caplog.records
        )

        for marker in (RESIDENT_EMAIL, WEBHOOK_URL, "pii-marker"):
            assert marker not in publish_json, f"{marker} leaked into the publish record"
            assert marker not in outcome_json, f"{marker} leaked into a delivery outcome row"
            assert marker not in logged, f"{marker} leaked into the operator log"

        # The reason is still legible without the recipient.
        summary = _surface(record).notification_summary
        assert summary is not None
        assert {row.error_code for row in summary.deliveries} == {"RuntimeError"}
        assert all("redacted" in row.detail for row in summary.deliveries)


def test_notices_are_portal_only_because_podcast_is_not_in_this_beta() -> None:
    """Owner decision 2026-09-01: Podcast is a "coming soon" card, so there is
    no podcast job to wait for and never a podcast URL to include."""

    from civiccast.publish.notifications import build_notification_payload

    payload = build_notification_payload(
        asset_id="meeting-42",
        title="Council Meeting",
        published_at=datetime(2026, 6, 10, tzinfo=UTC),
        public_base_url=_PUBLIC_BASE,
    )

    assert payload is not None
    assert payload.podcast_url is None
    assert payload.portal_url == f"{_PUBLIC_BASE}/#/watch/meeting-42"


def test_no_public_base_url_means_no_invented_link() -> None:
    from civiccast.publish.notifications import build_notification_payload

    payload = build_notification_payload(
        asset_id="meeting-42",
        title="Council Meeting",
        published_at=datetime(2026, 6, 10, tzinfo=UTC),
        public_base_url="",
    )

    assert payload is None


def test_the_persisted_summary_is_bounded_but_its_counts_are_not() -> None:
    """The summary rides in the publish run's JSON column, so it must be bounded.

    A station with thousands of confirmed subscribers must not grow that row
    without limit -- but a bounded list must never produce a misleading count.
    """

    from civiccast.publish.notifications import (
        NOTIFICATION_SUMMARY_MAX_DELIVERIES,
        summarize_outcomes,
    )
    from civiccast.subscribe.models import NotificationDeliveryOutcomeRecord

    now = datetime(2026, 6, 10, tzinfo=UTC)
    records = [
        NotificationDeliveryOutcomeRecord(
            delivery_key=f"ndk-{index:04d}",
            publication_id="pub:meeting-42",
            asset_id="meeting-42",
            subscription_id=f"sub-{index:04d}",
            target_type="channel",
            target_id="government",
            transport="email",
            # N1: deliberately the LAST subscription id, well past the cap, so
            # the "non-sent rows first" sort key is what saves it. Putting the
            # failure at index 0 would have passed even with no sort at all.
            outcome="failed" if index == NOTIFICATION_SUMMARY_MAX_DELIVERIES + 24 else "sent",
            attempts=1,
            created_at=now,
            updated_at=now,
        )
        for index in range(NOTIFICATION_SUMMARY_MAX_DELIVERIES + 25)
    ]

    summary = summarize_outcomes(records, publication_id="pub:meeting-42")

    assert summary.intended == NOTIFICATION_SUMMARY_MAX_DELIVERIES + 25
    assert summary.sent == NOTIFICATION_SUMMARY_MAX_DELIVERIES + 24
    assert summary.failed == 1
    assert len(summary.deliveries) == NOTIFICATION_SUMMARY_MAX_DELIVERIES
    assert summary.deliveries_truncated is True
    # The row that needs attention survives the truncation even though its id
    # sorts last of all 225.
    assert summary.deliveries[0].outcome == "failed"
    assert summary.deliveries[0].subscription_id == (
        f"sub-{NOTIFICATION_SUMMARY_MAX_DELIVERIES + 24:04d}"
    )


class TestReceiptStorageFailuresAreBounded:
    def test_an_unwritable_claim_skips_that_recipient_instead_of_sending_unguarded(
        self,
    ) -> None:
        """No guard means no send: a missing notice is recoverable, a duplicate is not."""

        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        _confirmed_email(subscribe_store, SECOND_EMAIL)
        mailbox = LocalMailbox()

        class _StoreThatCannotClaimOnce(InMemoryNotificationDeliveryStore):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def claim(self, **kwargs):  # type: ignore[no-untyped-def]
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("durable storage is unavailable")
                return super().claim(**kwargs)

        delivery_store = _StoreThatCannotClaimOnce()
        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            publish_store=InMemoryPublishStore(),
            mailbox=mailbox,
        )

        # The unguarded recipient was skipped; the next one still went out.
        assert len(mailbox.messages) == 1
        summary = _surface(record).notification_summary
        assert summary is not None
        assert summary.intended == 1
        assert summary.sent == 1
        # M3: a run that could not write a receipt must never read as
        # "no subscribers" or as a clean partial -- the operator is told the
        # database is the thing to fix.
        surface = _surface(record)
        assert surface.state == "failed"
        assert surface.message == (
            "Delivery receipts could not be written, so no notices were sent. "
            "Fix the database and retry."
        )
        assert "durable storage" in surface.next_step

    def test_an_unwritable_receipt_does_not_stop_later_recipients(self) -> None:
        """The notice already went out; losing the receipt must not abort the fan-out."""

        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        _confirmed_email(subscribe_store, SECOND_EMAIL)
        mailbox = LocalMailbox()

        class _StoreThatCannotRecordOnce(InMemoryNotificationDeliveryStore):
            def __init__(self) -> None:
                super().__init__()
                self.calls = 0

            def record_attempt(self, **kwargs):  # type: ignore[no-untyped-def]
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("durable storage is unavailable")
                return super().record_attempt(**kwargs)

        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=_StoreThatCannotRecordOnce(),
            publish_store=InMemoryPublishStore(),
            mailbox=mailbox,
        )

        assert len(mailbox.messages) == 2
        summary = _surface(record).notification_summary
        assert summary is not None
        # Two intended, one receipt written -- so the surface is NOT green.
        assert summary.intended == 2
        assert summary.sent == 1
        assert summary.pending == 1
        assert _surface(record).state == "partial"


class TestUnsubscribeIsAlwaysOffered:
    """B2: a government notice a resident cannot leave is a consent failure."""

    def test_the_mail_body_and_list_unsubscribe_header_carry_the_recipients_own_link(
        self,
    ) -> None:
        subscribe_store = InMemorySubscribeStore()
        created = _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        mailbox = LocalMailbox()

        _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=mailbox,
        )

        record = subscribe_store.get(created.subscription_id)
        assert record is not None
        expected = (
            f"{_PUBLIC_BASE}/api/public/subscribe/unsubscribe"
            f"?token={quote(record.unsubscribe_token, safe='')}"
        )
        message = mailbox.messages[-1]
        assert expected in message["body"]
        assert "Stop receiving these notices" in message["body"]
        assert message["list_unsubscribe"] == f"<{expected}>"

    def test_a_real_smtp_message_carries_both_unsubscribe_headers(
        self, smtp_server: _LoopbackSmtpServer
    ) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)

        _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=_smtp_mailbox(smtp_server),
        )

        wire = "\n".join(smtp_server.bodies)
        assert "List-Unsubscribe: <" in wire
        assert "List-Unsubscribe-Post: List-Unsubscribe=One-Click" in wire
        assert "/api/public/subscribe/unsubscribe?token=" in wire
        # N3: no episode, so no podcast line at all.
        assert "Podcast:" not in wire

    def test_each_recipient_gets_their_own_token_never_a_shared_one(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        first = _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        second = _confirmed_email(subscribe_store, SECOND_EMAIL)
        mailbox = LocalMailbox()

        _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=mailbox,
        )

        links = {message["list_unsubscribe"] for message in mailbox.messages}
        assert len(links) == 2, "a shared unsubscribe link would let one resident stop another"
        first_record = subscribe_store.get(first.subscription_id)
        second_record = subscribe_store.get(second.subscription_id)
        assert first_record is not None and second_record is not None
        assert first_record.unsubscribe_token != second_record.unsubscribe_token

    def test_the_webhook_payload_carries_the_same_link(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_webhook(subscribe_store, WEBHOOK_URL)
        seen: list[NotificationPayload] = []

        class _RecordingWebhooks:
            def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
                seen.append(payload)
                return "sig"

        _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            webhook_client=_RecordingWebhooks(),
        )

        assert seen[0].unsubscribe_url is not None
        assert seen[0].unsubscribe_url.startswith(
            f"{_PUBLIC_BASE}/api/public/subscribe/unsubscribe?token="
        )

    def test_the_queued_retry_row_stores_no_unsubscribe_token(self) -> None:
        """A durable queue row should not hold a capability token it can rebuild."""

        subscribe_store = InMemorySubscribeStore()
        _confirmed_webhook(subscribe_store, WEBHOOK_URL)

        class _BrokenWebhooks:
            def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
                raise RuntimeError("connection refused")

        _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            webhook_client=_BrokenWebhooks(),
        )

        queued = subscribe_store.list_webhook_retries()
        assert len(queued) == 1
        assert queued[0].payload.get("unsubscribe_url") is None

    def test_a_retried_webhook_delivery_re_attaches_the_unsubscribe_link(self) -> None:
        """The retry must not deliver a notice the resident cannot opt out of."""

        from civiccast.subscribe.retry_worker import WebhookRetrySettings, WebhookRetryWorker

        subscribe_store = InMemorySubscribeStore()
        _confirmed_webhook(subscribe_store, WEBHOOK_URL)

        class _BrokenWebhooks:
            def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
                raise RuntimeError("connection refused")

        _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            webhook_client=_BrokenWebhooks(),
        )
        queued = subscribe_store.list_webhook_retries()[0]
        subscribe_store.save_webhook_retry(
            queued.model_copy(update={"next_attempt_at": datetime(2026, 1, 1, tzinfo=UTC)})
        )

        seen: list[NotificationPayload] = []

        class _RecordingWebhooks:
            def post(self, *, url: str, payload: NotificationPayload, secret: str) -> str:
                seen.append(payload)
                return "sig"

        WebhookRetryWorker(
            subscribe_store,
            _RecordingWebhooks(),  # type: ignore[arg-type]
            load_subscription_secrets(),
            settings=WebhookRetrySettings(),
        ).run_once(now=datetime(2026, 6, 11, tzinfo=UTC))

        assert len(seen) == 1
        assert seen[0].unsubscribe_url is not None
        assert "/api/public/subscribe/unsubscribe?token=" in seen[0].unsubscribe_url


class TestNoDoubleSendEndToEnd:
    def test_a_reentrant_second_dispatch_cannot_mail_the_same_recipient_twice(self) -> None:
        """B1 end-to-end: two runs interleaved mid-send, exactly one message.

        The second run starts WHILE the first is inside the mail adapter, which
        is precisely the window the old "not already sent" gate left open: the
        row exists and is still ``pending``, so both callers were cleared.
        """

        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        delivery_store = InMemoryNotificationDeliveryStore()
        publish_store = InMemoryPublishStore()
        asset = _asset()
        sends: list[str] = []
        reentered: list[str] = []

        class _MailboxThatReentersMidSend:
            def send_notification(self, *, email: str, payload: NotificationPayload) -> str:
                sends.append(email)
                if len(sends) == 1:
                    # A second worker arrives before this send has recorded a
                    # result. It must find the delivery already owned.
                    second = deliver_publication_notifications(
                        asset_id=asset.asset_id,
                        title=asset.title,
                        published_at=datetime(2026, 6, 10, tzinfo=UTC),
                        targets=resolve_publication_targets(asset),
                        manifest_url=asset.manifest_url,
                        public_base_url=_PUBLIC_BASE,
                        subscribe_store=subscribe_store,
                        delivery_store=delivery_store,
                        mailbox=self,
                    )
                    reentered.append(second.state)
                return f"mail:{len(sends)}"

        record = _approve(
            asset,
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            publish_store=publish_store,
            mailbox=_MailboxThatReentersMidSend(),
        )

        assert sends == [RESIDENT_EMAIL], "the interleaved run sent a duplicate notice"
        # The interleaved run observed the in-flight delivery, not a success.
        assert reentered == ["pending"]
        assert _surface(record).state == "succeeded"


class TestRetryReachesNewlyConfirmedSubscribers:
    def test_a_subscriber_confirmed_after_approval_is_reached_by_the_retry(self) -> None:
        """M2: retry means reach every confirmed subscriber not yet sent."""

        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        delivery_store = InMemoryNotificationDeliveryStore()
        publish_store = InMemoryPublishStore()
        mailbox = LocalMailbox()
        asset = _asset()

        first = _approve(
            asset,
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            publish_store=publish_store,
            mailbox=mailbox,
        )
        first_summary = _surface(first).notification_summary
        assert first_summary is not None
        assert first_summary.intended == 1

        # A resident confirms between the approval and the retry.
        _confirmed_email(subscribe_store, SECOND_EMAIL)

        retried = retry_publish_surface(
            asset=asset,
            surface_id="subscriber-notifications",
            request=PublishRetryRequest(
                operator_id="staff-1", operator_display_name="Avery Operator"
            ),
            store=publish_store,
            registry=_registry(mailbox=mailbox),
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            target_lookup=StaticChannelAssociationLookup(),
        )

        summary = _surface(retried).notification_summary
        assert summary is not None
        assert summary.intended == 2, "the retry starved a newly-confirmed subscriber"
        assert summary.sent == 2
        assert [message["to"] for message in mailbox.messages] == [RESIDENT_EMAIL, SECOND_EMAIL]
        assert _surface(retried).state == "succeeded"


class TestSimulatedDeliveryIsNeverGreen:
    def test_mock_adapters_mark_the_surface_simulated_and_not_ok(self) -> None:
        """M4: a mock accepted the notice; nobody received it."""

        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)

        record = _approve(
            _asset(),
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=LocalMailbox(),
        )

        surface = _surface(record)
        assert surface.state == "succeeded"
        assert surface.simulated is True
        assert surface.health != "ok"
        assert "SIMULATED" in surface.message
        assert "CIVICCAST_PROVIDER_MAIL" in surface.next_step

    def test_a_real_adapter_is_not_marked_simulated(
        self, smtp_server: _LoopbackSmtpServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        registry = default_registry()
        registry.register(PROVIDER_KIND_MAIL, "real", lambda: _smtp_mailbox(smtp_server))
        monkeypatch.setenv("CIVICCAST_PROVIDER_MAIL", "real")

        record = approve_publish(
            asset=_asset(),
            request=PublishApprovalRequest(
                operator_id="staff-1",
                operator_display_name="Avery Operator",
                approved_surface_ids=["subscriber-notifications"],
            ),
            store=InMemoryPublishStore(),
            registry=registry,
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            target_lookup=StaticChannelAssociationLookup(),
        )

        surface = _surface(record)
        assert smtp_server.recipients == [RESIDENT_EMAIL]
        assert surface.state == "succeeded"
        assert surface.simulated is False
        assert surface.health == "ok"
        assert "SIMULATED" not in surface.message

    def test_an_unused_channels_mock_provider_does_not_taint_a_real_one(
        self, smtp_server: _LoopbackSmtpServer, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only channels that actually had a recipient count toward simulated."""

        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)  # no webhook subscribers
        registry = default_registry()
        registry.register(PROVIDER_KIND_MAIL, "real", lambda: _smtp_mailbox(smtp_server))
        monkeypatch.setenv("CIVICCAST_PROVIDER_MAIL", "real")

        record = approve_publish(
            asset=_asset(),
            request=PublishApprovalRequest(
                operator_id="staff-1",
                operator_display_name="Avery Operator",
                approved_surface_ids=["subscriber-notifications"],
            ),
            store=InMemoryPublishStore(),
            registry=registry,
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            target_lookup=StaticChannelAssociationLookup(),
        )

        assert _surface(record).simulated is False


class TestPreflightAndDeliveryCountTheSameRecipients:
    """M1: readiness used one hardcoded target while delivery used the real ones."""

    def test_preflight_sees_a_meeting_body_subscriber_delivery_would_reach(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(
            subscribe_store,
            RESIDENT_EMAIL,
            target_type="meeting_body",
            target_id="planning-commission",
        )
        asset = _asset(meeting_body="planning-commission")

        preflight = build_publish_preflight(
            asset,
            registry=_registry(),
            subscribe_store=subscribe_store,
            target_lookup=StaticChannelAssociationLookup(),
        )
        check = next(c for c in preflight.checks if c.id == "subscriber-notifications")

        # The old hardcoded channel/government target could not see this
        # recipient at all, so preflight said "nothing to send" and approval
        # then mailed them.
        assert "no confirmed subscribers" not in check.message
        assert "simulated" in check.message

        record = _approve(
            asset,
            subscribe_store=subscribe_store,
            delivery_store=InMemoryNotificationDeliveryStore(),
            publish_store=InMemoryPublishStore(),
            mailbox=LocalMailbox(),
        )
        summary = _surface(record).notification_summary
        assert summary is not None and summary.intended == 1

    def test_preflight_reports_nothing_to_send_when_the_targets_have_no_subscribers(
        self,
    ) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(
            subscribe_store,
            RESIDENT_EMAIL,
            target_type="meeting_body",
            target_id="a-different-body",
        )

        preflight = build_publish_preflight(
            _asset(meeting_body="planning-commission"),
            registry=_registry(),
            subscribe_store=subscribe_store,
            target_lookup=StaticChannelAssociationLookup(),
        )
        check = next(c for c in preflight.checks if c.id == "subscriber-notifications")

        assert "no confirmed subscribers" in check.message
        assert check.health == "ok"

    def test_one_subscriber_matching_two_targets_is_counted_once(self) -> None:
        subscribe_store = InMemorySubscribeStore()
        _confirmed_email(subscribe_store, RESIDENT_EMAIL)
        rows = subscribe_store.list_confirmed_for_target(
            target_type="channel", target_id="government"
        )

        class _StoreMatchingEveryTarget(InMemorySubscribeStore):
            def list_confirmed_for_target(self, *, target_type: str, target_id: str):  # type: ignore[no-untyped-def]
                return list(rows)

        preflight = build_publish_preflight(
            _asset(meeting_body="planning-commission"),
            registry=_registry(),
            subscribe_store=_StoreMatchingEveryTarget(),
            target_lookup=StaticChannelAssociationLookup(),
        )
        check = next(c for c in preflight.checks if c.id == "subscriber-notifications")

        # One channel reference, not one per matching target.
        assert check.credential_reference is not None
        assert check.credential_reference.count("CIVICCAST_PROVIDER_MAIL") == 1


def test_the_podcast_surface_uses_the_resolved_channel_not_a_hardcoded_one() -> None:
    """M1: the episode belongs to the channel the asset actually publishes to."""

    record = approve_publish(
        asset=_asset(),
        request=PublishApprovalRequest(
            operator_id="staff-1",
            operator_display_name="Avery Operator",
            approved_surface_ids=["podcast"],
        ),
        store=InMemoryPublishStore(),
        subscribe_store=InMemorySubscribeStore(),
        delivery_store=InMemoryNotificationDeliveryStore(),
        target_lookup=StaticChannelAssociationLookup(by_asset_id={"meeting-42": "education"}),
    )

    podcast = next(surface for surface in record.surfaces if surface.id == "podcast")
    assert podcast.url is not None
    assert "/podcast/education.xml" in podcast.url


def test_an_unwritable_receipt_store_shows_the_operator_a_degraded_recording() -> None:
    """M3, at the dashboard level: reach_degraded, never a clean "Complete"."""

    subscribe_store = InMemorySubscribeStore()
    _confirmed_email(subscribe_store, RESIDENT_EMAIL)

    class _StoreThatCannotClaim(InMemoryNotificationDeliveryStore):
        def claim(self, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("durable storage is unavailable")

    asset = _asset()
    record = approve_publish(
        asset=asset,
        request=PublishApprovalRequest(
            operator_id="staff-1", operator_display_name="Avery Operator"
        ),
        store=InMemoryPublishStore(),
        subscribe_store=subscribe_store,
        delivery_store=_StoreThatCannotClaim(),
        target_lookup=StaticChannelAssociationLookup(),
    )
    status = build_publish_asset_status(asset, record)
    surface = next(s for s in status.surfaces if s.id == "subscriber-notifications")

    assert surface.state == "failed"
    assert surface.message.startswith("Delivery receipts could not be written")
    assert status.reach_degraded is True
    assert status.dashboard_state != "complete"
