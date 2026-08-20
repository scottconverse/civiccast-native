# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""NATS broker configuration and documented subject registry."""

from __future__ import annotations

import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

BrokerMode = Literal["dev", "test", "production"]


class BrokerConfigurationError(ValueError):
    """Raised when broker configuration cannot satisfy the selected mode."""


class BrokerReadinessError(RuntimeError):
    """Raised when NATS readiness cannot be proven."""


@dataclass(frozen=True)
class BrokerSubjectEntry:
    """One platform-owned logical-to-provider subject mapping."""

    stream: str
    subject: str
    provider_subject: str
    durable_consumer_policy: str
    retention_policy: str
    ack_policy: str


class BrokerSubjectRegistry:
    """Closed registry of broker subjects that CivicCast modules may publish."""

    def __init__(self, entries: tuple[BrokerSubjectEntry, ...]) -> None:
        self._entries = {entry.subject: entry for entry in entries}

    def require_subject(self, subject: str) -> BrokerSubjectEntry:
        try:
            return self._entries[subject]
        except KeyError as exc:
            allowed = ", ".join(sorted(self._entries))
            raise BrokerConfigurationError(
                f"{subject!r} is not a documented broker subject. Use one of: {allowed}."
            ) from exc

    def provider_subjects_for_stream(self, stream_name: str) -> list[str]:
        return [
            entry.provider_subject
            for entry in self._entries.values()
            if entry.stream == stream_name
        ]

    def stream_config(self, stream_name: str) -> dict[str, object]:
        entries = [entry for entry in self._entries.values() if entry.stream == stream_name]
        if not entries:
            raise BrokerConfigurationError(
                f"CIVICCAST_NATS_STREAM={stream_name!r} has no documented subjects."
            )
        return {
            "name": stream_name,
            "subjects": [entry.provider_subject for entry in entries],
            "retention": entries[0].retention_policy,
            "ack_policy": entries[0].ack_policy,
        }


BROKER_SUBJECT_REGISTRY = BrokerSubjectRegistry(
    (
        BrokerSubjectEntry(
            stream="CIVICCAST_EVENTS",
            subject="publish.asset.approved",
            provider_subject="civiccast.publish.asset.approved",
            durable_consumer_policy="explicit_ack_durable",
            retention_policy="limits",
            ack_policy="explicit",
        ),
    )
)

_DURABLE_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


@dataclass(frozen=True)
class NATSMTLSFiles:
    """Certificate paths required for production NATS mTLS."""

    ca_file: Path
    client_cert_file: Path
    client_key_file: Path


@dataclass(frozen=True)
class BrokerConfig:
    """Selected broker adapter and required production NATS settings."""

    mode: BrokerMode = "dev"
    nats_url: str | None = None
    stream_name: str | None = None
    durable_name: str = "civiccast-publish"
    adapter_name: str = "in-process"
    nats_ca_file: str | None = None
    nats_client_cert_file: str | None = None
    nats_client_key_file: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"dev", "test", "production"}:
            raise BrokerConfigurationError(
                "CIVICCAST_BROKER_MODE must be dev, test, or production."
            )
        if not self.durable_name or any(char not in _DURABLE_ALLOWED for char in self.durable_name):
            raise BrokerConfigurationError(
                "CIVICCAST_NATS_DURABLE must be a durable consumer name containing only "
                "letters, numbers, hyphen, or underscore."
            )
        if self.mode == "production":
            if not self.nats_url:
                raise BrokerConfigurationError(
                    "CIVICCAST_NATS_URL is required when CIVICCAST_BROKER_MODE=production. "
                    "Set CIVICCAST_NATS_URL to the station NATS server, then rerun readiness."
                )
            if not self.stream_name:
                raise BrokerConfigurationError(
                    "CIVICCAST_NATS_STREAM stream is required in production and must be "
                    "CIVICCAST_EVENTS."
                )
            if self.stream_name != "CIVICCAST_EVENTS":
                raise BrokerConfigurationError(
                    "CIVICCAST_NATS_STREAM must be CIVICCAST_EVENTS so documented subjects "
                    "map to the managed JetStream stream."
                )
            parsed = urlparse(self.nats_url)
            if parsed.scheme != "tls":
                raise BrokerConfigurationError(
                    "CIVICCAST_NATS_URL must use tls:// for production NATS mTLS. "
                    "Use tls://host:4222 and local CA credentials generated by "
                    "`civiccast cert rotate civiccast-api`."
                )

    def mtls_files(self) -> NATSMTLSFiles:
        """Return configured or default local-CA paths for production NATS mTLS."""

        root = _default_cert_root()
        return NATSMTLSFiles(
            ca_file=Path(self.nats_ca_file)
            if self.nats_ca_file
            else root / "ca" / "civiccast-local-ca.crt",
            client_cert_file=Path(self.nats_client_cert_file)
            if self.nats_client_cert_file
            else root / "services" / "civiccast-api.crt",
            client_key_file=Path(self.nats_client_key_file)
            if self.nats_client_key_file
            else root / "services" / "civiccast-api.key",
        )


