# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for the v1.2 NATS JetStream broker adapter."""

from __future__ import annotations

import asyncio
import ssl
from importlib import import_module
from types import SimpleNamespace

import pytest

from civiccast.certs.authority import LocalCertificateAuthority


def _adapter_module():
    return import_module("civiccast.platform.nats_broker")


def _broker_module():
    return import_module("civiccast.platform.broker")


def _production_config():
    broker_config = import_module("civiccast.platform.broker_config")
    return broker_config.BrokerConfig(
        mode="production",
        nats_url="tls://127.0.0.1:4222",
        stream_name="CIVICCAST_EVENTS",
        durable_name="civiccast-publish",
    )


class FakeJetStream:
    def __init__(self) -> None:
        self.streams: list[dict[str, object]] = []
        self.published: list[tuple[str, bytes]] = []

    def ensure_stream(self, config: dict[str, object]) -> None:
        self.streams.append(config)

    def publish(self, subject: str, payload: bytes):
        self.published.append((subject, payload))
        return SimpleNamespace(stream="CIVICCAST_EVENTS", seq=42, domain="local")


class TestNATSJetStreamBrokerClient:
    def test_adapter_creates_or_validates_configured_stream(self) -> None:
        nats_broker = _adapter_module()
        fake = FakeJetStream()

        client = nats_broker.NATSJetStreamBrokerClient(
            _production_config(),
            jetstream=fake,
        )
        client.ensure_ready()

        assert fake.streams == [
            {
                "name": "CIVICCAST_EVENTS",
                "subjects": ["civiccast.publish.asset.approved"],
                "retention": "limits",
                "ack_policy": "explicit",
            }
        ]

    def test_publish_returns_immutable_receipt_with_provider_ack_metadata(self) -> None:
        nats_broker = _adapter_module()
        broker = _broker_module()
        client = nats_broker.NATSJetStreamBrokerClient(
            _production_config(),
            jetstream=FakeJetStream(),
        )
        event = broker.BrokerEvent(
            subject="publish.asset.approved",
            payload={"asset_id": "council-2026-05-19", "status": "approved"},
        )

        receipt = client.publish(event)

        assert receipt.subject == "publish.asset.approved"
        assert receipt.provider_stream == "CIVICCAST_EVENTS"
        assert receipt.provider_sequence == 42
        with pytest.raises(Exception):
            receipt.provider_sequence = 43

    def test_replay_returns_recorded_events_through_durable_consumer(self) -> None:
        nats_broker = _adapter_module()
        client = nats_broker.NATSJetStreamBrokerClient(
            _production_config(),
            jetstream=FakeJetStream(),
        )

        events = client.replay("publish.asset.approved")

        assert events
        assert all(event.subject == "publish.asset.approved" for event in events)

    def test_subscribe_dispatches_future_events_to_handler(self) -> None:
        nats_broker = _adapter_module()
        broker = _broker_module()
        client = nats_broker.NATSJetStreamBrokerClient(
            _production_config(),
            jetstream=FakeJetStream(),
        )
        received = []

        client.subscribe("publish.asset.approved", received.append)
        client.publish(
            broker.BrokerEvent(
                subject="publish.asset.approved",
                payload={"asset_id": "council-2026-05-19"},
            )
        )

        assert [event.subject for event in received] == ["publish.asset.approved"]

    def test_provider_errors_become_operator_actionable_platform_errors(self) -> None:
        nats_broker = _adapter_module()
        broker = _broker_module()

        class BrokenJetStream:
            def publish(self, subject: str, payload: bytes) -> None:
                raise TimeoutError("connection refused")

        client = nats_broker.NATSJetStreamBrokerClient(
            _production_config(),
            jetstream=BrokenJetStream(),
        )

        with pytest.raises(nats_broker.NATSBrokerError, match="NATS.*connection refused.*Next"):
            client.publish(
                broker.BrokerEvent(
                    subject="publish.asset.approved",
                    payload={"asset_id": "council-2026-05-19"},
                )
            )

    def test_provider_awaitable_inside_running_loop_fails_with_precise_error(self) -> None:
        nats_broker = _adapter_module()

        async def exercise() -> None:
            with pytest.raises(nats_broker.NATSBrokerError, match="active asyncio event loop"):
                nats_broker._resolve_provider_call(asyncio.sleep(0))

        asyncio.run(exercise())

    def test_real_provider_connect_uses_local_ca_client_tls_context(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        nats_broker = _adapter_module()
        broker_config = import_module("civiccast.platform.broker_config")
        authority = LocalCertificateAuthority(tmp_path)
        authority.rotate_service_certificate("civiccast-api")
        captured: dict[str, object] = {}

        class FakeConnection:
            def jetstream(self):
                return FakeJetStream()

        class FakeProvider:
            async def connect(self, url: str, *, tls: ssl.SSLContext, **kwargs: object):
                captured["url"] = url
                captured["tls"] = tls
                captured["kwargs"] = kwargs
                return FakeConnection()

        monkeypatch.setattr(nats_broker, "_nats_provider", FakeProvider())
        config = broker_config.BrokerConfig(
            mode="production",
            nats_url="tls://nats.local:4222",
            stream_name="CIVICCAST_EVENTS",
            durable_name="civiccast-publish",
            nats_ca_file=str(tmp_path / "ca" / "civiccast-local-ca.crt"),
            nats_client_cert_file=str(tmp_path / "services" / "civiccast-api.crt"),
            nats_client_key_file=str(tmp_path / "services" / "civiccast-api.key"),
        )
        client = nats_broker.NATSJetStreamBrokerClient(config)

        try:
            client.ensure_ready()
        finally:
            client.close()

        assert captured["url"] == "tls://nats.local:4222"
        assert isinstance(captured["tls"], ssl.SSLContext)
        assert captured["kwargs"] == {
            "connect_timeout": 2,
            "max_reconnect_attempts": 0,
            "reconnect_time_wait": 0.1,
        }
        assert client._provider_thread is None
