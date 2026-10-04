# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Outer recovery boundaries for the production flat NSIS installer.

The D3 adapter deliberately stays truthful: it cannot recover a tree which
NSIS already overwrote. This owner captures that tree before replacement,
retains a verified logical database backup even for same-version repairs,
and does not reactivate previous code until every recovery gate passes.

OS/database primitives are supplied by the installer entry, like D3's
UpgradeSeams. Snapshot and journal operations here are real filesystem IO.
No recovery operation deletes an unknown tree: failed payloads are retained.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shutil
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from civiccast.native.upgrade.journal import _harden_state_root_acl
from civiccast.native.upgrade.models import BackupRef


class FlatRecoveryError(RuntimeError):
    """Recovery cannot safely proceed; retain the recovery point and stop."""


def _validate_owner(owner: str) -> None:
    # Used in sibling staging names as well as the protected journal. Never
    # let an otherwise-authorized caller turn an owner token into a path.
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", owner) is None:
        raise FlatRecoveryError("invalid recovery owner token")


class FileIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class FlatRecoveryJournal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    owner: str = Field(min_length=1, max_length=128)
    install_root: str
    state_root: str
    old_version: str
    new_version: str
    phase: Literal[
        "capturing",
        "prepared",
        "replacing",
        "database_mutating",
        "recovering",
        "restored",
        "committed",
        "halted",
    ] = "capturing"
    tree: dict[str, FileIdentity] = Field(default_factory=dict)
    directories: list[str] = Field(default_factory=list)
    application_security: dict[str, str] = Field(default_factory=dict)
    registration: dict[str, Any] = Field(default_factory=dict)
    backup: BackupRef | None = None
    pre_schema_revision: str | None = None
    database_may_have_changed: bool = False
    # Persist intent before moving anything; a resumed owner reconciles these
    # exact names rather than guessing which nearby tree belongs to this run.
    restore_tree: str | None = None
    failed_tree: str | None = None


@dataclass(frozen=True)
class FlatRecoverySeams:
    """Only the entry owns live service/DB/registration operations."""

    # Bound by the installer entry's independent SCM/install admission, NEVER
    # reconstructed from the mutable recovery journal being validated.
    expected_install_root: Path
    expected_state_root: Path
    assert_owner: Callable[[str], None]
    contain: Callable[[], None]
    capture_registration: Callable[[], dict[str, Any]]
    restore_registration: Callable[[dict[str, Any]], None]
    capture_config: Callable[[Path], None]
    restore_config: Callable[[Path], None]
    backup: Callable[[str], BackupRef]
    verify_backup: Callable[[BackupRef], None]
    restore_database: Callable[[BackupRef], None]
    schema_revision: Callable[[], str | None]
    verify_previous_identity: Callable[[str, str], bool]
    reactivate: Callable[[dict[str, Any]], None]


def _safe_path(path: Path) -> Path:
    """Reject reparse traversal before resolve, including ancestor junctions."""
    if not path.is_absolute() or ".." in path.parts:
        raise FlatRecoveryError("recovery requires an absolute owned path")
    for node in [path, *path.parents]:
        try:
            info = node.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            raise FlatRecoveryError("recovery refuses a reparse path")
    resolved = path.resolve()
    if resolved.parent == resolved:
        raise FlatRecoveryError("recovery refuses a filesystem root")
    return resolved


def _identity(path: Path, deadline: float) -> FileIdentity:
    _safe_path(path)
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise FlatRecoveryError("snapshot contains a non-regular file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            if time.monotonic() >= deadline:
                raise FlatRecoveryError("recovery filesystem budget expired")
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (
        after.st_size,
        after.st_mtime_ns,
        after.st_ino,
    ):
        raise FlatRecoveryError("snapshot source changed while being read")
    return FileIdentity(size=after.st_size, sha256=digest.hexdigest())


def _inventory(root: Path, deadline: float) -> tuple[dict[str, FileIdentity], list[str]]:
    root = _safe_path(root)
    if not root.is_dir():
        raise FlatRecoveryError("owned application tree is missing")
    files: dict[str, FileIdentity] = {}
    directories: list[str] = []
    for directory, children, names in os.walk(root, followlinks=False):
        if time.monotonic() >= deadline:
            raise FlatRecoveryError("recovery filesystem budget expired")
        parent = _safe_path(Path(directory))
        for name in sorted(children):
            child = _safe_path(parent / name)
            if not child.is_dir():
                raise FlatRecoveryError("snapshot directory is not a directory")
            directories.append(child.relative_to(root).as_posix())
        for name in sorted(names):
            child = parent / name
            files[child.relative_to(root).as_posix()] = _identity(child, deadline)
    return files, sorted(directories)


def _journal_path(state_root: Path) -> Path:
    return state_root / "flat-install-recovery.json"


def _capture_application_security(root: Path, members: list[str]) -> dict[str, str]:
    """Retain owner/group/DACL, not the recovery directory's private ACL."""
    if os.name != "nt":
        return {}
    import win32security

    flags = (
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.GROUP_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION
    )
    result = {}
    for member in [".", *members]:
        descriptor = win32security.GetFileSecurity(str(_safe_path(root / member)), flags)
        result[member] = win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            descriptor, win32security.SDDL_REVISION_1, flags
        )
    return result


