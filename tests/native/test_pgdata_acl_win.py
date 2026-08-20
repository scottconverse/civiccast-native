# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Windows-only real-Win32 proof for the pgdata DACL normalization
(row-4b update-path blocker, Sandbox run 21).

``win`` appears in this module's own filename (per the D3/CI naming
convention -- see ``test_provision_journal_win.py``) so ``-k "not win"``
deselects it honestly. Skipped entirely on non-Windows.

``test_pgdata_acl.py`` proves the DECISION logic and the descriptor text
through injected seams; this file drives
:func:`civiccast.native.pgdata_acl.normalize_pgdata_acl`'s PRODUCTION path
(real ``SetNamedSecurityInfo``) and asserts the two properties the fix
actually depends on and that no pure test can establish:

1. the resulting DACL is PROTECTED and grants exactly SYSTEM +
   Administrators + the calling account (``BUILTIN\\Users`` -- which
   ``C:\\ProgramData`` hands down by default and which is the ONLY access a
   restricted-token postmaster has to a LocalSystem-created WAL file -- is
   gone), and
2. it PROPAGATES onto an EXISTING nested child file. That is the whole
   repair: the offending ``pg_wal/000000010000000000000002`` already exists
   when this runs, and a directory-only ACL change would not touch it.

F4/F1/F2 (audit follow-up): the tree above is now SEEDED with an explicit
inheritable ``BUILTIN\\Users`` ACE before normalization runs, so the
narrowing assertions are actually falsifiable rather than trivially true of
an untouched ``tmp_path`` (which never carries a ``BUILTIN\\Users`` ACE to
begin with). Two more tests below pin the measured propagation LIMITS as
documented behavior: an EXPLICIT child ACE survives (only the inherited
portion of a child's DACL is replaced), and propagation stops at a
PROTECTED child directory while the call itself still reports success.

F5 (audit follow-up): every assertion above (and in ``test_pgdata_acl.py``)
is a substring match on a read-back SDDL string, which a semantically-wrong
descriptor could still satisfy by accident. The final test in this file
instead builds a restricted token shaped exactly like ``pg_ctl``'s own
postmaster token (``src/common/restricted_token.c``'s
``CreateRestrictedToken(..., DISABLE_MAX_PRIVILEGE, ..., dropSids=
{BUILTIN\\Administrators, BUILTIN\\Power Users}, ...)``), impersonates it,
and proves EFFECTIVE ACCESS by actually opening a nested file for
READ+WRITE -- succeeding on a normalized tree, and failing with
``PermissionError`` on the negative control (the pre-fix ACE shape). That is
the test that proves the fix, not just its spelling.

PRIVILEGE TIER: ordinary, non-elevated user token. ``tmp_path`` is created by
this test process, so ``WRITE_DAC``/``READ_CONTROL`` come from the
owner-implicit rights the sibling journal ACL test already relies on -- no
admin, and the outcome does not depend on which UAC tier the run happens to
have. The restricted-token tests need no elevation either: ``CreateRestrictedToken``
only ever narrows the calling token's own access, never widens it, and are
skipped cleanly if the token APIs this needs are unavailable.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from civiccast.native.pgdata_acl import normalize_pgdata_acl

pytestmark = [
    pytest.mark.windows_only,
    pytest.mark.skipif(os.name != "nt", reason="real Win32 ACL is only meaningful on Windows"),
]


def _dacl_sddl(path: Path) -> str:
    import win32security

    descriptor = win32security.GetNamedSecurityInfo(
        str(path), win32security.SE_FILE_OBJECT, win32security.DACL_SECURITY_INFORMATION
    )
    return str(
        win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(
            descriptor,
            win32security.SDDL_REVISION_1,
            win32security.DACL_SECURITY_INFORMATION,
        )
    )


def _current_sid() -> str:
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    sid, _attributes = win32security.GetTokenInformation(token, win32security.TokenUser)
    return str(win32security.ConvertSidToStringSid(sid))


def _sddl_grants_current_process(sddl: str) -> bool:
    """Recognize Windows canonicalizing the built-in Administrator SID as ``LA``."""

    sid = _current_sid()
    return f";;;{sid})" in sddl or (sid.endswith("-500") and ";;;LA)" in sddl)


def _set_dacl_sddl(path: Path, sddl_str: str, *, protected: bool) -> None:
    """Directly set ``path``'s DACL to ``sddl_str`` -- the test-side seeding
    primitive for F4/F1/F2 below. ``protected=False`` mimics an ordinary
    inheritable ACE (what ``C:\\ProgramData`` hands down by default);
    ``protected=True`` mimics a ``D:P`` object that blocks further inbound
    propagation (F2)."""

    import win32security

    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        sddl_str, win32security.SDDL_REVISION_1
    )
    flags = win32security.DACL_SECURITY_INFORMATION
    flags |= (
        win32security.PROTECTED_DACL_SECURITY_INFORMATION
        if protected
        else win32security.UNPROTECTED_DACL_SECURITY_INFORMATION
    )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        flags,
        None,
        None,
        descriptor.GetSecurityDescriptorDacl(),
        None,
    )


