# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Upgrade-vs-fresh routing for the D3 engine (chain K/K2).

Live defect, real hardware R7, 2026-08-01 (request 0053b). Preinstall state,
verbatim from the tester's report:

* ``C:\\Program Files\\CivicCast (Native)``: absent
* ``CivicCastSupervisor``: absent
* CivicCast processes: none
* Add/Remove Programs entries: 0
* ``C:\\ProgramData\\CivicCast``: deliberately preserved as uninstall evidence
* ``HKLM\\SOFTWARE\\CivicCast\\...``: preserved

That is a machine with NO installed product and only preserved DATA. The
installer nevertheless entered the upgrade engine, which logged
``old=1.0.0-rc15 new=1.0.0-rc15`` and then failed and rolled back, ending the
install in a dialog telling the operator that "the previously installed
version (1.0.0-rc15) is healthy and still running" -- on a machine where
nothing was installed and nothing was running.

Decided behavior (chain K/K2):

* the upgrade path runs ONLY when a real installed product exists;
* data remnants alone route to a FRESH install that PRESERVES and ADOPTS the
  existing data root, and says so in the install log;
* same-version with a real installed product is a loud no-op, never the
  migration engine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from civiccast.native.supervisor.config import SERVICE_NAME
from civiccast.native.upgrade import __main__ as upgrade_main
from civiccast.native.upgrade import routing
from civiccast.native.upgrade.routing import (
    UpgradeRoute,
    decide_route,
    default_installed_product_probe,
)

_R7_VERSION = "1.0.0-rc15"
_R7_DATABASE_URL = "postgresql://civiccast:secret@127.0.0.1:5432/civiccast"


# ---------------------------------------------------------------------------
# The pure decision
# ---------------------------------------------------------------------------


def test_r7_state_routes_to_fresh_install_not_upgrade(tmp_path: Path) -> None:
    """R7's exact state: remnants present, product absent."""

    state_root = tmp_path / "ProgramData" / "CivicCast" / "upgrade"
    state_root.mkdir(parents=True)

    decision = decide_route(
        old_version=_R7_VERSION,  # the preserved InstalledVersion marker
        new_version=_R7_VERSION,  # the same version being installed again
        database_url=_R7_DATABASE_URL,  # the preserved DatabaseUrl credential
        installed_product=False,  # sc query CivicCastSupervisor -> 1060
        state_root=str(state_root),
    )

    assert decision.route is UpgradeRoute.FRESH_INSTALL


def test_r7_state_reports_the_preserved_data_as_adopted(tmp_path: Path) -> None:
    """A fresh install over preserved data must ADOPT it -- and must say so.

    The preserve-on-uninstall design is deliberate (``native_uninstall.rs``'s
    ``NATIVE_D4_STATE_INVENTORY``: the credential and the cluster are one
    unit). What was missing was the honest statement that the new install is
    taking the old data over rather than starting empty or deleting it.
    """

    state_root = tmp_path / "ProgramData" / "CivicCast" / "upgrade"
    state_root.mkdir(parents=True)

    decision = decide_route(
        old_version=_R7_VERSION,
        new_version=_R7_VERSION,
        database_url=_R7_DATABASE_URL,
        installed_product=False,
        state_root=str(state_root),
    )

    assert decision.data_root_adopted is True
    reason = decision.reason
    assert "preserved and adopted" in reason
    assert "never deleted" in reason
    assert _R7_VERSION in reason, "the reason must name the remnant it found"
    assert str(state_root) in reason, "the reason must name the data root being adopted"
    assert SERVICE_NAME in reason, "the reason must name the signal the decision was made on"


def test_first_ever_install_routes_to_fresh_install_with_no_remnants() -> None:
    """A genuinely pristine machine: fresh, and honest that it found nothing."""

    decision = decide_route(
        old_version=routing.NO_RECORDED_VERSION,
        new_version=_R7_VERSION,
        database_url="",
        installed_product=False,
        state_root=None,
    )

    assert decision.route is UpgradeRoute.FRESH_INSTALL
    assert decision.data_root_adopted is False
    assert "No existing CivicCast data was found" in decision.reason


