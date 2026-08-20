# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Pure decision-logic and model tests for the provisioning engine.

Pure -- no Windows, no Postgres, no NATS, no subprocess. These pin the
idempotency decisions (D4: "detect existing cluster and DO NOT re-init;
version-check existing cluster") and the DatabaseUrl construction the
installer writes to
``HKLM\\SOFTWARE\\CivicCast\\Native\\DatabaseUrl``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from civiccast.native.provision.models import (
    NatsTlsFiles,
    ProvisionContext,
    ProvisionPhase,
    ProvisionPlan,
    build_database_url,
    evaluate_nats_store,
    evaluate_postgres_cluster,
    resolve_database_url,
)

# --- ProvisionPhase rank / terminal grammar ---------------------------------


def test_forward_phase_ranks_are_strictly_increasing() -> None:
    forward = [
        ProvisionPhase.INIT,
        ProvisionPhase.PACK_VERIFIED,
        ProvisionPhase.POSTGRES_CLUSTER_READY,
        ProvisionPhase.POSTGRES_CONFIG_WRITTEN,
        ProvisionPhase.DATABASE_READY,
        ProvisionPhase.NATS_STORE_READY,
        ProvisionPhase.NATS_CONFIG_WRITTEN,
        ProvisionPhase.COMPLETE,
    ]
    ranks = [p.rank for p in forward]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)


def test_terminal_phases_flagged() -> None:
    assert ProvisionPhase.COMPLETE.is_terminal
    assert ProvisionPhase.FAILED.is_terminal
    assert not ProvisionPhase.INIT.is_terminal
    assert not ProvisionPhase.NATS_CONFIG_WRITTEN.is_terminal


# --- build_database_url -----------------------------------------------------


def test_build_database_url_happy_path() -> None:
    url = build_database_url(
        host="127.0.0.1",
        port=5432,
        database="civiccast",
        username="civiccast_svc",
        password="hunter2",
    )
    assert url == "postgresql://civiccast_svc:hunter2@127.0.0.1:5432/civiccast"


def test_build_database_url_quotes_special_characters_in_password() -> None:
    url = build_database_url(
        host="127.0.0.1",
        port=5432,
        database="civiccast",
        username="civiccast_svc",
        password="p@ss:w/ord?#",
    )
    # The percent-encoded password must round-trip through urlsplit/unquote
    # exactly like civiccast.dr.backup._parse_postgres_url expects.
    from urllib.parse import unquote, urlsplit

    parsed = urlsplit(url)
    assert unquote(parsed.password) == "p@ss:w/ord?#"
    assert parsed.hostname == "127.0.0.1"
    assert parsed.port == 5432
    assert parsed.path == "/civiccast"


def test_build_database_url_quotes_special_characters_in_username() -> None:
    url = build_database_url(
        host="127.0.0.1", port=5432, database="civiccast", username="svc@acct", password="x"
    )
    from urllib.parse import unquote, urlsplit

    assert unquote(urlsplit(url).username) == "svc@acct"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"host": "", "port": 5432, "database": "civiccast", "username": "u", "password": "p"},
        {"host": "  ", "port": 5432, "database": "civiccast", "username": "u", "password": "p"},
    ],
)
def test_build_database_url_rejects_empty_host(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="host"):
        build_database_url(**kwargs)


@pytest.mark.parametrize("port", [0, -1, 65536, 100000])
def test_build_database_url_rejects_out_of_range_port(port: int) -> None:
    with pytest.raises(ValueError, match="port"):
        build_database_url(
            host="127.0.0.1", port=port, database="civiccast", username="u", password="p"
        )


def test_build_database_url_rejects_bool_port() -> None:
    with pytest.raises(ValueError, match="port"):
        build_database_url(
            host="127.0.0.1", port=True, database="civiccast", username="u", password="p"
        )


@pytest.mark.parametrize("database", ["", "1civiccast", "civic-cast", "civic cast", "civic;drop"])
def test_build_database_url_rejects_unsafe_database_identifier(database: str) -> None:
    with pytest.raises(ValueError, match="database"):
        build_database_url(
            host="127.0.0.1", port=5432, database=database, username="u", password="p"
        )


def test_build_database_url_rejects_empty_username() -> None:
    with pytest.raises(ValueError, match="username"):
        build_database_url(
            host="127.0.0.1", port=5432, database="civiccast", username="", password="p"
        )


def test_build_database_url_rejects_empty_password() -> None:
    with pytest.raises(ValueError, match="password"):
        build_database_url(
            host="127.0.0.1", port=5432, database="civiccast", username="u", password=""
        )


# --- resolve_database_url (plan + context combination) ----------------------


def _plan(**overrides: object) -> ProvisionPlan:
    defaults: dict[str, object] = {
        "postgres_major_version": "17",
        "database_name": "civiccast",
        "database_username": "civiccast_svc",
        "server_pack_product_version": "1.0.0",
        "server_pack_compatible_core": "1.0.0",
        "server_pack_signing_key_id": "key-1",
    }
    defaults.update(overrides)
    return ProvisionPlan(**defaults)