def _restore_application_security(root: Path, descriptors: dict[str, str]) -> None:
    if os.name != "nt":
        return
    import win32security

    flags = (
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.GROUP_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION
    )
    # Parent-first followed by exact children; retain inherited/protected state.
    for member, sddl in sorted(descriptors.items(), key=lambda item: (item[0].count("/"), item[0])):
        descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            sddl, win32security.SDDL_REVISION_1
        )
        control, _revision = descriptor.GetSecurityDescriptorControl()
        protection = (
            win32security.PROTECTED_DACL_SECURITY_INFORMATION
            if control & win32security.SE_DACL_PROTECTED
            else win32security.UNPROTECTED_DACL_SECURITY_INFORMATION
        )
        win32security.SetFileSecurity(
            str(_safe_path(root / member)), flags | protection, descriptor
        )


def _persist(journal: FlatRecoveryJournal) -> None:
    state_root = _safe_path(Path(journal.state_root))
    _harden_state_root_acl(state_root)
    path = _journal_path(state_root)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    # Exclusive creation refuses leftovers instead of following a planted
    # temp link or overwriting another entry's unfinished write.
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(journal.model_dump_json(indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def load(state_root: Path, owner: str, seams: FlatRecoverySeams) -> FlatRecoveryJournal:
    _validate_owner(owner)
    seams.assert_owner(owner)
    root = _safe_path(state_root)
    if root != _safe_path(seams.expected_state_root):
        raise FlatRecoveryError("recovery state root is not independently bound")
    journal_path = _safe_path(_journal_path(root))
    journal = FlatRecoveryJournal.model_validate_json(journal_path.read_bytes())
    if journal.owner != owner or _safe_path(Path(journal.state_root)) != root:
        raise FlatRecoveryError("recovery journal belongs to another installer")
    install = _safe_path(Path(journal.install_root))
    if install != _safe_path(seams.expected_install_root):
        raise FlatRecoveryError("recovery install root is not independently bound")
    if journal.registration or journal.phase != "capturing":
        _check_registration_root(journal.registration, seams.expected_install_root)
    if root == install or root.is_relative_to(install) or install.is_relative_to(root):
        raise FlatRecoveryError("recovery point overlaps the application tree")
    members = set(journal.tree) | set(journal.directories)
    for member in members:
        if (
            not member
            or "\\" in member
            or ":" in member
            or any(part in {"", ".", ".."} for part in member.split("/"))
        ):
            raise FlatRecoveryError("recovery journal contains an unsafe application member")
    if (
        os.name == "nt"
        and journal.phase != "capturing"
        and set(journal.application_security) != members | {"."}
    ):
        raise FlatRecoveryError("previous application security snapshot is incomplete")
    expected_staged = install.with_name(f".{install.name}.restore-{owner}")
    expected_failed = install.with_name(f".{install.name}.failed-{owner}")
    if (
        journal.restore_tree is not None
        and _safe_path(Path(journal.restore_tree)) != expected_staged
    ):
        raise FlatRecoveryError("recovery staging does not belong to this owner")
    if journal.failed_tree is not None and _safe_path(Path(journal.failed_tree)) != expected_failed:
        raise FlatRecoveryError("failed application tree does not belong to this owner")
    return journal


def _check_registration_root(registration: dict[str, Any], expected: Path) -> None:
    captured_root = registration.get("install_root")
    if not isinstance(captured_root, str) or _safe_path(Path(captured_root)) != _safe_path(
        expected
    ):
        raise FlatRecoveryError("service registration root is not independently bound")


def prepare(
    *,
    install_root: Path,
    state_root: Path,
    owner: str,
    old_version: str,
    new_version: str,
    seams: FlatRecoverySeams,
    filesystem_budget: float = 600.0,
) -> FlatRecoveryJournal:
    """Prepare the complete recovery point before any application replacement.

    The caller classifies SCM registration and native ownership before this
    entry. It passes only a new, protected, owner-bound recovery directory.
    User media and live PostgreSQL files are NOT copied by capture_config.
    """
    _validate_owner(owner)
    seams.assert_owner(owner)
    install, state = _safe_path(install_root), _safe_path(state_root)
    if install != _safe_path(seams.expected_install_root) or state != _safe_path(
        seams.expected_state_root
    ):
        raise FlatRecoveryError("recovery roots are not independently bound")
    if state == install or state.is_relative_to(install) or install.is_relative_to(state):
        raise FlatRecoveryError("recovery point overlaps the application tree")
    if state.exists():
        raise FlatRecoveryError("recovery point already exists; explicit resume required")
    if not 0 < filesystem_budget <= 3600:
        raise FlatRecoveryError("invalid recovery filesystem budget")
    deadline = time.monotonic() + filesystem_budget
    state.mkdir()
    _harden_state_root_acl(state)
    journal = FlatRecoveryJournal(
        owner=owner,
        install_root=str(install),
        state_root=str(state),
        old_version=old_version,
        new_version=new_version,
    )
    _persist(journal)
    # Capture the original running/start policy BEFORE containment changes it.
    journal.registration = seams.capture_registration()
    _check_registration_root(journal.registration, seams.expected_install_root)
    _persist(journal)
    seams.contain()
    seams.assert_owner(owner)
    journal.pre_schema_revision = seams.schema_revision()
    if not journal.pre_schema_revision:
        raise FlatRecoveryError("previous schema identity unavailable")
    # Always present, including same-version repair which D3 routes to NOOP.
    journal.backup = seams.backup(str(state / "database"))
    if not (journal.backup.verified and journal.backup.restore_drill_ok):
        raise FlatRecoveryError("logical database recovery point is unverified")
    seams.verify_backup(journal.backup)
    seams.capture_config(state / "configuration")
    files, directories = _inventory(install, deadline)
    security = _capture_application_security(install, [*directories, *files])
    total = sum(item.size for item in files.values())
    # The snapshot and subsequent restore staging each require a whole tree.
    if shutil.disk_usage(state).free < total * 2 + 64 * 1024 * 1024:
        raise FlatRecoveryError("insufficient space for snapshot and recovery staging")
    snapshot = state / "previous-application"
    shutil.copytree(install, snapshot, copy_function=shutil.copy2)
    copied, copied_dirs = _inventory(snapshot, deadline)
    current, current_dirs = _inventory(install, deadline)
    if (
        copied != files
        or current != files
        or copied_dirs != directories
        or current_dirs != directories
    ):
        raise FlatRecoveryError("application snapshot changed or failed byte verification")
    journal.tree, journal.directories = files, directories
    journal.application_security = security
    journal.phase = "prepared"
    _persist(journal)
    return journal


def mark_replacement(state_root: Path, owner: str, seams: FlatRecoverySeams) -> None:
    journal = load(state_root, owner, seams)
    if journal.phase != "prepared":
        raise FlatRecoveryError("replacement requires a prepared recovery point")
    deadline = time.monotonic() + 600.0
    if _inventory(state_root / "previous-application", deadline) != (
        journal.tree,
        journal.directories,
    ):
        raise FlatRecoveryError("application snapshot failed verification before replacement")
    install = Path(journal.install_root)
    if _inventory(install, deadline) != (journal.tree, journal.directories):
        raise FlatRecoveryError("previous application changed before replacement")
    if (
        _capture_application_security(install, [*journal.directories, *journal.tree])
        != journal.application_security
    ):
        raise FlatRecoveryError("previous application security changed before replacement")
    journal.phase = "replacing"
    _persist(journal)


def mark_database_mutation(state_root: Path, owner: str, seams: FlatRecoverySeams) -> None:
    journal = load(state_root, owner, seams)
    if journal.phase != "replacing":
        raise FlatRecoveryError("database mutation requires the replacement phase")
    journal.database_may_have_changed = True
    journal.phase = "database_mutating"
    _persist(journal)


def recover(
    state_root: Path,
    owner: str,
    seams: FlatRecoverySeams,
    *,
    filesystem_budget: float = 600.0,
) -> FlatRecoveryJournal:
    """Restore DB before code and reactivate only verified previous identity."""
    journal = load(state_root, owner, seams)
    if journal.phase in {"committed", "capturing", "prepared"}:
        raise FlatRecoveryError("this journal has no failed replacement to recover")
    if journal.phase == "restored":
        return journal
    if not 0 < filesystem_budget <= 3600:
        raise FlatRecoveryError("invalid recovery filesystem budget")
    deadline = time.monotonic() + filesystem_budget
    install = _safe_path(Path(journal.install_root))
    snapshot = _safe_path(state_root / "previous-application")
    try:
        seams.contain()
        seams.assert_owner(owner)
        if _inventory(snapshot, deadline) != (journal.tree, journal.directories):
            raise FlatRecoveryError("previous application snapshot failed verification")
        if journal.backup is None:
            raise FlatRecoveryError("logical database recovery point is absent")
        seams.verify_backup(journal.backup)
        journal.phase = "recovering"
        _persist(journal)
        # Configuration/owned-role access must be restored before reconnecting
        # to the original DB; the supplied entry never touches shared PG files.
        seams.restore_config(state_root / "configuration")
        if journal.database_may_have_changed:
            seams.restore_database(journal.backup)
        if seams.schema_revision() != journal.pre_schema_revision:
            raise FlatRecoveryError("restored database has the wrong schema identity")
        # Keep every failed payload byte, including unknown files, rather than
        # removing a directory whose contents may include user additions.
        if journal.restore_tree is None:
            journal.restore_tree = str(install.with_name(f".{install.name}.restore-{owner}"))
            journal.failed_tree = str(install.with_name(f".{install.name}.failed-{owner}"))
            _persist(journal)
        staged = _safe_path(Path(journal.restore_tree))
        failed = _safe_path(Path(journal.failed_tree or ""))
        if staged.parent != install.parent or failed.parent != install.parent:
            raise FlatRecoveryError("recovery staging escaped the owned install parent")
        if not failed.exists():
            if staged.exists():
                if _inventory(staged, deadline) != (journal.tree, journal.directories):
                    raise FlatRecoveryError("existing restore staging is not the bound snapshot")
            else:
                shutil.copytree(snapshot, staged, copy_function=shutil.copy2)
            if _inventory(staged, deadline) != (journal.tree, journal.directories):
                raise FlatRecoveryError("restore staging failed byte verification")
            seams.assert_owner(owner)
            if install.exists():
                install.rename(failed)
        if not install.exists():
            staged.rename(install)
        if _inventory(install, deadline) != (journal.tree, journal.directories):
            raise FlatRecoveryError("restored application tree does not match the recovery point")
        _restore_application_security(install, journal.application_security)
        if (
            _capture_application_security(install, [*journal.directories, *journal.tree])
            != journal.application_security
        ):
            raise FlatRecoveryError(
                "restored application security does not match the recovery point"
            )
        seams.restore_registration(journal.registration)
        if not seams.verify_previous_identity(
            journal.old_version, journal.pre_schema_revision or ""
        ):
            raise FlatRecoveryError("previous application identity/health was not verified")
        seams.assert_owner(owner)
        seams.reactivate(journal.registration)
        journal.phase = "restored"
        _persist(journal)
        return journal
    except Exception:
        # Do not stringify failures carrying credentials into the journal or
        # installer log. All evidence stays in the protected recovery point.
        # Safety cannot depend on a working journal/disk: in particular a
        # failed terminal write after reactivation must still stop writers.
        try:
            seams.contain()
        finally:
            journal.phase = "halted"
            # Preserve the original operation/containment failure. The last
            # durable phase remains nonterminal if the disk is unavailable.
            with contextlib.suppress(Exception):
                _persist(journal)
        raise


def commit(state_root: Path, owner: str, seams: FlatRecoverySeams) -> None:
    journal = load(state_root, owner, seams)
    if journal.phase not in {"replacing", "database_mutating"}:
        raise FlatRecoveryError("commit requires a completed installer replacement")
    journal.phase = "committed"
    _persist(journal)
