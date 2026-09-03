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

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

import pytest

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
    # <installer-path-audit> injections the pre-batch harness could not
    # express, each named for the finding it exists to prove. Before these,
    # `acquire_interlock` could never fail (so the concurrent-second-instance
    # shape had no test at all), and neither could the rollback's own
    # flip-back, interlock release, or the halt's service stop -- the three
    # paths BL-07 shows escaping as exit 40 with no terminal journal.
    fail_interlock: bool = False  # BL-05: a second concurrent engine instance
    fail_flip_back: bool = False  # BL-07: a raise inside _rollback
    fail_release_interlock: bool = False  # BL-07: a raise inside _rollback
    fail_stop_service: bool = False  # BL-07: a raise inside _halt
    no_op_migrate: bool = False  # BL-03: `alembic upgrade head` silently no-ops
    #: BL-03: what the SHIPPED payload expects. None models a bundle with no
    #: expected_schema_head seam wired at all.
    expected_head: str | None = "new-rev"
    #: MA-01: what adapt_flat_installer_layout sets on the production bundle.
    filesystem_rollback: bool = True

    def _record(self, name: str) -> None:
        self.calls.append(name)

    # --- seam implementations -------------------------------------------------

    def acquire_interlock(self) -> None:
        self._record("acquire_interlock")
        if self.fail_interlock:
            # The real take_interlock's message shape when another run holds
            # it (civiccast.native.win_probes._held_interlock_detail).
            raise RuntimeError(
                "cannot take interlock: held by run 'run-A'; taken 2026-09-03T00:00:00+00:00; "
                "generation 4; owning process pid=4242 is STILL RUNNING"
            )
        self.interlock_held = True

    def release_interlock(self) -> None:
        self._record("release_interlock")
        if self.fail_release_interlock:
            raise RuntimeError("injected interlock release failure (registry ACL denied)")
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
        if self.fail_flip_back and Path(target).name == "1.0":
            raise RuntimeError("injected junction flip-back failure (target locked)")
        junction.point_current_at(self.install_root, target)

    def read_junction(self) -> str | None:
        return junction.read_current_target(self.install_root)

    def migrate(self) -> None:
        self._record("migrate")
        if self.fail_migrate:
            raise RuntimeError("injected migration failure")
        if self.no_op_migrate:
            # <installer-path-audit BL-03> `alembic upgrade head` silently
            # doing NOTHING -- the version-location discovery regression
            # alembic/env.py's own docstring warns about. The seam returns
            # cleanly; the database simply never moved.
            return
        self.db_schema = "new-rev"

    def health_gate(self) -> bool:
        self._record("health_gate")
        return not self.fail_health

    def schema_revision(self) -> str | None:
        return self.db_schema

    def expected_schema_head(self) -> str | None:
        return self.expected_head

    def stop_service(self) -> None:
        self._record("stop_service")
        if self.fail_stop_service:
            # The real build_stop_service_seam documents that a failing SCM
            # stop PROPAGATES ("the halt must not falsely believe it stopped
            # the service") -- e.g. a service wedged in STOP_PENDING.
            raise RuntimeError("injected SCM stop failure (service stuck in STOP_PENDING)")
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
            expected_schema_head=self.expected_schema_head,
            filesystem_rollback=self.filesystem_rollback,
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
    # <installer-path-audit MA-40> The `or "stop_service" in h.calls` disjunct
    # SUBSUMED the ordering assertion this test's own name makes, so a
    # regression that ran health_gate AFTER stop_service passed. Deleted.
    assert h.calls[-1] == "stop_service", (
        f"stop_service must be the LAST lifecycle action on the halt path; got {h.calls}"
    )
    assert h.service_stopped is True


# ---------------------------------------------------------------------------
# Installer-path audit (2026-09-03): the engine's own blind spots.
# ---------------------------------------------------------------------------


def test_bl03_a_migration_that_silently_no_ops_rolls_back_instead_of_committing(
    tmp_path,
) -> None:
    """<installer-path-audit BL-03> ``post_schema_revision`` was written to the
    journal and NEVER READ.

    Nothing compared it to the expected head and nothing compared it to
    ``pre_schema_revision``. So an ``alembic upgrade head`` that silently
    no-ops left the control plane maintenance-attested, D3 committing
    COMPLETE, exit 0, and the station running new code on the old schema --
    with the only backstop an external CI check, not the product.
    """
    h = _make(tmp_path)
    h.no_op_migrate = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())

    assert outcome.phase is UpgradePhase.ROLLED_BACK, (
        "a migration that did not land must never commit"
    )
    assert outcome.journal.error is not None
    assert "migration did not land" in outcome.journal.error
    assert "old-rev" in outcome.journal.error and "new-rev" in outcome.journal.error
    assert "health_gate" not in h.calls, "the health gate must not even be reached"


