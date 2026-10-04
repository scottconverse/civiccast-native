# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Installer-process identity for the pre-overwrite flat recovery entry.

The actual NSIS parent is observed by the child, never accepted as a PID or
birth timestamp supplied on its command line. The remaining production
SCM/config/NSIS bindings are not wired yet; this module is not a recovery CLI.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import psutil
from pydantic import BaseModel, ConfigDict, Field

from civiccast.native.models import InterlockRead, MaintenanceRecord
from civiccast.native.upgrade.flat_recovery import (
    FlatRecoveryError,
    FlatRecoverySeams,
    _inventory,
    _safe_path,
    _validate_owner,
)
from civiccast.native.upgrade.journal import _harden_state_root_acl
from civiccast.native.upgrade.models import UpgradeSeams
from civiccast.native.win_probes import (
    RuntimeOwnerMutex,
    read_interlock,
    release_interlock,
    take_interlock,
)

if TYPE_CHECKING:
    from civiccast.native.upgrade.flat_recovery_database import FlatVerificationTarget


def installer_child_environment() -> dict[str, str]:
    """Do not let inherited libpq overrides redirect an admitted installer child.

    This is a fresh child environment, not a mutation of the installer or agent
    process. The child receives its independently bound connection context.
    """
    return {name: value for name, value in os.environ.items() if not name.upper().startswith("PG")}


def retain_previous_postgres_tools(
    *, pg_bin: Path, expected_install_root: Path, destination: Path, budget_seconds: float = 120.0
) -> Path:
    """Retain the complete OLD tool distribution before application replacement.

    The tool location is independently resolved from the admitted installation,
    not a recovery journal. Copy the distribution containing bin/lib/share,
    never PGDATA. This copy remains protected even after a failed copy or check.
    """
    install, source_bin, target = map(_safe_path, (expected_install_root, pg_bin, destination))
    source = _safe_path(source_bin.parent)
    if (
        source_bin.name.lower() != "bin"
        or source == install
        or install not in source.parents
        or target == install
        or install in target.parents
        or target in install.parents
        or target.exists()
        or not math.isfinite(budget_seconds)
        or not 0 < budget_seconds <= 600
    ):
        raise FlatRecoveryError("invalid independently bound old-tool retention roots")
    for name in (
        "initdb.exe",
        "pg_ctl.exe",
        "postgres.exe",
        "pg_dump.exe",
        "pg_restore.exe",
        "psql.exe",
    ):
        if not _safe_path(source_bin / name).is_file():
            raise FlatRecoveryError("previous PostgreSQL tool distribution is incomplete")
    deadline = time.monotonic() + budget_seconds
    identity = _inventory(source, deadline)
    if any(Path(name).name == "PG_VERSION" for name in identity[0]):
        raise FlatRecoveryError("PostgreSQL data is not an old-tool distribution")
    total = sum(member.size for member in identity[0].values())
    if shutil.disk_usage(target.parent).free < total + 64 * 1024 * 1024:
        raise FlatRecoveryError("insufficient space to retain previous PostgreSQL tools")
    target.mkdir()
    _harden_state_root_acl(target)
    shutil.copytree(source, target, dirs_exist_ok=True, copy_function=shutil.copy2)
    if _inventory(target, deadline) != identity or _inventory(source, deadline) != identity:
        raise FlatRecoveryError("previous PostgreSQL tool retention failed byte verification")
    return target / "bin"


