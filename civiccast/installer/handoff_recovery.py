# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""W-2: in-product recovery for a lost or expired setup-handoff URL.

BACKGROUND. First-run setup mutations (``/api/setup/*``) are gated on the
installer handoff nonce (``X-CivicCast-Setup-Nonce``,
``civiccast.native.setup_nonce`` / ``installer.router._require_local_setup_
mutation``). If an operator's browser never received that nonce -- a closed
tab, a bookmark from a previous session, a second workstation -- the console
dead-ends: ``SetupScreen.tsx``'s ``isSetupHandoffError`` branch can only tell
them to run the installer's ``--civiccast-restore-setup-handoff`` command
line switch. That is a real fix, but it is not IN-PRODUCT: it requires a
terminal, the exact install path, and comfort with command-line flags -- not
reasonable to ask of the clerk who is the actual first-run operator at most
stations. GauntletGate finding W-2 is this gap.

TRUST MODEL. The nonce proves "this person controls the installer/admin
context of this box." Recovery must prove the SAME thing and must not open a
new remote path (``civiccast.installer.router``'s setup surface stays
loopback-only). The mechanism here is a disposable, single-use CHALLENGE
FILE: :func:`start_recovery` writes an unambiguous 8-character code to
``code.txt`` inside :func:`recovery_dir`, and hardens that directory with the
same "SYSTEM + Administrators only" protected DACL every other product-owned
ProgramData object in this codebase uses
(:mod:`civiccast.native.pgdata_acl`, :mod:`civiccast.native.provision.
journal`'s ``_harden_state_root_acl``). Reading the file therefore requires
either being SYSTEM or opening it from an elevated (Administrator) context --
Windows prompts for that itself. Whoever can read it and type the code back
into :func:`complete_recovery` has proven exactly the fact the nonce already
proves, so a successful redemption hands back the SAME setup nonce
(``CIVICCAST_SETUP_NONCE``) rather than minting a second kind of setup
credential (``civiccast.installer.router``'s ``/handoff-recovery/complete``
route reads the env var and returns it -- this module never sees or stores
the nonce itself).

WHY NOT alternatives considered and rejected (recorded here, not only in the
punchlist spec, so a future reader does not have to go find the spec to
learn why): re-displaying the HKLM nonce in-product would broadcast the real,
long-lived credential to any local process that can screenshot the operator
console; relaunching the installer requires the installer binary to still
exist on disk and teaches a workflow this module does not control. The
challenge file proves admin-on-box with a disposable secret that expires in
15 minutes and burns after 5 wrong guesses -- equivalent trust to the nonce,
zero new remote surface, nothing long-lived to leak.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

#: Directory name under ``%ProgramData%\CivicCast`` (or
#: ``CIVICCAST_SETUP_RECOVERY_DIR`` when overridden for tests).
_RECOVERY_DIR_NAME = "setup-recovery"

#: The plaintext code lives here -- what the operator console tells an
#: administrator to open.
CODE_FILENAME = "code.txt"

#: Verification state (salted hash, TTL, attempt counter) lives in a SEPARATE
#: file so the file an administrator is told to open never needs to hold
#: anything but the one thing they are asked to type back: the code itself.
_STATE_FILENAME = "state.json"

#: 8 characters, drawn from an alphabet with the classic look-alikes removed
#: (0/O, 1/I/L) so a code read off a screen or a low-resolution remote
#: desktop session is never ambiguous to retype. ~5 bits/char * 8 = ~41 bits
#: of entropy -- far more than the 5-guess burn budget below needs, but the
#: length is also what a person reads aloud or types in one glance.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8

#: 15 minutes, per the W-2 design spec.
CODE_TTL_SECONDS = 15 * 60

#: Wrong-guess budget before the code is burned outright (a further
#: :func:`start_recovery` call is required to try again).
MAX_ATTEMPTS = 5

FailureReason = Literal["no-code", "burned", "expired", "wrong"]

#: Injectable seam matching the shape of
#: :func:`civiccast.native.pgdata_acl.normalize_pgdata_acl`'s own
#: ``apply_dacl`` parameter -- production default is
#: :func:`_harden_recovery_dir_acl`; tests substitute a recording stub so the
#: ACL call is asserted without touching a real Windows security descriptor.
AclApplier = Callable[[Path], None]

#: FastAPI/Starlette runs synchronous route handlers (both
#: ``public_handoff_recovery_start`` and ``public_handoff_recovery_complete``
#: are plain ``def``, not ``async def``) in a worker threadpool, so two
#: requests from the same operator -- two tabs, a double-submit -- can enter
#: :func:`start_recovery` or :func:`complete_recovery` concurrently on
#: DIFFERENT threads of the SAME process (the control-plane child is launched
#: with no ``--workers`` flag, i.e. exactly one process, see
#: ``civiccast.native.supervisor.children``). Without serialization, two
#: concurrent :func:`complete_recovery` calls can both observe
#: ``consumed=False`` before either writes back ``consumed=True`` (a
#: check-then-act race on the "single-use" guarantee) and, independently,
#: both land on the SAME ``<name>.<pid>.tmp`` staging path and clobber or
#: race each other's :func:`_atomic_write`. This lock serializes the whole
#: read-modify-write cycle for both entry points; :func:`_atomic_write` also
#: gets a per-call unique staging filename (mirrors the ``uuid4().hex``
#: convention ``civiccast.installer.service`` already uses for its own
#: atomic writes) as defense in depth against any caller that reaches the
#: filesystem outside this lock.
_RECOVERY_LOCK = threading.Lock()


class HandoffRecoveryError(RuntimeError):
    """The recovery code or its directory ACL could not be written safely.

    Fail-loud, mirroring :class:`civiccast.native.pgdata_acl.PgDataAclError`
    and :class:`civiccast.native.provision.journal.JournalError`: a
    challenge file this module could not actually secure is worse than no
    challenge file, so the router turns this into a 503 rather than quietly
    handing back a code file with the wrong permissions.
    """


def recovery_dir() -> Path:
    """Where the challenge file and its verification state live.

    ``CIVICCAST_SETUP_RECOVERY_DIR`` overrides for tests, the same
    ``CIVICCAST_STATION_STATE_PATH``-style escape hatch
    ``civiccast.installer.station_state.station_state_path`` already uses.
    Production default matches the W-2 spec's literal path,
    ``C:\\ProgramData\\CivicCast\\setup-recovery``, built from ``PROGRAMDATA``
    the same way :mod:`civiccast.native.runtime_cli` and
    :mod:`civiccast.native.provision.__main__` already do, so it tracks a
    relocated ProgramData root instead of hard-coding the letter ``C``.
    """

    configured = os.environ.get("CIVICCAST_SETUP_RECOVERY_DIR")
    if configured:
        return Path(configured).expanduser()
    root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    return root / "CivicCast" / _RECOVERY_DIR_NAME


def code_file_path() -> Path:
    """The exact path the operator console tells an administrator to open."""

    return recovery_dir() / CODE_FILENAME


def _state_path() -> Path:
    return recovery_dir() / _STATE_FILENAME


def _generate_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(CODE_LENGTH))


def _hash_code(code: str, *, salt: str) -> str:
    """Salted HMAC, not raw equality -- matches
    ``civiccast.installer.station_state._hash_token``'s "hash high-entropy
    setup tokens without adding per-request PBKDF2 cost" reasoning: this
    code is already high-entropy and single-use, so a fast keyed hash is
    the right cost, and :func:`complete_recovery` compares the resulting
    digests with :func:`secrets.compare_digest`, never the raw code."""

    return hmac.new(salt.encode("utf-8"), code.encode("utf-8"), hashlib.sha256).hexdigest()


def _atomic_write(path: Path, content: str) -> None:
    # ``uuid4().hex`` (not just ``os.getpid()``) so two threads of this same
    # process writing the same ``path`` concurrently never share a staging
    # file -- see ``_RECOVERY_LOCK`` above for the full race this closes.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(path)


#: SYSTEM + Administrators only, protected (inheritance-blocked) so
#: ``C:\ProgramData``'s inherited, world-readable default DACL
#: (``BUILTIN\Users:(OI)(CI)(RX)``, measured and documented in
#: :mod:`civiccast.native.pgdata_acl`) cannot flow back in. ``OICI`` so both
#: ``code.txt`` and ``state.json`` -- created fresh on every
#: :func:`start_recovery` call -- inherit it automatically without a
#: separate per-file ACL call. Unlike :data:`civiccast.native.pgdata_acl.
#: PGDATA_DACL_SDDL_TEMPLATE` and journal.py's ``_STATE_ROOT_SDDL_TEMPLATE``,
#: this omits the calling process's own SID: those two need it because an
#: unprivileged installing account must read its own freshly-hardened state
#: back later, but the process writing this file is the native control
#: plane itself, which ``civiccast.native.station_runtime`` documents runs
#: "pre-DB under LocalSystem" -- i.e. it already IS the SYSTEM grantee.
_RECOVERY_DIR_SDDL = "D:P(A;OICI;GA;;;SY)(A;OICI;GA;;;BA)"


def _harden_recovery_dir_acl(directory: Path) -> None:
    """Restrict ``directory`` to SYSTEM + Administrators, same house
    convention as :func:`civiccast.native.pgdata_acl.normalize_pgdata_acl`
    and :func:`civiccast.native.provision.journal._harden_state_root_acl`
    (``SetNamedSecurityInfo`` with a protected, inheritable SDDL literal
    naming only the well-known ``SY``/``BA`` aliases -- never a localized
    account name, per the same module's reasoning).

    Windows-only; a no-op on any other platform so this module -- and the
    pure code/TTL/attempt logic around it -- keeps importing and unit-testing
    on Linux, per the house rule in :mod:`civiccast.native.win_probes`
    ("``import civiccast.native.*`` must succeed on Linux even though these
    functions are only ever callable on Windows"). ``pywin32`` is imported
    LAZILY for the same reason.
    """

    if os.name != "nt":  # pragma: no cover - exercised via the injected seam
        return

    import win32security

    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        _RECOVERY_DIR_SDDL, win32security.SDDL_REVISION_1
    )
    win32security.SetNamedSecurityInfo(
        str(directory),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        descriptor.GetSecurityDescriptorDacl(),
        None,
    )


@dataclass(frozen=True)
class RecoveryStartResult:
    """What :func:`start_recovery` hands the router -- never the code."""

    code_file: str
    expires_in: int


def start_recovery(*, harden_acl: AclApplier | None = None) -> RecoveryStartResult:
    """Issue a fresh single-use recovery code and (re)harden its directory.

    Overwrites any code from a previous call: this IS the "regenerate"
    action the SetupScreen's expired-code state offers (the router's 3/hour
    rate limit on this route is what bounds how often a caller may do that,
    not this function). Directory hardening runs on every call, mirroring
    ``civiccast.native.provision.journal.write_journal``'s "idempotent and
    self-healing, not just first creation" convention -- a directory
    provisioned by an older build, or one an operator's own tooling touched,
    is repaired on the very next recovery attempt instead of needing a
    separate remediation step.

    Raises :class:`HandoffRecoveryError` if the directory's ACL could not be
    applied: a challenge file this call could not actually secure to
    Administrators+SYSTEM must never be left in place looking like a working
    recovery path.
    """

    directory = recovery_dir()

    with _RECOVERY_LOCK:
        directory.mkdir(parents=True, exist_ok=True)

        apply_acl = harden_acl if harden_acl is not None else _harden_recovery_dir_acl
        try:
            apply_acl(directory)
        except Exception as exc:
            raise HandoffRecoveryError(
                f"could not restrict {directory} to Administrators and SYSTEM: {exc}"
            ) from exc

        code = _generate_code()
        salt = secrets.token_hex(16)
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=CODE_TTL_SECONDS)
        state = {
            "code_hash": _hash_code(code, salt=salt),
            "salt": salt,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "attempts": 0,
            "consumed": False,
        }

        _atomic_write(code_file_path(), code + "\n")
        _atomic_write(_state_path(), json.dumps(state))

    return RecoveryStartResult(code_file=str(code_file_path()), expires_in=CODE_TTL_SECONDS)


@dataclass(frozen=True)
class RecoveryCompleteResult:
    """Outcome of one :func:`complete_recovery` call.

    ``reason`` exists for tests and for this module's own callers to reason
    about precisely -- ``civiccast.installer.router``'s HTTP handler
    deliberately collapses every ``ok=False`` case to the SAME generic 403
    (the W-2 spec's "no oracle about which check failed"), so this
    distinction never reaches an unauthenticated caller over the wire.
    """

    ok: bool
    reason: FailureReason | Literal["ok"]


def _load_state() -> dict[str, object] | None:
    try:
        raw = json.loads(_state_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict):
        return None
    return raw


def complete_recovery(code: str) -> RecoveryCompleteResult:
    """Redeem ``code`` against the current challenge, single-use and
    constant-time.

    Order of checks, all fail-closed: no active challenge -> ``no-code``;
    already consumed (a replay) -> ``wrong``; 5 prior wrong guesses ->
    ``burned``; TTL elapsed -> ``expired``; hash mismatch -> ``wrong`` (and
    the attempt is recorded). Only an exact, unexpired, not-yet-burned match
    marks the challenge consumed, deletes the plaintext code file (best
    effort -- a failure to delete does not undo the successful redemption,
    since ``consumed`` in the state file already makes the code unusable
    again), and returns ``ok=True``.
    """

    # Whole read-modify-write cycle under one lock: without it, two
    # concurrent callers (two tabs, a double-submit -- see
    # ``_RECOVERY_LOCK``) can both read ``consumed=False`` before either
    # writes back ``consumed=True`` and both redeem the same "single-use"
    # code, or both race ``_atomic_write`` on ``_state_path()``.
    with _RECOVERY_LOCK:
        state = _load_state()
        if state is None:
            return RecoveryCompleteResult(ok=False, reason="no-code")

        if state.get("consumed") is True:
            return RecoveryCompleteResult(ok=False, reason="wrong")

        attempts = int(state.get("attempts") or 0)
        if attempts >= MAX_ATTEMPTS:
            return RecoveryCompleteResult(ok=False, reason="burned")

        try:
            expires_at = datetime.fromisoformat(str(state.get("expires_at")))
        except ValueError:
            return RecoveryCompleteResult(ok=False, reason="no-code")
        if datetime.now(UTC) >= expires_at:
            return RecoveryCompleteResult(ok=False, reason="expired")

        salt = str(state.get("salt") or "")
        expected_hash = str(state.get("code_hash") or "")
        observed_hash = _hash_code(code.strip(), salt=salt)
        if not secrets.compare_digest(observed_hash, expected_hash):
            state["attempts"] = attempts + 1
            _atomic_write(_state_path(), json.dumps(state))
            return RecoveryCompleteResult(ok=False, reason="wrong")

        state["consumed"] = True
        _atomic_write(_state_path(), json.dumps(state))
        with contextlib.suppress(OSError):  # best-effort cleanup only
            code_file_path().unlink(missing_ok=True)
        return RecoveryCompleteResult(ok=True, reason="ok")


__all__ = [
    "CODE_FILENAME",
    "CODE_LENGTH",
    "CODE_TTL_SECONDS",
    "MAX_ATTEMPTS",
    "AclApplier",
    "HandoffRecoveryError",
    "RecoveryCompleteResult",
    "RecoveryStartResult",
    "code_file_path",
    "complete_recovery",
    "recovery_dir",
    "start_recovery",
]