def test_real_installed_product_with_a_new_version_routes_to_upgrade() -> None:
    """The case the D3 engine exists for -- unchanged by this fix."""

    decision = decide_route(
        old_version=_R7_VERSION,
        new_version="1.0.0-rc16",
        database_url=_R7_DATABASE_URL,
        installed_product=True,
        state_root=None,
    )

    assert decision.route is UpgradeRoute.UPGRADE
    assert "1.0.0-rc16" in decision.reason


def test_real_installed_product_at_the_same_version_is_a_loud_no_op() -> None:
    """X -> X with a real product installed: never the migration engine.

    Repair semantics were not adopted -- D5 repair is not wired into this
    install chain (see ``UpgradeRoute.SAME_VERSION_NO_OP``'s docstring) -- so
    the requirement is that the text is honest about having done nothing.
    """

    decision = decide_route(
        old_version=_R7_VERSION,
        new_version=_R7_VERSION,
        database_url=_R7_DATABASE_URL,
        installed_product=True,
        state_root=None,
    )

    assert decision.route is UpgradeRoute.SAME_VERSION_NO_OP
    assert "no migration between a version and itself" in decision.reason
    assert "did not run" in decision.reason


def test_an_unanswerable_probe_routes_to_fresh_install_and_says_so() -> None:
    """Fail-safe, not fail-silent: an ambiguous SCM answer cannot PROVE a
    product exists, and the two error directions are not symmetric (see
    :func:`decide_route`). The ambiguity must be visible in the log."""

    decision = decide_route(
        old_version=_R7_VERSION,
        new_version="1.0.0-rc16",
        database_url=_R7_DATABASE_URL,
        installed_product=None,
        state_root=None,
    )

    assert decision.route is UpgradeRoute.FRESH_INSTALL
    assert "Could not determine" in decision.reason


@pytest.mark.parametrize(
    ("database_url", "recorded_version"),
    [
        (_R7_DATABASE_URL, routing.NO_RECORDED_VERSION),
        ("", _R7_VERSION),
        (_R7_DATABASE_URL, _R7_VERSION),
    ],
)
def test_no_combination_of_data_remnants_can_select_the_upgrade_route(
    database_url: str, recorded_version: str
) -> None:
    """The heart of the fix: remnants NEVER select the route.

    The old NSIS gate ran the upgrade engine whenever EITHER preserved value
    was present. This pins that no combination of them can, on a machine with
    no installed product.
    """

    decision = decide_route(
        old_version=recorded_version,
        new_version=_R7_VERSION,
        database_url=database_url,
        installed_product=False,
        state_root=None,
    )

    assert decision.route is UpgradeRoute.FRESH_INSTALL


# ---------------------------------------------------------------------------
# The product-existence probe
# ---------------------------------------------------------------------------


def _completed(returncode: int) -> subprocess.CompletedProcess[bytes]:
    return subprocess.CompletedProcess(
        args=["sc.exe"], returncode=returncode, stdout=b"", stderr=b""
    )


@pytest.mark.parametrize(
    ("returncode", "expected"),
    [
        (0, True),  # registered, in any run state
        (1060, False),  # ERROR_SERVICE_DOES_NOT_EXIST -- R7's exact answer
        (5, None),  # access denied: cannot answer
        (1, None),  # anything else: cannot answer
    ],
)
def test_installed_product_probe_classifies_the_documented_sc_query_codes(
    returncode: int, expected: bool | None
) -> None:
    """The probe must distinguish "registered" from "cannot tell" -- the D3
    drain's existing probe folds exit 0 and an error into the same ``None``
    bucket, which is fine for its fail-closed question but would make an
    installed product indistinguishable from an unreadable SCM here."""

    def _runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return _completed(returncode)

    assert default_installed_product_probe(runner=_runner) is expected


@pytest.mark.parametrize("error", [OSError("sc.exe missing"), subprocess.TimeoutExpired("sc", 5)])
def test_installed_product_probe_never_raises(error: Exception) -> None:
    """A probe failure must be an unanswerable route input, not a crash that
    takes the whole install down through the exit-40 fault branch."""

    def _runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        raise error

    assert default_installed_product_probe(runner=_runner) is None


# ---------------------------------------------------------------------------
# End to end through the CLI the NSIS hook actually invokes
# ---------------------------------------------------------------------------


