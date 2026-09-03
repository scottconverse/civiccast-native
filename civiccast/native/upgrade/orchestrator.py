# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The D3 journaled upgrade sequence, its rollback, and its halt path.

This module is PURE ORCHESTRATION over the injected
:class:`~civiccast.native.upgrade.models.UpgradeSeams`. It never touches
Windows, Postgres, or the supervisor itself -- every real action is a seam.
That is what lets a fake-seam test exercise the REAL state machine (the same
code that runs in production), rather than a re-implementation of it.

The forward sequence (spec D3):

  1 acquire interlock              -> INTERLOCK_ACQUIRED
  2 drain writers + verify quiesce -> WRITERS_DRAINED
  3 verified pre-upgrade backup    -> BACKUP_VERIFIED   (recovery point exists)
  4 lay app\\<new>\\ + flip junction -> TREE_LAID          (records prev target)
  5 alembic upgrade head           -> MIGRATED           (records post revision)
  6 maintenance/read-only health   -> HEALTH_GREEN
  7 release interlock (commit)     -> COMPLETE

Failure handling (spec D3, exact):

* A failure BEFORE the mutation frontier (before MIGRATED) unwinds the
  filesystem only: flip the junction back to the recorded previous target (if
  a flip happened) and release the interlock -> ROLLED_BACK. The database was
  never mutated, so no restore is needed.
* A failure AT or AFTER MIGRATED flips the junction back AND restores the
  step-3 backup, so the old binary never runs against a newer schema. Success
  -> ROLLED_BACK.
* If that restore itself fails, HALT: ensure the service is stopped (never
  running on a wrong schema), preserve the verified backup + journal, and emit
  the operator recovery document -> HALTED_RESTORE_FAILED.
* A release whose migration is declared non-restorable
  (``plan.migration_restorable=False``) with no ``operator_ack`` is refused at
  phase 0 -> REFUSED_NON_RESTORABLE.

Resume (idempotent): :func:`run_upgrade` reads any existing journal for the
context and continues from its recorded boundary. Because the on-disk phase is
only advanced AFTER its real action succeeds and is persisted, a kill at any
boundary leaves a journal the resume can drive to a clean COMPLETE or a clean
rollback. Each forward step is individually idempotent (see the per-step
docstrings), so re-running a step whose effect already landed is safe.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from civiccast.native.upgrade import journal as journal_io
from civiccast.native.upgrade.models import (
    OperatorRecovery,
    UpgradeContext,
    UpgradeJournal,
    UpgradeOutcome,
    UpgradePhase,
    UpgradePlan,
    UpgradeSeams,
)

RECOVERY_DOC_NAME = "UPGRADE-RECOVERY.md"


def _persist(
    journal: UpgradeJournal, phase: UpgradePhase, detail: str, **updates: object
) -> UpgradeJournal:
    """Advance the journal one boundary and write it atomically."""

    journal = journal_io.advance(journal, phase, detail, **updates)
    journal_io.write_journal(journal)
    return journal


def _terminal(
    journal: UpgradeJournal, phase: UpgradePhase, detail: str, **updates: object
) -> UpgradeJournal:
    """Move to a terminal phase (not rank-gated) and write it atomically."""

    journal = journal_io.advance(journal, phase, detail, **updates)
    journal_io.write_journal(journal)
    return journal