#: An ordinary inheritable DACL naming SYSTEM, Administrators, and
#: BUILTIN\\Users -- the shape ``C:\\ProgramData`` actually hands down
#: (module docstring's THE MECHANISM section, item 1), seeded explicitly
#: here so the narrowing assertions below have something to narrow FROM. A
#: bare ``tmp_path`` never carries a BUILTIN\\Users ACE at all (measured:
#: ``D:(A;OICIID;FA;;;SY)(A;OICIID;FA;;;BA)(A;OICIID;FA;;;OW)``), so without
#: this seed every "BU is gone" assertion below would pass vacuously
#: regardless of what :func:`normalize_pgdata_acl` does (F4).
_PROGRAMDATA_LIKE_SDDL = "D:(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;BU)"


def test_normalize_protects_the_data_dir_and_propagates_to_existing_children(
    tmp_path: Path,
) -> None:
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    # Seed BEFORE creating any children, so they inherit BUILTIN\\Users from
    # the parent exactly as a real ProgramData-born file would (F4).
    _set_dacl_sddl(pgdata, _PROGRAMDATA_LIKE_SDDL, protected=False)

    wal = pgdata / "pg_wal"
    wal.mkdir(parents=True)
    segment = wal / "000000010000000000000002"
    segment.write_bytes(b"wal")

    # Sanity check on the seed itself: prove the pre-fix state actually
    # carries BUILTIN\\Users, so the "BU is gone" assertions below are
    # falsifiable (RED before the fix runs, GREEN only because the fix
    # removed it -- not because it was never there).
    pre_segment_sddl = _dacl_sddl(segment)
    assert ";;;BU)" in pre_segment_sddl, (
        f"test bug: the seed must give the pre-existing child an inherited "
        f"BUILTIN\\Users ACE, or the narrowing assertion below is vacuous: "
        f"{pre_segment_sddl!r}"
    )

    applied = normalize_pgdata_acl(pgdata)
    assert applied is not None

    root_sddl = _dacl_sddl(pgdata)
    assert root_sddl.startswith("D:P"), (
        f"the data dir's DACL must be PROTECTED so ProgramData's BUILTIN\\Users "
        f"entries cannot re-inherit: {root_sddl!r}"
    )
    for principal in (";;;SY)", ";;;BA)"):
        assert principal in root_sddl, f"data dir DACL must grant {principal}: {root_sddl!r}"
    assert _sddl_grants_current_process(root_sddl), (
        f"data dir DACL must grant the calling account: {root_sddl!r}"
    )
    for broad in (";;;BU)", ";;;AU)", ";;;WD)"):
        assert broad not in root_sddl, (
            f"data dir DACL must NOT grant {broad} -- this cluster holds recorded "
            f"public-records data and the service credential: {root_sddl!r}"
        )

    # (2) THE repair property: the pre-existing nested file -- the stand-in
    # for the LocalSystem-created WAL segment the live failure died on -- now
    # carries the caller's own inherited full-control ACE, and no longer
    # carries BUILTIN\Users. This assertion is now falsifiable (see the
    # pre-normalize sanity check above): it fails against the seeded,
    # unfixed state and only passes once normalize_pgdata_acl has run.
    segment_sddl = _dacl_sddl(segment)
    assert _sddl_grants_current_process(segment_sddl), (
        f"the normalization must PROPAGATE to files that already existed, or the "
        f"restricted-token postmaster still cannot open them: {segment_sddl!r}"
    )
    assert ";;;SY)" in segment_sddl, (
        f"the LocalSystem service must keep full access to the cluster: {segment_sddl!r}"
    )
    assert ";;;BU)" not in segment_sddl, f"BUILTIN\\Users must be gone: {segment_sddl!r}"


