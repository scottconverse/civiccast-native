# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real webhook adapter + durable retry/dead-letter tests (issue #111).

No live external calls: the HTTP contract is tested against
``httpx.MockTransport`` and the integration proof runs an in-process HTTP
server on a loopback socket. No real secrets appear anywhere.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401 -- ATTACH ':memory:' AS civiccast on SQLite connect
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.platform.providers import PROVIDER_KIND_WEBHOOK, default_registry
from civiccast.subscribe.crypto import DeterministicSecretBox
from civiccast.subscribe.delivery import LocalWebhookClient
from civiccast.subscribe.models import (
    NotificationPayload,
    SubscriptionRecord,
    WebhookRetryRecord,
)
from civiccast.subscribe.retry_worker import (
    WebhookRetrySettings,
    WebhookRetryWorker,
    enqueue_failed_webhook_delivery,
)
from civiccast.subscribe.secrets import SubscriptionSecrets
from civiccast.subscribe.service import dispatch_notifications
from civiccast.subscribe.store import InMemorySubscribeStore, PostgresSubscribeStore
from civiccast.subscribe.webhook import HttpWebhookClient, WebhookSettings

_PAYLOAD = NotificationPayload(
    asset_id="meeting-42",
    title="Planning Commission 2026-06-10",
    portal_url="https://portal.example/watch/meeting-42",
    podcast_url=None,
    summary=None,
    published_at=datetime(2026, 6, 10, 19, 0, tzinfo=UTC),
)


class TestHttpWebhookClient:
    def test_posts_canonical_signed_json(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        client = HttpWebhookClient(transport=httpx.MockTransport(handler))
        signature = client.post(
            url="https://hooks.example/civiccast", payload=_PAYLOAD, secret="hook-secret"
        )

        assert len(seen) == 1
        request = seen[0]
        assert request.method == "POST"
        assert str(request.url) == "https://hooks.example/civiccast"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["x-civiccast-asset-id"] == "meeting-42"
        body = request.read()
        # The signature covers the exact bytes on the wire.
        expected = hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
        assert signature == expected
        assert request.headers["x-civiccast-signature"] == f"sha256={expected}"
        # Canonical JSON: sorted keys, compact separators.
        assert (
            body
            == json.dumps(
                _PAYLOAD.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode()
        )

    def test_matches_the_mock_signature_for_the_same_payload_and_secret(self) -> None:
        real = HttpWebhookClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
        mock = LocalWebhookClient()

        real_signature = real.post(url="https://hooks.example/h", payload=_PAYLOAD, secret="s")
        mock_signature = mock.post(url="https://hooks.example/h", payload=_PAYLOAD, secret="s")

        assert real_signature == mock_signature

    def test_failed_delivery_raises_instead_of_claiming_success(self) -> None:
        client = HttpWebhookClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500, text="boom"))
        )
        with pytest.raises(httpx.HTTPStatusError):
            client.post(url="https://hooks.example/h", payload=_PAYLOAD, secret="hook-secret")

    def test_error_path_never_echoes_the_secret(self) -> None:
        client = HttpWebhookClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(500, text="boom"))
        )
        with pytest.raises(httpx.HTTPStatusError) as excinfo:
            client.post(
                url="https://hooks.example/h",
                payload=_PAYLOAD,
                secret="webhook-secret-sentinel",
            )
        rendered = f"{excinfo.value!s} {excinfo.value!r}"
        assert "webhook-secret-sentinel" not in rendered

    def test_settings_from_env_validates_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_WEBHOOK_TIMEOUT_SECONDS", "not-a-number")
        with pytest.raises(ValueError, match="CIVICCAST_WEBHOOK_TIMEOUT_SECONDS"):
            WebhookSettings.from_env()
        monkeypatch.setenv("CIVICCAST_WEBHOOK_TIMEOUT_SECONDS", "0")
        with pytest.raises(ValueError, match="positive"):
            WebhookSettings.from_env()
        monkeypatch.setenv("CIVICCAST_WEBHOOK_TIMEOUT_SECONDS", "12.5")
        assert WebhookSettings.from_env().timeout_seconds == 12.5
        monkeypatch.delenv("CIVICCAST_WEBHOOK_TIMEOUT_SECONDS")
        assert WebhookSettings.from_env().timeout_seconds == 30.0