def load_broker_config(env: Mapping[str, str] | None = None) -> BrokerConfig:
    """Load broker settings from the environment and fail closed in production."""

    source = env if env is not None else os.environ
    mode = source.get("CIVICCAST_BROKER_MODE", "dev").lower()
    if mode not in {"dev", "test", "production"}:
        raise BrokerConfigurationError("CIVICCAST_BROKER_MODE must be dev, test, or production.")
    if mode == "production":
        broker_mode: BrokerMode = "production"
    elif mode == "test":
        broker_mode = "test"
    else:
        broker_mode = "dev"
    adapter_name = "nats-jetstream" if broker_mode == "production" else "in-process"
    return BrokerConfig(
        mode=broker_mode,
        nats_url=source.get("CIVICCAST_NATS_URL"),
        stream_name=source.get("CIVICCAST_NATS_STREAM"),
        durable_name=source.get("CIVICCAST_NATS_DURABLE", "civiccast-publish"),
        adapter_name=adapter_name,
        nats_ca_file=source.get("CIVICCAST_NATS_CA_FILE"),
        nats_client_cert_file=source.get("CIVICCAST_NATS_CLIENT_CERT_FILE"),
        nats_client_key_file=source.get("CIVICCAST_NATS_CLIENT_KEY_FILE"),
    )


def check_nats_readiness(
    config: BrokerConfig | None = None, *, jetstream: object | None = None
) -> bool:
    """Return true only after production NATS and JetStream subject proof succeeds."""

    broker_config = config or BrokerConfig(
        mode="production",
        nats_url=os.getenv("CIVICCAST_NATS_URL"),
        stream_name=os.getenv("CIVICCAST_NATS_STREAM"),
        durable_name=os.getenv("CIVICCAST_NATS_DURABLE", "civiccast-publish"),
        adapter_name="nats-jetstream",
        nats_ca_file=os.getenv("CIVICCAST_NATS_CA_FILE"),
        nats_client_cert_file=os.getenv("CIVICCAST_NATS_CLIENT_CERT_FILE"),
        nats_client_key_file=os.getenv("CIVICCAST_NATS_CLIENT_KEY_FILE"),
    )
    if broker_config.mode != "production":
        broker_config = BrokerConfig(
            mode="production",
            nats_url=broker_config.nats_url,
            stream_name=broker_config.stream_name,
            durable_name=broker_config.durable_name,
            adapter_name="nats-jetstream",
        )
    BROKER_SUBJECT_REGISTRY.stream_config(broker_config.stream_name or "")
    parsed = urlparse(broker_config.nats_url or "")
    if parsed.scheme != "tls" or not parsed.hostname:
        raise BrokerReadinessError(
            "CIVICCAST_NATS_URL must be a tls:// URL with a host for production mTLS. "
            "Set CIVICCAST_NATS_URL=tls://host:4222, then rerun installer readiness."
        )
    _require_mtls_files(broker_config.mtls_files())
    port = parsed.port or 4222
    try:
        with socket.create_connection((parsed.hostname, port), timeout=0.25):
            pass
    except OSError as exc:
        raise BrokerReadinessError(
            f"NATS JetStream is unreachable at {broker_config.nats_url}: {exc}. "
            "Next: start NATS with JetStream enabled, check firewall or port mapping, "
            "then rerun `civiccast installer health-check`."
        ) from exc
    from civiccast.platform.nats_broker import NATSJetStreamBrokerClient

    try:
        NATSJetStreamBrokerClient(broker_config, jetstream=jetstream).ensure_ready()
    except Exception as exc:
        raise BrokerReadinessError(
            f"NATS JetStream is reachable but stream/subject validation failed: {exc}. "
            "Next: enable JetStream and ensure the CIVICCAST_EVENTS stream contains "
            "civiccast.publish.asset.approved, then rerun installer readiness."
        ) from exc
    return True


def _default_cert_root() -> Path:
    configured = os.getenv("CIVICCAST_CERT_ROOT")
    if configured:
        return Path(configured)
    return Path.home() / ".civiccast" / "certs"


def _require_mtls_files(files: NATSMTLSFiles) -> None:
    missing = [
        f"{name}={path}"
        for name, path in (
            ("CIVICCAST_NATS_CA_FILE", files.ca_file),
            ("CIVICCAST_NATS_CLIENT_CERT_FILE", files.client_cert_file),
            ("CIVICCAST_NATS_CLIENT_KEY_FILE", files.client_key_file),
        )
        if not path.exists()
    ]
    if missing:
        raise BrokerReadinessError(
            "NATS mTLS certificate material is missing: "
            + ", ".join(missing)
            + ". Next: run `civiccast cert rotate civiccast-api`, ensure the local CA "
            "and client certificate files exist, then rerun installer readiness."
        )
