# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""ActivityPub delivery retry worker tests (Stage F).

Capability gap: delivery was production-wired with "no retry/backoff/
dead-letter worker" — a follower inbox that is down at publish time never
hears about the recording, silently. Failed deliveries now enqueue durably
and a worker retries them with bounded exponential backoff until delivered
or dead-lettered.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from civiccast.activitypub.models import FollowerRecord, OutboxRecord
from civiccast.activitypub.remote import DeliveryResult
from civiccast.activitypub.retry_worker import (
    ActivityPubRetrySettings,
    ActivityPubRetryWorker,
)
from civiccast.activitypub.service import deliver_publish_activity
from civiccast.activitypub.store import InMemoryActivityPubStore

_NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


class ScriptedDeliveryClient:
    """Delivery client returning scripted status codes per call."""

    def __init__(self, status_codes: list[int]) -> None:
        self._status_codes = list(status_codes)
        self.calls: list[str] = []

    def deliver(self, *, inbox_url: str, activity: dict[str, Any]) -> DeliveryResult:
        self.calls.append(inbox_url)
        status = self._status_codes.pop(0) if self._status_codes else 202
        return DeliveryResult(
            inbox_url=inbox_url,
            status_code=status,
            response_body="" if status < 400 else "remote error",
            delivered_at=_NOW,
        )


def _store_with_follower() -> InMemoryActivityPubStore:
    store = InMemoryActivityPubStore()
    store.upsert_follower(
        FollowerRecord(
            actor="https://town.example/users/resident",
            domain="town.example",
            status="accepted",
            activity_id="https://town.example/activities/follow-1",
            inbox_url="https://town.example/users/resident/inbox",
            shared_inbox_url=None,
            public_key_id="https://town.example/users/resident#main-key",
            public_key_pem="-----BEGIN PUBLIC KEY-----\nstub\n-----END PUBLIC KEY-----",
            created_at=_NOW,
        )
    )
    return store


def _outbox_record() -> OutboxRecord:
    return OutboxRecord(
        activity_id="https://station.example/activities/publish-1",
        activity={"type": "Create", "id": "https://station.example/activities/publish-1"},
        created_at=_NOW,
    )


def _settings(**overrides: object) -> ActivityPubRetrySettings:
    values: dict[str, Any] = {
        "mode": "inline",
        "poll_seconds": 60.0,
        "backoff_seconds": 120.0,
        "max_attempts": 8,
    }
    values.update(overrides)
    return ActivityPubRetrySettings(**values)


class TestEnqueueOnFailure:
    def test_failed_delivery_enqueues_a_retry(self) -> None:
        store = _store_with_follower()
        client = ScriptedDeliveryClient([503])

        deliver_publish_activity(record=_outbox_record(), store=store, delivery_client=client)

        pending = store.list_delivery_retries()
        assert len(pending) == 1
        row = pending[0]
        assert row.state == "pending"
        assert row.attempts == 1
        assert row.last_status_code == 503
        assert row.next_attempt_at is not None
        assert row.inbox_url == "https://town.example/users/resident/inbox"

    def test_network_error_status_zero_enqueues(self) -> None:
        store = _store_with_follower()
        client = ScriptedDeliveryClient([0])
        deliver_publish_activity(record=_outbox_record(), store=store, delivery_client=client)
        assert len(store.list_delivery_retries()) == 1

    def test_successful_delivery_does_not_enqueue(self) -> None:
        store = _store_with_follower()
        client = ScriptedDeliveryClient([202])
        deliver_publish_activity(record=_outbox_record(), store=store, delivery_client=client)
        assert store.list_delivery_retries() == []