def run_upgrade(
    plan: UpgradePlan,
    context: UpgradeContext,
    seams: UpgradeSeams,
) -> UpgradeOutcome:
    """Execute (or resume) the D3 upgrade for ``context``; return the outcome.

    Never raises for an expected upgrade failure -- every failure lands as a
    terminal journal phase (ROLLED_BACK / HALTED_RESTORE_FAILED /
    REFUSED_NON_RESTORABLE) so the caller (NSIS hook / CLI) reads an exit code,
    not a stack trace. A programming error in a seam still propagates.
    """

    existing = journal_io.load_journal(context.state_root)
    if existing is not None and not existing.phase.is_terminal:
        return _resume(existing, seams)
    # A terminal journal for this state root: a fresh upgrade would overwrite a
    # recovery point that may still matter. Start fresh ONLY from COMPLETE (the
    # previous upgrade committed); a terminal FAILURE journal is left for the
    # operator, and we refuse to bulldoze it silently.
    if existing is not None and existing.phase is not UpgradePhase.COMPLETE:
        return UpgradeOutcome(phase=existing.phase, journal=existing)

    journal = UpgradeJournal(plan=plan, context=context, phase=UpgradePhase.INIT)

    # D3 gate: a declared-non-restorable migration refuses auto-upgrade.
    if not plan.migration_restorable and not plan.operator_ack:
        journal = _terminal(
            journal,
            UpgradePhase.REFUSED_NON_RESTORABLE,
            "migration declared non-restorable and no operator_ack supplied; "
            "auto-upgrade refused (manual path required)",
            error="migration_restorable=False without operator_ack",
        )
        return UpgradeOutcome(phase=journal.phase, journal=journal)

    journal_io.write_journal(journal)  # phase-0 recorded before anything is acquired
    journal = journal.model_copy(
        update={
            "pre_schema_revision": seams.schema_revision(),
        }
    )
    journal_io.write_journal(journal)
    return _drive_forward(journal, seams)


def _resume(journal: UpgradeJournal, seams: UpgradeSeams) -> UpgradeOutcome:
    """Continue an interrupted upgrade from its recorded boundary.

    The recorded phase names the LAST boundary whose real action both
    succeeded and was persisted. Resume re-drives forward from there; every
    forward step is idempotent, so re-attempting the next step is safe even if
    the kill happened just after its effect but just before its journal write.
    """

    return _drive_forward(journal, seams)


def _drive_forward(journal: UpgradeJournal, seams: UpgradeSeams) -> UpgradeOutcome:
    """Walk the forward D3 steps from the journal's current phase to COMPLETE.

    On any step failure, hand off to :func:`_rollback`, which chooses the
    pre- vs post-mutation unwind based on the step being ATTEMPTED when the
    failure fired -- not merely the last persisted phase. This distinction is
    load-bearing: a ``seams.migrate()`` that RAISES leaves the journal at
    TREE_LAID (MIGRATED is only persisted on success), yet the migration was
    attempted and may have partially mutated the schema, so the unwind MUST
    restore the backup. ``attempting`` carries that intent into the handler.
    """

    attempting = journal.phase
    try:
        if journal.phase.rank < UpgradePhase.INTERLOCK_ACQUIRED.rank:
            attempting = UpgradePhase.INTERLOCK_ACQUIRED
            seams.acquire_interlock()
            journal = _persist(
                journal, UpgradePhase.INTERLOCK_ACQUIRED, "D7a maintenance interlock acquired"
            )

        if journal.phase.rank < UpgradePhase.WRITERS_DRAINED.rank:
            attempting = UpgradePhase.WRITERS_DRAINED
            if not seams.drain_and_verify_quiescence():
                raise RuntimeError("writers did not drain / quiescence not verified (WS2 snapshot)")
            journal = _persist(
                journal, UpgradePhase.WRITERS_DRAINED, "writers drained; quiescence verified"
            )

        if journal.phase.rank < UpgradePhase.BACKUP_VERIFIED.rank:
            attempting = UpgradePhase.BACKUP_VERIFIED
            backup_dir = str(
                Path(journal.context.state_root) / "backups" / f"pre-{journal.plan.new_version}"
            )
            backup_ref = seams.backup(backup_dir)
            if not (backup_ref.verified and backup_ref.restore_drill_ok):
                detail = (
                    "; ".join(backup_ref.restore_drill_errors)
                    if backup_ref.restore_drill_errors
                    else "no detail reported (verified=False before a restore-drill ran)"
                )
                raise RuntimeError(
                    "pre-upgrade backup failed verification (hash or restore-drill spot check): "
                    f"{detail}"
                )
            journal = _persist(
                journal,
                UpgradePhase.BACKUP_VERIFIED,
                "verified pre-upgrade backup taken (hash + restore-drill spot check)",
                backup=backup_ref,
            )

        if journal.phase.rank < UpgradePhase.TREE_LAID.rank:
            attempting = UpgradePhase.TREE_LAID
            previous_target = seams.read_junction()
            new_target = seams.lay_tree(journal.plan.new_version)
            seams.flip_junction(new_target)
            journal = _persist(
                journal,
                UpgradePhase.TREE_LAID,
                f"payload target prepared and selected: {new_target}",
                previous_junction_target=previous_target,
                new_junction_target=new_target,
            )

        if journal.phase.rank < UpgradePhase.MIGRATED.rank:
            attempting = UpgradePhase.MIGRATED
            seams.migrate()
            post_revision = seams.schema_revision()
            journal = _persist(
                journal,
                UpgradePhase.MIGRATED,
                "alembic upgrade head applied",
                post_schema_revision=post_revision,
            )

        if journal.phase.rank < UpgradePhase.HEALTH_GREEN.rank:
            attempting = UpgradePhase.HEALTH_GREEN
            if not seams.health_gate():
                raise RuntimeError(
                    "service did not reach green in maintenance/read-only health mode"
                )
            journal = _persist(
                journal, UpgradePhase.HEALTH_GREEN, "maintenance/read-only health green"
            )

        if journal.phase.rank < UpgradePhase.COMPLETE.rank:
            attempting = UpgradePhase.COMPLETE
            seams.release_interlock()
            journal = _persist(
                journal, UpgradePhase.COMPLETE, "interlock released; upgrade committed"
            )

    except NotImplementedError:
        # A genuinely unwired seam is a programming/wiring fault, NOT an
        # operational upgrade failure -- it must propagate loud, never be
        # laundered into a normal ROLLED_BACK outcome. (WP-4 wired the three
        # service-control seams; this guard remains for any future unwired seam.)
        raise
    except Exception as exc:  # any OPERATIONAL step failure funnels to the D3 unwind
        return _rollback(journal, seams, reason=str(exc), attempting=attempting)

    return UpgradeOutcome(phase=journal.phase, journal=journal)


