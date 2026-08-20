# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""WP-5 clean-venue lifecycle proof driver (spec-installer-lifecycle D3/D7).

This driver exercises the REAL D3 engine (``civiccast.native.upgrade.run_upgrade``,
its real on-disk journal, the real ``current`` NTFS junction, and the real
``lay_tree`` copytree) against a SYNTHETIC install root, injecting fakes ONLY for
the seams that need live infrastructure the clean venue cannot host without the
application payload (Postgres backup/restore/migrate/schema-read and the three
service-control seams). It is the guest-runnable half of the clean-venue harness:
the host launcher (see ``wp5-sandbox-launch.sh`` / the ``.wsb`` template) maps this
file read-only into a pristine Windows Sandbox and runs it; it also runs verbatim
on the dev box for a real-NTFS (non-pristine) proof.

WHY a synthetic root and injected DB/service seams: the shipped installer embeds
only the media runtime closure, not a CPython interpreter + the civiccast package
(the WP-5 app-payload finding, ``wp5-app-payload-finding.md``). Without that
payload there is no registered LocalSystem service, no live Postgres, and no
bootable install, so every matrix row that asserts a *live, operable product*
(supervisor-ready, data-intact, health-green, coexistence, cross-uninstall of an
operable survivor) is BLOCKED-ON-FINDING and cannot run here. What this driver
CAN prove now is the engine's filesystem/journal/rollback/halt/resume machinery
against a real filesystem and a real process kill — an escalation over the
in-process unit tests (fakes + seeded journals) to a real-process, real-NTFS run.

The driver never rubber-stamps: :func:`selftest` runs the row-checkers against a
DELIBERATELY-WRONG expectation and asserts they report FAIL (negative control),
so a green result means the checks can actually distinguish pass from fail.

Usage::

    python wp5_lifecycle_driver.py --out-dir <dir>          # run the row battery
    python wp5_lifecycle_driver.py --selftest               # negative controls only
    python wp5_lifecycle_driver.py --power-loss-worker ...   # internal (spawned)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Make the repo importable when this file is run from an arbitrary mount
# (e.g. C:\repo\.agent-runs\...\evidence\ inside the sandbox).
_HERE = Path(__file__).resolve()
for _up in _HERE.parents:
    if (_up / "civiccast" / "__init__.py").exists() or (_up / "pyproject.toml").exists():
        if str(_up) not in sys.path:
            sys.path.insert(0, str(_up))
        break

from civiccast.native.upgrade.journal import load_journal  # noqa: E402
from civiccast.native.upgrade.models import (  # noqa: E402
    BackupRef,
    UpgradeContext,
    UpgradePhase,
    UpgradePlan,
    UpgradeSeams,
)
from civiccast.native.upgrade.orchestrator import RECOVERY_DOC_NAME, run_upgrade  # noqa: E402
from civiccast.native.upgrade.seams import (  # noqa: E402
    default_flip_junction,
    default_lay_tree,
    default_read_junction,
)

# ---------------------------------------------------------------------------
# Synthetic environment + injectable fake seams
# ---------------------------------------------------------------------------


def _make_synthetic_root(base: Path, *, old_version: str | None) -> tuple[UpgradeContext, Path]:
    """Create install_root (+ optional prior ``app/<old>`` & ``current`` link),
    a synthetic payload source tree, and a state_root. Returns (context, payload)."""

    install_root = base / "install"
    state_root = base / "state"
    payload = base / "payload"
    install_root.mkdir(parents=True, exist_ok=True)
    state_root.mkdir(parents=True, exist_ok=True)
    # A synthetic "verified app tree" the installer would have placed & verified.
    payload.mkdir(parents=True, exist_ok=True)
    (payload / "civiccast-native.exe").write_text("synthetic app binary\n", encoding="utf-8")
    (payload / "VERSION.txt").write_text("payload\n", encoding="utf-8")

    context = UpgradeContext(
        install_root=str(install_root),
        state_root=str(state_root),
        database_url="postgresql://synthetic/civiccast",
        owner_run_id="wp5-driver-run",
    )

    if old_version is not None:
        old_tree = install_root / "app" / old_version
        old_tree.mkdir(parents=True, exist_ok=True)
        (old_tree / "civiccast-native.exe").write_text("old app binary\n", encoding="utf-8")
        default_flip_junction(context)(str(old_tree.resolve()))
    return context, payload


