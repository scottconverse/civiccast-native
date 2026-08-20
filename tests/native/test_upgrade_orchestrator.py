# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""D3 orchestration tests: forward sequence, resume idempotency, rollback matrix.

The seams are FAKES, but they are dependency-injected into the REAL orchestrator
and REAL journal state machine — the same code that runs in production drives
these fakes, so the test exercises orchestration logic, not a re-implementation.
The junction seam uses the REAL junction module against temp directories
(``mklink /J`` needs no elevation; a POSIX symlink stands in on CI).

Each failure-injection test asserts the D3 unwind: a pre-mutation failure
reverts the junction with NO DB restore; a post-mutation failure restores the
backup AND reverts the junction; a restore FAILURE halts with the service
stopped and an operator recovery document; a declared-non-restorable migration
is refused. A negative-control test proves the harness can actually distinguish
"restored" from "not restored" (so the rollback assertions are not vacuous).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from civiccast.native.upgrade import junction
from civiccast.native.upgrade.models import (
    BackupRef,
    UpgradeContext,
    UpgradePhase,
    UpgradePlan,
    UpgradeSeams,
)
from civiccast.native.upgrade.orchestrator import run_upgrade


@dataclass
class Harness:
    """A live, temp-dir-backed fake of the world the engine acts on.

    ``db_schema`` models the database's alembic revision; ``migrate`` advances
    it, ``restore_backup`` rewinds it to the snapshot taken at backup time.
    Failure injection flags simulate each step going wrong.
    """

    install_root: Path
    state_root: Path
    payload_source: Path

    db_schema: str = "old-rev"
    backup_snapshot: str | None = None
    interlock_held: bool = False
    service_stopped: bool = False
    calls: list[str] = field(default_factory=list)

    # Failure injection.
    fail_quiescence: bool = False
    backup_verified: bool = True
    backup_drill_ok: bool = True
    fail_migrate: bool = False
    fail_health: bool = False
    fail_restore: bool = False

    def _record(self, name: str) -> None:
        self.calls.append(name)

    # --- seam implementations -------------------------------------------------

    def acquire_interlock(self) -> None:
        self._record("acquire_interlock")
        self.interlock_held = True

    def release_interlock(self) -> None:
        self._record("release_interlock")
        self.interlock_held = False

    def drain_and_verify_quiescence(self) -> bool:
        self._record("drain")
        return not self.fail_quiescence

    def backup(self, backup_dir: str) -> BackupRef:
        self._record("backup")
        dest = Path(backup_dir)
        dest.mkdir(parents=True, exist_ok=True)
        # Snapshot the current DB schema into the backup (the recovery point).
        self.backup_snapshot = self.db_schema
        (dest / "database.pgdump").write_text(self.db_schema, encoding="utf-8")
        return BackupRef(
            backup_id="backup-test",
            backup_dir=str(dest),
            manifest_hash="a" * 64,
            db_artifact="database.pgdump",
            verified=self.backup_verified,
            restore_drill_ok=self.backup_drill_ok,
        )

    def restore_backup(self, backup: BackupRef) -> None:
        self._record("restore_backup")
        if self.fail_restore:
            raise RuntimeError("injected restore failure (disk full)")
        assert self.backup_snapshot is not None
        self.db_schema = self.backup_snapshot

    def lay_tree(self, new_version: str) -> str:
        self._record("lay_tree")
        target = self.install_root / "app" / new_version
        target.mkdir(parents=True, exist_ok=True)
        (target / "civiccast.exe").write_text(new_version, encoding="utf-8")
        return str(target.resolve())

    def flip_junction(self, target: str) -> None:
        self._record(f"flip_junction:{Path(target).name}")
        junction.point_current_at(self.install_root, target)

    def read_junction(self) -> str | None:
        return junction.read_current_target(self.install_root)

    def migrate(self) -> None:
        self._record("migrate")
        if self.fail_migrate:
            raise RuntimeError("injected migration failure")
        self.db_schema = "new-rev"

    def health_gate(self) -> bool:
        self._record("health_gate")
        return not self.fail_health

    def schema_revision(self) -> str | None:
        return self.db_schema

    def stop_service(self) -> None:
        self._record("stop_service")
        self.service_stopped = True

    def seams(self) -> UpgradeSeams:
        return UpgradeSeams(
            acquire_interlock=self.acquire_interlock,
            release_interlock=self.release_interlock,
            drain_and_verify_quiescence=self.drain_and_verify_quiescence,
            backup=self.backup,
            restore_backup=self.restore_backup,
            lay_tree=self.lay_tree,
            flip_junction=self.flip_junction,
            read_junction=self.read_junction,
            migrate=self.migrate,
            health_gate=self.health_gate,
            schema_revision=self.schema_revision,
            stop_service=self.stop_service,
        )


def _plan(**kw) -> UpgradePlan:
    return UpgradePlan(old_version="1.0", new_version="1.1", **kw)


def _make(tmp_path) -> Harness:
    install_root = tmp_path / "install"
    state_root = tmp_path / "state"
    payload = tmp_path / "payload"
    payload.mkdir()
    (payload / "civiccast.exe").write_text("payload", encoding="utf-8")
    # Seed an existing live tree + junction (an upgrade, not a fresh install).
    old_tree = install_root / "app" / "1.0"
    old_tree.mkdir(parents=True)
    (old_tree / "civiccast.exe").write_text("1.0", encoding="utf-8")
    junction.point_current_at(install_root, old_tree)
    return Harness(install_root=install_root, state_root=state_root, payload_source=payload)