def _retry_record(
    *,
    retry_id: str = "swr-test-1",
    subscription_id: str = "sub-abc",
    attempts: int = 1,
    next_attempt_at: datetime | None = datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
) -> WebhookRetryRecord:
    return WebhookRetryRecord(
        retry_id=retry_id,
        subscription_id=subscription_id,
        payload=_PAYLOAD.model_dump(mode="json"),
        state="pending",
        attempts=attempts,
        next_attempt_at=next_attempt_at,
        last_status_code=500,
        last_error="boom",
        created_at=datetime(2026, 6, 11, 11, 0, tzinfo=UTC),
        updated_at=datetime(2026, 6, 11, 11, 0, tzinfo=UTC),
    )


class TestWebhookRetryQueueStores:
    def test_in_memory_store_round_trips_and_filters_due_rows(self) -> None:
        store = InMemorySubscribeStore()
        due = store.enqueue_webhook_retry(_retry_record())
        not_due = store.enqueue_webhook_retry(
            _retry_record(
                retry_id="swr-test-2",
                next_attempt_at=datetime(2026, 6, 11, 18, 0, tzinfo=UTC),
            )
        )

        now = datetime(2026, 6, 11, 12, 30, tzinfo=UTC)
        assert store.get_webhook_retry(due.retry_id) == due
        assert store.due_webhook_retries(now=now) == [due]
        assert {row.retry_id for row in store.list_webhook_retries()} == {
            due.retry_id,
            not_due.retry_id,
        }

        delivered = due.model_copy(
            update={"state": "delivered", "attempts": 2, "next_attempt_at": None}
        )
        store.save_webhook_retry(delivered)
        assert store.get_webhook_retry(due.retry_id) == delivered
        assert store.due_webhook_retries(now=now) == []

    def test_postgres_store_round_trips_with_sqlalchemy_engine(self) -> None:
        engine = create_engine("sqlite:///:memory:", future=True)
        bind_engine(engine)
        Base.metadata.create_all(engine)
        try:

            @contextmanager
            def session_factory() -> Iterator[Session]:
                sess = Session(bind=engine)
                try:
                    yield sess
                finally:
                    sess.close()

            store = PostgresSubscribeStore(session_factory)
            record = store.enqueue_webhook_retry(_retry_record())
            assert store.get_webhook_retry(record.retry_id) == record
            assert store.due_webhook_retries(now=datetime(2026, 6, 11, 12, 30, tzinfo=UTC)) == [
                record
            ]

            dead = record.model_copy(
                update={"state": "dead_letter", "attempts": 8, "next_attempt_at": None}
            )
            store.save_webhook_retry(dead)
            assert store.get_webhook_retry(record.retry_id) == dead
            assert store.due_webhook_retries(now=datetime(2026, 6, 11, 12, 30, tzinfo=UTC)) == []
            assert store.list_webhook_retries() == [dead]
        finally:
            reset_engine()
            engine.dispose()


class TestRegistrySelection:
    def test_real_resolves_http_client_and_mock_stays_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CIVICCAST_PROVIDER_WEBHOOK", raising=False)
        assert isinstance(default_registry().resolve(PROVIDER_KIND_WEBHOOK), LocalWebhookClient)
        monkeypatch.setenv("CIVICCAST_PROVIDER_WEBHOOK", "real")
        assert isinstance(default_registry().resolve(PROVIDER_KIND_WEBHOOK), HttpWebhookClient)