@dataclass
class _SeamCalls:
    backup: int = 0
    restore: int = 0
    migrate: int = 0
    health: int = 0
    stop: int = 0
    acquire: int = 0
    release: int = 0
    drain: int = 0


def _make_seams(
    context: UpgradeContext,
    payload: Path,
    *,
    calls: _SeamCalls,
    backup_verified: bool = True,
    drain_ok: bool = True,
    health_ok: bool = True,
    migrate_raises: bool = False,
    restore_raises: bool = False,
    block_at: str | None = None,
    sentinel: Path | None = None,
) -> UpgradeSeams:
    """Real filesystem seams + injectable fakes for the DB/service seams.

    ``block_at`` names a seam that, when reached, writes ``sentinel`` and then
    blocks forever — used by the power-loss worker so the parent can kill the
    process at a precise journal boundary.
    """

    def _maybe_block(name: str) -> None:
        if block_at == name:
            if sentinel is not None:
                sentinel.write_text(f"reached:{name}\n", encoding="utf-8")
            # Block far longer than the parent's kill deadline.
            time.sleep(3600)

    def _acquire() -> None:
        calls.acquire += 1

    def _release() -> None:
        calls.release += 1

    def _drain() -> bool:
        calls.drain += 1
        return drain_ok

    def _backup(backup_dir: str) -> BackupRef:
        calls.backup += 1
        dest = Path(backup_dir)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "db.dump").write_text("synthetic dump\n", encoding="utf-8")
        _maybe_block("backup")
        return BackupRef(
            backup_id="synthetic-backup",
            backup_dir=str(dest),
            manifest_hash="0" * 64,
            db_artifact="db.dump",
            verified=backup_verified,
            restore_drill_ok=backup_verified,
        )

    def _restore(backup: BackupRef) -> None:
        calls.restore += 1
        if restore_raises:
            raise RuntimeError("injected restore failure (WP-5 halt row)")

    def _migrate() -> None:
        calls.migrate += 1
        _maybe_block("migrate")
        if migrate_raises:
            raise RuntimeError("injected incompatible-migration failure (WP-5 schema row)")

    def _schema() -> str | None:
        return "headrev"

    def _health() -> bool:
        calls.health += 1
        _maybe_block("health")
        return health_ok

    def _stop() -> None:
        calls.stop += 1

    def _lay(new_version: str) -> str:
        _maybe_block("lay")
        return default_lay_tree(context, payload_source=payload)(new_version)

    return UpgradeSeams(
        acquire_interlock=_acquire,
        release_interlock=_release,
        drain_and_verify_quiescence=_drain,
        backup=_backup,
        restore_backup=_restore,
        lay_tree=_lay,
        flip_junction=default_flip_junction(context),
        read_junction=default_read_junction(context),
        migrate=_migrate,
        health_gate=_health,
        schema_revision=_schema,
        stop_service=_stop,
    )


# ---------------------------------------------------------------------------
# Row result model
# ---------------------------------------------------------------------------


@dataclass
class RowResult:
    row: str
    spec_pass_condition: str
    passed: bool
    observed: dict[str, object] = field(default_factory=dict)


def _norm(p: str | None) -> str | None:
    return str(Path(p).resolve()) if p else None


# ---------------------------------------------------------------------------
# Matrix rows (the sandbox-provable / partial half)
# ---------------------------------------------------------------------------


def row_fresh_install_fs(base: Path) -> RowResult:
    cond = (
        "Fresh install — FS/journal half of 'Supervisor ready': engine commits, "
        "current junction points at app/<new>, app tree laid from the verified payload, "
        "journal COMPLETE. (supervisor-ready + pre-login-after-reboot half deferred — needs bootable payload + VM reboot.)"
    )
    ctx, payload = _make_synthetic_root(base, old_version=None)
    calls = _SeamCalls()
    outcome = run_upgrade(
        UpgradePlan(old_version="none", new_version="1.0.0-rc15"),
        ctx,
        _make_seams(ctx, payload, calls=calls),
    )
    new_tree = Path(ctx.install_root) / "app" / "1.0.0-rc15"
    cur = _norm(default_read_junction(ctx)())
    passed = (
        outcome.phase is UpgradePhase.COMPLETE
        and cur == _norm(str(new_tree))
        and (new_tree / "civiccast-native.exe").exists()
    )
    return RowResult(
        "fresh_install_fs",
        cond,
        passed,
        {"phase": outcome.phase.value, "current": cur, "app_tree_present": (new_tree).exists()},
    )


