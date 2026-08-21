# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only real-Win32 test for the provisioning journal's state-root ACL
hardening (municipal-shared-PC security fix, 2026-07-30).

``win`` appears in this module's own filename (per the D3/CI naming
convention -- see ``test_supervisor_job_object_win.py``) so ``-k "not win"``
deselects it honestly. Skipped entirely on non-Windows. The pure/cross-platform
suite in ``test_provision_journal.py`` proves the WIRING (the hardening
function is called, via a monkeypatched spy); this file proves the actual
Win32 call restricts the real on-disk DACL the way the fix requires --
``civiccast.native.provision.journal.write_journal``'s own production code
path, unmodified, not a reimplementation of the ACL logic.

PRIVILEGE TIER: this test requires only an ordinary, non-elevated user token.
``tmp_path`` is a directory this test process itself creates (and is
therefore the OWNER of), so ``GetFileSecurity``/reading the DACL back
afterward relies on the same owner-implicit ``READ_CONTROL`` right the Rust
installer's own equivalent test relies on (see
``native_service_registration.rs``'s ``write_value_to_key_hardens_the_dacl_...``
test) -- no admin/elevation needed, and the outcome does not depend on which
tier the test happens to run under.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from civiccast.native.provision.journal import write_journal
from civiccast.native.provision.models import (
    ProvisionContext,
    ProvisionJournal,
    ProvisionPhase,
    ProvisionPlan,
)

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="real Win32 ACL is only meaningful on Windows"),
]


def _plan() -> ProvisionPlan:
    return ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )


def _journal(tmp_path: Path) -> ProvisionJournal:
    context = ProvisionContext(
        postgres_data_dir=str(tmp_path / "pgdata"),
        postgres_config_path=str(tmp_path / "pgdata" / "postgresql.conf"),
        postgres_hba_path=str(tmp_path / "pgdata" / "pg_hba.conf"),
        database_password="hunter2",
        server_pack_path=str(tmp_path / "server-binaries.ccpack"),
        state_root=str(tmp_path / "state"),
        owner_run_id="run-1",
    )
    return ProvisionJournal(plan=_plan(), context=context, phase=ProvisionPhase.INIT)


def test_write_journal_hardens_the_state_root_dacl_for_real(tmp_path: Path) -> None:
    """FALSIFIABLE proof: read the REAL DACL back off the directory
    ``write_journal`` created and assert it is PROTECTED (no inherited ACEs
    -- so ProgramData's real-world ``BUILTIN\\Users: ReadAndExecute`` cannot
    flow in) and grants only SYSTEM + Administrators + the calling account
    (see ``journal._STATE_ROOT_SDDL_TEMPLATE``'s docstring for why the
    caller's own SID must also be present -- otherwise a non-elevated caller
    locks itself out of a directory it just created), never Authenticated
    Users / BUILTIN\\Users / Everyone.

    Also proves the SECOND write (a later provisioning phase, same process)
    still succeeds against the now-hardened directory -- the exact
    regression the first cut of this fix hit live (a bare
    ``PermissionError`` on the phase-2 journal write)."""

    import win32security

    from civiccast.native.provision.journal import _current_process_sid_sddl, advance
    from civiccast.native.provision.models import ProvisionPhase

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
    assert f";;;{_current_process_sid_sddl()})" in sddl or (
        _current_process_sid_sddl().endswith("-500") and ";;;LA)" in sddl
    ), f"state root DACL must grant the calling account (else it locks itself out): {sddl!r}"
    assert ";;;AU)" not in sddl, f"state root DACL must NOT grant Authenticated Users: {sddl!r}"
    assert ";;;BU)" not in sddl, f"state root DACL must NOT grant BUILTIN\\Users: {sddl!r}"
    assert ";;;WD)" not in sddl, f"state root DACL must NOT grant Everyone/World: {sddl!r}"

    # The regression proof: a second write (as a later phase's persist would
    # do, from the SAME process) against the now-hardened directory.
    advanced = advance(j, ProvisionPhase.PACK_VERIFIED, "pack verified")
    write_journal(advanced)  # must not raise PermissionError