def _rollback(
    journal: UpgradeJournal,
    seams: UpgradeSeams,
    *,
    reason: str,
    attempting: UpgradePhase,
) -> UpgradeOutcome:
    """Unwind a failed upgrade per D3, choosing pre- vs post-mutation semantics.

    * Before the mutation frontier (the failing step was BEFORE the migration):
      flip the junction back (if it moved) and release the interlock. No DB
      restore -- the schema was never touched.
    * At/after the mutation frontier (the failing step WAS the migration, or a
      step after it): flip the junction back AND restore the step-3 backup so
      the old binary never runs against a newer schema. If the restore raises,
      HALT (service stopped, backup + journal preserved, operator recovery
      document emitted).

    ``attempting`` is the phase whose action was running when the failure fired.
    Keying on it (not the last persisted phase) is what makes a RAISING migrate
    -- which never advances the journal to MIGRATED -- still restore the DB.
    """

    after_mutation = attempting.rank >= UpgradePhase.MIGRATED.rank

    # Restore the DB FIRST on the post-mutation path, so that if the restore
    # fails we never flip the old binary live against the new schema (the
    # service is left stopped by the halt). The junction flip-back follows a
    # successful restore.
    if after_mutation:
        try:
            if journal.backup is None:  # pragma: no cover - MIGRATED implies a backup exists
                raise RuntimeError("no backup recorded at/after MIGRATED — cannot restore")
            seams.restore_backup(journal.backup)
        except Exception as restore_exc:  # restore failure IS the halt trigger
            return _halt(journal, seams, upgrade_reason=reason, restore_error=str(restore_exc))

    # Flip the junction back to the recorded previous target (both paths, if a
    # flip happened). previous_junction_target is None on a fresh install with
    # no prior live tree; nothing to flip back to then.
    if (
        journal.previous_junction_target is not None
        and journal.phase.rank >= UpgradePhase.TREE_LAID.rank
    ):
        seams.flip_junction(journal.previous_junction_target)

    # Release the interlock so the (rolled-back, old-version) runtime resumes.
    seams.release_interlock()

    detail = f"rolled back after failure ({reason}); " + (
        "DB restored from backup + junction reverted"
        if after_mutation
        else "junction/tree reverted (no DB mutation)"
    )
    journal = _terminal(journal, UpgradePhase.ROLLED_BACK, detail, error=reason)
    return UpgradeOutcome(phase=journal.phase, journal=journal)


