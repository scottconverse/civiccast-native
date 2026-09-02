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

import pytest

from civiccast.platform.providers import (
    PROVIDER_KIND_MAIL,
    PROVIDER_KIND_WEBHOOK,
    ProviderRegistry,
    default_registry,
)
from civiccast.publish.models import PublishApprovalRequest, PublishRetryRequest
from civiccast.publish.service import (
    approve_publish,
    build_publish_asset_status,
    retry_publish_surface,
)
from civiccast.publish.store import InMemoryPublishStore
from civiccast.publish.targets import StaticChannelAssociationLookup
from civiccast.schedule.models import StaffAssetRow
from civiccast.subscribe.delivery import LocalMailbox, LocalWebhookClient
from civiccast.subscribe.models import (
    NotificationPayload,
    SubscriptionPublicResponse,
    SubscriptionSignupRequest,
    SubscriptionWebhookRequest,
)
from civiccast.subscribe.outcome_store import InMemoryNotificationDeliveryStore
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
            outcome="failed" if index == 0 else "sent",
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
    # The row that needs attention survives the truncation.
    assert summary.deliveries[0].outcome == "failed"


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
