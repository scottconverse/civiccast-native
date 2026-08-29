# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the W-2 in-product setup-handoff recovery mechanism
(:mod:`civiccast.installer.handoff_recovery`).

Router-level HTTP behavior (loopback gate, rate limiting, the generic-403
"no oracle" contract) lives in ``test_handoff_recovery_api.py``. These tests
exercise the module's own decision logic directly, always through the
injected ``harden_acl`` seam -- never the real ``win32security`` call --
mirroring ``tests/native/test_pgdata_acl.py``'s own convention for the same
reason: the real Win32 call is proven by inspection of the SDDL literal
here, and would otherwise make these tests depend on the calling account's
own Windows privileges.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from civiccast.installer import handoff_recovery
from civiccast.installer.handoff_recovery import (
    CODE_LENGTH,
    MAX_ATTEMPTS,
    HandoffRecoveryError,
    complete_recovery,
    start_recovery,
)


class _AclRecorder:
    """Records every directory the module asks to be hardened; never touches
    a real security descriptor."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def __call__(self, directory: Path) -> None:
        self.calls.append(directory)


@pytest.fixture(autouse=True)
def _recovery_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "setup-recovery"
    monkeypatch.setenv("CIVICCAST_SETUP_RECOVERY_DIR", str(directory))
    return directory


def _state() -> dict[str, object]:
    raw = json.loads(
        (handoff_recovery.recovery_dir() / handoff_recovery._STATE_FILENAME).read_text()
    )
    assert isinstance(raw, dict)
    return raw


def _rewrite_state(**updates: object) -> None:
    state = _state()
    state.update(updates)
    (handoff_recovery.recovery_dir() / handoff_recovery._STATE_FILENAME).write_text(
        json.dumps(state)
    )


def _read_code() -> str:
    return handoff_recovery.code_file_path().read_text().strip()


# --- start_recovery: the challenge file and its ACL --------------------------


def test_start_recovery_writes_an_unambiguous_code_and_hardens_the_directory(
    tmp_path: Path,
) -> None:
    acl = _AclRecorder()

    result = start_recovery(harden_acl=acl)

    code = _read_code()
    assert len(code) == CODE_LENGTH
    assert set(code) <= set(handoff_recovery._CODE_ALPHABET)
    for ambiguous in "0O1IL":
        assert ambiguous not in handoff_recovery._CODE_ALPHABET, (
            f"{ambiguous!r} is a classic look-alike and must not be in the code alphabet"
        )
    assert acl.calls == [handoff_recovery.recovery_dir()]
    assert result.code_file == str(handoff_recovery.code_file_path())
    assert result.expires_in == handoff_recovery.CODE_TTL_SECONDS


def test_start_recovery_result_never_carries_the_code(tmp_path: Path) -> None:
    """The response the router hands back to an HTTP caller is built
    directly from this dataclass -- it must be structurally impossible for
    the code to leak through it."""

    result = start_recovery(harden_acl=_AclRecorder())

    assert set(result.__dataclass_fields__) == {"code_file", "expires_in"}
    code = _read_code()
    assert code not in result.code_file


def test_start_recovery_raises_when_the_acl_cannot_be_applied(tmp_path: Path) -> None:
    def _refuse(directory: Path) -> None:
        raise PermissionError("access denied writing the DACL")

    with pytest.raises(HandoffRecoveryError, match="Administrators and SYSTEM"):
        start_recovery(harden_acl=_refuse)

    # Fail-loud, no partial state: a code this call could not actually
    # secure must never be left on disk looking like a working challenge.
    assert not handoff_recovery.code_file_path().exists()


def test_start_recovery_preserves_the_previous_code_when_a_regenerate_fails_before_overwriting_it(
    tmp_path: Path,
) -> None:
    """A failed "Get a new code" (`start_recovery` called again over an
    already-valid earlier code) must not ALSO destroy the still-usable
    earlier code -- that would turn one failed regenerate into total
    lockout. Only once ``code.txt`` has actually been overwritten is there
    no longer an intact previous challenge to protect (covered by
    :func:`test_start_recovery_raises_when_the_code_file_cannot_be_written_after_hardening`,
    which removes the half-written state after that point)."""

    acl = _AclRecorder()
    start_recovery(harden_acl=acl)
    original_code = _read_code()

    def _refuse(directory: Path) -> None:
        raise PermissionError("access denied writing the DACL")

    with pytest.raises(HandoffRecoveryError):
        start_recovery(harden_acl=_refuse)

    assert _read_code() == original_code
    assert complete_recovery(original_code).ok is True


def test_start_recovery_raises_when_the_code_file_cannot_be_written_after_hardening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Field incident 2026-08-28: on a real box, the ACL hardening step can
    succeed (it only needs WRITE_DAC, which the directory's own creator
    already has) while the SAME call's own write into that now-hardened
    directory fails with a bare ``PermissionError`` -- e.g. a caller whose
    token does not carry the ``SY``/``BA`` SIDs it just granted the
    directory (a de-elevated administrator is the *default* Windows token
    state; UAC only attaches the Administrators group to an elevated
    process). Before this fix that ``PermissionError`` was never caught --
    neither here nor in the router -- so it reached an HTTP caller as an
    unhandled 500 instead of the module's own fail-loud
    :class:`HandoffRecoveryError`/503 contract. This directly repros that
    class of bug through the injected seam (never the real ``win32security``
    call -- see the module docstring)."""

    acl = _AclRecorder()

    def _fail_to_write(path: Path, content: str) -> None:
        raise PermissionError(f"access denied writing {path}")

    monkeypatch.setattr(handoff_recovery, "_atomic_write", _fail_to_write)

    with pytest.raises(HandoffRecoveryError, match="Administrators and SYSTEM"):
        start_recovery(harden_acl=acl)

    # The ACL step itself ran (this is not a refused-ACL failure)...
    assert acl.calls == [handoff_recovery.recovery_dir()]
    # ...but no half-issued challenge is left behind: a caller that got the
    # exception must never also be able to redeem a code for this attempt.
    assert not handoff_recovery.code_file_path().exists()
    assert not (handoff_recovery.recovery_dir() / handoff_recovery._STATE_FILENAME).exists()