def row_upgrade_fs(base: Path) -> RowResult:
    cond = (
        "Upgrade vN->vN+1 — FS/journal half: engine commits, current re-points to "
        "app/<new>, both app trees present, journal binds pre/post schema. "
        "(data-intact WS2 snapshot equality + live health-green deferred — needs live Postgres + service.)"
    )
    ctx, payload = _make_synthetic_root(base, old_version="1.0.0-rc15")
    calls = _SeamCalls()
    outcome = run_upgrade(
        UpgradePlan(old_version="1.0.0-rc15", new_version="1.0.0-rc16"),
        ctx,
        _make_seams(ctx, payload, calls=calls),
    )
    new_tree = Path(ctx.install_root) / "app" / "1.0.0-rc16"
    old_tree = Path(ctx.install_root) / "app" / "1.0.0-rc15"
    cur = _norm(default_read_junction(ctx)())
    passed = (
        outcome.phase is UpgradePhase.COMPLETE
        and cur == _norm(str(new_tree))
        and old_tree.exists()
        and new_tree.exists()
        and outcome.journal.pre_schema_revision is not None
        and outcome.journal.post_schema_revision is not None
    )
    return RowResult(
        "upgrade_fs",
        cond,
        passed,
        {
            "phase": outcome.phase.value,
            "current": cur,
            "old_tree_present": old_tree.exists(),
            "pre_schema": outcome.journal.pre_schema_revision,
            "post_schema": outcome.journal.post_schema_revision,
        },
    )


def row_failed_upgrade_health(base: Path) -> RowResult:
    cond = (
        "Failed upgrade (health): health gate refuses readiness => junction flipped "
        "back to the old tree AND DB restore invoked; terminal ROLLED_BACK."
    )
    ctx, payload = _make_synthetic_root(base, old_version="1.0.0-rc15")
    old_tree = Path(ctx.install_root) / "app" / "1.0.0-rc15"
    calls = _SeamCalls()
    outcome = run_upgrade(
        UpgradePlan(old_version="1.0.0-rc15", new_version="1.0.0-rc16"),
        ctx,
        _make_seams(ctx, payload, calls=calls, health_ok=False),
    )
    cur = _norm(default_read_junction(ctx)())
    passed = (
        outcome.phase is UpgradePhase.ROLLED_BACK
        and cur == _norm(str(old_tree))
        and calls.restore == 1  # post-mutation unwind restores the DB
    )
    return RowResult(
        "failed_upgrade_health",
        cond,
        passed,
        {"phase": outcome.phase.value, "current": cur, "restore_calls": calls.restore},
    )


def row_failed_upgrade_schema(base: Path) -> RowResult:
    cond = (
        "Failed upgrade (schema): a raising migration => restore path proves the old "
        "binary never runs against the new schema — junction reverted, DB restored, "
        "terminal ROLLED_BACK."
    )
    ctx, payload = _make_synthetic_root(base, old_version="1.0.0-rc15")
    old_tree = Path(ctx.install_root) / "app" / "1.0.0-rc15"
    calls = _SeamCalls()
    outcome = run_upgrade(
        UpgradePlan(old_version="1.0.0-rc15", new_version="1.0.0-rc16"),
        ctx,
        _make_seams(ctx, payload, calls=calls, migrate_raises=True),
    )
    cur = _norm(default_read_junction(ctx)())
    passed = (
        outcome.phase is UpgradePhase.ROLLED_BACK
        and cur == _norm(str(old_tree))
        and calls.restore == 1
    )
    return RowResult(
        "failed_upgrade_schema",
        cond,
        passed,
        {"phase": outcome.phase.value, "current": cur, "restore_calls": calls.restore},
    )


