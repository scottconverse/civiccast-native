# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only real-Win32 test for the upgrade journal's state-root ACL
hardening (municipal-shared-PC security fix, 2026-07-30).

Mirrors ``test_provision_journal_win.py`` for the sibling provisioning
journal fix -- same defect class (a bare ``mkdir`` under ProgramData
inheriting ``BUILTIN\\Users: ReadAndExecute``), same SDDL shape, same trap
(hardening to only SYSTEM+Administrators locks the writing process out of
its own SECOND write).

``win`` appears in this module's own filename (per the D3/CI naming
convention) so ``-k "not win"`` deselects it honestly. Skipped entirely on
non-Windows. The pure/cross-platform suite in ``test_upgrade_journal.py``
proves the WIRING (the hardening function is called, via a monkeypatched
spy); this file proves the actual Win32 call restricts the real on-disk DACL
the way the fix requires -- ``civiccast.native.upgrade.journal.write_journal``'s
own production code path, unmodified, not a reimplementation of the ACL
logic.

PRIVILEGE TIER: these tests require only an ordinary, non-elevated user
token. ``tmp_path`` is a directory this test process itself creates (and is
therefore the OWNER of), so ``GetFileSecurity``/reading the DACL back
afterward relies on the same owner-implicit ``READ_CONTROL`` right the
provisioning journal's equivalent test relies on -- no admin/elevation
needed, and the outcome does not depend on which tier the test happens to
run under (dev box: UAC-split non-admin; CI: full admin).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from civiccast.native.upgrade.journal import write_journal
from civiccast.native.upgrade.models import (
    UpgradeContext,
    UpgradeJournal,
    UpgradePhase,
    UpgradePlan,
)

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="real Win32 ACL is only meaningful on Windows"),
]


def _journal(tmp_path: Path) -> UpgradeJournal:
    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url="postgresql://u@localhost/db",
        owner_run_id="run-1",
    )
    return UpgradeJournal(
        plan=UpgradePlan(old_version="1.0", new_version="1.1"),
        context=context,
        phase=UpgradePhase.INIT,
    )


def test_write_journal_hardens_the_state_root_dacl_for_real(tmp_path: Path) -> None:
    """FALSIFIABLE proof: read the REAL DACL back off the directory
    ``write_journal`` created and assert it is PROTECTED (no inherited ACEs
    -- so ProgramData's real-world ``BUILTIN\\Users: ReadAndExecute`` cannot
    flow in) and grants only SYSTEM + Administrators + the calling account
    (see ``journal._STATE_ROOT_SDDL_TEMPLATE``'s docstring for why the
    caller's own SID must also be present -- otherwise a non-elevated caller
    locks itself out of a directory it just created), never Authenticated
    Users / BUILTIN\\Users / Everyone.

    Also proves the SECOND write (a later upgrade phase, same process) still
    succeeds against the now-hardened directory -- the exact regression the
    provisioning sibling fix hit live (a bare ``PermissionError`` on the
    phase-2 journal write)."""

    import win32security

    from civiccast.native.upgrade.journal import _current_process_sid_sddl, advance

    j = _journal(tmp_path)
    write_journal(j)
    state_root = Path(j.context.state_root)
    assert state_root.is_dir()

    security_descriptor = win32security.GetFileSecurity(
        str(state_root), win32security.DACL_SECURITY_INFORMATION
    )
    sddl = win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
        security_descriptor,
        win32security.SDDL_REVISION_1,
        win32security.DACL_SECURITY_INFORMATION,
    )

    assert sddl.startswith("D:P"), (
        f"state root DACL must be PROTECTED so the inherited world-readable "
        f"ProgramData default cannot flow in: {sddl!r}"
    )
    assert ";;;SY)" in sddl, f"state root DACL must grant SYSTEM: {sddl!r}"
    assert ";;;BA)" in sddl, f"state root DACL must grant BUILTIN\\Administrators: {sddl!r}"
    assert (f";;;{_current_process_sid_sddl()})" in sddl or (_current_process_sid_sddl().endswith("-500") and ";;;LA)" in sddl)), (
        f"state root DACL must grant the calling account (else it locks itself out): {sddl!r}"
    )
    assert ";;;AU)" not in sddl, f"state root DACL must NOT grant Authenticated Users: {sddl!r}"
    assert ";;;BU)" not in sddl, f"state root DACL must NOT grant BUILTIN\\Users: {sddl!r}"
    assert ";;;WD)" not in sddl, f"state root DACL must NOT grant Everyone/World: {sddl!r}"

    # The regression proof: a second write (as a later phase's persist would
    # do, from the SAME process) against the now-hardened directory.
    advanced = advance(j, UpgradePhase.INTERLOCK_ACQUIRED, "interlock acquired")
    write_journal(advanced)  # must not raise PermissionError


