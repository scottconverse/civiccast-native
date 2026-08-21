# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Orchestration tests: forward sequence, idempotent resume, and the
fail-closed halt. The seams are FAKES, but they are dependency-injected into
the REAL orchestrator and REAL journal state machine -- the same code that
runs in production drives these fakes, so the test exercises orchestration
logic, not a re-implementation of it.

HARD RULE: no real PostgreSQL process is ever spawned here -- every
seam is an in-memory fake operating on a tmp_path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from civiccast.native.provision.models import (
    DatabaseDecision,
    ProvisionContext,
    ProvisionPhase,
    ProvisionPlan,
    ProvisionSeams,
)
from civiccast.native.provision.orchestrator import run_provision


@dataclass
class Harness:
    """A live, temp-dir-backed fake of the world the engine acts on."""

    postgres_data_dir: Path

    # World state.
    postgres_version: str | None = None  # None == uninitialized data dir
    postgres_conf_written: str | None = None
    pg_hba_conf_written: str | None = None
    database_exists: bool = False  # BLOCKER #52: world state for ensure_database
    calls: list[str] = field(default_factory=list)

    # Failure injection.
    fail_pack_verify: bool = False
    fail_initdb: bool = False
    fail_ensure_database: bool = False

    def _record(self, name: str) -> None:
        self.calls.append(name)

    def verify_pack(self) -> None:
        self._record("verify_pack")
        if self.fail_pack_verify:
            raise ValueError("server-binaries pack signature is invalid")

    def detect_postgres_cluster(self) -> str | None:
        self._record("detect_postgres_cluster")
        return self.postgres_version

    def run_initdb(self) -> None:
        self._record("run_initdb")
        if self.fail_initdb:
            raise RuntimeError("injected initdb failure")
        self.postgres_version = "17"

    def write_postgres_conf(self, content: str) -> None:
        self._record("write_postgres_conf")
        self.postgres_conf_written = content

    def write_pg_hba_conf(self, content: str) -> None:
        self._record("write_pg_hba_conf")
        self.pg_hba_conf_written = content

    def ensure_database(self) -> DatabaseDecision:
        self._record("ensure_database")
        if self.fail_ensure_database:
            raise RuntimeError("injected database-creation failure")
        if self.database_exists:
            return DatabaseDecision(outcome="already_exists", detail="already existed")
        self.database_exists = True
        return DatabaseDecision(outcome="created", detail="created")

    def seams(self) -> ProvisionSeams:
        return ProvisionSeams(
            verify_pack=self.verify_pack,
            detect_postgres_cluster=self.detect_postgres_cluster,
            run_initdb=self.run_initdb,
            write_postgres_conf=self.write_postgres_conf,
            write_pg_hba_conf=self.write_pg_hba_conf,
            ensure_database=self.ensure_database,
        )


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


def _context(tmp_path: Path) -> ProvisionContext:
    return ProvisionContext(
        postgres_data_dir=str(tmp_path / "pgdata"),
        postgres_config_path=str(tmp_path / "pgdata" / "postgresql.conf"),
        postgres_hba_path=str(tmp_path / "pgdata" / "pg_hba.conf"),
        database_password="hunter2",
        server_pack_path=str(tmp_path / "server-binaries.ccpack"),
        state_root=str(tmp_path / "state"),
        owner_run_id="run-1",
    )


def _harness(tmp_path: Path) -> Harness:
    return Harness(
        postgres_data_dir=tmp_path / "pgdata",
    )


# --- happy path ----------------------------------------------------------------