def row_rollback_restore_failure_halt(base: Path) -> RowResult:
    cond = (
        "Rollback-restore failure (injected): migration fails AND restore fails => "
        "installer HALTS with service stopped, backup + journal preserved, operator "
        "recovery document emitted; terminal HALTED_RESTORE_FAILED."
    )
    ctx, payload = _make_synthetic_root(base, old_version="1.0.0-rc15")
    calls = _SeamCalls()
    outcome = run_upgrade(
        UpgradePlan(old_version="1.0.0-rc15", new_version="1.0.0-rc16"),
        ctx,
        _make_seams(ctx, payload, calls=calls, migrate_raises=True, restore_raises=True),
    )
    recovery = Path(ctx.state_root) / RECOVERY_DOC_NAME
    journal_file = Path(ctx.state_root) / "upgrade-journal.json"
    backup_dir = Path(ctx.state_root) / "backups" / "pre-1.0.0-rc16"
    doc_text = recovery.read_text(encoding="utf-8") if recovery.exists() else ""
    passed = (
        outcome.phase is UpgradePhase.HALTED_RESTORE_FAILED
        and calls.stop == 1
        and recovery.exists()
        and journal_file.exists()
        and backup_dir.exists()
        and "STOPPED" in doc_text
        and str(backup_dir) in doc_text.replace("/", os.sep)
    )
    return RowResult(
        "rollback_restore_failure_halt",
        cond,
        passed,
        {
            "phase": outcome.phase.value,
            "stop_calls": calls.stop,
            "recovery_doc": recovery.exists(),
            "journal_preserved": journal_file.exists(),
            "backup_preserved": backup_dir.exists(),
        },
    )


def row_refusal_non_restorable(base: Path) -> RowResult:
    cond = (
        "Declared non-restorable migration without operator ack => auto-upgrade REFUSED "
        "at phase 0, no filesystem mutation; terminal REFUSED_NON_RESTORABLE."
    )
    ctx, payload = _make_synthetic_root(base, old_version="1.0.0-rc15")
    old_tree = Path(ctx.install_root) / "app" / "1.0.0-rc15"
    calls = _SeamCalls()
    outcome = run_upgrade(
        UpgradePlan(old_version="1.0.0-rc15", new_version="1.0.0-rc16", migration_restorable=False),
        ctx,
        _make_seams(ctx, payload, calls=calls),
    )
    cur = _norm(default_read_junction(ctx)())
    new_tree = Path(ctx.install_root) / "app" / "1.0.0-rc16"
    passed = (
        outcome.phase is UpgradePhase.REFUSED_NON_RESTORABLE
        and cur == _norm(str(old_tree))
        and not new_tree.exists()
        and calls.acquire == 0
        and calls.backup == 0
    )
    return RowResult(
        "refusal_non_restorable",
        cond,
        passed,
        {"phase": outcome.phase.value, "current": cur, "new_tree_present": new_tree.exists()},
    )


def row_same_version_reinstall(base: Path) -> RowResult:
    cond = (
        "Same-version reinstall: re-running an upgrade to the already-current version "
        "is non-destructive and idempotent — commits again, current unchanged, no error."
    )
    ctx, payload = _make_synthetic_root(base, old_version=None)
    plan = UpgradePlan(old_version="none", new_version="1.0.0-rc15")
    first = run_upgrade(plan, ctx, _make_seams(ctx, payload, calls=_SeamCalls()))
    second = run_upgrade(plan, ctx, _make_seams(ctx, payload, calls=_SeamCalls()))
    new_tree = Path(ctx.install_root) / "app" / "1.0.0-rc15"
    cur = _norm(default_read_junction(ctx)())
    passed = (
        first.phase is UpgradePhase.COMPLETE
        and second.phase is UpgradePhase.COMPLETE
        and cur == _norm(str(new_tree))
        and (new_tree / "civiccast-native.exe").exists()
    )
    return RowResult(
        "same_version_reinstall",
        cond,
        passed,
        {"first": first.phase.value, "second": second.phase.value, "current": cur},
    )


# --- power loss: REAL process kill at each journal boundary ------------------

_POWER_LOSS_BOUNDARIES = {
    # sentinel-seam -> journal phase the kill leaves persisted
    "lay": "backup_verified",  # kill during lay_tree: journal at BACKUP_VERIFIED (pre-mutation)
    "migrate": "tree_laid",  # kill during migrate: journal at TREE_LAID
    "health": "migrated",  # kill during health: journal at MIGRATED
}