def test_pg_dump_backup_directory_inherits_the_hardened_state_root_dacl(
    tmp_path: Path,
) -> None:
    """Finding (3) from the task: the pre-upgrade ``pg_dump`` backup directory
    (``state_root/backups/pre-<version>/``, created by
    ``civiccast.dr.backup``'s ``dest_dir.mkdir(parents=True, exist_ok=True)``
    -- a bare mkdir, same as the state root's own pre-fix code) is NOT
    created with any hardening call of its own. This test proves it does not
    need one: it inherits the state root's hardened DACL via ordinary NTFS
    ACE inheritance, because (a) ``_STATE_ROOT_SDDL_TEMPLATE`` marks every
    grant ``OICI`` (object-inherit + container-inherit) and (b) the
    orchestrator always calls ``write_journal`` (which hardens state_root)
    at phase INIT, BEFORE ``_drive_forward`` ever reaches the BACKUP_VERIFIED
    step that creates this subdirectory -- so the parent is already hardened
    by the time the child is created.

    This does not invoke ``civiccast.dr.backup`` itself (that module has its
    own test surface); it replicates only the one relevant fact -- a bare,
    multi-level ``mkdir(parents=True)`` under the hardened state root -- to
    isolate the inheritance claim from backup/pg_dump machinery."""

    import win32security

    from civiccast.native.upgrade.journal import _current_process_sid_sddl

    j = _journal(tmp_path)
    write_journal(j)  # hardens state_root, per the fix under test
    state_root = Path(j.context.state_root)

    # Mirrors civiccast/dr/backup.py's `dest_dir.mkdir(parents=True, exist_ok=True)`
    # for `state_root/backups/pre-<new_version>/`, exactly as
    # orchestrator._drive_forward's BACKUP_VERIFIED step computes it.
    backup_dir = state_root / "backups" / "pre-1.1"
    backup_dir.mkdir(parents=True, exist_ok=True)

    security_descriptor = win32security.GetFileSecurity(
        str(backup_dir), win32security.DACL_SECURITY_INFORMATION
    )
    sddl = win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
        security_descriptor,
        win32security.SDDL_REVISION_1,
        win32security.DACL_SECURITY_INFORMATION,
    )

    # The discriminating assertion: Windows' ORDINARY default new-directory
    # DACL (what this test would show if state_root were NOT hardened, or if
    # the child somehow escaped the hardened tree) grants the owner via the
    # generic "OW" alias, e.g. 'D:(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)'
    # -- SY/BA present either way, so asserting on those alone would pass
    # whether or not this fix's hardening actually flowed down. Our
    # hardening template grants the caller's LITERAL SID string instead of
    # the "OW" alias (see _STATE_ROOT_SDDL_TEMPLATE's docstring), so only an
    # inherited copy of OUR hardened ACL contains that literal string.
    assert (f";;;{_current_process_sid_sddl()})" in sddl or (_current_process_sid_sddl().endswith("-500") and ";;;LA)" in sddl)), (
        f"backup dir must inherit the state root's hardened DACL (literal caller "
        f"SID, not the ordinary Windows default 'OW' owner alias) -- if this "
        f"fails, the pg_dump backups escaped the hardened tree: {sddl!r}"
    )
    assert ";;;SY)" in sddl, f"backup dir must inherit the SYSTEM grant: {sddl!r}"
    assert ";;;BA)" in sddl, f"backup dir must inherit the Administrators grant: {sddl!r}"
    assert ";;;BU)" not in sddl, (
        f"backup dir must NOT carry BUILTIN\\Users -- if this fails, the pg_dump "
        f"backups escaped the hardened tree: {sddl!r}"
    )
    assert ";;;AU)" not in sddl, f"backup dir must NOT carry Authenticated Users: {sddl!r}"
    assert ";;;WD)" not in sddl, f"backup dir must NOT carry Everyone/World: {sddl!r}"