class TestLoopbackIntegration:
    """Issue #111 fake-server proof: a real socket receives the signed POST."""

    def test_delivers_a_verifiable_signed_post_over_a_real_socket(self) -> None:
        received: dict[str, object] = {}

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                received["path"] = self.path
                received["body"] = self.rfile.read(length)
                received["signature"] = self.headers.get("x-civiccast-signature")
                received["content_type"] = self.headers.get("content-type")
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_args: object) -> None:
                return None

        server = HTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            client = HttpWebhookClient(WebhookSettings(timeout_seconds=10.0))
            signature = client.post(
                url=f"http://127.0.0.1:{port}/hook",
                payload=_PAYLOAD,
                secret="loopback-hook-secret",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert received["path"] == "/hook"
        assert received["content_type"] == "application/json"
        body = received["body"]
        assert isinstance(body, bytes)
        expected = hmac.new(b"loopback-hook-secret", body, hashlib.sha256).hexdigest()
        assert signature == expected
        assert received["signature"] == f"sha256={expected}"
        assert json.loads(body)["asset_id"] == "meeting-42"


_TEST_SECRETS = SubscriptionSecrets(
    token_secret="webhook-worker-test-token-secret",
    legacy_token_secrets=(),
    secret_box=DeterministicSecretBox("webhook-worker-test-box-key"),
    source="test",
)


def _confirmed_webhook_subscription(
    store: InMemorySubscribeStore, *, url: str = "https://hooks.example/civiccast"
) -> SubscriptionRecord:
    box = _TEST_SECRETS.secret_box
    subscription_id = "sub-webhook-test"
    record = SubscriptionRecord(
        subscription_id=subscription_id,
        channel="webhook",
        encrypted_subscriber_handle=box.seal(url, aad=subscription_id),
        encrypted_webhook_secret=box.seal("hook-secret", aad=f"{subscription_id}:secret"),
        target_type="channel",
        target_id="government",
        status="confirmed",
        confirmation_token="confirm-token",
        unsubscribe_token="unsubscribe-token",
        created_at=datetime(2026, 6, 11, 10, 0, tzinfo=UTC),
        confirmed_at=datetime(2026, 6, 11, 10, 5, tzinfo=UTC),
    )
    store.create(record)
    return record


def _queued_retry(store: InMemorySubscribeStore, subscription_id: str) -> WebhookRetryRecord:
    return enqueue_failed_webhook_delivery(
        store=store,
        subscription_id=subscription_id,
        payload=_PAYLOAD.model_dump(mode="json"),
        status_code=500,
        error="boom",
        backoff_seconds=120.0,
        now=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
    )


class TestWebhookRetryWorker:
    def _worker(
        self,
        store: InMemorySubscribeStore,
        handler,  # type: ignore[no-untyped-def]
        *,
        max_attempts: int = 8,
    ) -> WebhookRetryWorker:
        client = HttpWebhookClient(transport=httpx.MockTransport(handler))
        settings = WebhookRetrySettings(
            mode="inline", poll_seconds=60.0, backoff_seconds=120.0, max_attempts=max_attempts
        )
        return WebhookRetryWorker(store, client, _TEST_SECRETS, settings=settings)

    def test_enqueue_counts_the_original_send_as_attempt_one(self) -> None:
        store = InMemorySubscribeStore()
        record = _queued_retry(store, "sub-webhook-test")
        assert record.attempts == 1
        assert record.state == "pending"
        assert record.next_attempt_at == datetime(2026, 6, 11, 12, 2, tzinfo=UTC)
        assert store.get_webhook_retry(record.retry_id) == record

    def test_successful_retry_delivers_with_a_verifiable_signature(self) -> None:
        store = InMemorySubscribeStore()
        _confirmed_webhook_subscription(store)
        record = _queued_retry(store, "sub-webhook-test")
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200)

        worker = self._worker(store, handler)
        processed = worker.run_once(now=datetime(2026, 6, 11, 12, 30, tzinfo=UTC))

        assert len(processed) == 1
        assert processed[0].state == "delivered"
        assert processed[0].attempts == 2
        assert store.get_webhook_retry(record.retry_id).state == "delivered"  # type: ignore[union-attr]
        request = seen[0]
        assert str(request.url) == "https://hooks.example/civiccast"
        body = request.read()
        expected = hmac.new(b"hook-secret", body, hashlib.sha256).hexdigest()
        assert request.headers["x-civiccast-signature"] == f"sha256={expected}"

    def test_failed_retry_backs_off_exponentially(self) -> None:
        store = InMemorySubscribeStore()
        _confirmed_webhook_subscription(store)
        record = _queued_retry(store, "sub-webhook-test")

        worker = self._worker(store, lambda _: httpx.Response(503, text="down"))
        now = datetime(2026, 6, 11, 12, 30, tzinfo=UTC)
        processed = worker.run_once(now=now)

        assert processed[0].state == "pending"
        assert processed[0].attempts == 2
        # backoff_seconds * 2 ** (attempts - 1) = 120 * 2 = 240s
        assert processed[0].next_attempt_at == now + timedelta(seconds=240)
        assert store.get_webhook_retry(record.retry_id).attempts == 2  # type: ignore[union-attr]

    def test_exhausted_attempts_dead_letter(self) -> None:
        store = InMemorySubscribeStore()
        _confirmed_webhook_subscription(store)
        _queued_retry(store, "sub-webhook-test")

        worker = self._worker(store, lambda _: httpx.Response(503, text="down"), max_attempts=2)
        processed = worker.run_once(now=datetime(2026, 6, 11, 12, 30, tzinfo=UTC))

        assert processed[0].state == "dead_letter"
        assert processed[0].attempts == 2
        assert processed[0].next_attempt_at is None

    def test_unsubscribed_subscription_dead_letters_without_a_call(self) -> None:
        store = InMemorySubscribeStore()
        record = _confirmed_webhook_subscription(store)
        store.update(record.model_copy(update={"status": "unsubscribed"}))
        _queued_retry(store, "sub-webhook-test")

        def handler(_: httpx.Request) -> httpx.Response:
            raise AssertionError("unsubscribed endpoints must never be called")

        worker = self._worker(store, handler)
        processed = worker.run_once(now=datetime(2026, 6, 11, 12, 30, tzinfo=UTC))

        assert processed[0].state == "dead_letter"
        assert "no longer confirmed" in processed[0].last_error

    def test_settings_from_env_validates_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_WEBHOOK_RETRY_WORKER", "sometimes")
        with pytest.raises(ValueError, match="CIVICCAST_WEBHOOK_RETRY_WORKER"):
            WebhookRetrySettings.from_env()
        monkeypatch.setenv("CIVICCAST_WEBHOOK_RETRY_WORKER", "off")
        assert WebhookRetrySettings.from_env().mode == "off"
        monkeypatch.delenv("CIVICCAST_WEBHOOK_RETRY_WORKER")
        assert WebhookRetrySettings.from_env().mode == "inline"