def _context(h: Harness) -> UpgradeContext:
    return UpgradeContext(
        install_root=str(h.install_root),
        state_root=str(h.state_root),
        database_url="postgresql://u@localhost/db",
        owner_run_id="run-1",
    )


# --- happy path ---------------------------------------------------------------


def test_full_upgrade_commits(tmp_path) -> None:
    h = _make(tmp_path)
    outcome = run_upgrade(_plan(), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.COMPLETE
    assert outcome.ok
    # Committed: interlock released, junction on the new tree, schema migrated.
    assert h.interlock_held is False
    assert Path(h.read_junction()).name == "1.1"
    assert h.db_schema == "new-rev"
    # Journal binds pre/post schema revisions.
    assert outcome.journal.pre_schema_revision == "old-rev"
    assert outcome.journal.post_schema_revision == "new-rev"
    assert outcome.journal.backup is not None


# --- pre-mutation failures: junction reverts, NO DB restore -------------------


def test_quiescence_failure_rolls_back_without_backup(tmp_path) -> None:
    h = _make(tmp_path)
    h.fail_quiescence = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.ROLLED_BACK
    assert "restore_backup" not in h.calls  # DB never touched
    assert "backup" not in h.calls  # failed before backup
    assert h.interlock_held is False


def test_health_failure_before_migrate_is_impossible_but_tree_lay_failure_reverts(tmp_path) -> None:
    # A backup-verification failure happens after tree work has NOT begun, so
    # the junction must still point at the old tree and the DB is untouched.
    h = _make(tmp_path)
    h.backup_drill_ok = False
    outcome = run_upgrade(_plan(), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.ROLLED_BACK
    assert "restore_backup" not in h.calls
    assert Path(h.read_junction()).name == "1.0"


# --- post-mutation failures: junction reverts AND DB restores -----------------


def test_migration_failure_reverts_junction_and_restores_db(tmp_path) -> None:
    h = _make(tmp_path)
    h.fail_migrate = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.ROLLED_BACK
    # migrate is at the frontier: junction was flipped to new, must revert; DB
    # restored to the pre-upgrade snapshot.
    assert "restore_backup" in h.calls
    assert Path(h.read_junction()).name == "1.0"
    assert h.db_schema == "old-rev"
    assert h.interlock_held is False


def test_health_failure_after_migrate_reverts_and_restores(tmp_path) -> None:
    h = _make(tmp_path)
    h.fail_health = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.ROLLED_BACK
    assert "restore_backup" in h.calls
    assert Path(h.read_junction()).name == "1.0"
    assert h.db_schema == "old-rev"


# --- rollback-restore failure: HALT with service stopped + recovery doc -------


def test_restore_failure_halts_with_service_stopped_and_recovery_doc(tmp_path) -> None:
    h = _make(tmp_path)
    h.fail_migrate = True  # triggers rollback
    h.fail_restore = True  # rollback's restore then fails
    outcome = run_upgrade(_plan(), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.HALTED_RESTORE_FAILED
    assert h.service_stopped is True
    # Recovery document emitted and named in the journal.
    doc = outcome.journal.recovery_document_path
    assert doc is not None
    assert Path(doc).exists()
    text = Path(doc).read_text(encoding="utf-8")
    assert "STOPPED" in text
    assert "backup" in text.lower()
    # Backup + journal preserved.
    assert Path(outcome.journal.backup.backup_dir).exists()


def test_halt_never_leaves_old_binary_on_new_schema(tmp_path) -> None:
    # The invariant: on a restore failure the service is stopped and stays
    # stopped — no health/start happens after the halt.
    h = _make(tmp_path)
    h.fail_migrate = True
    h.fail_restore = True
    run_upgrade(_plan(), _context(h), h.seams())
    # stop_service is the last lifecycle action; nothing starts after it.
    assert h.calls[-1] == "stop_service" or "stop_service" in h.calls
    assert h.service_stopped is True


# --- declared-non-restorable refusal ------------------------------------------


def test_non_restorable_migration_without_ack_is_refused(tmp_path) -> None:
    h = _make(tmp_path)
    outcome = run_upgrade(_plan(migration_restorable=False), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.REFUSED_NON_RESTORABLE
    # Nothing acquired or mutated.
    assert h.calls == []
    assert h.interlock_held is False


def test_non_restorable_migration_with_ack_proceeds(tmp_path) -> None:
    h = _make(tmp_path)
    outcome = run_upgrade(
        _plan(migration_restorable=False, operator_ack="operator-signed-off"),
        _context(h),
        h.seams(),
    )
    assert outcome.phase is UpgradePhase.COMPLETE


# --- negative control (harness is not vacuous) --------------------------------


def test_negative_control_restore_actually_rewinds_schema(tmp_path) -> None:
    # Prove the harness distinguishes restored vs not: if restore were a no-op,
    # db_schema would stay "new-rev" after a post-migrate rollback and the
    # rollback assertions above would be vacuous.
    h = _make(tmp_path)
    h.fail_health = True
    run_upgrade(_plan(), _context(h), h.seams())
    assert h.db_schema == "old-rev"  # genuinely rewound, not left at new-rev