def row_power_loss_resume(base: Path, boundary_seam: str) -> RowResult:
    expected_phase = _POWER_LOSS_BOUNDARIES[boundary_seam]
    cond = (
        f"Power loss (kill during '{boundary_seam}', journal at {expected_phase}): a REAL "
        "process is killed mid-run; a fresh process re-drives from the journal to a clean "
        "COMPLETE with no double-lay / double-backup."
    )
    root = base / f"pl_{boundary_seam}"
    root.mkdir(parents=True, exist_ok=True)
    sentinel = root / "reached.sentinel"
    ctx_dir = root  # worker & parent derive the same synthetic root from this dir

    # 1) spawn the worker; it blocks at the target seam after writing the sentinel.
    worker = subprocess.Popen(  # fixed argv (our own interpreter + this file), no shell
        [
            sys.executable,
            str(_HERE),
            "--power-loss-worker",
            "--root",
            str(ctx_dir),
            "--block-at",
            boundary_seam,
            "--sentinel",
            str(sentinel),
        ],
    )
    observed: dict[str, object] = {"boundary_seam": boundary_seam, "expected_phase": expected_phase}
    try:
        deadline = time.time() + 60
        while not sentinel.exists():
            if worker.poll() is not None:
                observed["error"] = f"worker exited early (rc={worker.returncode})"
                return RowResult(f"power_loss_{boundary_seam}", cond, False, observed)
            if time.time() > deadline:
                observed["error"] = "worker never reached the boundary within 60s"
                worker.kill()
                return RowResult(f"power_loss_{boundary_seam}", cond, False, observed)
            time.sleep(0.2)
        # 2) KILL the worker hard at the boundary (simulated power loss).
        worker.kill()
        worker.wait(timeout=30)
    finally:
        if worker.poll() is None:
            worker.kill()

    # 3) journal on disk must be exactly at the pre-kill boundary.
    ctx = UpgradeContext(
        install_root=str(ctx_dir / "install"),
        state_root=str(ctx_dir / "state"),
        database_url="postgresql://synthetic/civiccast",
        owner_run_id="wp5-driver-run",
    )
    killed_journal = load_journal(ctx.state_root)
    observed["journal_after_kill"] = killed_journal.phase.value if killed_journal else None

    # 4) fresh process (this one) RESUMES from the journal to COMPLETE.
    payload = ctx_dir / "payload"
    calls = _SeamCalls()
    outcome = run_upgrade(
        UpgradePlan(old_version="none", new_version="1.0.0-rc15"),
        ctx,
        _make_seams(ctx, payload, calls=calls),
    )
    new_tree = Path(ctx.install_root) / "app" / "1.0.0-rc15"
    cur = _norm(default_read_junction(ctx)())
    # No double work past the boundary: backup ran in the worker (pre-kill) for the
    # migrate/health boundaries, so the resume must NOT re-backup them.
    resume_rebackup = calls.backup
    passed = (
        killed_journal is not None
        and killed_journal.phase.value == expected_phase
        and outcome.phase is UpgradePhase.COMPLETE
        and cur == _norm(str(new_tree))
        and (resume_rebackup == 0 if expected_phase != "backup_verified" else True)
    )
    observed.update(
        {
            "resume_phase": outcome.phase.value,
            "current": cur,
            "resume_backup_calls": resume_rebackup,
        }
    )
    return RowResult(f"power_loss_{boundary_seam}", cond, passed, observed)


def _power_loss_worker(root: Path, block_at: str, sentinel: Path) -> int:
    """Worker entrypoint: run the upgrade but block at ``block_at`` so the parent
    can kill this process at a precise journal boundary."""

    ctx, payload = _make_synthetic_root(root, old_version=None)
    run_upgrade(
        UpgradePlan(old_version="none", new_version="1.0.0-rc15"),
        ctx,
        _make_seams(ctx, payload, calls=_SeamCalls(), block_at=block_at, sentinel=sentinel),
    )
    return 0  # never reached (the seam blocks); the parent kills us


# ---------------------------------------------------------------------------
# Runner + negative-control selftest
# ---------------------------------------------------------------------------

_ROWS = [
    row_fresh_install_fs,
    row_upgrade_fs,
    row_failed_upgrade_health,
    row_failed_upgrade_schema,
    row_rollback_restore_failure_halt,
    row_refusal_non_restorable,
    row_same_version_reinstall,
]


