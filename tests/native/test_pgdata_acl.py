# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the pgdata DACL normalization
(:mod:`civiccast.native.pgdata_acl`, row-4b update-path blocker).

Descriptor rendering is pure. The tests that drive the Windows branch through
injected apply/read-SID seams still require native Windows path semantics;
they run in the Windows lane. The REAL Win32 call -- and propagation onto
existing child files -- is proven in ``test_pgdata_acl_win.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from civiccast.native import pgdata_acl
from civiccast.native.pgdata_acl import (
    FAILURE_STEP,
    PGDATA_DACL_SDDL_TEMPLATE,
    PgDataAclError,
    normalize_pgdata_acl,
    pgdata_dacl_sddl,
)

_SID = "S-1-5-21-1662294811-121888399-200151778-1001"

_WINDOWS_PATH_TEST = pytest.mark.skipif(
    os.name != "nt", reason="requires native Windows path semantics"
)


@pytest.fixture
def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the module's ``os.name != "nt"`` early-out see Windows, so the
    decision logic is exercised identically on the Linux CI leg."""

    monkeypatch.setattr(pgdata_acl.os, "name", "nt")


class _Applier:
    """Records every (path, sddl) the normalizer asks Windows to apply."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, path: str, sddl: str) -> None:
        self.calls.append((path, sddl))


# --- the descriptor itself (pure) --------------------------------------------


def test_sddl_grants_exactly_system_administrators_and_the_caller() -> None:
    """The whole security argument in one assertion: PROTECTED, inheritable,
    exactly three grantees, and NONE of the broad principals ProgramData
    hands down by default."""

    sddl = pgdata_dacl_sddl(_SID)

    assert sddl == f"D:P(A;OICI;GA;;;SY)(A;OICI;GA;;;BA)(A;OICI;GA;;;{_SID})"
    assert sddl.startswith("D:P"), "must be PROTECTED so ProgramData's ACEs cannot re-inherit"
    assert sddl.count("(A;") == 3, f"exactly three ACEs, no more: {sddl!r}"
    assert "OICI" in sddl, (
        "must be inheritable, or future service-created WAL files are unreachable"
    )
    for broad in (";;;BU)", ";;;AU)", ";;;WD)", ";;;IU)"):
        assert broad not in sddl, (
            f"pgdata holds recorded public-records data and the service credential; "
            f"it must never grant {broad}: {sddl!r}"
        )


def test_sddl_template_is_the_single_source_of_the_rendered_descriptor() -> None:
    assert pgdata_dacl_sddl(_SID) == PGDATA_DACL_SDDL_TEMPLATE.format(caller_sid=_SID)


@pytest.mark.parametrize(
    "bogus",
    ["", "Administrators", "S-1-5", "BA)(A;OICI;GA;;;WD", "S-1-5-21-abc", None],
)
def test_sddl_refuses_anything_that_is_not_a_textual_sid(bogus: object) -> None:
    """SDDL-injection guard: a non-SID grantee (notably one carrying its own
    ``)(A;...`` ACE text) must never be spliced into the descriptor."""

    with pytest.raises(PgDataAclError, match="not a textual SID"):
        pgdata_dacl_sddl(bogus)  # type: ignore[arg-type]


# --- normalize_pgdata_acl (decision logic over injected seams) ---------------


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_normalize_applies_the_expected_descriptor_to_the_data_dir(
    tmp_path: Path, on_windows: None
) -> None:
    applier = _Applier()

    applied = normalize_pgdata_acl(tmp_path, sid_reader=lambda: _SID, apply_dacl=applier)

    assert applied == pgdata_dacl_sddl(_SID)
    assert applier.calls == [(str(tmp_path), pgdata_dacl_sddl(_SID))]


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_normalize_is_idempotent(tmp_path: Path, on_windows: None) -> None:
    """Re-running must be safe and must converge on the SAME descriptor --
    this runs on every install-time start, including repairs and reinstalls
    over an already-normalized cluster."""

    applier = _Applier()

    first = normalize_pgdata_acl(tmp_path, sid_reader=lambda: _SID, apply_dacl=applier)
    second = normalize_pgdata_acl(tmp_path, sid_reader=lambda: _SID, apply_dacl=applier)

    assert first == second
    assert applier.calls == [
        (str(tmp_path), pgdata_dacl_sddl(_SID)),
        (str(tmp_path), pgdata_dacl_sddl(_SID)),
    ]


def test_normalize_is_a_noop_off_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pgdata_acl.os, "name", "posix")
    applier = _Applier()

    def _never_called() -> str:  # pragma: no cover - asserted not to run
        raise AssertionError("the SID must not be read off Windows")

    assert normalize_pgdata_acl(tmp_path, sid_reader=_never_called, apply_dacl=applier) is None
    assert applier.calls == []


# --- failure is LOUD, in every one of its three modes ------------------------


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_normalize_fails_loud_when_the_data_dir_is_missing(
    tmp_path: Path, on_windows: None
) -> None:
    missing = tmp_path / "pgdata"
    applier = _Applier()

    with pytest.raises(PgDataAclError) as excinfo:
        normalize_pgdata_acl(missing, sid_reader=lambda: _SID, apply_dacl=applier)

    assert FAILURE_STEP in str(excinfo.value)
    # repr(), matching the surrounding modules' own path-quoting convention
    # (pg_lifecycle's "data_dir={paths.data_dir!r}").
    assert repr(str(missing)) in str(excinfo.value)
    assert applier.calls == [], "nothing may be applied when the target does not exist"


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_normalize_fails_loud_when_the_caller_sid_cannot_be_read(
    tmp_path: Path, on_windows: None
) -> None:
    applier = _Applier()

    def _boom() -> str:
        raise OSError("token query refused")

    with pytest.raises(PgDataAclError) as excinfo:
        normalize_pgdata_acl(tmp_path, sid_reader=_boom, apply_dacl=applier)

    message = str(excinfo.value)
    assert FAILURE_STEP in message
    assert "token query refused" in message
    assert applier.calls == []


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_normalize_fails_loud_when_windows_refuses_the_dacl(
    tmp_path: Path, on_windows: None
) -> None:
    """The case that matters most: silently continuing here would either hit
    the opaque ``Permission denied`` this fix exists to prevent, or leave the
    cluster world-readable."""

    def _refuse(path: str, sddl: str) -> None:
        raise PermissionError("access denied writing the DACL")

    with pytest.raises(PgDataAclError) as excinfo:
        normalize_pgdata_acl(tmp_path, sid_reader=lambda: _SID, apply_dacl=_refuse)

    message = str(excinfo.value)
    assert FAILURE_STEP in message
    assert "access denied writing the DACL" in message
    assert repr(str(tmp_path)) in message


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_normalize_does_not_double_wrap_its_own_sid_validation_error(
    tmp_path: Path, on_windows: None
) -> None:
    applier = _Applier()

    with pytest.raises(PgDataAclError, match="not a textual SID"):
        normalize_pgdata_acl(tmp_path, sid_reader=lambda: "nonsense", apply_dacl=applier)

    assert applier.calls == []
