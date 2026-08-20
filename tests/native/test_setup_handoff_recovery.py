# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the native station's operator-console handoff recovery path.

THE DEFECT THESE PIN (native beta 1.0.0-beta.1-rc1, TESTER3 2026-08-13):

Every ``/api/setup/*`` route -- including ``POST /api/setup/login``, the only
way to obtain a staff token on a native station -- is gated on the installer
handoff nonce. That nonce lives in ``HKLM\\SOFTWARE\\CivicCast\\Native``,
ACL'd to SYSTEM + Administrators only
(``native_service_registration.rs``'s ``SYSTEM_ADMIN_ONLY_SDDL``). The setup
app that is supposed to hand it to the operator ships ``asInvoker``
(``apps/installer/src-tauri/build.rs``), so its registry read fails and its
"Open operator console" button opens ``http://127.0.0.1:8000/operator/`` with
no nonce at all. The console then answers "Could not read setup state" and
tells the operator to reopen the setup app -- the control that just failed.

Before this change there was NO supported way to recover the handoff without
reinstalling, and no way for any caller to even tell "you are not elevated"
apart from "this station was never provisioned".

Platform-independent by construction: every registry interaction goes through
an injected fake, exactly like ``tests/native/test_runtime_cli.py``. This file
has no "win" in its name deliberately -- it must pass on Linux CI too.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from civiccast.native import runtime_cli
from civiccast.native.setup_nonce import (
    NATIVE_REGISTRY_SUBKEY,
    OPERATOR_CONSOLE_URL,
    SETUP_NONCE_VALUE_NAME,
    PersistedSetupNonce,
    build_operator_handoff_url,
    build_setup_handoff_report,
    validate_setup_nonce,
)

runner = CliRunner()

# Inside the shared envelope (16..256, URL-safe alphabet) that
# `validate_setup_nonce`, `main.rs`'s `validated_setup_nonce`, and
# `native_service_registration.rs`'s `validate_setup_nonce_value` all state.
_REAL_SHAPED_NONCE = "Zx9-_aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789ab"


def _patch_status(monkeypatch: pytest.MonkeyPatch, status: PersistedSetupNonce) -> None:
    monkeypatch.setattr(runtime_cli, "read_persisted_setup_nonce_status", lambda: status)


# ---------------------------------------------------------------------------
# The URL itself
# ---------------------------------------------------------------------------


def test_handoff_url_matches_the_shape_the_installer_button_produces() -> None:
    """`main.rs`'s `resolved_operator_console_url` builds exactly this.

    A URL that differs by even a query-parameter name is one the operator SPA
    (`portal-operator/src/api/client.ts`'s `runtimeSetupNonce`, which reads
    `?nonce=` from `window.location.search`) would ignore, leaving the
    operator with the same 403 they started with.
    """

    assert (
        build_operator_handoff_url(_REAL_SHAPED_NONCE)
        == f"{OPERATOR_CONSOLE_URL}?nonce={_REAL_SHAPED_NONCE}"
    )


def test_handoff_url_is_not_built_from_a_nonce_outside_the_shared_envelope() -> None:
    """Fails CLOSED. A value the server would reject must never be handed to
    an operator as if it were a working handoff -- that turns a clear "not
    elevated" failure into an unexplained 403 at the console."""

    for outside_envelope in ("", "tooshort", "has spaces in it 1234", "semi;colon;value;1234"):
        assert validate_setup_nonce(outside_envelope) is None
        with pytest.raises(ValueError):
            build_operator_handoff_url(outside_envelope)


# ---------------------------------------------------------------------------
# The report decision (pure -- no registry, no Windows, no elevation)
# ---------------------------------------------------------------------------


def test_readable_nonce_reports_the_url_and_succeeds() -> None:
    report = build_setup_handoff_report(PersistedSetupNonce(nonce=_REAL_SHAPED_NONCE, reason="ok"))

    assert report.url == f"{OPERATOR_CONSOLE_URL}?nonce={_REAL_SHAPED_NONCE}"
    assert report.exit_code == 0


def test_access_denied_tells_the_operator_to_run_elevated_and_leaks_no_nonce() -> None:
    """The load-bearing branch.

    "Not elevated" is the ONLY failure an operator can act on, and it is the
    one the shipped setup app silently swallows. The message must name the
    action (run as administrator) and the key, and must not disclose or
    invent a nonce.
    """

    report = build_setup_handoff_report(PersistedSetupNonce(nonce=None, reason="access-denied"))

    assert report.url is None
    assert report.exit_code == 2
    assert "Run as administrator" in report.message
    assert NATIVE_REGISTRY_SUBKEY in report.message
    assert SETUP_NONCE_VALUE_NAME in report.message
    assert "nonce=" not in report.message


def test_missing_and_access_denied_are_not_the_same_answer() -> None:
    """The distinction this whole change exists to make.

    `read_persisted_setup_nonce` collapsed both into `None`, so no caller --
    including the installer app -- could tell "you are not elevated" from
    "this station was never provisioned". Those have opposite next steps.
    """

    denied = build_setup_handoff_report(PersistedSetupNonce(nonce=None, reason="access-denied"))
    missing = build_setup_handoff_report(PersistedSetupNonce(nonce=None, reason="missing"))

    assert denied.message != missing.message
    assert "Run as administrator" not in missing.message
    assert "provision" in missing.message.lower()
    assert missing.url is None and missing.exit_code == 2


def test_invalid_persisted_value_is_treated_as_absent_not_trusted() -> None:
    report = build_setup_handoff_report(PersistedSetupNonce(nonce=None, reason="invalid"))

    assert report.url is None
    assert report.exit_code == 2


def test_non_windows_platform_reports_that_rather_than_a_bare_failure() -> None:
    report = build_setup_handoff_report(PersistedSetupNonce(nonce=None, reason="not-windows"))

    assert report.url is None
    assert report.exit_code == 2


# ---------------------------------------------------------------------------
# The supported command an operator can actually run
# ---------------------------------------------------------------------------


def test_cli_prints_the_handoff_url_when_the_nonce_is_readable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`civiccast runtime setup-handoff` is the supported recovery path.

    Fails on base: no such command existed anywhere in the product -- not in
    the Typer CLI, not as a `--civiccast-*` installer subcommand, not as a
    script, and not as a documented procedure.
    """

    _patch_status(monkeypatch, PersistedSetupNonce(nonce=_REAL_SHAPED_NONCE, reason="ok"))

    result = runner.invoke(runtime_cli.runtime_app, ["setup-handoff"])

    assert result.exit_code == 0
    assert f"{OPERATOR_CONSOLE_URL}?nonce={_REAL_SHAPED_NONCE}" in result.stdout


def test_cli_json_mode_is_machine_readable_and_null_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_status(monkeypatch, PersistedSetupNonce(nonce=_REAL_SHAPED_NONCE, reason="ok"))
    ok = json.loads(runner.invoke(runtime_cli.runtime_app, ["setup-handoff", "--json"]).stdout)
    assert ok["ok"] is True
    assert ok["url"] == f"{OPERATOR_CONSOLE_URL}?nonce={_REAL_SHAPED_NONCE}"

    _patch_status(monkeypatch, PersistedSetupNonce(nonce=None, reason="access-denied"))
    denied_result = runner.invoke(runtime_cli.runtime_app, ["setup-handoff", "--json"])
    denied = json.loads(denied_result.stdout)
    assert denied_result.exit_code == 2
    assert denied["ok"] is False
    assert denied["url"] is None


def test_cli_exits_nonzero_and_prints_no_url_when_not_elevated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-elevated caller must get a refusal, never a nonce.

    This is the security property under test: the command is a READ of an
    admin-only key, not a bypass around it.
    """

    _patch_status(monkeypatch, PersistedSetupNonce(nonce=None, reason="access-denied"))

    result = runner.invoke(runtime_cli.runtime_app, ["setup-handoff"])

    assert result.exit_code == 2
    assert "nonce=" not in result.stdout
    assert "Run as administrator" in result.stdout


def test_setup_handoff_is_registered_on_the_runtime_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reachable as `civiccast runtime setup-handoff` -- `civiccast/cli.py`
    already does `app.add_typer(runtime_app)`, so registering it here is what
    puts it on the operator-facing CLI surface."""

    _patch_status(monkeypatch, PersistedSetupNonce(nonce=None, reason="missing"))
    registered = {command.name for command in runtime_cli.runtime_app.registered_commands}

    assert "setup-handoff" in registered