def _r7_argv(tmp_path: Path) -> list[str]:
    return [
        "--old-version",
        _R7_VERSION,
        "--new-version",
        _R7_VERSION,
        "--install-root",
        str(tmp_path / "install"),
        "--state-root",
        str(tmp_path / "state"),
        "--database-url",
        _R7_DATABASE_URL,
        "--owner-run-id",
        "nsis-0x1234",
        "--payload-source",
        str(tmp_path / "install" / "runtime"),
    ]


@pytest.mark.windows_only
def test_r7_state_never_reaches_the_migration_engine_through_the_real_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The RED case, driven through the exact entry point NSIS invokes.

    The product-existence signal is NOT mocked here: this test host has no
    ``CivicCastSupervisor`` registered, which is precisely R7's post-uninstall
    state (``sc.exe query`` -> 1060), so the real probe answers the real
    question. The precondition is asserted rather than assumed, so the proof
    can never go vacuous on a host where the service IS installed.
    """

    if default_installed_product_probe() is not False:
        pytest.skip(
            f"this host has {SERVICE_NAME} registered (or an unreadable SCM); "
            "R7's no-installed-product state cannot be reproduced without mocks here"
        )

    reached: list[str] = []

    def _must_not_run(*args: object, **kwargs: object) -> object:
        reached.append("run_upgrade")
        raise AssertionError("the D3 migration engine ran on a machine with no product")

    monkeypatch.setattr(upgrade_main, "run_upgrade", _must_not_run)

    exit_code = upgrade_main.main(_r7_argv(tmp_path))

    assert reached == [], (
        "the D3 migration engine was entered on R7's state: no installed product, "
        "only preserved data"
    )
    assert exit_code == upgrade_main._ROUTE_EXIT_CODES[UpgradeRoute.FRESH_INSTALL]


def test_cli_records_the_route_and_the_adoption_in_the_durable_engine_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The install log is the only artifact a support case has. The route and
    the data-adoption statement must both be in it."""

    monkeypatch.setattr(upgrade_main, "installed_product_probe", lambda: False)

    exit_code = upgrade_main.main(_r7_argv(tmp_path))

    assert exit_code == 11
    log_text = upgrade_main.engine_log_path(str(tmp_path / "state")).read_text(encoding="utf-8")
    assert f"route: {UpgradeRoute.FRESH_INSTALL.value}" in log_text
    assert "preserved and adopted" in log_text
    assert _R7_DATABASE_URL not in log_text, "the engine log must never carry the credential"


def test_cli_same_version_with_a_real_product_returns_the_no_op_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(upgrade_main, "installed_product_probe", lambda: True)

    def _must_not_run(*args: object, **kwargs: object) -> object:
        raise AssertionError("the D3 migration engine ran for a same-version install")

    monkeypatch.setattr(upgrade_main, "run_upgrade", _must_not_run)

    assert upgrade_main.main(_r7_argv(tmp_path)) == 12


def test_cli_still_runs_the_engine_for_a_real_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The routing fix must not disable the engine it is protecting."""

    monkeypatch.setattr(upgrade_main, "installed_product_probe", lambda: True)

    ran: list[str] = []

    class _Outcome:
        phase = upgrade_main.UpgradePhase.COMPLETE

    def _record(*args: object, **kwargs: object) -> _Outcome:
        ran.append("run_upgrade")
        return _Outcome()

    monkeypatch.setattr(upgrade_main, "run_upgrade", _record)
    monkeypatch.setattr(
        upgrade_main,
        "_resolve_pg_client_commands",
        lambda context: dict.fromkeys(upgrade_main._PG_CLIENT_EXECUTABLES, "pg.exe"),
    )

    argv = _r7_argv(tmp_path)
    argv[argv.index("--new-version") + 1] = "1.0.0-rc16"

    assert upgrade_main.main(argv) == 0
    assert ran == ["run_upgrade"]


def test_route_exit_codes_do_not_collide_with_the_phase_exit_codes() -> None:
    """11/12 must stay distinguishable from 0/10/20/30/40 -- the NSIS ladder
    branches on the number alone."""

    phase_codes = set(upgrade_main._EXIT_CODES.values()) | {40}
    route_codes = set(upgrade_main._ROUTE_EXIT_CODES.values())

    assert phase_codes.isdisjoint(route_codes)
    assert len(route_codes) == len(upgrade_main._ROUTE_EXIT_CODES)