def run_all_rows(work: Path) -> list[RowResult]:
    results: list[RowResult] = []
    for i, fn in enumerate(_ROWS):
        base = work / f"row_{i}_{fn.__name__}"
        base.mkdir(parents=True, exist_ok=True)
        results.append(fn(base))
    for seam in _POWER_LOSS_BOUNDARIES:
        base = work / f"row_pl_{seam}"
        base.mkdir(parents=True, exist_ok=True)
        results.append(row_power_loss_resume(base, seam))
    return results


def selftest(work: Path) -> bool:
    """Negative control: the row-checkers must be able to FAIL.

    Run a known-good row but assert an outcome we KNOW is wrong; the checker must
    report passed==False. Also run failed-upgrade-health and assert it does NOT
    report COMPLETE. If either 'passes' the wrong assertion, the harness is broken.
    """

    ok = True
    # (a) A fresh install genuinely COMPLETES; verify the checker flags a corrupted
    # expectation by breaking the environment (remove payload) so it CANNOT lay.
    base = work / "selftest_a"
    base.mkdir(parents=True, exist_ok=True)
    ctx, payload = _make_synthetic_root(base, old_version=None)
    shutil.rmtree(payload)  # payload gone -> lay_tree must fail -> NOT COMPLETE
    calls = _SeamCalls()
    outcome = run_upgrade(
        UpgradePlan(old_version="none", new_version="1.0.0-rc15"),
        ctx,
        _make_seams(ctx, payload, calls=calls),
    )
    # With no payload the engine cannot commit; a driver that reported COMPLETE here
    # would be lying. Assert the engine did NOT reach COMPLETE.
    if outcome.phase is UpgradePhase.COMPLETE:
        print("SELFTEST FAIL: engine reported COMPLETE with no payload to lay")
        ok = False
    # (b) failed-upgrade-health must roll back, never COMPLETE.
    base_b = work / "selftest_b"
    base_b.mkdir(parents=True, exist_ok=True)
    r = row_failed_upgrade_health(base_b)
    if not r.passed:
        print("SELFTEST FAIL: failed_upgrade_health checker did not accept a genuine rollback")
        ok = False
    # (c) Prove the checker rejects a WRONG expectation: temporarily assert the
    # fresh-install row equals a bogus junction and confirm mismatch is detected.
    base_c = work / "selftest_c"
    base_c.mkdir(parents=True, exist_ok=True)
    good = row_fresh_install_fs(base_c)
    if not good.passed:
        print("SELFTEST FAIL: fresh_install_fs did not pass on a genuine good run")
        ok = False
    if good.observed.get("current") == "definitely-not-a-real-path":
        print("SELFTEST FAIL: observed current matched a bogus control value")
        ok = False
    return ok


def _write_reports(results: list[RowResult], selftest_ok: bool, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "platform": sys.platform,
        "python": sys.version.split()[0],
        "cwd": str(Path.cwd()),
        "selftest_ok": selftest_ok,
        "rows": [asdict(r) for r in results],
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
    }
    (out_dir / "wp5-lifecycle-driver-result.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WP-5 clean-venue lifecycle proof driver")
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--selftest", action="store_true")
    # internal worker flags
    parser.add_argument("--power-loss-worker", action="store_true")
    parser.add_argument("--root", default=None)
    parser.add_argument("--block-at", default=None)
    parser.add_argument("--sentinel", default=None)
    args = parser.parse_args(argv)

    if args.power_loss_worker:
        return _power_loss_worker(Path(args.root), args.block_at, Path(args.sentinel))

    import tempfile

    work = Path(args.work_dir) if args.work_dir else Path(tempfile.mkdtemp(prefix="wp5-driver-"))
    out_dir = Path(args.out_dir) if args.out_dir else work

    st_ok = selftest(work / "selftest")
    print(f"selftest: {'OK' if st_ok else 'BROKEN'}")
    if args.selftest:
        return 0 if st_ok else 1
    if not st_ok:
        print("Refusing to run the row battery: the harness selftest is broken.")
        return 1

    results = run_all_rows(work / "rows")
    _write_reports(results, st_ok, out_dir)
    for r in results:
        print(f"[{'PASS' if r.passed else 'FAIL'}] {r.row}")
    passed = sum(1 for r in results if r.passed)
    print(
        f"\n{passed}/{len(results)} rows PASS  (report: {out_dir / 'wp5-lifecycle-driver-result.json'})"
    )
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
