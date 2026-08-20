# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contracts for v1.2 NATS broker configuration and subject registry."""

from __future__ import annotations

from importlib import import_module

import pytest


def _broker_config_module():
    return import_module("civiccast.platform.broker_config")


class TestBrokerConfigSelection:
    def test_production_missing_nats_url_fails_with_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_BROKER_MODE", "production")
        monkeypatch.delenv("CIVICCAST_NATS_URL", raising=False)
        broker_config = _broker_config_module()

        with pytest.raises(broker_config.BrokerConfigurationError, match="CIVICCAST_NATS_URL"):
            broker_config.load_broker_config()

    def test_production_missing_stream_name_fails_with_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_BROKER_MODE", "production")
        monkeypatch.setenv("CIVICCAST_NATS_URL", "nats://127.0.0.1:4222")
        monkeypatch.delenv("CIVICCAST_NATS_STREAM", raising=False)
        broker_config = _broker_config_module()

        with pytest.raises(broker_config.BrokerConfigurationError, match="stream"):
            broker_config.load_broker_config()

    def test_production_undocumented_subject_fails_before_provider_call(self) -> None:
        broker_config = _broker_config_module()
        registry = broker_config.BROKER_SUBJECT_REGISTRY

        with pytest.raises(broker_config.BrokerConfigurationError, match="documented"):
            registry.require_subject("provider.nats.raw_subject")

    def test_production_invalid_durable_name_fails_with_actionable_error(self) -> None:
        broker_config = _broker_config_module()

        with pytest.raises(broker_config.BrokerConfigurationError, match="durable"):
            broker_config.BrokerConfig(
                mode="production",
                nats_url="nats://127.0.0.1:4222",
                stream_name="CIVICCAST_EVENTS",
                durable_name="bad durable name",
            )

    def test_production_requires_tls_url_for_mtls_transport(self) -> None:
        broker_config = _broker_config_module()

        with pytest.raises(broker_config.BrokerConfigurationError, match="tls://"):
            broker_config.BrokerConfig(
                mode="production",
                nats_url="nats://127.0.0.1:4222",
                stream_name="CIVICCAST_EVENTS",
                durable_name="civiccast-publish",
            )

    def test_production_mode_never_silently_falls_back_to_in_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_BROKER_MODE", "production")
        monkeypatch.delenv("CIVICCAST_NATS_URL", raising=False)
        broker = import_module("civiccast.platform.broker")

        with pytest.raises(Exception, match="NATS|production|CIVICCAST_NATS_URL"):
            broker.get_broker_client()

    def test_dev_mode_may_select_named_in_process_adapter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_BROKER_MODE", "dev")
        broker_config = _broker_config_module()
        broker = import_module("civiccast.platform.broker")

        config = broker_config.load_broker_config()
        client = broker.get_broker_client(config=config)

        assert config.mode == "dev"
        assert client.__class__.__name__ == "InProcessBrokerClient"


class TestDocumentedSubjectRegistry:
    def test_publish_asset_approved_maps_to_one_stream_and_provider_subject(self) -> None:
        broker_config = _broker_config_module()

        entry = broker_config.BROKER_SUBJECT_REGISTRY.require_subject("publish.asset.approved")

        assert entry.stream == "CIVICCAST_EVENTS"
        assert entry.subject == "publish.asset.approved"
        assert entry.provider_subject == "civiccast.publish.asset.approved"

    def test_registry_entries_include_stream_durable_retention_and_ack_policy(self) -> None:
        broker_config = _broker_config_module()

        entry = broker_config.BROKER_SUBJECT_REGISTRY.require_subject("publish.asset.approved")

        assert entry.stream
        assert entry.subject
        assert entry.provider_subject
        assert entry.durable_consumer_policy
        assert entry.retention_policy
        assert entry.ack_policy