def test_bl03_a_landed_migration_records_the_head_it_was_verified_against(
    tmp_path,
) -> None:
    h = _make(tmp_path)
    outcome = run_upgrade(_plan(), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.COMPLETE
    assert outcome.journal.post_schema_revision == "new-rev"
    migrated = [entry for entry in outcome.journal.history if entry[0] == "migrated"]
    assert migrated and "verified at new-rev" in migrated[0][2]


def test_bl03_an_unwired_expected_head_seam_says_so_rather_than_passing_silently(
    tmp_path,
) -> None:
    """A bundle with no expected-head seam must RECORD that the assertion was
    unavailable, not quietly behave as though it passed."""
    h = _make(tmp_path)
    h.expected_head = None
    outcome = run_upgrade(_plan(), _context(h), h.seams())
    assert outcome.phase is UpgradePhase.COMPLETE
    migrated = [entry for entry in outcome.journal.history if entry[0] == "migrated"]
    assert migrated and "UNAVAILABLE" in migrated[0][2]


def test_bl05_a_second_engine_instance_never_releases_the_first_ones_interlock(
    tmp_path,
) -> None:
    """<installer-path-audit BL-05> THE concurrency defect.

    Run A holds the interlock inside ``migrate()``. Run B (a second setup.exe,
    a retry, an operator double-click) cannot take it, funnels into
    ``_rollback`` -- and the unconditional ``seams.release_interlock()`` there
    released **A's**. The supervisor then re-permits writers against a schema
    mid-migration; B reports ROLLED_BACK/exit 10 and A reports COMPLETE/exit
    0, both journals internally consistent and both wrong about the machine.

    The engine's own guard is "release only when this run recorded acquiring
    it"; ``win_probes.release_interlock``'s owner check is the second half.
    """
    h = _make(tmp_path)
    h.fail_interlock = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())

    assert outcome.phase is UpgradePhase.ROLLED_BACK
    assert "release_interlock" not in h.calls, (
        "the loser must not touch the interlock it never took"
    )
    assert outcome.journal.error is not None
    assert "interlock NOT released" in outcome.journal.error
    # It also says WHY it could not proceed, carrying the holder's identity
    # through from the real probe's message.
    assert "cannot take interlock" in outcome.journal.error


def test_bl07_a_raising_flip_back_still_lands_a_terminal_journal(tmp_path) -> None:
    """<installer-path-audit BL-07> ``_rollback`` had no failure containment.

    A raise from ``flip_junction`` escaped ``_rollback``, escaped
    ``run_upgrade`` (the try in ``_drive_forward`` has already been exited),
    and reached ``__main__`` as exit 40 "unexpected fault" -- leaving a
    NON-TERMINAL journal and a leaked interlock.
    """
    h = _make(tmp_path)
    h.fail_health = True  # a pre-mutation failure, so the flip-back runs
    h.fail_flip_back = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())

    assert outcome.phase is UpgradePhase.ROLLED_BACK
    assert outcome.journal.phase.is_terminal
    assert "junction flip-back failed" in (outcome.journal.error or "")
    assert h.interlock_held is False, "the interlock must still be released"


def test_bl07_a_raising_interlock_release_still_lands_a_terminal_journal(tmp_path) -> None:
    h = _make(tmp_path)
    h.fail_health = True
    h.fail_release_interlock = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())

    assert outcome.phase is UpgradePhase.ROLLED_BACK
    assert "interlock release failed" in (outcome.journal.error or "")


def test_bl07_a_wedged_service_stop_still_writes_the_recovery_document(tmp_path) -> None:
    """The halt's own worst case, and the whole point of the finding.

    Migration fails, the restore fails, AND the SCM stop fails -- a service
    stuck in STOP_PENDING, which is common when a child hangs. Previously:
    no HALTED_RESTORE_FAILED journal, no UPGRADE-RECOVERY.md, a journal frozen
    at TREE_LAID/MIGRATED, a possibly-RUNNING service on a half-migrated
    schema, and an operator told "unexpected fault, see the installer log".
    **The one artifact designed for exactly this case was the one that did not
    get written.**
    """
    h = _make(tmp_path)
    h.fail_migrate = True
    h.fail_restore = True
    h.fail_stop_service = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())

    assert outcome.phase is UpgradePhase.HALTED_RESTORE_FAILED
    doc = outcome.journal.recovery_document_path
    assert doc is not None and Path(doc).exists(), (
        "the recovery document must be written even when the stop that follows it fails"
    )
    assert "could not be confirmed STOPPED" in (outcome.journal.error or "")
    assert "sc.exe stop" in outcome.journal.error