class TestRetryWorker:
    def _enqueue_failure(self, store: InMemoryActivityPubStore) -> None:
        client = ScriptedDeliveryClient([503])
        # Enqueue at the fixed test clock so next_attempt_at is deterministic
        # relative to the times we scan the worker with (otherwise the enqueue
        # uses real wall-clock and a fixed-past scan time looks not-yet-due).
        deliver_publish_activity(
            record=_outbox_record(), store=store, delivery_client=client, now=_NOW
        )

    def test_due_retry_that_succeeds_is_delivered_and_recorded(self) -> None:
        store = _store_with_follower()
        self._enqueue_failure(store)
        retry_client = ScriptedDeliveryClient([202])
        worker = ActivityPubRetryWorker(store, retry_client, settings=_settings())

        later = _NOW + timedelta(hours=1)
        worker.run_once(now=later)

        rows = store.list_delivery_retries()
        assert rows[0].state == "delivered"
        assert retry_client.calls == ["https://town.example/users/resident/inbox"]
        # The successful retry shows up in the normal delivery log too.
        deliveries = store.list_deliveries(
            activity_id="https://station.example/activities/publish-1"
        )
        assert any(d.status_code == 202 for d in deliveries)

    def test_not_yet_due_rows_are_left_alone(self) -> None:
        from civiccast.activitypub.retry_worker import enqueue_failed_delivery

        store = _store_with_follower()
        enqueue_failed_delivery(
            store=store,
            activity_id="https://station.example/activities/publish-1",
            inbox_url="https://town.example/users/resident/inbox",
            activity={"type": "Create"},
            status_code=503,
            error="remote error",
            backoff_seconds=120,
            now=_NOW,
        )
        retry_client = ScriptedDeliveryClient([202])
        worker = ActivityPubRetryWorker(store, retry_client, settings=_settings())

        worker.run_once(now=_NOW + timedelta(seconds=60))  # backoff has not elapsed

        assert retry_client.calls == []
        assert store.list_delivery_retries()[0].state == "pending"

    def test_repeated_failure_backs_off_then_dead_letters(self) -> None:
        store = _store_with_follower()
        self._enqueue_failure(store)
        retry_client = ScriptedDeliveryClient([503] * 10)
        worker = ActivityPubRetryWorker(
            store, retry_client, settings=_settings(max_attempts=3, backoff_seconds=60)
        )

        first = store.list_delivery_retries()[0]
        assert first.attempts == 1

        worker.run_once(now=_NOW + timedelta(hours=1))
        second = store.list_delivery_retries()[0]
        assert second.attempts == 2
        assert second.state == "pending"
        assert second.next_attempt_at is not None
        assert second.next_attempt_at > _NOW + timedelta(hours=1)

        worker.run_once(now=_NOW + timedelta(hours=2))
        final = store.list_delivery_retries()[0]
        assert final.attempts == 3
        assert final.state == "dead_letter"
        assert final.next_attempt_at is None
        assert final.last_status_code == 503

    def test_dead_letter_rows_are_not_rescanned(self) -> None:
        store = _store_with_follower()
        self._enqueue_failure(store)
        retry_client = ScriptedDeliveryClient([503] * 10)
        worker = ActivityPubRetryWorker(
            store, retry_client, settings=_settings(max_attempts=2, backoff_seconds=0)
        )
        worker.run_once(now=_NOW + timedelta(hours=1))
        assert store.list_delivery_retries()[0].state == "dead_letter"
        calls_after_dead_letter = len(retry_client.calls)

        worker.run_once(now=_NOW + timedelta(hours=2))

        assert len(retry_client.calls) == calls_after_dead_letter

    def test_run_forever_survives_scan_exception(self) -> None:
        import threading
        import time as time_module

        class ExplodingStore(InMemoryActivityPubStore):
            def __init__(self) -> None:
                super().__init__()
                self.scans = 0

            def due_delivery_retries(self, *, now: datetime):  # type: ignore[override]
                self.scans += 1
                if self.scans == 1:
                    raise RuntimeError("transient db error")
                return super().due_delivery_retries(now=now)

        store = ExplodingStore()
        worker = ActivityPubRetryWorker(store, ScriptedDeliveryClient([]), settings=_settings())
        stop = threading.Event()
        thread = threading.Thread(
            target=worker.run_forever,
            kwargs={"poll_seconds": 0.01, "stop_event": stop},
            daemon=True,
        )
        thread.start()
        deadline = time_module.monotonic() + 5.0
        while store.scans < 3 and time_module.monotonic() < deadline:
            time_module.sleep(0.01)
        stop.set()
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        assert store.scans >= 3


class TestSettings:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in (
            "CIVICCAST_ACTIVITYPUB_RETRY_WORKER",
            "CIVICCAST_ACTIVITYPUB_RETRY_POLL_SECONDS",
            "CIVICCAST_ACTIVITYPUB_RETRY_BACKOFF_SECONDS",
            "CIVICCAST_ACTIVITYPUB_RETRY_MAX_ATTEMPTS",
        ):
            monkeypatch.delenv(name, raising=False)
        settings = ActivityPubRetrySettings.from_env()
        assert settings.mode == "inline"
        assert settings.max_attempts == 8

    def test_invalid_mode_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_ACTIVITYPUB_RETRY_WORKER", "sometimes")
        with pytest.raises(ValueError, match="CIVICCAST_ACTIVITYPUB_RETRY_WORKER"):
            ActivityPubRetrySettings.from_env()
