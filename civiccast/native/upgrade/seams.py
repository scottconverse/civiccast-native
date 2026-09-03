# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Default (real) seam implementations for the D3 upgrade engine.

The orchestrator is pure over :class:`~civiccast.native.upgrade.models.UpgradeSeams`;
this module builds the PRODUCTION bundle that wires each seam to the real
machinery already proven elsewhere in the tree:

* interlock  -> :mod:`civiccast.native.win_probes` (D7a, ws4)
* backup     -> :func:`civiccast.dr.backup.run_full_backup` + a restore-drill
                spot check via :func:`civiccast.dr.restore_drill.run_postgres_restore_drill`
                (WS2). Verification is "artifact hash + restore-drill spot check"
                exactly as D3 step 3 requires.
* restore    -> :func:`civiccast.dr.backup.run_postgres_restore` (WS2)
* migrate    -> ``alembic.command.upgrade(cfg, "head")`` against the live DB,
                using the same path resolution the startup schema check uses
                (:func:`civiccast.schema_check._alembic_runtime_paths`)
* schema rev -> :func:`civiccast.schema_check.read_db_revision`
* junction   -> :mod:`civiccast.native.upgrade.junction`

Three seams are service-control actions (drain writers, start the
maintenance/read-only health gate, stop the service). Those cross into the
Windows Service Control Manager + the running supervisor. WP-4 wired them to
real production callables in
:mod:`civiccast.native.upgrade.service_control` (SCM start/stop, the D7
control-pipe status read, the ``/health`` maintenance attestation, and the WS2
snapshot-equality quiescence proof). :func:`build_default_seams` therefore
REQUIRES the caller to pass those three callables rather than shipping a fake
default that would silently no-op a safety-critical step; ``__main__`` supplies
them via ``service_control.resolve_service_control_seams``. Their real OS/DB
round trips fire only on the elevated install host (the WP-5 live matrix).
"""

from __future__ import annotations

import dataclasses
import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

from civiccast.db.url import normalize_database_url
from civiccast.dr.backup import run_full_backup, run_postgres_restore
from civiccast.dr.models import BackupManifest
from civiccast.dr.restore_drill import run_postgres_restore_drill
from civiccast.native.upgrade import junction
from civiccast.native.upgrade.models import (
    BackupRef,
    UpgradeContext,
    UpgradeSeams,
)


def _manifest_blob_hash(manifest: BackupManifest) -> str:
    """A single sha256 over the backup set's per-file integrity hashes.

    The manifest's ``integrity`` block already carries a sha256 per shipped
    file (see :func:`civiccast.dr.backup.write_integrity_manifest`); folding
    them into one digest gives the whole backup a stable blob identity the
    journal can bind to and a later step can re-derive to detect tampering.
    """

    hasher = hashlib.sha256()
    for entry in sorted(manifest.integrity, key=lambda e: e.member):
        hasher.update(entry.member.encode("utf-8"))
        hasher.update(b"\x1f")
        hasher.update(entry.sha256.encode("utf-8"))
        hasher.update(b"\x1e")
    return hasher.hexdigest()


def default_acquire_interlock(owner_run_id: str) -> Callable[[], None]:
    def _acquire() -> None:
        from civiccast.native.win_probes import take_interlock

        take_interlock(owner_run_id)

    return _acquire


def default_release_interlock() -> Callable[[], None]:
    def _release() -> None:
        from civiccast.native.win_probes import release_interlock

        release_interlock()

    return _release


def default_backup(
    context: UpgradeContext,
    *,
    media_root: Path | None = None,
    pg_dump_command: list[str] | None = None,
    pg_dumpall_command: list[str] | None = None,
    pg_restore_command: list[str] | None = None,
    psql_command: list[str] | None = None,
) -> Callable[[str], BackupRef]:
    """Real pre-upgrade backup: WS2 full backup + a restore-drill spot check.

    D3 step 3 requires the backup be VERIFIED "artifact hash + restore-drill
    spot check" BEFORE any mutation. This does both: takes the WS2 full backup
    (which itself writes + hashes an integrity manifest), then restores it into
    a throwaway database and asserts row/checksum/schema parity via
    :func:`run_postgres_restore_drill`. A failure of either raises (the
    orchestrator treats a raise or an unverified ref as a hard stop, so no
    mutation proceeds without a proven recovery point).
    """

    def _backup(backup_dir: str) -> BackupRef:
        dest = Path(backup_dir)
        manifest = run_full_backup(
            database_url=context.database_url,
            dest_dir=dest,
            media_root=media_root,
            pg_dump_command=pg_dump_command,
            pg_dumpall_command=pg_dumpall_command,
        )
        blob_hash = _manifest_blob_hash(manifest)

        restore_ok = False
        drill_errors: list[str] = []
        if manifest.engine == "postgres":
            # The pre-upgrade drill's "schema_ok" question is "does the
            # restored copy match what we actually dumped", NOT "does it
            # match the NEW code's migration head" -- migrate() has not run
            # yet, so on any release that ships a migration the latter is
            # always false (Gate A run 33681670855 root cause). Pass the
            # SOURCE database's own current revision -- read from the same
            # database this backup was just taken from, so it reflects the
            # exact pre-upgrade state the dump captured.
            from civiccast.schema_check import read_db_revision

            source_revision = read_db_revision(context.database_url)
            report = run_postgres_restore_drill(
                backup_dir=dest,
                manifest=manifest,
                source_database_url=context.database_url,
                pg_restore_command=pg_restore_command,
                psql_command=psql_command,
                expected_revision=source_revision,
            )
            restore_ok = report.ok
            if not restore_ok:
                drill_errors = list(report.errors)
                if not report.schema_ok:
                    drill_errors.append(
                        "schema_ok=False: restored revision "
                        f"{report.db_revision!r} != expected {report.expected_head!r}"
                    )
        else:
            # SQLite deployments verify via the same drill entry point in WS2;
            # the native product targets Postgres, so a non-postgres engine
            # here is unexpected — fail closed rather than claim a spot check
            # we did not run.
            restore_ok = False
            drill_errors = ["backup manifest engine is not 'postgres'; no restore-drill was run"]

        return BackupRef(
            backup_id=manifest.backup_id,
            backup_dir=str(dest),
            manifest_hash=blob_hash,
            db_artifact=manifest.db_artifact,
            verified=bool(manifest.integrity),
            restore_drill_ok=restore_ok,
            restore_drill_errors=drill_errors,
        )

    return _backup


def default_restore_backup(
    context: UpgradeContext,
    *,
    pg_restore_command: list[str] | None = None,
) -> Callable[[BackupRef], None]:
    def _restore(backup: BackupRef) -> None:
        artifact = Path(backup.backup_dir) / backup.db_artifact
        run_postgres_restore(
            artifact,
            context.database_url,
            pg_restore_command=pg_restore_command,
        )

    return _restore


def default_lay_tree(
    context: UpgradeContext, *, payload_source: str | Path
) -> Callable[[str], str]:
    """Lay ``app\\<new>\\`` by copying the (already verified) payload tree in.

    WP-4 Part B produced the BUILD-time half of D2: the audited closure is
    embedded in the signed bundle, byte-verified against runtime-manifest.json
    (see ``scripts/build_native_installer.py``). The payload SOURCE here is
    whatever the NSIS installer unpacked to a staging dir; D2's install-time
    verification (SHA256SUMS chained to the Authenticode signature) is
    asserted by the installer BEFORE this runs, so this copy trusts an
    already-verified staging tree. Wiring that install-time staging path +
    verification call is WP-5 -- see ``next-cleanup.md``.
    """

    def _lay(new_version: str) -> str:
        target = Path(context.install_root) / "app" / new_version
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copytree(payload_source, target)
        return str(target.resolve())

    return _lay


def default_flip_junction(context: UpgradeContext) -> Callable[[str], None]:
    def _flip(target: str) -> None:
        junction.point_current_at(context.install_root, target)

    return _flip


def default_read_junction(context: UpgradeContext) -> Callable[[], str | None]:
    def _read() -> str | None:
        return junction.read_current_target(context.install_root)

    return _read


def adapt_flat_installer_layout(
    seams: UpgradeSeams,
    context: UpgradeContext,
) -> UpgradeSeams:
    """Model the payload layout the production NSIS installer actually uses.

    The bootstrap extracts and D2-verifies the live Python payload directly at
    ``<install_root>\\runtime`` before it starts D3.  Service registration and
    station activation also consume that flat path; they do not consume the
    generic engine's ``app\\<version>`` / ``current`` junction convention.

    Replacing only the three payload-selection seams keeps D3's safety-critical
    writer drain, verified backup/restore drill, migration, health gate, and
    journal intact.  The adapter deliberately refuses any target other than the
    verified flat runtime, so it cannot silently turn into a general no-op.
    """

    runtime = (Path(context.install_root) / "runtime").resolve()

    def _require_runtime() -> str:
        if not runtime.is_dir():
            raise RuntimeError(
                f"flat runtime payload is missing after installer D2 verification: {runtime}"
            )
        return str(runtime)

    def _select_runtime(target: str) -> None:
        expected = _require_runtime()
        if Path(target).resolve() != runtime:
            raise RuntimeError(
                "flat runtime payload selector refused an unexpected target: "
                f"expected {expected}, got {target}"
            )

    return dataclasses.replace(
        seams,
        read_junction=_require_runtime,
        lay_tree=lambda _new_version: _require_runtime(),
        flip_junction=_select_runtime,
    )


def default_migrate(context: UpgradeContext) -> Callable[[], None]:
    """Run ``alembic upgrade head`` against the live DB, in-process.

    Uses the same ini/script/version-location resolution the startup schema
    check uses (:func:`civiccast.schema_check._alembic_runtime_paths`), so the
    engine walks EVERY module's migration head exactly like a shell
    ``alembic upgrade head`` would, and is idempotent (already-applied
    revisions are skipped by alembic).
    """

    def _migrate() -> None:
        from alembic import command
        from alembic.config import Config

        from civiccast.schema_check import _alembic_runtime_paths

        ini, script_location, version_locations = _alembic_runtime_paths()
        cfg = Config(str(ini))
        cfg.set_main_option("script_location", str(script_location.resolve()))
        cfg.set_main_option(
            "version_locations",
            "\n".join(str(path.resolve()) for path in version_locations),
        )
        cfg.set_main_option("path_separator", "newline")
        # normalize_database_url: a bare `postgresql://` scheme maps to the
        # uninstalled psycopg2 dialect (ADR 0008 ships psycopg v3 only) --
        # beta BLOCKER #51. alembic's env.py reads this back from cfg, so
        # normalizing here covers the whole `alembic upgrade head` run.
        cfg.set_main_option("sqlalchemy.url", normalize_database_url(context.database_url))
        command.upgrade(cfg, "head")

    return _migrate


def default_schema_revision(context: UpgradeContext) -> Callable[[], str | None]:
    def _revision() -> str | None:
        from civiccast.schema_check import read_db_revision

        return read_db_revision(context.database_url)

    return _revision


def build_default_seams(
    context: UpgradeContext,
    *,
    payload_source: str | Path,
    drain_and_verify_quiescence: Callable[[], bool],
    health_gate: Callable[[], bool],
    stop_service: Callable[[], None],
    media_root: Path | None = None,
    pg_dump_command: list[str] | None = None,
    pg_dumpall_command: list[str] | None = None,
    pg_restore_command: list[str] | None = None,
    psql_command: list[str] | None = None,
) -> UpgradeSeams:
    """Assemble the production seam bundle for ``context``.

    The three service-control seams (``drain_and_verify_quiescence``,
    ``health_gate``, ``stop_service``) are REQUIRED arguments, not defaulted:
    they cross into the SCM + the running supervisor. Requiring them keeps this
    function honest — it never ships a silent no-op for a safety-critical step.
    WP-4 wired them in :mod:`civiccast.native.upgrade.service_control`
    (``resolve_service_control_seams``): SCM start for the maintenance health
    gate, SCM stop for the halt path, and a control-pipe drain-confirm + WS2
    snapshot-equality check for drain; ``__main__`` passes them here.
    """

    return UpgradeSeams(
        acquire_interlock=default_acquire_interlock(context.owner_run_id),
        release_interlock=default_release_interlock(),
        drain_and_verify_quiescence=drain_and_verify_quiescence,
        backup=default_backup(
            context,
            media_root=media_root,
            pg_dump_command=pg_dump_command,
            pg_dumpall_command=pg_dumpall_command,
            pg_restore_command=pg_restore_command,
            psql_command=psql_command,
        ),
        restore_backup=default_restore_backup(context, pg_restore_command=pg_restore_command),
        lay_tree=default_lay_tree(context, payload_source=payload_source),
        flip_junction=default_flip_junction(context),
        read_junction=default_read_junction(context),
        migrate=default_migrate(context),
        health_gate=health_gate,
        schema_revision=default_schema_revision(context),
        stop_service=stop_service,
    )