def test_ma01_a_flat_layout_rollback_does_not_claim_it_reverted_the_payload(
    tmp_path,
) -> None:
    """<installer-path-audit MA-01> The journal used to state a false fact.

    Under ``--flat-installer-layout`` -- which
    ``nsis-hooks-bootstrap.nsh`` passes on EVERY invocation, so it is the only
    layout production runs -- ``read_junction``/``lay_tree``/``flip_junction``
    all resolve to the same ``<install_root>\\runtime`` string, so
    ``previous_junction_target == new_junction_target`` and the flip-back is a
    tautology. The journal wrote "junction/tree reverted" anyway. After
    PR #143 the installer and the journal told different stories about the
    same event, with only the installer right.
    """
    h = _make(tmp_path)
    h.filesystem_rollback = False
    h.fail_health = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())

    assert outcome.phase is UpgradePhase.ROLLED_BACK
    assert outcome.journal.filesystem_rollback is False
    rolled_back = [e for e in outcome.journal.history if e[0] == "rolled_back"]
    assert rolled_back
    detail = rolled_back[0][2]
    assert "was NOT reverted" in detail
    assert "junction/tree reverted" not in detail


def test_ma01_the_flat_layout_recovery_document_names_the_step_that_matters(
    tmp_path,
) -> None:
    """The old document told the operator to "re-point the 'current' junction"
    -- a junction that does not exist under this layout -- at a path that
    already holds the NEW code, and omitted the reinstall that actually
    matters. The worst-case recovery document for the only layout that ships.
    """
    h = _make(tmp_path)
    h.filesystem_rollback = False
    h.fail_migrate = True
    h.fail_restore = True
    outcome = run_upgrade(_plan(), _context(h), h.seams())

    assert outcome.phase is UpgradePhase.HALTED_RESTORE_FAILED
    text = Path(outcome.journal.recovery_document_path).read_text(encoding="utf-8")
    assert "re-install 1.0" in text.lower() or "re-install 1.0" in text
    assert "Restoring the database alone is NOT enough" in text
    assert "re-point the 'current' junction" not in text


@pytest.mark.parametrize(
    "failing_seam",
    ["backup", "lay_tree", "restore_backup"],
)
def test_item16_a_real_enospc_lands_a_terminal_journal_not_a_string_labelled_one(
    tmp_path, failing_seam: str
) -> None:
    """<batch-fix-list item 16> "disk full" was a LABEL IN A STRING.

    ``test_upgrade_orchestrator.py``'s only disk-full coverage was
    ``RuntimeError("injected restore failure (disk full)")`` -- a
    ``RuntimeError`` whose message happens to contain the words. A real
    ``OSError(errno.ENOSPC)`` is a different type entirely, and the engine's
    funnel is ``except Exception``, so the distinction matters only if
    something along the way narrows it. Nothing should: an out-of-space
    failure at ANY seam must still land a terminal journal and a documented
    exit code, never escape as the CLI's exit-40 "unexpected fault".
    """
    import errno

    h = _make(tmp_path)
    seams = h.seams()

    def _enospc(*args: object, **kwargs: object) -> object:
        raise OSError(errno.ENOSPC, "No space left on device")

    if failing_seam == "restore_backup":
        # Reachable only past the mutation frontier.
        h.fail_migrate = True
        seams = dataclasses.replace(h.seams(), restore_backup=_enospc)
        expected = UpgradePhase.HALTED_RESTORE_FAILED
    else:
        seams = dataclasses.replace(h.seams(), **{failing_seam: _enospc})
        expected = UpgradePhase.ROLLED_BACK

    outcome = run_upgrade(_plan(), _context(h), seams)

    assert outcome.phase is expected, (
        f"an ENOSPC at {failing_seam} landed {outcome.phase}, not a terminal phase"
    )
    assert outcome.journal.phase.is_terminal
    assert "No space left on device" in (outcome.journal.error or ""), (
        "the real OS error must reach the journal, so the operator reads 'disk full' "
        "rather than a generic step name"
    )


def test_ma02_the_previous_junction_target_is_persisted_before_the_flip(tmp_path) -> None:
    """<installer-path-audit MA-02> ``junction.py`` already CLAIMS the journal
    records the previous target "BEFORE the flip". The code recorded it after.

    A journal write that raised between the flip and the persist left
    ``previous_junction_target=None``, so ``_rollback``'s guard skipped the
    flip-back entirely while reporting "junction/tree reverted" -- PR #143's
    own defect, one level up. Proven by reading the journal from disk at the
    instant ``lay_tree`` runs, i.e. after ``read_junction`` and before
    ``flip_junction``.
    """
    from civiccast.native.upgrade.journal import load_journal

    h = _make(tmp_path)
    observed: list[str | None] = []
    real_lay_tree = h.lay_tree

    def _observing_lay_tree(new_version: str) -> str:
        journal = load_journal(str(h.state_root))
        observed.append(journal.previous_junction_target if journal else None)
        return real_lay_tree(new_version)

    seams = dataclasses.replace(h.seams(), lay_tree=_observing_lay_tree)
    outcome = run_upgrade(_plan(), _context(h), seams)

    assert outcome.phase is UpgradePhase.COMPLETE
    assert observed, "lay_tree must have run"
    assert observed[0] is not None, (
        "previous_junction_target must already be on disk before the flip; it was None"
    )
    assert Path(observed[0]).name == "1.0"


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
