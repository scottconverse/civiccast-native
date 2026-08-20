# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the v1.2 platform broker substrate."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from importlib import import_module


class TestBrokerProtocolContract:
    def test_in_process_broker_implements_protocol_when_imported(self) -> None:
        broker_module = import_module("civiccast.platform.broker")

        client = broker_module.InProcessBrokerClient()

        assert isinstance(client, broker_module.BrokerClient)

    def test_publish_receipt_is_immutable_when_event_is_recorded(self) -> None:
        broker_module = import_module("civiccast.platform.broker")
        client = broker_module.InProcessBrokerClient()
        event = broker_module.BrokerEvent(
            subject="publish.asset.approved",
            payload={"asset_id": "council-2026-05-08", "status": "approved"},
        )

        receipt = client.publish(event)

        assert receipt.subject == "publish.asset.approved"
        assert receipt.message_id
        assert receipt.published_at.tzinfo is not None
        try:
            receipt.subject = "publish.asset.rewritten"
        except FrozenInstanceError:
            pass
        else:  # pragma: no cover - failing red test should not reach this on correct code.
            raise AssertionError("BrokerPublishReceipt must be immutable.")

    def test_invalid_subject_fails_before_publish_when_not_documented(self) -> None:
        broker_module = import_module("civiccast.platform.broker")
        client = broker_module.InProcessBrokerClient()
        event = broker_module.BrokerEvent(
            subject="provider.nats.raw_subject",
            payload={"asset_id": "council-2026-05-08"},
        )

        try:
            client.publish(event)
        except ValueError as exc:
            assert "documented broker subject" in str(exc)
        else:  # pragma: no cover - failing red test should not reach this on correct code.
            raise AssertionError("Undocumented broker subjects must fail before publish.")

    def test_replay_returns_recorded_events_for_subject(self) -> None:
        broker_module = import_module("civiccast.platform.broker")
        client = broker_module.InProcessBrokerClient()
        event = broker_module.BrokerEvent(
            subject="publish.asset.approved",
            payload={"asset_id": "council-2026-05-08", "status": "approved"},
        )

        client.publish(event)

        assert client.replay("publish.asset.approved") == [event]

    def test_subscribed_handler_receives_future_events(self) -> None:
        broker_module = import_module("civiccast.platform.broker")
        client = broker_module.InProcessBrokerClient()
        event = broker_module.BrokerEvent(
            subject="publish.asset.approved",
            payload={"asset_id": "council-2026-05-08", "status": "approved"},
        )
        received = []

        client.subscribe("publish.asset.approved", received.append)
        client.publish(event)

        assert received == [event]

    def test_invalid_subscription_subject_fails_before_registration(self) -> None:
        broker_module = import_module("civiccast.platform.broker")
        client = broker_module.InProcessBrokerClient()

        try:
            client.subscribe("provider.nats.raw_subject", lambda event: None)
        except ValueError as exc:
            assert "documented broker subject" in str(exc)
        else:  # pragma: no cover - failing red test should not reach this on correct code.
            raise AssertionError(
                "Undocumented subscription subjects must fail before registration."
            )
