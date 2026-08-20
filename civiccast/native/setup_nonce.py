# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The native station's installer-handoff setup nonce.

``civiccast.installer.router`` gates every ``/api/setup/*`` mutation on
``CIVICCAST_SETUP_NONCE`` matching the ``X-CivicCast-Setup-Nonce`` header
(``_require_local_setup_mutation`` / ``_require_local_setup_request``, both
via ``hmac.compare_digest``). The WSL product produced that value in
``headless-bootstrap.ps1`` and wrote it into the distro's environment file;
the NATIVE station had no equivalent anywhere, so its control plane started
with no nonce, every setup mutation answered 403, and first-run setup could
not be completed at all.

This module owns the three pieces the native lane needs, and nothing else:

* :func:`generate_setup_nonce` -- called ONCE per provisioning run
  (``civiccast.native.provision.__main__``), which hands the value to the
  elevated Rust installer over the same stdout marker-line convention the
  resolved ``DatabaseUrl`` already uses, so it never appears on any argv.
* :data:`SETUP_NONCE_VALUE_NAME` under :data:`NATIVE_REGISTRY_SUBKEY` -- where
  the Rust side persists it, in the SAME ACL-hardened
  ``HKLM\\SOFTWARE\\CivicCast\\Native`` key as ``DatabaseUrl``
  (``native_service_registration.rs``'s ``write_value_to_key`` with
  ``SYSTEM_ADMIN_ONLY_SDDL`` -- SYSTEM + Administrators only, inheritance
  disabled). The nonce authorizes creating the first administrator, so it gets
  the same protection as the database credential, not a weaker one.
* :func:`read_persisted_setup_nonce` -- how the LocalSystem supervisor reads it
  back when building the control plane child's environment
  (``civiccast.native.station_runtime``).

:func:`validate_setup_nonce` mirrors the Rust installer's own
``validated_setup_nonce`` envelope (``main.rs``) exactly, so a value this
module produces or accepts always survives the other end's check and vice
versa. Neither side imports the other; both sides state the same rule and are
tested against it.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Literal

#: 256 bits, the same budget ``provision.__main__.generate_database_password``
#: uses. ``secrets.token_urlsafe`` draws from the URL-safe base64 alphabet
#: (A-Z a-z 0-9 - _), which needs no escaping in the query string the
#: installer's handoff URL puts it in and no escaping in the registry.
_SETUP_NONCE_ENTROPY_BYTES = 32

#: The registry subkey (under ``HKEY_LOCAL_MACHINE``) shared with
#: ``DatabaseUrl``/``InstalledVersion`` -- the literal string
#: ``native_service_registration.rs``'s ``DATABASE_URL_KEY`` and
#: ``nsis-hooks-bootstrap.nsh``'s ``ReadRegStr`` both use.
NATIVE_REGISTRY_SUBKEY = r"SOFTWARE\CivicCast\Native"

#: The value name under :data:`NATIVE_REGISTRY_SUBKEY`.
SETUP_NONCE_VALUE_NAME = "SetupNonce"

#: Envelope shared with the Rust installer's ``validated_setup_nonce``.
_MIN_NONCE_LENGTH = 16
_MAX_NONCE_LENGTH = 256
_ALLOWED_NONCE_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)

#: The local operator console the handoff URL points at. Stated here as well
#: as in ``main.rs`` (``OPERATOR_CONSOLE_URL``) on purpose: neither side
#: imports the other, so -- exactly like the nonce envelope above -- both
#: sides state the same rule and are tested against it. The control plane's
#: own port default is ``civiccast.native.supervisor.core.CONTROL_PLANE_PORT``.
OPERATOR_CONSOLE_URL = "http://127.0.0.1:8000/operator/"

#: Why :func:`read_persisted_setup_nonce_status` could not return a nonce.
#:
#: ``access-denied`` is the one an operator can act on, and it is the whole
#: reason this distinction exists: ``NATIVE_REGISTRY_SUBKEY`` is ACL'd to
#: SYSTEM + Administrators only (``native_service_registration.rs``'s
#: ``SYSTEM_ADMIN_ONLY_SDDL``), so a non-elevated process -- including one
#: started by an administrator under UAC's filtered token -- cannot read it.
#: Collapsing that into the same "no nonce" answer as "this station was never
#: provisioned" is what leaves an operator with no next step.
SetupNonceReadReason = Literal[
    "ok",
    "not-windows",
    "access-denied",
    "missing",
    "invalid",
]


@dataclass(frozen=True)
class PersistedSetupNonce:
    """The persisted nonce, or a named reason it could not be read."""

    nonce: str | None
    reason: SetupNonceReadReason


@dataclass(frozen=True)
class SetupHandoffReport:
    """What to tell an operator who asked for the handoff URL, and an exit code.

    Pure data. :func:`build_setup_handoff_report` decides it from a
    :class:`PersistedSetupNonce` alone, so every branch is testable without a
    registry, without Windows, and without elevation.
    """

    url: str | None
    message: str
    exit_code: int


def build_operator_handoff_url(
    nonce: str,
    *,
    console_url: str = OPERATOR_CONSOLE_URL,
) -> str:
    """The nonce-bearing operator-console URL for ``nonce``.

    Byte-for-byte the shape ``main.rs``'s ``resolved_operator_console_url``
    builds (``{OPERATOR_CONSOLE_URL}?nonce={nonce}``), so a URL produced here
    is indistinguishable from one the installer's own button produces. The
    operator SPA reads it from ``window.location.search`` (see
    ``portal-operator/src/api/client.ts``'s ``runtimeSetupNonce``).

    The nonce alphabet is URL-safe by construction (:func:`generate_setup_nonce`
    and :func:`validate_setup_nonce`), so no escaping is applied or needed --
    escaping here would silently produce a value the server's
    ``hmac.compare_digest`` would reject.
    """

    validated = validate_setup_nonce(nonce)
    if validated is None:
        raise ValueError(
            "Refusing to build a handoff URL from a nonce outside the shared envelope."
        )
    return f"{console_url}?nonce={validated}"


def build_setup_handoff_report(
    status: PersistedSetupNonce,
    *,
    console_url: str = OPERATOR_CONSOLE_URL,
) -> SetupHandoffReport:
    """Turn a read attempt into an operator-facing answer plus an exit code.

    Fails CLOSED in the only way that matters: a report with ``url=None``
    never invents, guesses, or partially discloses a nonce. Every non-``ok``
    branch names the next real action instead of repeating the circular
    "reopen the installer" advice that sends an operator back to the control
    that just failed.
    """

    if status.reason == "ok" and status.nonce:
        return SetupHandoffReport(
            url=build_operator_handoff_url(status.nonce, console_url=console_url),
            message=(
                "Open this URL in a browser on this computer to reach first-run setup "
                "and station sign-in. Treat it as a password: it authorizes creating "
                "the first administrator. Do not paste it into a screenshot, a ticket, "
                "or a chat message."
            ),
            exit_code=0,
        )
    if status.reason == "access-denied":
        return SetupHandoffReport(
            url=None,
            message=(
                f"CivicCast could not read HKLM\\{NATIVE_REGISTRY_SUBKEY}\\"
                f"{SETUP_NONCE_VALUE_NAME}. That key is restricted to SYSTEM and "
                "Administrators, so this command must run from a command prompt "
                "opened with 'Run as administrator'. Reopen an elevated prompt and "
                "run this command again."
            ),
            exit_code=2,
        )
    if status.reason == "not-windows":
        return SetupHandoffReport(
            url=None,
            message=(
                "The operator handoff is a native Windows station's installer "
                "handoff; there is nothing to read on this platform."
            ),
            exit_code=2,
        )
    if status.reason == "invalid":
        return SetupHandoffReport(
            url=None,
            message=(
                f"HKLM\\{NATIVE_REGISTRY_SUBKEY}\\{SETUP_NONCE_VALUE_NAME} holds a "
                "value that is not a valid setup nonce, so it is being treated as "
                "absent rather than trusted. Repair or reinstall CivicCast (Native) "
                "to re-provision the station's handoff."
            ),
            exit_code=2,
        )
    return SetupHandoffReport(
        url=None,
        message=(
            f"No setup handoff is recorded at HKLM\\{NATIVE_REGISTRY_SUBKEY}\\"
            f"{SETUP_NONCE_VALUE_NAME}. Either this computer is not a provisioned "
            "CivicCast (Native) station, or provisioning did not finish. Check "
            "%ProgramData%\\CivicCast\\provision for the provisioning journal."
        ),
        exit_code=2,
    )


def generate_setup_nonce() -> str:
    """A cryptographically random installer-handoff nonce. No I/O."""

    return secrets.token_urlsafe(_SETUP_NONCE_ENTROPY_BYTES)


def validate_setup_nonce(value: str | None) -> str | None:
    """The trimmed nonce if it is inside the shared envelope, else ``None``.

    Fails CLOSED on anything unexpected. A nonce is an authorization token:
    accepting a short, empty, or punctuation-bearing value here would either
    weaken the gate or smuggle characters into the handoff URL's query string.
    """

    if value is None:
        return None
    nonce = value.strip()
    if not _MIN_NONCE_LENGTH <= len(nonce) <= _MAX_NONCE_LENGTH:
        return None
    if not set(nonce) <= _ALLOWED_NONCE_CHARACTERS:
        return None
    return nonce


def read_persisted_setup_nonce() -> str | None:
    """Read the nonce the installer persisted, or ``None``.

    ``None`` covers every legitimate absence -- a station provisioned by a
    build from before this existed, a non-Windows interpreter, a key the
    caller cannot read -- and callers must degrade rather than invent a value:
    an absent nonce means setup mutations stay refused, which is the correct
    fail-closed outcome, whereas a fabricated one would be a guessable
    credential.

    ``winreg`` is imported lazily inside the function, the same convention
    ``civiccast.native.runtime_cli`` uses, so this module imports cleanly on a
    non-Windows interpreter.
    """

    return read_persisted_setup_nonce_status().nonce


def read_persisted_setup_nonce_status() -> PersistedSetupNonce:
    """Read the nonce AND why, when there isn't one.

    Same read as :func:`read_persisted_setup_nonce` (which is now a thin
    wrapper over this and keeps its exact contract), but it distinguishes
    ``access-denied`` -- the case an operator can fix by re-running from an
    elevated prompt -- from ``missing`` and ``invalid``, which they cannot.
    Every branch still degrades to "no nonce": nothing here can invent one.

    ``winreg`` is imported lazily inside the function, the same convention
    ``civiccast.native.runtime_cli`` uses, so this module imports cleanly on a
    non-Windows interpreter.
    """

    try:
        import winreg
    except ImportError:  # pragma: no cover - non-Windows interpreter
        return PersistedSetupNonce(nonce=None, reason="not-windows")
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            NATIVE_REGISTRY_SUBKEY,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_WOW64_64KEY,
        ) as key:
            value, value_type = winreg.QueryValueEx(key, SETUP_NONCE_VALUE_NAME)
    except PermissionError:
        # ERROR_ACCESS_DENIED on the ACL-hardened key: the caller is not
        # elevated. This is the whole reason this function exists.
        return PersistedSetupNonce(nonce=None, reason="access-denied")
    except FileNotFoundError:
        return PersistedSetupNonce(nonce=None, reason="missing")
    except OSError as error:
        # winreg raises bare OSError for some win32 codes rather than one of
        # the mapped subclasses above; ERROR_ACCESS_DENIED (5) is the one that
        # changes the operator's next step, so recover it from winerror.
        if getattr(error, "winerror", None) == 5:
            return PersistedSetupNonce(nonce=None, reason="access-denied")
        return PersistedSetupNonce(nonce=None, reason="missing")
    if value_type != winreg.REG_SZ or not isinstance(value, str):
        return PersistedSetupNonce(nonce=None, reason="invalid")
    nonce = validate_setup_nonce(value)
    if nonce is None:
        return PersistedSetupNonce(nonce=None, reason="invalid")
    return PersistedSetupNonce(nonce=nonce, reason="ok")


__all__ = [
    "NATIVE_REGISTRY_SUBKEY",
    "OPERATOR_CONSOLE_URL",
    "SETUP_NONCE_VALUE_NAME",
    "PersistedSetupNonce",
    "SetupHandoffReport",
    "SetupNonceReadReason",
    "build_operator_handoff_url",
    "build_setup_handoff_report",
    "generate_setup_nonce",
    "read_persisted_setup_nonce",
    "read_persisted_setup_nonce_status",
    "validate_setup_nonce",
]