def test_start_recovery_raises_if_it_cannot_read_back_what_it_just_wrote(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense in depth beyond the write itself succeeding: if this call
    cannot read back the code it just wrote (the identity answering "a code
    is ready" is not the identity that can actually reach the file it is
    describing), it must refuse to report success rather than hand back a
    ``code_file`` path an admin who follows it may not be able to open
    either."""

    real_read_text = Path.read_text

    def _lie_on_readback(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == handoff_recovery.CODE_FILENAME:
            raise PermissionError(f"access denied reading {self}")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _lie_on_readback)

    with pytest.raises(HandoffRecoveryError, match="Administrators and SYSTEM"):
        start_recovery(harden_acl=_AclRecorder())

    assert not handoff_recovery.code_file_path().exists()


def test_start_recovery_regenerates_and_invalidates_the_previous_code(tmp_path: Path) -> None:
    acl = _AclRecorder()
    start_recovery(harden_acl=acl)
    first_code = _read_code()

    start_recovery(harden_acl=acl)
    second_code = _read_code()

    assert first_code != second_code
    assert complete_recovery(first_code).ok is False
    assert complete_recovery(second_code).ok is True


def test_recovery_dir_sddl_grants_exactly_system_and_administrators() -> None:
    sddl = handoff_recovery._RECOVERY_DIR_SDDL

    assert sddl.startswith("D:P"), "must be PROTECTED so ProgramData's ACEs cannot re-inherit"
    assert sddl.count("(A;") == 2, f"exactly two ACEs, no more: {sddl!r}"
    assert ";;;SY)" in sddl
    assert ";;;BA)" in sddl
    for broad in (";;;BU)", ";;;AU)", ";;;WD)", ";;;IU)"):
        assert broad not in sddl, f"must never grant {broad}: {sddl!r}"


def test_harden_recovery_dir_acl_is_a_noop_off_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(handoff_recovery.os, "name", "posix")

    # Must return without ever importing win32security -- if it did, this
    # call would raise ImportError on a non-Windows interpreter.
    assert handoff_recovery._harden_recovery_dir_acl(tmp_path) is None


# --- complete_recovery: single-use, TTL, burn, no oracle ---------------------


def test_complete_recovery_happy_path_consumes_the_code() -> None:
    start_recovery(harden_acl=_AclRecorder())
    code = _read_code()

    outcome = complete_recovery(code)

    assert outcome.ok is True
    assert outcome.reason == "ok"
    assert not handoff_recovery.code_file_path().exists(), "used code must not remain readable"


def test_complete_recovery_replay_is_rejected() -> None:
    start_recovery(harden_acl=_AclRecorder())
    code = _read_code()
    assert complete_recovery(code).ok is True

    replay = complete_recovery(code)

    assert replay.ok is False
    assert replay.reason == "wrong"


def test_complete_recovery_wrong_code_is_rejected_and_recorded() -> None:
    start_recovery(harden_acl=_AclRecorder())

    outcome = complete_recovery("ZZZZZZZZ")

    assert outcome.ok is False
    assert outcome.reason == "wrong"
    assert _state()["attempts"] == 1


def test_complete_recovery_with_no_active_challenge_is_rejected() -> None:
    outcome = complete_recovery("ANYCODE1")

    assert outcome.ok is False
    assert outcome.reason == "no-code"


def test_complete_recovery_burns_after_five_wrong_attempts() -> None:
    start_recovery(harden_acl=_AclRecorder())
    code = _read_code()

    for _ in range(MAX_ATTEMPTS):
        outcome = complete_recovery("NNNNNNNN")
        assert outcome.ok is False
        assert outcome.reason == "wrong"

    burned = complete_recovery("NNNNNNNN")
    assert burned.ok is False
    assert burned.reason == "burned"

    # Even the genuinely correct code is refused once burned -- the only
    # way forward is a fresh /start call (a new rate-limited request, at the
    # router layer).
    still_burned = complete_recovery(code)
    assert still_burned.ok is False
    assert still_burned.reason == "burned"


def test_complete_recovery_expired_code_is_rejected() -> None:
    start_recovery(harden_acl=_AclRecorder())
    code = _read_code()
    past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    _rewrite_state(expires_at=past)

    outcome = complete_recovery(code)

    assert outcome.ok is False
    assert outcome.reason == "expired"


def test_complete_recovery_uses_constant_time_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    """Structural guard against a future refactor that swaps in ``==``: the
    verification path must go through :func:`secrets.compare_digest`."""

    calls: list[tuple[str, str]] = []
    real_compare_digest = handoff_recovery.secrets.compare_digest

    def _spy(a: str, b: str) -> bool:
        calls.append((a, b))
        return real_compare_digest(a, b)

    monkeypatch.setattr(handoff_recovery.secrets, "compare_digest", _spy)
    start_recovery(harden_acl=_AclRecorder())
    code = _read_code()

    complete_recovery(code)

    assert len(calls) == 1
    # Both operands are salted-hash hex digests, never the raw code.
    assert code not in calls[0]


# --- concurrency: two callers hitting the same challenge at once -------------
#
# Codex review finding on PR #415: FastAPI runs these synchronous handlers in
# a threadpool, so two requests from the same operator (two tabs, a
# double-submit) can enter `complete_recovery`/`start_recovery` on different
# threads of the SAME process at once. Before `_RECOVERY_LOCK`, that raced on
# the "already consumed" check-then-act AND on `_atomic_write`'s shared
# `<name>.<pid>.tmp` staging path -- either double-granting a "single-use"
# code or raising `FileNotFoundError` (a 500) when one thread's `tmp.replace`
# beat the other's. These tests actually run two threads, not two sequential
# calls -- a sequential call gives the race window no chance to exist.


def test_complete_recovery_serializes_concurrent_redemption_of_the_same_code() -> None:
    start_recovery(harden_acl=_AclRecorder())
    code = _read_code()

    barrier = threading.Barrier(2)
    results: list[handoff_recovery.RecoveryCompleteResult] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def _redeem() -> None:
        barrier.wait()
        try:
            outcome = complete_recovery(code)
        except BaseException as exc:  # the pre-fix bug surfaced as FileNotFoundError
            with lock:
                errors.append(exc)
            return
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_redeem) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == [], f"concurrent redemption raised: {errors!r}"
    assert len(results) == 2
    oks = [result for result in results if result.ok]
    assert len(oks) == 1, "exactly one concurrent caller may redeem a single-use code"


def test_start_recovery_concurrent_calls_do_not_collide_on_the_tmp_staging_file() -> None:
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    lock = threading.Lock()

    def _start() -> None:
        barrier.wait()
        try:
            start_recovery(harden_acl=_AclRecorder())
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == [], f"concurrent start_recovery raised: {errors!r}"
    # Whichever call's code ended up on disk last must still be a
    # well-formed, currently-redeemable challenge -- not a file half-written
    # by one thread and clobbered mid-write by the other.
    code = _read_code()
    assert len(code) == CODE_LENGTH
    assert complete_recovery(code).ok is True