def _context(tmp_path, **overrides: object) -> ProvisionContext:
    defaults: dict[str, object] = {
        "postgres_data_dir": str(tmp_path / "pgdata"),
        "postgres_config_path": str(tmp_path / "pgdata" / "postgresql.conf"),
        "postgres_hba_path": str(tmp_path / "pgdata" / "pg_hba.conf"),
        "database_password": "hunter2",
        "nats_store_dir": str(tmp_path / "nats" / "store"),
        "nats_config_path": str(tmp_path / "nats" / "nats-server.conf"),
        "server_pack_path": str(tmp_path / "server-binaries.ccpack"),
        "state_root": str(tmp_path / "state"),
        "owner_run_id": "run-1",
    }
    defaults.update(overrides)
    return ProvisionContext(**defaults)


def test_resolve_database_url_combines_plan_and_context(tmp_path) -> None:
    plan = _plan()
    context = _context(tmp_path)
    url = resolve_database_url(plan=plan, context=context)
    assert url == "postgresql://civiccast_svc:hunter2@127.0.0.1:5432/civiccast"


def test_resolve_database_url_is_not_persisted_as_its_own_journal_field(tmp_path) -> None:
    # ProvisionContext/ProvisionJournal must never carry a `database_url`
    # field -- it is always re-derived so there is exactly one place the
    # string is assembled (see models.py's resolve_database_url docstring).
    assert "database_url" not in ProvisionContext.model_fields
    from civiccast.native.provision.models import ProvisionJournal

    assert "database_url" not in ProvisionJournal.model_fields


def test_provision_plan_rejects_unsafe_database_name() -> None:
    with pytest.raises(ValidationError, match="database_name"):
        _plan(database_name="civic-cast")


def test_provision_plan_rejects_unsafe_database_username() -> None:
    """BLOCKER #52: database_username is now embedded (double-quoted, never
    parameterized) into the CREATE DATABASE OWNER clause
    (civiccast.native.provision.seams._create_database) -- it needs the same
    safe-identifier guarantee database_name already carries."""

    with pytest.raises(ValidationError, match="database_username"):
        _plan(database_username='civiccast_svc"; DROP DATABASE civiccast; --')


def test_provision_context_extra_field_is_rejected(tmp_path) -> None:
    with pytest.raises(ValidationError):
        ProvisionContext(
            postgres_data_dir=str(tmp_path / "pgdata"),
            postgres_config_path=str(tmp_path / "pgdata" / "postgresql.conf"),
            postgres_hba_path=str(tmp_path / "pgdata" / "pg_hba.conf"),
            database_password="hunter2",
            nats_store_dir=str(tmp_path / "nats" / "store"),
            nats_config_path=str(tmp_path / "nats" / "nats-server.conf"),
            server_pack_path=str(tmp_path / "server-binaries.ccpack"),
            state_root=str(tmp_path / "state"),
            owner_run_id="run-1",
            unexpected_field="boom",
        )


# --- NatsTlsFiles ------------------------------------------------------------


def test_nats_tls_files_round_trips_through_json() -> None:
    tls = NatsTlsFiles(ca_file="ca.pem", cert_file="cert.pem", key_file="key.pem")
    restored = NatsTlsFiles.model_validate_json(tls.model_dump_json())
    assert restored == tls


# --- evaluate_postgres_cluster ----------------------------------------------


def test_evaluate_postgres_cluster_needs_initdb_when_no_existing_version() -> None:
    decision = evaluate_postgres_cluster(observed_version=None, expected_major_version="17")
    assert decision.outcome == "needs_initdb"


def test_evaluate_postgres_cluster_already_initialized_when_version_matches() -> None:
    decision = evaluate_postgres_cluster(observed_version="17", expected_major_version="17")
    assert decision.outcome == "already_initialized"


def test_evaluate_postgres_cluster_already_initialized_strips_whitespace() -> None:
    decision = evaluate_postgres_cluster(observed_version="17\n", expected_major_version="17")
    assert decision.outcome == "already_initialized"


def test_evaluate_postgres_cluster_version_mismatch_fails_closed() -> None:
    decision = evaluate_postgres_cluster(observed_version="16", expected_major_version="17")
    assert decision.outcome == "version_mismatch"
    assert "16" in decision.detail
    assert "17" in decision.detail


def test_evaluate_postgres_cluster_rejects_empty_expected_version() -> None:
    with pytest.raises(ValueError, match="expected_major_version"):
        evaluate_postgres_cluster(observed_version=None, expected_major_version="")


# --- evaluate_nats_store ------------------------------------------------------


def test_evaluate_nats_store_create_when_absent() -> None:
    decision = evaluate_nats_store(path_exists=False, is_directory=False)
    assert decision.outcome == "create"


def test_evaluate_nats_store_reuse_when_present_and_matches() -> None:
    decision = evaluate_nats_store(path_exists=True, is_directory=True)
    assert decision.outcome == "reuse_existing"


def test_evaluate_nats_store_fails_closed_when_path_is_a_file() -> None:
    decision = evaluate_nats_store(path_exists=True, is_directory=False)
    assert decision.outcome == "fail_closed_not_a_directory"