def test_happy_path_completes_all_phases_in_order(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.ok
    assert outcome.phase is ProvisionPhase.COMPLETE
    assert harness.calls == [
        "verify_pack",
        "detect_postgres_cluster",
        "run_initdb",
        "write_postgres_conf",
        "write_pg_hba_conf",
        "ensure_database",
    ]
    assert harness.postgres_conf_written is not None
    assert "127.0.0.1" in harness.postgres_conf_written
    assert harness.database_exists is True


def test_happy_path_journal_history_records_every_forward_phase(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())
    phases = [entry[0] for entry in outcome.journal.history]
    assert phases == [
        ProvisionPhase.PACK_VERIFIED.value,
        ProvisionPhase.POSTGRES_CLUSTER_READY.value,
        ProvisionPhase.POSTGRES_CONFIG_WRITTEN.value,
        ProvisionPhase.DATABASE_READY.value,
        ProvisionPhase.COMPLETE.value,
    ]


# --- idempotency -----------------------------------------------------------------


def test_existing_cluster_same_version_skips_initdb_idempotent(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.postgres_version = "17"  # already initialized
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.ok
    assert "run_initdb" not in harness.calls


def test_database_absent_is_created_and_journaled(tmp_path: Path) -> None:
    """BLOCKER #52: a fresh provisioning run over an absent database creates
    it and journals the action."""

    harness = _harness(tmp_path)
    assert harness.database_exists is False
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.ok
    assert "ensure_database" in harness.calls
    assert harness.database_exists is True
    detail = next(
        entry[2]
        for entry in outcome.journal.history
        if entry[0] == ProvisionPhase.DATABASE_READY.value
    )
    assert "created" in detail.lower()


def test_database_already_present_is_idempotent_no_op(tmp_path: Path) -> None:
    """BLOCKER #52: a rerun (e.g. a repair install) against an
    already-provisioned cluster finds the database present and records
    no-action -- the seam is still called (it owns the idempotency check),
    but the world is not mutated a second time."""

    harness = _harness(tmp_path)
    harness.database_exists = True  # already provisioned by an earlier run
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.ok
    assert "ensure_database" in harness.calls
    detail = next(
        entry[2]
        for entry in outcome.journal.history
        if entry[0] == ProvisionPhase.DATABASE_READY.value
    )
    assert "already exist" in detail.lower() or "no action" in detail.lower()


def test_adoption_journey_reuses_cluster_and_database_without_destroying_data(
    tmp_path: Path,
) -> None:
    """N-15 data-preservation invariant: the reinstall-over-preserved-data
    journey drives the engine over a cluster that ALREADY EXISTS (PG_VERSION
    present) AND a database that ALREADY EXISTS -- exactly the world the CLI's
    ADOPT_EXISTING path hands the engine after re-establishing the credential.
    The engine must REUSE both: NO initdb (would wipe the cluster) and NO
    CREATE DATABASE (the civiccast database, holding station data, is left
    intact), yet still reach COMPLETE and write config for the supervisor.

    This is the orchestrator-level proof that adoption never destroys station
    data; the CLI-level proof that adoption is REACHED (instead of the old
    fail-loud) lives in tests/native/test_provision_cli.py."""

    harness = _harness(tmp_path)
    harness.postgres_version = "17"  # preserved, already-initialized cluster
    harness.database_exists = True  # preserved civiccast database (station data)

    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.ok
    # The data-destroying action must NOT have run.
    assert "run_initdb" not in harness.calls, "adoption must never re-initdb a preserved cluster"
    # ensure_database is still CALLED (it owns the idempotency check) but takes
    # no action -- the database detail records reuse, not creation.
    assert "ensure_database" in harness.calls
    db_detail = next(
        entry[2]
        for entry in outcome.journal.history
        if entry[0] == ProvisionPhase.DATABASE_READY.value
    )
    assert "already exist" in db_detail.lower() or "no action" in db_detail.lower()
    # Config IS re-written (the supervisor reads the scram pg_hba the reset
    # seam's finally restored), so the station comes up working.
    assert "write_postgres_conf" in harness.calls
    assert "write_pg_hba_conf" in harness.calls


def test_database_creation_failure_halts_loud_through_existing_error_path(tmp_path: Path) -> None:
    """BLOCKER #52: a database-creation failure funnels through the SAME
    fail-closed halt every other provisioning step uses -- no new exit code,
    no silent swallow."""

    harness = _harness(tmp_path)
    harness.fail_ensure_database = True
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.failed
    assert outcome.phase is ProvisionPhase.FAILED
    assert "injected database-creation failure" in (outcome.journal.error or "")
    assert outcome.journal.recovery_document_path is not None
    recovery_doc = Path(outcome.journal.recovery_document_path)
    assert recovery_doc.exists()


def test_rerun_after_complete_touches_nothing(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    context = _context(tmp_path)
    first = run_provision(_plan(), context, harness.seams())
    assert first.ok

    harness.calls.clear()
    second = run_provision(_plan(), context, harness.seams())

    assert second.ok
    assert harness.calls == []


# --- fail-closed refusals ---------------------------------------------------------


def test_pack_verification_failure_halts_before_any_mutation(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.fail_pack_verify = True
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.failed
    assert outcome.phase is ProvisionPhase.FAILED
    assert harness.calls == ["verify_pack"]
    assert harness.postgres_version is None


def test_version_mismatch_fails_closed_without_running_initdb(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.postgres_version = "16"  # wrong major version already present
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.failed
    assert "run_initdb" not in harness.calls
    assert "16" in (outcome.journal.error or "")
    assert "17" in (outcome.journal.error or "")


def test_initdb_failure_halts_and_writes_recovery_document(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.fail_initdb = True
    outcome = run_provision(_plan(), _context(tmp_path), harness.seams())

    assert outcome.failed
    assert outcome.journal.recovery_document_path is not None
    recovery_doc = Path(outcome.journal.recovery_document_path)
    assert recovery_doc.exists()
    text = recovery_doc.read_text(encoding="utf-8")
    assert "HALTED" in text
    assert "injected initdb failure" in text


def test_rerun_of_a_failed_run_never_retries_silently(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.fail_pack_verify = True
    context = _context(tmp_path)
    first = run_provision(_plan(), context, harness.seams())
    assert first.failed

    harness.calls.clear()
    harness.fail_pack_verify = False  # even if the underlying problem is "fixed"...
    second = run_provision(_plan(), context, harness.seams())

    # ...a FAILED journal is never auto-retried; the caller must act (a fresh
    # state_root, or an explicit operator-driven retry outside this module).
    assert second.failed
    assert harness.calls == []


# --- resume after a simulated kill --------------------------------------------------


def test_resume_after_simulated_kill_continues_from_persisted_phase(tmp_path: Path) -> None:
    # A real power-loss kill terminates the OS process outright -- it is not
    # an exception the orchestrator catches, so it is simulated (same
    # convention as tests/native/test_upgrade_resume.py) by directly
    # persisting a journal at the mid-flight phase the kill would have left
    # behind, with the fake world state advanced to match (initdb already
    # ran), then re-running against a FRESH call log.
    from civiccast.native.provision.journal import write_journal
    from civiccast.native.provision.models import ProvisionJournal

    harness = _harness(tmp_path)
    context = _context(tmp_path)
    harness.postgres_version = "17"  # world state: initdb already ran before the kill

    seeded = ProvisionJournal(
        plan=_plan(),
        context=context,
        phase=ProvisionPhase.POSTGRES_CLUSTER_READY,
        history=[
            (ProvisionPhase.PACK_VERIFIED.value, "2026-01-01T00:00:00+00:00", "verified"),
            (
                ProvisionPhase.POSTGRES_CLUSTER_READY.value,
                "2026-01-01T00:00:01+00:00",
                "initdb ran",
            ),
        ],
    )
    write_journal(seeded)

    resumed = run_provision(_plan(), context, harness.seams())

    assert resumed.ok
    # verify_pack / detect_postgres_cluster / run_initdb must NOT be
    # re-invoked -- resume continues from POSTGRES_CLUSTER_READY, not INIT.
    assert "verify_pack" not in harness.calls
    assert "run_initdb" not in harness.calls
    assert harness.calls == [
        "write_postgres_conf",
        "write_pg_hba_conf",
        "ensure_database",
    ]


def test_negative_control_call_log_actually_distinguishes_ran_from_skipped(
    tmp_path: Path,
) -> None:
    """Proves the harness itself can tell 'ran' from 'skipped' -- otherwise
    the idempotency assertions above would be vacuously true."""

    harness = _harness(tmp_path)
    assert harness.calls == []
    harness.run_initdb()
    assert harness.calls == ["run_initdb"]