def test_normalize_propagation_replaces_only_the_inherited_portion_of_a_childs_dacl(
    tmp_path: Path,
) -> None:
    """F1 (measured limit, now pinned as documented behavior -- see the
    module docstring's SECURITY REASONING section): a child that already
    carries its OWN EXPLICIT ``BUILTIN\\Users`` ACE keeps it after
    normalize. ``SetNamedSecurityInfo``'s propagation recomputes only the
    INHERITED portion of each child's DACL; an explicit ACE set directly on
    a child is untouched. This is not a bug to "fix" silently -- it is
    documented, measured Windows behavior this test exists to pin so nobody
    changes it by accident without noticing the doc goes stale."""

    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    _set_dacl_sddl(pgdata, _PROGRAMDATA_LIKE_SDDL, protected=False)

    explicit_child = pgdata / "explicit_child.txt"
    explicit_child.write_bytes(b"x")
    # An EXPLICIT (non-inherited) BUILTIN\\Users ACE, set directly on the
    # child -- e.g. as though some other tool had ACL'd this one file.
    _set_dacl_sddl(explicit_child, "D:(A;;FA;;;BU)", protected=False)
    pre_sddl = _dacl_sddl(explicit_child)
    assert "(A;;FA;;;BU)" in pre_sddl, (
        f"test bug: the explicit ACE must actually be set before normalize runs: {pre_sddl!r}"
    )

    applied = normalize_pgdata_acl(pgdata)
    assert applied is not None

    post_sddl = _dacl_sddl(explicit_child)
    assert "(A;;FA;;;BU)" in post_sddl, (
        f"an EXPLICIT BUILTIN\\Users ACE on a child must SURVIVE normalize -- "
        f"propagation only replaces the inherited portion of a child's DACL "
        f"(measured, documented behavior, not a defect): {post_sddl!r}"
    )
    # The inherited portion is still refreshed to the new three grantees --
    # this is not "nothing happened to the child", only "the explicit ACE
    # specifically survives".
    assert _sddl_grants_current_process(post_sddl), (
        f"the child's INHERITED ACEs must still be refreshed to the new grantees: {post_sddl!r}"
    )
    assert ";;;SY)" in post_sddl


