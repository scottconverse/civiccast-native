# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure config-rendering tests for the provisioned PostgreSQL and NATS
servers. No I/O -- these pin the exact deterministic bytes the orchestrator
hands to its write_* seams."""

from __future__ import annotations

import pytest

from civiccast.native.provision.conf import (
    render_nats_conf,
    render_pg_hba_conf,
    render_pg_hba_trust_conf,
    render_postgresql_conf,
)
from civiccast.native.provision.models import NatsTlsFiles

# --- render_postgresql_conf ---------------------------------------------------


def test_render_postgresql_conf_binds_loopback_and_port() -> None:
    content = render_postgresql_conf(host="127.0.0.1", port=5432)
    assert "listen_addresses = '127.0.0.1'" in content
    assert "port = 5432" in content


def test_render_postgresql_conf_disables_unix_socket_for_windows() -> None:
    content = render_postgresql_conf()
    assert "unix_socket_directories = ''" in content


def test_render_postgresql_conf_disables_ssl_for_loopback_control_plane() -> None:
    content = render_postgresql_conf()
    assert "ssl = off" in content


def test_render_postgresql_conf_is_deterministic() -> None:
    first = render_postgresql_conf(host="127.0.0.1", port=5432)
    second = render_postgresql_conf(host="127.0.0.1", port=5432)
    assert first == second


def test_render_postgresql_conf_rejects_empty_host() -> None:
    with pytest.raises(ValueError, match="host"):
        render_postgresql_conf(host="")


@pytest.mark.parametrize("port", [0, -1, 70000])
def test_render_postgresql_conf_rejects_bad_port(port: int) -> None:
    with pytest.raises(ValueError, match="port"):
        render_postgresql_conf(port=port)


def test_render_postgresql_conf_rejects_non_positive_max_connections() -> None:
    with pytest.raises(ValueError, match="max_connections"):
        render_postgresql_conf(max_connections=0)


# --- render_pg_hba_conf --------------------------------------------------------


def test_render_pg_hba_conf_only_allows_exact_loopback_scram() -> None:
    content = render_pg_hba_conf(host="127.0.0.1")
    assert "127.0.0.1/32" in content
    assert "scram-sha-256" in content


def test_render_pg_hba_conf_never_contains_a_wildcard_or_trust_method() -> None:
    content = render_pg_hba_conf(host="127.0.0.1")
    assert "0.0.0.0/0" not in content
    assert "trust" not in content


def test_render_pg_hba_conf_is_deterministic() -> None:
    assert render_pg_hba_conf(host="127.0.0.1") == render_pg_hba_conf(host="127.0.0.1")


def test_render_pg_hba_conf_rejects_empty_host() -> None:
    with pytest.raises(ValueError, match="host"):
        render_pg_hba_conf(host="")


# --- render_pg_hba_trust_conf (N-15 adoption maintenance window) ---------------


def test_render_pg_hba_trust_conf_grants_loopback_trust_only() -> None:
    # The transient adoption window needs trust auth (no recoverable password)
    # but MUST stay scoped to the exact loopback address -- no wildcard host.
    content = render_pg_hba_trust_conf(host="127.0.0.1")
    assert "127.0.0.1/32" in content
    assert "trust" in content
    assert "0.0.0.0/0" not in content
    assert "scram-sha-256" not in content


def test_render_pg_hba_trust_conf_is_a_transient_overwriteable_parity_with_scram() -> None:
    # Same one-loopback-rule shape as the real scram file, so the scram
    # renderer can overwrite it byte-for-byte in the reset seam's finally. The
    # ONLY meaningful difference is the METHOD column.
    trust = render_pg_hba_trust_conf(host="127.0.0.1")
    scram = render_pg_hba_conf(host="127.0.0.1")
    assert trust.count("host    all       all") == scram.count("host    all       all") == 1
    assert "TRANSIENT" in trust  # self-documents that it is not the resting state


def test_render_pg_hba_trust_conf_is_deterministic() -> None:
    assert render_pg_hba_trust_conf(host="127.0.0.1") == render_pg_hba_trust_conf(host="127.0.0.1")


def test_render_pg_hba_trust_conf_rejects_empty_host() -> None:
    with pytest.raises(ValueError, match="host"):
        render_pg_hba_trust_conf(host="")


# --- render_nats_conf -----------------------------------------------------------


def test_render_nats_conf_sets_jetstream_store_dir() -> None:
    rendered = render_nats_conf(
        host="127.0.0.1", port=4222, store_dir=r"C:\ProgramData\CivicCast\nats\store"
    )
    assert "jetstream {" in rendered.content
    assert r"C:\\ProgramData\\CivicCast\\nats\\store" in rendered.content


def test_render_nats_conf_without_tls_when_no_cert_files() -> None:
    rendered = render_nats_conf(host="127.0.0.1", port=4222, store_dir="/tmp/store")
    assert rendered.tls_enabled is False
    assert "tls {" not in rendered.content


def test_render_nats_conf_with_tls_block_when_cert_files_supplied() -> None:
    tls = NatsTlsFiles(ca_file="ca.pem", cert_file="cert.pem", key_file="key.pem")
    rendered = render_nats_conf(host="127.0.0.1", port=4222, store_dir="/tmp/store", tls=tls)
    assert rendered.tls_enabled is True
    assert "tls {" in rendered.content
    assert "ca.pem" in rendered.content
    assert "cert.pem" in rendered.content
    assert "key.pem" in rendered.content
    assert "verify: true" in rendered.content


def test_render_nats_conf_escapes_backslashes_and_quotes_in_paths() -> None:
    tls = NatsTlsFiles(
        ca_file=r'C:\certs\ca "special".pem', cert_file="cert.pem", key_file="key.pem"
    )
    rendered = render_nats_conf(host="127.0.0.1", port=4222, store_dir=r"C:\store", tls=tls)
    assert r"C:\\certs\\ca \"special\".pem" in rendered.content


def test_render_nats_conf_is_deterministic() -> None:
    first = render_nats_conf(host="127.0.0.1", port=4222, store_dir="/tmp/store")
    second = render_nats_conf(host="127.0.0.1", port=4222, store_dir="/tmp/store")
    assert first.content == second.content


def test_render_nats_conf_rejects_empty_store_dir() -> None:
    with pytest.raises(ValueError, match="store_dir"):
        render_nats_conf(host="127.0.0.1", port=4222, store_dir="")


def test_render_nats_conf_rejects_empty_host() -> None:
    with pytest.raises(ValueError, match="host"):
        render_nats_conf(host="", port=4222, store_dir="/tmp/store")


def test_render_nats_conf_pins_the_lame_duck_values_the_real_server_accepts() -> None:
    """The rendered conf carries lame-duck values the REAL server accepts.

    nats-server 2.14.3 enforces a HARD 30-SECOND FLOOR on
    ``lame_duck_duration`` (verified against the real pack-cache binary at
    C:\\CivicCastProof\\server-pack-cache\\extracted\\nats\\nats-server.exe:
    ``nats-server.exe -t -c <conf>`` REJECTS a 5s value with "invalid
    lame_duck_duration of 5s, minimum is 30 seconds" and ACCEPTS "30s"). This
    pins the enforced MINIMUM (not the originally-proposed 5s, which the real
    server refuses) rather than the silent 2-minute default, plus a short
    ``lame_duck_grace_period`` so the server does not wait needlessly before
    starting a drain it has been asked to begin.

    CORRECTION (2026-07-31, F3): this test's previous name and docstring
    claimed the setting FIXED the supervisor's graceful stop of nats (the 2
    minute default "ran out the clock" against the 15s deadline). That claim is
    FALSE on Windows and this test never proved it -- it only ever read the
    rendered text. MEASURED: ``nats-server --signal ldm=<pid>`` fails "Access is
    denied" PID-INDEPENDENTLY on Windows (the flag routes through the SCM's
    OpenService and this nats-server is a plain child, not a registered
    service), so the signal never reaches the server and no lame_duck_* value
    can change the supervisor's stop path -- nats is ended by the D5 deadline +
    TerminateProcess, as it was before. What this test pins is what it can
    prove: the rendered configuration is the one the real binary accepts."""

    rendered = render_nats_conf(host="127.0.0.1", port=4222, store_dir="/tmp/store")
    assert 'lame_duck_duration: "30s"' in rendered.content
    assert 'lame_duck_grace_period: "5s"' in rendered.content