class TestDispatchQueuesFailures:
    def test_failed_real_webhook_dispatch_counts_failed_and_queues_retry(self) -> None:
        store = InMemorySubscribeStore()
        _confirmed_webhook_subscription(store)
        failing_client = HttpWebhookClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(502, text="bad gateway"))
        )

        response = dispatch_notifications(
            _PAYLOAD,
            store=store,
            secrets=_TEST_SECRETS,
            webhook_client=failing_client,
        )

        assert response.sent == 0
        assert response.failed == 1
        assert len(response.deliveries) == 1
        assert response.deliveries[0].status == "failed"
        assert "queued for retry" in response.deliveries[0].message
        queued = store.list_webhook_retries()
        assert len(queued) == 1
        assert queued[0].subscription_id == "sub-webhook-test"
        assert queued[0].state == "pending"
        assert queued[0].attempts == 1

    def test_successful_real_webhook_dispatch_stays_sent(self) -> None:
        store = InMemorySubscribeStore()
        _confirmed_webhook_subscription(store)
        client = HttpWebhookClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))

        response = dispatch_notifications(
            _PAYLOAD,
            store=store,
            secrets=_TEST_SECRETS,
            webhook_client=client,
        )

        assert response.sent == 1
        assert response.failed == 0
        assert store.list_webhook_retries() == []