def test_normalize_propagation_stops_at_a_protected_child_and_still_succeeds(
    tmp_path: Path,
) -> None:
    """F2 (measured limit, now pinned): propagation stops at a PROTECTED
    (``D:P``) child directory, and :func:`normalize_pgdata_acl` still
    returns success -- the Win32 call it makes on the root succeeded; there
    is no per-child result to observe or report (see the module docstring's
    fail-loud scoping note)."""

    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    _set_dacl_sddl(pgdata, _PROGRAMDATA_LIKE_SDDL, protected=False)

    protected_child = pgdata / "protected_child"
    protected_child.mkdir()
    grandchild = protected_child / "grand.txt"
    grandchild.write_bytes(b"x")
    # Protect the child directory itself, blocking further inbound
    # propagation from its parent.
    _set_dacl_sddl(protected_child, _PROGRAMDATA_LIKE_SDDL.replace("D:", "D:P", 1), protected=True)
    pre_child_sddl = _dacl_sddl(protected_child)
    pre_grandchild_sddl = _dacl_sddl(grandchild)
    assert pre_child_sddl.startswith("D:P")
    assert ";;;BU)" in pre_grandchild_sddl

    applied = normalize_pgdata_acl(pgdata)
    assert applied is not None, (
        "a protected child must not make normalize_pgdata_acl itself fail -- "
        "the root DACL write it performs still succeeds"
    )

    # The root and its ordinary (unprotected) descendants are still fixed.
    root_sddl = _dacl_sddl(pgdata)
    assert root_sddl.startswith("D:P")
    assert _sddl_grants_current_process(root_sddl)

    # But the protected subtree never saw the new grantees -- propagation
    # stopped at its boundary, exactly as documented.
    post_child_sddl = _dacl_sddl(protected_child)
    post_grandchild_sddl = _dacl_sddl(grandchild)
    assert ";;;BU)" in post_grandchild_sddl, (
        f"a protected child directory must block propagation from its parent -- "
        f"the grandchild's stale BUILTIN\\Users ACE must survive untouched: "
        f"{post_grandchild_sddl!r}"
    )
    assert not _sddl_grants_current_process(post_grandchild_sddl), (
        f"the caller SID must NOT have propagated past the protected boundary: "
        f"{post_grandchild_sddl!r}"
    )
    assert post_child_sddl == pre_child_sddl, (
        f"the protected child's own DACL must be completely untouched by normalize: "
        f"before={pre_child_sddl!r} after={post_child_sddl!r}"
    )


def test_normalize_is_idempotent_against_a_real_dacl(tmp_path: Path) -> None:
    pgdata = tmp_path / "pgdata"
    (pgdata / "global").mkdir(parents=True)
    (pgdata / "global" / "pg_control").write_bytes(b"control")

    first = normalize_pgdata_acl(pgdata)
    after_first = _dacl_sddl(pgdata)
    child_after_first = _dacl_sddl(pgdata / "global" / "pg_control")

    second = normalize_pgdata_acl(pgdata)

    assert first == second
    assert _dacl_sddl(pgdata) == after_first
    assert _dacl_sddl(pgdata / "global" / "pg_control") == child_after_first


# --- F5: EFFECTIVE ACCESS under a pg_ctl-shaped restricted token -------------
#
# Everything above pins the DESCRIPTOR TEXT. That leaves a gap: a
# semantically-wrong-but-textually-right SDDL string (e.g. the three
# grantees present but with the wrong access mask, or DENY ACEs the
# substring checks never look for) would still pass every assertion above.
# The tests below instead build a token shaped exactly like the one
# ``pg_ctl`` hands its postmaster child (module docstring's THE MECHANISM,
# item 5: ``CreateRestrictedToken(origToken, DISABLE_MAX_PRIVILEGE, 2,
# dropSids={BUILTIN\\Administrators, BUILTIN\\Power Users}, ...)``),
# impersonate it, and try to actually OPEN a file for read+write. That is
# the property the whole fix exists to establish.

_RESTRICTED_TOKEN_API_ATTRS = (
    "OpenProcessToken",
    "DuplicateTokenEx",
    "CreateRestrictedToken",
    "SetThreadToken",
    "RevertToSelf",
    "CreateWellKnownSid",
    "WinBuiltinAdministratorsSid",
    "WinBuiltinPowerUsersSid",
    "DISABLE_MAX_PRIVILEGE",
    "SecurityImpersonation",
    "TokenImpersonation",
)


def _require_restricted_token_apis() -> None:
    import win32security

    missing = [name for name in _RESTRICTED_TOKEN_API_ATTRS if not hasattr(win32security, name)]
    if missing:
        pytest.skip(f"win32security is missing restricted-token APIs: {missing!r}")