def _halt(
    journal: UpgradeJournal,
    seams: UpgradeSeams,
    *,
    upgrade_reason: str,
    restore_error: str,
) -> UpgradeOutcome:
    """The rollback-restore-failure terminal state (spec D3).

    Ensures the service is stopped (so no binary runs against a wrong schema),
    preserves the verified backup + journal, and emits an operator recovery
    document naming exact next steps.
    """

    # Never leave anything running on a schema we could not roll back.
    seams.stop_service()

    doc_path = _write_recovery_document(
        journal, upgrade_reason=upgrade_reason, restore_error=restore_error
    )
    detail = (
        f"HALTED: rollback restore failed ({restore_error}) after upgrade failure ({upgrade_reason}); "
        f"service stopped, backup + journal preserved, recovery document at {doc_path}"
    )
    journal = _terminal(
        journal,
        UpgradePhase.HALTED_RESTORE_FAILED,
        detail,
        error=f"restore failed: {restore_error}",
        recovery_document_path=str(doc_path),
    )
    return UpgradeOutcome(phase=journal.phase, journal=journal)


def _write_recovery_document(
    journal: UpgradeJournal,
    *,
    upgrade_reason: str,
    restore_error: str,
) -> Path:
    """Write the operator recovery markdown next to the journal; return its path."""

    state_root = Path(journal.context.state_root)
    state_root.mkdir(parents=True, exist_ok=True)
    doc_path = state_root / RECOVERY_DOC_NAME
    journal_file = journal_io.journal_path(state_root)
    backup = journal.backup

    next_steps = [
        "Do NOT start the CivicCast (Native) service — its schema may be the "
        "partially-migrated new schema while the binary on disk is the old "
        "version. Starting it risks corrupting data.",
        f"The verified pre-upgrade backup is preserved at: "
        f"{backup.backup_dir if backup else '(none recorded)'}",
        f"Manually restore that backup into the database at "
        f"{journal.context.database_url} using the WS2 restore tooling "
        f"(civiccast.dr.backup.run_postgres_restore against "
        f"{backup.db_artifact if backup else '(artifact)'}).",
        f"After a verified restore, re-point the 'current' junction under "
        f"{journal.context.install_root} back to "
        f"{journal.previous_junction_target or '(the previous app tree)'}.",
        "Then release the D7a maintenance interlock "
        "(HKLM\\SOFTWARE\\CivicCast\\Maintenance) and start the old version.",
        f"Preserve this journal for support: {journal_file}",
    ]
    recovery = OperatorRecovery(
        written_utc=datetime.now(UTC).isoformat(),
        old_version=journal.plan.old_version,
        new_version=journal.plan.new_version,
        backup_dir=backup.backup_dir if backup else "(none recorded)",
        backup_manifest_hash=backup.manifest_hash if backup else "(none)",
        journal_path=str(journal_file),
        reason=f"upgrade failed ({upgrade_reason}); automatic rollback restore also failed ({restore_error})",
        next_steps=next_steps,
    )

    lines = [
        "# CivicCast (Native) — Upgrade Recovery Required",
        "",
        f"- Written: {recovery.written_utc}",
        f"- Upgrade: {recovery.old_version} -> {recovery.new_version}",
        f"- Reason: {recovery.reason}",
        f"- Backup dir: {recovery.backup_dir}",
        f"- Backup manifest hash: {recovery.backup_manifest_hash}",
        f"- Journal: {recovery.journal_path}",
        "",
        "## The service has been STOPPED and left stopped on purpose.",
        "",
        "Automatic rollback could not restore the pre-upgrade database, so the "
        "engine halted rather than risk running a binary against a schema it "
        "does not match. Follow these steps IN ORDER:",
        "",
    ]
    lines.extend(f"{i}. {step}" for i, step in enumerate(recovery.next_steps, start=1))
    lines.append("")
    doc_path.write_text("\n".join(lines), encoding="utf-8")
    return doc_path
