# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure config-rendering tests for the provisioned PostgreSQL server. No I/O
-- these pin the exact deterministic bytes the orchestrator hands to its
write_* seams.

Formerly also covered the provisioned NATS server's config renderer. NATS
JetStream was removed from the product (owner decision 2026-08-20; see ADR
0023, which supersedes ADR 0001); ``render_nats_conf`` and
``NatsTlsFiles`` are gone, and this module no longer renders a
``nats-server.conf``.
"""

from __future__ import annotations

import pytest

from civiccast.native.provision.conf import (
    render_pg_hba_conf,
    render_pg_hba_trust_conf,
    render_postgresql_conf,
)

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