def _build_pg_ctl_shaped_restricted_token() -> object:
    """A restricted TOKEN_IMPERSONATE-capable token mirroring PostgreSQL's
    own ``CreateRestrictedProcess`` (``src/common/restricted_token.c``):
    ``DISABLE_MAX_PRIVILEGE`` plus ``BUILTIN\\Administrators`` and
    ``BUILTIN\\Power Users`` marked deny-only (``SidsToDisable``). The
    calling token's own user SID is left enabled -- exactly as PostgreSQL's
    call does -- which is what makes this the right stand-in for the
    install-time postmaster's actual effective identity.
    """

    import win32api
    import win32security

    process_token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(),
        win32security.TOKEN_DUPLICATE | win32security.TOKEN_QUERY,
    )
    impersonation_token = win32security.DuplicateTokenEx(
        process_token,
        win32security.SecurityImpersonation,
        win32security.TOKEN_QUERY
        | win32security.TOKEN_DUPLICATE
        | win32security.TOKEN_IMPERSONATE
        | win32security.TOKEN_ASSIGN_PRIMARY,
        win32security.TokenImpersonation,
        None,
    )
    admins_sid = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid)
    power_users_sid = win32security.CreateWellKnownSid(win32security.WinBuiltinPowerUsersSid)
    return win32security.CreateRestrictedToken(
        impersonation_token,
        win32security.DISABLE_MAX_PRIVILEGE,
        [(admins_sid, 0), (power_users_sid, 0)],
        None,
        None,
    )


@contextlib.contextmanager
def _impersonating(token: object) -> Iterator[None]:
    import win32security

    win32security.SetThreadToken(None, token)
    try:
        yield
    finally:
        win32security.RevertToSelf()


def test_effective_access_pg_ctl_shaped_token_can_open_normalized_tree_readwrite(
    tmp_path: Path,
) -> None:
    """THE positive proof: under a restricted token shaped exactly like
    ``pg_ctl``'s own postmaster token, opening a pre-existing nested file
    under a normalized pgdata tree for READ+WRITE must SUCCEED. This is
    what the whole fix is for -- everything else in this file only proves
    the descriptor's text."""

    _require_restricted_token_apis()

    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    nested = pgdata / "pg_wal"
    nested.mkdir()
    target = nested / "000000010000000000000002"
    target.write_bytes(b"wal")

    applied = normalize_pgdata_acl(pgdata)
    assert applied is not None

    restricted_token = _build_pg_ctl_shaped_restricted_token()
    with _impersonating(restricted_token), target.open("r+b") as handle:
        handle.write(b"!")


def test_effective_access_pg_ctl_shaped_token_is_denied_on_pre_fix_shape(
    tmp_path: Path,
) -> None:
    """THE negative control: the SAME restricted token, against a tree
    shaped like the DEFECT this module exists to fix -- SY:F, BA:F,
    BUILTIN\\Users:RX, all inherited, no caller ACE (module docstring's THE
    MECHANISM, item 3) -- must be DENIED. Without this half, the positive
    test above could pass for the wrong reason (e.g. because the restricted
    token was somehow not actually restricted)."""

    _require_restricted_token_apis()

    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    nested = pgdata / "pg_wal"
    nested.mkdir()
    target = nested / "000000010000000000000002"
    target.write_bytes(b"wal")

    # Apply the pre-fix shape directly: PROTECTED (so no ancestor ACE, e.g.
    # an inherited "Owner Rights" entry from the pytest tmp tree, leaks in
    # and masks the scenario), no caller SID, BUILTIN\\Users read+execute
    # only. Applied to the already-existing tree so it propagates onto
    # ``target`` the same way a real ACL pass would.
    _set_dacl_sddl(
        pgdata,
        "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;BU)",
        protected=True,
    )

    restricted_token = _build_pg_ctl_shaped_restricted_token()
    with _impersonating(restricted_token), pytest.raises(PermissionError), target.open("r+b"):
        pass