def stage_recovery_executor(
    *,
    bootstrap: Path,
    expected_bootstrap_sha256: str,
    app_pack: Path,
    server_pack: Path,
    state_root: Path,
    expected_install_root: Path,
    owner: str,
) -> Path:
    """Persist a verified incoming executor outside the tree NSIS overwrites.

    The bootstrap digest must come from the signed installer's embedded build
    binding, never from the recovery journal or an untrusted sidecar. The
    caller performs parent admission before this operation. This does not
    touch/stop the old installation or acquire writer permission.
    """
    _validate_owner(owner)
    bootstrap, app_pack, server_pack, state_root = map(
        _safe_path, (bootstrap, app_pack, server_pack, state_root)
    )
    install = _safe_path(expected_install_root)
    if state_root == install or state_root in install.parents or install in state_root.parents:
        raise FlatRecoveryError("executor state overlaps the replaceable installation")
    if (
        len(expected_bootstrap_sha256) != 64
        or hashlib.sha256(bootstrap.read_bytes()).hexdigest() != expected_bootstrap_sha256.lower()
    ):
        raise FlatRecoveryError("incoming bootstrap binding changed")
    state_root.mkdir(parents=True, exist_ok=True)
    _harden_state_root_acl(state_root)
    executor = _safe_path(state_root / f"executor-{owner}")
    executor.mkdir(exist_ok=False)
    _harden_state_root_acl(executor)
    verifier = executor / "CivicCast Native.exe"
    shutil.copyfile(bootstrap, verifier)
    if hashlib.sha256(verifier.read_bytes()).hexdigest() != expected_bootstrap_sha256.lower():
        raise FlatRecoveryError("persisted bootstrap binding changed")
    for source, component, destination in (
        (app_pack, "native-app-payload", executor / "runtime"),
        (server_pack, "native-server-binaries", executor / "server"),
    ):
        # Input basenames must never overwrite the independently bound verifier.
        retained = executor / f"{component}.ccpack"
        shutil.copyfile(source, retained)
        for operation in ("--civiccast-import-pack", "--civiccast-verify-pack-tree"):
            try:
                # Exact bootstrap bytes are bound above to the signed installer;
                # closed operation/component arguments, no shell or URL input.
                result = subprocess.run(  # noqa: S603
                    [
                        str(verifier),
                        operation,
                        str(retained),
                        "--destination",
                        str(destination),
                        "--expected-component",
                        component,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=600,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    env=installer_child_environment(),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise FlatRecoveryError("incoming executor verification did not complete") from exc
            if result.returncode != 0:
                raise FlatRecoveryError("incoming executor signed pack verification failed")
        if (
            component == "native-app-payload"
            and not _safe_path(destination / "python.exe").is_file()
        ):
            raise FlatRecoveryError("verified incoming interpreter is absent")
    return executor


@contextmanager
def restore_security_privilege() -> Iterator[None]:
    """Enable only SeRestorePrivilege around exact captured-security restoration.

    Elevation alone does not imply that this privilege is assigned/enabled.
    Never enter recovery writes when assignment failed, and restore the token's
    original privilege state even when the protected operation raises.
    """
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_ADJUST_PRIVILEGES | win32con.TOKEN_QUERY
    )
    try:
        luid = win32security.LookupPrivilegeValue(None, "SeRestorePrivilege")
        win32api.SetLastError(0)
        previous = win32security.AdjustTokenPrivileges(
            token, False, [(luid, win32con.SE_PRIVILEGE_ENABLED)]
        )
        try:
            if win32api.GetLastError() != 0:
                raise FlatRecoveryError("required security restore privilege is unavailable")
            yield
        finally:
            win32api.SetLastError(0)
            win32security.AdjustTokenPrivileges(token, False, previous)
            if win32api.GetLastError() != 0:
                raise FlatRecoveryError("security restore privilege state could not be restored")
    finally:
        win32api.CloseHandle(token)


class InstallerParent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pid: int = Field(gt=0)
    birth: float = Field(gt=0, allow_inf_nan=False)
    executable: str


class InstallerAdmission(BaseModel):
    """Protected ownership independent of a short-lived entry process."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1, ge=1, le=1, strict=True)
    parent: InstallerParent
    recovery_actor: InstallerParent | None = None
    owner: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
    generation: int = Field(gt=0, strict=True)
    install_root: str
    admission_root: str
    state_root: str
    phase: str = Field(pattern=r"^(intent|held|restored|committed)$")


@contextmanager
def installer_admission_mutex() -> Iterator[None]:
    """Serialize entry callbacks, not the independently running supervisor.

    The existing kernel primitive supplies the SYSTEM/Administrators DACL and
    closes the handle on a denied acquisition. Abandonment only grants this
    mutex: it never grants permission to reclaim a persisted D7 lease.
    """
    mutex = RuntimeOwnerMutex(name=r"Global\CivicCastInstallerAdmission")
    result = mutex.acquire()
    if result.status not in ("acquired", "acquired_abandoned"):
        raise FlatRecoveryError("another installer owns admission or ownership is unreadable")
    try:
        yield
    finally:
        mutex.release()


def admit_installer(
    *, parent: InstallerParent, owner: str, expected_install_root: Path, admission_root: Path
) -> InstallerAdmission:
    """Durably bind this actual installer before it can contain/replace files.

    Existing admissions are never overwritten here, even if their process is
    gone. Explicit recovery must first settle that exact recorded installation
    and lease; a dead process alone is not authority to permit writers.
    """
    _validate_owner(owner)
    require_current_installer_parent(parent)
    root = _safe_path(admission_root)
    install = _safe_path(expected_install_root)
    with installer_admission_mutex():
        if _safe_path(root / "installer-admission.json").exists():
            raise FlatRecoveryError("unsettled installer admission already exists")
        current = read_interlock()
        if current.status != "free":
            raise FlatRecoveryError("maintenance ownership is not independently free")
        generation = current.record.generation + 1 if current.record is not None else 1
        admission = InstallerAdmission(
            parent=parent,
            owner=owner,
            generation=generation,
            install_root=str(install),
            admission_root=str(root),
            state_root=str(root / f"recovery-{owner}"),
            phase="intent",
        )
        persist_installer_admission(admission)
        record = take_installer_interlock(parent, owner)
        observed = read_interlock()
        if (
            observed.status != "held"
            or observed.record != record
            or record.owner_run_id != owner
            or record.owner_pid != parent.pid
            or record.generation != generation
            or record.state != "held"
        ):
            raise FlatRecoveryError("physical maintenance lease changed during admission")
        held = admission.model_copy(update={"phase": "held"})
        persist_installer_admission(held)
        return held


def persist_installer_admission(admission: InstallerAdmission) -> None:
    """Persist intent before taking D7, then held state after exact readback.

    The dedicated admission mutex must bracket each invocation. A crash between
    the two writes is recoverable only if the physical lease exactly matches
    this protected intent and the recorded parent incarnation is definitely gone.
    This function does not steal/release any lease or declare recovery complete.
    """
    require_current_installer_parent(admission.recovery_actor or admission.parent)
    root = _safe_path(Path(admission.admission_root))
    install = _safe_path(Path(admission.install_root))
    recovery = _safe_path(Path(admission.state_root))
    if root == install or root in install.parents or install in root.parents:
        raise FlatRecoveryError("admission state overlaps the installation")
    if recovery == root or root not in recovery.parents:
        raise FlatRecoveryError("recovery point is not a distinct protected admission child")
    root.mkdir(parents=True, exist_ok=True)
    _harden_state_root_acl(root)
    target = _safe_path(root / "installer-admission.json")
    actor = admission.recovery_actor or admission.parent
    temporary = _safe_path(root / f"installer-admission-{actor.pid}.tmp")
    if temporary.exists():
        raise FlatRecoveryError("unsettled admission write already exists")
    with temporary.open("xb") as stream:
        stream.write(admission.model_dump_json().encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    require_current_installer_parent(actor)
    temporary.replace(target)


def load_installer_admission(
    *, expected_install_root: Path, expected_admission_root: Path, expected_state_root: Path
) -> InstallerAdmission:
    root = _safe_path(expected_admission_root)
    install = _safe_path(expected_install_root)
    recovery = _safe_path(expected_state_root)
    if (
        root == install
        or root in install.parents
        or install in root.parents
        or recovery == root
        or root not in recovery.parents
    ):
        raise FlatRecoveryError("invalid independent admission/recovery roots")
    path = _safe_path(root / "installer-admission.json")
    if path.stat().st_size > 16384:
        raise FlatRecoveryError("installer admission exceeds bounds")
    try:
        admission = InstallerAdmission.model_validate(json.loads(path.read_bytes()))
    except (ValueError, TypeError) as exc:
        raise FlatRecoveryError("installer admission is malformed") from exc
    if (
        _safe_path(Path(admission.install_root)) != install
        or _safe_path(Path(admission.admission_root)) != root
        or _safe_path(Path(admission.state_root)) != recovery
    ):
        raise FlatRecoveryError("installer admission root binding changed")
    return admission


def settle_installer_admission(
    *, admission: InstallerAdmission, seams: FlatRecoverySeams
) -> InstallerAdmission:
    """Release writers only after the exact recovery journal is durably terminal.

    Kept separate from core.commit/recover: the physical lease belongs to NSIS,
    not the short-lived Python callback. Terminal admission remains retained;
    neither a dead process nor a missing journal grants release permission.
    """
    from civiccast.native.upgrade.flat_recovery import load

    if not isinstance(seams, FlatRecoverySeams):
        raise FlatRecoveryError("independently bound recovery seams are required")
    require_current_installer_parent(admission.recovery_actor or admission.parent)
    with installer_admission_mutex():
        current = load_installer_admission(
            expected_install_root=seams.expected_install_root,
            expected_admission_root=Path(admission.admission_root),
            expected_state_root=seams.expected_state_root,
        )
        if current != admission:
            raise FlatRecoveryError("installer admission identity changed before settlement")
        journal = load(Path(admission.state_root), admission.owner, seams)
        if journal.phase not in {"restored", "committed"}:
            raise FlatRecoveryError("recovery journal is not durably terminal")
        physical = read_interlock()
        lease = physical.record
        if (
            physical.status != "held"
            or lease is None
            or lease.state != "held"
            or lease.owner_run_id != admission.owner
            or lease.owner_pid != admission.parent.pid
            or lease.generation != admission.generation
        ):
            raise FlatRecoveryError("physical maintenance lease changed before settlement")
        terminal = admission.model_copy(update={"phase": journal.phase})
        persist_installer_admission(terminal)
        require_current_installer_parent(admission.recovery_actor or admission.parent)
        released = release_interlock(owner_run_id=admission.owner)
        if (
            released.state != "released"
            or released.owner_run_id != admission.owner
            or released.owner_pid != admission.parent.pid
            or released.generation != admission.generation
        ):
            raise FlatRecoveryError("physical maintenance release identity changed")
        return terminal


def archive_settled_installer_admission(
    *, admission: InstallerAdmission, seams: FlatRecoverySeams
) -> Path:
    """Permit a later installer only after the old terminal owner is gone.

    This never reclaims a held lease or settles interrupted recovery. Keep the
    complete old admission and recovery point; a failed/ambiguous owner remains
    blocking until actual contained recovery is performed.
    """
    from civiccast.native.upgrade.flat_recovery import load

    with installer_admission_mutex():
        current = load_installer_admission(
            expected_install_root=seams.expected_install_root,
            expected_admission_root=Path(admission.admission_root),
            expected_state_root=seams.expected_state_root,
        )
        if (
            current != admission
            or installer_parent_alive(admission.recovery_actor or admission.parent) is not False
        ):
            raise FlatRecoveryError("previous installer ownership is not definitively settled")
        journal = load(Path(admission.state_root), admission.owner, seams)
        if admission.phase not in {"restored", "committed"} or journal.phase != admission.phase:
            raise FlatRecoveryError("previous recovery is not durably terminal")
        physical = read_interlock()
        lease = physical.record
        if (
            physical.status != "free"
            or lease is None
            or lease.state != "released"
            or lease.owner_run_id != admission.owner
            or lease.owner_pid != admission.parent.pid
            or lease.generation != admission.generation
        ):
            raise FlatRecoveryError("previous physical maintenance release is not exact")
        root = _safe_path(Path(admission.admission_root))
        active = _safe_path(root / "installer-admission.json")
        archive = _safe_path(root / f"installer-admission-{admission.owner}.json")
        if archive.exists():
            raise FlatRecoveryError("previous admission archive already exists")
        active.rename(archive)
        return archive


def adopt_interrupted_installer(
    *,
    previous: InstallerAdmission,
    actor: InstallerParent,
    expected_install_root: Path,
    expected_admission_root: Path,
    expected_state_root: Path,
) -> InstallerAdmission:
    """Lend the exact old held lease to a newly observed NSIS recovery actor.

    This grants contained recovery only, never forward replacement or writers.
    The physical owner/PID/generation are not rewritten. Any ambiguous old
    incarnation or changed lease refuses before recording a new actor.
    """
    require_current_installer_parent(actor)
    with installer_admission_mutex():
        current = load_installer_admission(
            expected_install_root=expected_install_root,
            expected_admission_root=expected_admission_root,
            expected_state_root=expected_state_root,
        )
        if current != previous or current.phase not in {"intent", "held", "restored", "committed"}:
            raise FlatRecoveryError("interrupted admission is not the exact unresolved owner")
        if installer_parent_alive(current.recovery_actor or current.parent) is not False:
            raise FlatRecoveryError("previous installer incarnation is not definitively gone")
        physical = read_interlock()
        lease = physical.record
        if (
            physical.status != "held"
            or lease is None
            or lease.state != "held"
            or lease.owner_run_id != current.owner
            or lease.owner_pid != current.parent.pid
            or lease.generation != current.generation
        ):
            raise FlatRecoveryError("interrupted physical maintenance ownership changed")
        adopted = current.model_copy(update={"recovery_actor": actor})
        persist_installer_admission(adopted)
        # Persisting a claimant cannot turn an uncertain process exit into
        # permission. Every subsequent operation repeats actual actor liveness.
        require_current_installer_parent(actor)
        return adopted


def observe_installer_parent(expected_executable: Path) -> InstallerParent:
    """Bind the real immediate parent to NSIS's own EXEPATH, without trusting PID args."""
    expected = _safe_path(expected_executable)
    try:
        process = psutil.Process(os.getppid())
        with process.oneshot():
            parent = InstallerParent(
                pid=process.pid, birth=process.create_time(), executable=process.exe()
            )
        if _safe_path(Path(parent.executable)) != expected:
            raise FlatRecoveryError("recovery entry was not invoked by the expected installer")
        if installer_parent_alive(parent) is not True:
            raise FlatRecoveryError("installer parent identity changed during admission")
        return parent
    except (psutil.Error, OSError, ValueError) as exc:
        raise FlatRecoveryError("installer parent identity unavailable") from exc


def installer_parent_alive(parent: InstallerParent) -> bool | None:
    """False means that exact incarnation is gone; unreadable is NOT stale."""
    try:
        process = psutil.Process(parent.pid)
        with process.oneshot():
            return process.create_time() == parent.birth and _safe_path(
                Path(process.exe())
            ) == _safe_path(Path(parent.executable))
    except psutil.NoSuchProcess:
        return False
    except (psutil.Error, OSError, ValueError, FlatRecoveryError):
        return None


def verification_postmaster(
    data_dir: Path, postgres_executable: Path, *, started_after: float
) -> InstallerParent:
    """Bind the disposable verifier before handing it to DR or stopping it.

    A launcher PID alone is insufficient: pg_ctl exits while postgres remains.
    Both its protected pidfile and actual process incarnation must match the
    independently supplied scratch directory and admitted OLD executable.
    """
    try:
        data = _safe_path(data_dir)
        expected = _safe_path(postgres_executable)
        pidfile = _safe_path(data / "postmaster.pid")
        if pidfile.stat().st_size > 4096:
            raise FlatRecoveryError("verification postmaster identity exceeds bounds")
        lines = pidfile.read_text(encoding="utf-8").splitlines()
        pid, born = int(lines[0]), float(lines[2])
        if (
            pid <= 0
            or _safe_path(Path(lines[1])) != data
            or not math.isfinite(born)
            or not math.isfinite(started_after)
            or born < started_after
        ):
            raise FlatRecoveryError("verification postmaster data identity changed")
        process = psutil.Process(pid)
        with process.oneshot():
            identity = InstallerParent(
                pid=pid, birth=process.create_time(), executable=process.exe()
            )
            arguments = process.cmdline()
        data_arguments = [
            arguments[index + 1]
            for index, argument in enumerate(arguments[:-1])
            if argument == "-D"
        ]
        if (
            _safe_path(Path(identity.executable)) != expected
            or identity.birth < started_after
            or abs(identity.birth - born) > 2.0
            or len(data_arguments) != 1
            or _safe_path(Path(data_arguments[0])) != data
        ):
            raise FlatRecoveryError("verification postmaster process identity changed")
        return identity
    except (OSError, ValueError, IndexError, psutil.Error) as exc:
        raise FlatRecoveryError("verification postmaster identity unavailable") from exc


@contextmanager
def disposable_verification_target(
    *, old_pg_bin: Path, scratch_root: Path, expected_install_root: Path
) -> Iterator[FlatVerificationTarget]:
    """Own a private OLD-tools verifier, never the external source database.

    The caller must independently admit OLD tool bytes before invoking this
    lifecycle. Scratch bytes are retained protected for failure diagnosis;
    neither live PGDATA nor an installation is copied, removed, or modified.
    """
    from sqlalchemy.engine import URL

    from civiccast.native.pg_ctl_exec import run_captured_argv
    from civiccast.native.pgdata_acl import normalize_pgdata_acl
    from civiccast.native.provision.seams import _initdb_pwfile, initdb_argv
    from civiccast.native.supervisor.children import graceful_stop_action, postgres_child_spec
    from civiccast.native.upgrade.flat_recovery_database import FlatVerificationTarget

    root = _safe_path(scratch_root)
    install = _safe_path(expected_install_root)
    tools = _safe_path(old_pg_bin)
    if root.exists() or root == install or root in install.parents or install in root.parents:
        raise FlatRecoveryError("verification scratch root is not independently vacant")
    if (
        tools in (install, root)
        or install in tools.parents
        or tools in root.parents
        or root in tools.parents
    ):
        raise FlatRecoveryError("verification OLD tools are not independently retained")
    executables = {
        name: _safe_path(tools / (name + (".exe" if os.name == "nt" else "")))
        for name in ("initdb", "pg_ctl", "postgres")
    }
    if not all(path.is_file() for path in executables.values()):
        raise FlatRecoveryError("verification requires admitted OLD PostgreSQL executables")
    hashes = {
        name: hashlib.sha256(path.read_bytes()).digest() for name, path in executables.items()
    }

    def command(argv: list[str], timeout: float) -> None:
        if any(
            hashlib.sha256(executables[name].read_bytes()).digest() != digest
            for name, digest in hashes.items()
        ):
            raise FlatRecoveryError("verification OLD tool bytes changed")
        try:
            result = run_captured_argv(
                argv, timeout_seconds=timeout, env=installer_child_environment()
            )
        except (OSError, subprocess.TimeoutExpired):
            raise FlatRecoveryError("verification cluster operation did not complete") from None
        if result.returncode != 0:
            raise FlatRecoveryError("verification cluster operation failed")

    root.mkdir()
    _harden_state_root_acl(root)
    data = root / "pgdata"
    data.mkdir()
    password = secrets.token_urlsafe(32)
    with _initdb_pwfile(root, password) as password_file:
        command(
            initdb_argv(
                initdb_path=str(executables["initdb"]),
                data_dir=str(data),
                username="civiccast_verifier",
                pwfile=str(password_file),
            ),
            120.0,
        )
    normalize_pgdata_acl(str(data))
    # A bind race is not authorization to stop the foreign listener. Startup
    # and the factory's actual data_directory admission must fail closed.
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    spec = postgres_child_spec(
        pg_ctl_path=str(executables["pg_ctl"]),
        data_dir=str(data),
        host="127.0.0.1",
        port=port,
        log_path=str(root / "postgres.log"),
    )
    started_after = time.time() - 1.0  # postmaster.pid uses whole-second epochs
    identity: InstallerParent | None = None
    try:
        command(spec.argv, 75.0)
        identity = verification_postmaster(
            data, executables["postgres"], started_after=started_after
        )
        yield FlatVerificationTarget(
            database_url=URL.create(
                "postgresql+psycopg",
                username="civiccast_verifier",
                password=password,
                host="127.0.0.1",
                port=port,
                database="postgres",
            ).render_as_string(hide_password=False),
            expected_pgdata=data,
        )
    finally:
        if _safe_path(data / "postmaster.pid").exists():
            observed = verification_postmaster(
                data, executables["postgres"], started_after=started_after
            )
            if identity is not None and observed != identity:
                raise FlatRecoveryError("verification ownership changed; cleanup refused")
            action = graceful_stop_action(spec, pid=observed.pid)
            assert action.argv is not None
            command(action.argv, 45.0)
            if installer_parent_alive(observed) is not False:
                raise FlatRecoveryError("verification postmaster absence is not established")
        elif identity is not None and installer_parent_alive(identity) is not False:
            raise FlatRecoveryError("verification pidfile disappeared before owned cleanup")


def require_current_installer_parent(parent: InstallerParent) -> None:
    if os.getppid() != parent.pid or installer_parent_alive(parent) is not True:
        raise FlatRecoveryError(
            "recovery callback does not belong to the admitted installer parent"
        )


def take_installer_interlock(parent: InstallerParent, owner: str) -> MaintenanceRecord:
    """Called under the dedicated admission mutex, after protected parent admission.

    No PID/birth CLI assertions are accepted. The physical lease survives this
    child process because it names the observed NSIS incarnation; its birth and
    executable remain in the independently protected admission record.
    """
    _validate_owner(owner)
    require_current_installer_parent(parent)
    record = take_interlock(owner, owner_pid=parent.pid)
    # If the installer died during the write, retain the held lease for explicit
    # contained recovery. Never silently release ownership on an uncertain exit.
    require_current_installer_parent(parent)
    return record


def borrow_installer_interlock(
    seams: UpgradeSeams,
    *,
    parent: InstallerParent,
    owner: str,
    generation: int,
    read: Callable[[], InterlockRead] = read_interlock,
) -> UpgradeSeams:
    """Lend D3 an already-admitted installer lease, never acquire/release it.

    The entry must obtain these values from its protected recovery admission,
    not CLI ownership claims. Both D3 boundaries recheck the actual parent
    incarnation and the exact physical lease. Ordinary D3 seams are unchanged.
    """

    def verify() -> None:
        require_current_installer_parent(parent)
        current = read()
        record = current.record
        if (
            current.status != "held"
            or record is None
            or record.state != "held"
            or record.owner_run_id != owner
            or record.generation != generation
            or record.owner_pid != parent.pid
        ):
            raise FlatRecoveryError("outer installer maintenance lease identity changed")

    verify()
    return replace(
        seams,
        acquire_interlock=verify,
        release_interlock=verify,
        outer_interlock_owned=True,
    )
