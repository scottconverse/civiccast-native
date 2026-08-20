# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real NATS JetStream smoke for the production broker adapter."""

from __future__ import annotations

import ipaddress
import os
import socket
import time
from base64 import b64encode
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID, ObjectIdentifier

try:
    from testcontainers.core.container import DockerContainer  # type: ignore[import-untyped]

    _TESTCONTAINERS_OK = True
except ImportError:
    _TESTCONTAINERS_OK = False
    DockerContainer = None  # type: ignore[assignment,misc]

from civiccast.platform.broker import BrokerEvent
from civiccast.platform.broker_config import BrokerConfig
from civiccast.platform.nats_broker import NATSJetStreamBrokerClient
from tests.support.docker_engine import docker_engine_available


def _docker_available() -> bool:
    return docker_engine_available()


def _skip_if_no_docker() -> None:
    if not _TESTCONTAINERS_OK:
        if os.environ.get("CIVICCAST_RUN_NATS_TESTS"):
            pytest.fail(
                "NATS real-boundary tests required by env but testcontainers is not installed"
            )
        pytest.skip("testcontainers not installed; real NATS JetStream smoke cannot run")
    if _docker_available():
        return
    if os.environ.get("CIVICCAST_RUN_NATS_TESTS"):
        pytest.fail("NATS real-boundary tests required by env but Docker is unavailable")
    pytest.skip("Docker unavailable; real NATS JetStream smoke cannot run")


def _write_private_key(path: Path, key: rsa.RSAPrivateKey) -> None:
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def _issue_certificate(
    *,
    ca_key: rsa.RSAPrivateKey,
    ca_cert: x509.Certificate,
    common_name: str,
    san_names: list[x509.GeneralName],
    extended_key_usage: ObjectIdentifier,
) -> tuple[rsa.RSAPrivateKey, x509.Certificate]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.ExtendedKeyUsage([extended_key_usage]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _write_cert_bundle(root: Path) -> dict[str, Path]:
    certs_dir = root / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(UTC)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CivicCast NATS Test CA")])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key, server_cert = _issue_certificate(
        ca_key=ca_key,
        ca_cert=ca_cert,
        common_name="localhost",
        san_names=[
            x509.DNSName("localhost"),
            x509.DNSName("host.docker.internal"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ],
        extended_key_usage=ExtendedKeyUsageOID.SERVER_AUTH,
    )
    client_key, client_cert = _issue_certificate(
        ca_key=ca_key,
        ca_cert=ca_cert,
        common_name="civiccast-api",
        san_names=[x509.DNSName("civiccast-api")],
        extended_key_usage=ExtendedKeyUsageOID.CLIENT_AUTH,
    )
    paths = {
        "ca": certs_dir / "ca.crt",
        "server_cert": certs_dir / "server.crt",
        "server_key": certs_dir / "server.key",
        "client_cert": certs_dir / "client.crt",
        "client_key": certs_dir / "client.key",
        "config": root / "nats.conf",
    }
    paths["ca"].write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
    paths["server_cert"].write_bytes(server_cert.public_bytes(serialization.Encoding.PEM))
    _write_private_key(paths["server_key"], server_key)
    paths["client_cert"].write_bytes(client_cert.public_bytes(serialization.Encoding.PEM))
    _write_private_key(paths["client_key"], client_key)
    paths["config"].write_text(
        "\n".join(
            [
                "port: 4222",
                "jetstream {",
                '  store_dir: "/data/jetstream"',
                "}",
                "tls {",
                '  cert_file: "/certs/server.crt"',
                '  key_file: "/certs/server.key"',
                '  ca_file: "/certs/ca.crt"',
                "  verify: true",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return paths


def _b64(path: Path) -> str:
    return b64encode(path.read_bytes()).decode("ascii")


def _nats_bootstrap_command(paths: dict[str, Path]) -> str:
    """Start NATS without host bind mounts so cleanroom containers work.

    In the Docker cleanroom, testcontainers talks to the host Docker daemon.
    A sibling container cannot see temp files created inside the cleanroom
    filesystem, so volume mapping those files makes NATS exit before it runs.
    Embed only throwaway test certificates into the startup command instead.
    """

    return " ".join(
        [
            "sh -c 'set -eu;",
            "mkdir -p /certs /data/jetstream /etc/nats;",
            f"printf %s {_b64(paths['ca'])!r} | base64 -d > /certs/ca.crt;",
            f"printf %s {_b64(paths['server_cert'])!r} | base64 -d > /certs/server.crt;",
            f"printf %s {_b64(paths['server_key'])!r} | base64 -d > /certs/server.key;",
            f"printf %s {_b64(paths['config'])!r} | base64 -d > /etc/nats/nats.conf;",
            "exec nats-server -c /etc/nats/nats.conf'",
        ]
    )


@pytest.fixture
def nats_jetstream(tmp_path: Path) -> Iterator[tuple[str, int, dict[str, Path]]]:
    _skip_if_no_docker()
    paths = _write_cert_bundle(tmp_path)
    container = (
        DockerContainer("nats:2.11-alpine")
        .with_exposed_ports(4222)
        .with_command(_nats_bootstrap_command(paths))
    )
    container.start()
    try:
        port = int(container.get_exposed_port(4222))
        host = os.environ.get("TESTCONTAINERS_HOST_OVERRIDE") or "127.0.0.1"
        deadline = time.monotonic() + 20
        while True:
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.25)
        yield host, port, paths
    finally:
        container.stop()


def test_real_nats_jetstream_publish_and_replay_over_tls(
    nats_jetstream: tuple[str, int, dict[str, Path]],
) -> None:
    host, port, paths = nats_jetstream
    durable = "civiccast_test_" + uuid4().hex[:8]
    client = NATSJetStreamBrokerClient(
        BrokerConfig(
            mode="production",
            nats_url=f"tls://{host}:{port}",
            stream_name="CIVICCAST_EVENTS",
            durable_name=durable,
            nats_ca_file=str(paths["ca"]),
            nats_client_cert_file=str(paths["client_cert"]),
            nats_client_key_file=str(paths["client_key"]),
        )
    )

    try:
        client.ensure_ready()
        receipt = client.publish(
            BrokerEvent(
                subject="publish.asset.approved",
                payload={"asset_id": "real-nats-smoke", "status": "approved"},
            )
        )
        replayed = client.replay("publish.asset.approved")
    finally:
        client.close()

    assert receipt.provider_stream == "CIVICCAST_EVENTS"
    assert receipt.provider_sequence is not None
    assert any(event.payload.get("asset_id") == "real-nats-smoke" for event in replayed)
