# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CLI contract tests for ``python -m civiccast.native.upgrade``.

Covers the argument surface the NSIS hook set depends on and the terminal-phase
-> exit-code mapping. The refusal path is exercised end-to-end because it
returns BEFORE any service-control seam is needed; the live-upgrade paths need
the WP-4 service-control wiring (SCM + control pipe + live Postgres), so without
that real infra the CLI must fail LOUD (never silently no-op). The seam LOGIC
itself is proven in ``tests/native/test_upgrade_service_control.py``.
"""

from __future__ import annotations

import os

import pytest

from civiccast.native.upgrade import __main__ as upgrade_main
from civiccast.native.upgrade.__main__ import build_arg_parser, main
from civiccast.native.upgrade.models import UpgradePhase
from civiccast.native.upgrade.orchestrator import RECOVERY_DOC_NAME  # noqa: F401 - import smoke

_WINDOWS_PATH_TEST = pytest.mark.skipif(
    os.name != "nt", reason="requires native Windows path semantics"
)


@pytest.fixture(autouse=True)
def _installed_product(monkeypatch: pytest.MonkeyPatch) -> None:
    """Put every test in this file on the UPGRADE route.

    Chain K/K2 added a routing decision ahead of the engine: with no installed
    product (no ``CivicCastSupervisor`` in the SCM -- the state of any dev or
    CI machine) the CLI now correctly returns the FRESH_INSTALL code and never
    enters the D3 sequence. That is the whole point of the fix, and it is
    proven in ``tests/native/test_upgrade_routing.py``. THIS file's subject is
    what the engine does once the route says upgrade, so it declares that
    precondition instead of accidentally testing the router.
    """

    monkeypatch.setattr(upgrade_main, "installed_product_probe", lambda: True)


def _base_args(tmp_path) -> list[str]:
    return [
        "--old-version",
        "1.0",
        "--new-version",
        "1.1",
        "--install-root",
        str(tmp_path / "install"),
        "--state-root",
        str(tmp_path / "state"),
        "--database-url",
        "postgresql://u@localhost/db",
        "--owner-run-id",
        "run-1",
        "--payload-source",
        str(tmp_path / "payload"),
    ]


def test_parser_requires_core_args() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_parser_accepts_full_arg_set(tmp_path) -> None:
    args = build_arg_parser().parse_args(_base_args(tmp_path))
    assert args.new_version == "1.1"
    assert args.migration_non_restorable is False
    assert args.operator_ack is None


def test_refused_non_restorable_maps_to_exit_30(tmp_path) -> None:
    # Refusal returns before any service-control seam is resolved, so the CLI
    # runs end-to-end and yields exit code 30.
    code = main([*_base_args(tmp_path), "--migration-non-restorable"])
    assert code == 30


def test_service_control_seams_resolve_to_real_callables(tmp_path) -> None:
    # WP-4 wired the three service-control seams to real production callables.
    # Resolving them is inert (no Win32/Postgres); each is a distinct callable.
    # Invoking them would cross the real SCM/pipe/pg boundary (the WP-5 live
    # matrix), so this only asserts resolution, not invocation.
    from civiccast.native.upgrade.__main__ import _resolve_service_control_seams
    from civiccast.native.upgrade.models import UpgradeContext

    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url="postgresql://u@localhost/db",
        owner_run_id="run-1",
    )
    drain, health, stop = _resolve_service_control_seams(context)
    assert callable(drain) and callable(health) and callable(stop)
    assert drain is not health and health is not stop


def test_live_upgrade_path_never_silently_noops(tmp_path, capsys) -> None:
    # A live (restorable) upgrade needs real infra (a DB driver + the WP-5
    # service-control wiring). Without it the CLI must FAIL LOUD, never return a
    # success/no-op exit code. Any infra fault (missing driver, unwired seam)
    # qualifies -- the property under test is "does not silently succeed".
    # Since the exit-contract wrapper (Sandbox row-1 fix), loud failure is
    # expressed as contract exit 40 with the traceback on stderr, not as an
    # exception escaping the CLI.
    code = main(_base_args(tmp_path))
    assert code == 40, (
        "live upgrade path must fail loud (contract exit 40) without real "
        f"infra, not silently no-op (got {code})"
    )
    err = capsys.readouterr().err
    assert "Traceback" in err, "the loud failure must keep the full traceback on stderr"


def test_exit_code_table_covers_every_terminal_phase() -> None:
    from civiccast.native.upgrade.__main__ import _EXIT_CODES

    terminal = {p for p in UpgradePhase if p.is_terminal}
    assert set(_EXIT_CODES) == terminal


def test_uncaught_engine_exception_maps_to_contract_exit_40(tmp_path, monkeypatch, capsys) -> None:
    # Sandbox matrix row 1 (2026-07-30): an empty --database-url made the
    # engine crash with an uncaught SQLAlchemy ArgumentError, escaping as the
    # interpreter's exit 1 -- outside the documented 0/10/20/30/40 contract.
    # ANY unexpected exception must map to 40, with the traceback preserved
    # on stderr for the installer log.
    import civiccast.native.upgrade.__main__ as cli

    def _boom(plan, context, seams):
        raise RuntimeError("engine exploded mid-flight")

    monkeypatch.setattr(cli, "run_upgrade", _boom)
    code = cli.main(_base_args(tmp_path))
    assert code == 40
    err = capsys.readouterr().err
    assert "engine exploded mid-flight" in err
    assert "upgrade outcome: unexpected fault" in err


def test_engine_log_created_before_run_upgrade_ever_called(tmp_path, monkeypatch) -> None:
    """beta BLOCKER #51 (Defect B): the durable tee log must exist BEFORE any
    DB touch, so even a crash in seam assembly (before run_upgrade) leaves
    evidence. Monkeypatch run_upgrade to prove-by-construction: assert the
    log file already exists the instant run_upgrade would be called, without
    letting run_upgrade itself run (which would need real infra)."""

    import civiccast.native.upgrade.__main__ as cli

    seen_log_exists: list[bool] = []

    def _spy(plan, context, seams):
        seen_log_exists.append((tmp_path / "state" / cli.ENGINE_LOG_FILENAME).exists())
        raise RuntimeError("stop before real orchestration")

    monkeypatch.setattr(cli, "run_upgrade", _spy)
    cli.main(_base_args(tmp_path))

    assert seen_log_exists == [True]


def test_engine_log_path_is_sibling_to_the_journal(tmp_path) -> None:
    from civiccast.native.upgrade import journal as journal_mod
    from civiccast.native.upgrade.__main__ import engine_log_path

    state_root = tmp_path / "state"
    assert engine_log_path(state_root).parent == journal_mod.journal_path(state_root).parent


def test_engine_log_captures_unexpected_exception_traceback(tmp_path, monkeypatch) -> None:
    import civiccast.native.upgrade.__main__ as cli

    def _boom(plan, context, seams):
        raise RuntimeError("engine exploded mid-flight, distinctive-marker-9f3a")

    monkeypatch.setattr(cli, "run_upgrade", _boom)
    code = cli.main(_base_args(tmp_path))
    assert code == 40

    log_text = (tmp_path / "state" / cli.ENGINE_LOG_FILENAME).read_text(encoding="utf-8")
    assert "distinctive-marker-9f3a" in log_text
    assert "Traceback" in log_text
    assert "RuntimeError" in log_text
    assert "upgrade outcome: unexpected fault" in log_text


def test_engine_log_never_contains_the_database_url_value(tmp_path, monkeypatch) -> None:
    """Even if an exception's own message embeds the live database_url (a
    realistic worst case -- e.g. a driver connection-string parse error),
    the durable log file must never carry it. Uses a distinctive password so
    a false negative (matching unrelated text) is not possible."""

    import civiccast.native.upgrade.__main__ as cli

    distinctive_url = "postgresql://civiccast:tr0ub4dor-marker-77e1@127.0.0.1:5432/civiccast"
    args = [
        "--old-version",
        "1.0",
        "--new-version",
        "1.1",
        "--install-root",
        str(tmp_path / "install"),
        "--state-root",
        str(tmp_path / "state"),
        "--database-url",
        distinctive_url,
        "--owner-run-id",
        "run-1",
        "--payload-source",
        str(tmp_path / "payload"),
    ]

    def _boom(plan, context, seams):
        # Worst case: the exception message itself embeds the full URL.
        raise RuntimeError(f"could not connect using {context.database_url}")

    monkeypatch.setattr(cli, "run_upgrade", _boom)
    code = cli.main(args)
    assert code == 40

    log_text = (tmp_path / "state" / cli.ENGINE_LOG_FILENAME).read_text(encoding="utf-8")
    assert "tr0ub4dor-marker-77e1" not in log_text
    assert distinctive_url not in log_text
    # The redaction placeholder should be present instead, proving this is
    # actual redaction, not a passive absence.
    assert "<database-url-redacted>" in log_text


def test_engine_log_records_terminal_phase_on_success_path(tmp_path) -> None:
    # test_refused_non_restorable_maps_to_exit_30 already proves this run
    # completes end-to-end without real infra (refusal returns before any
    # service-control seam is needed).
    import civiccast.native.upgrade.__main__ as cli

    code = cli.main([*_base_args(tmp_path), "--migration-non-restorable"])
    assert code == 30

    log_text = (tmp_path / "state" / cli.ENGINE_LOG_FILENAME).read_text(encoding="utf-8")
    assert "upgrade outcome: refused_non_restorable" in log_text
    assert "upgrade engine starting" in log_text


def test_empty_database_url_exits_40_not_1(tmp_path, capsys) -> None:
    # The row-1 reproduction: same invocation shape the NSIS hook used, empty
    # --database-url. Must exit 40 (unexpected fault), never the bare
    # interpreter exit 1 the fault dialog showed.
    #
    # Chain K/K2: row 1's literal argument pair was rc15 -> rc15, which is now
    # its own route (SAME_VERSION_NO_OP, exit 12 -- there is no migration
    # between a version and itself, so the engine must not run at all, and
    # that outcome is pinned in tests/native/test_upgrade_routing.py). The
    # subject HERE is the empty-credential fault mapping, so this drives a
    # version-CHANGING upgrade, which is the only shape that can still reach
    # the engine with an unusable database URL.
    code = main(
        [
            "--old-version",
            "1.0.0-rc15",
            "--new-version",
            "1.0.0-rc16",
            "--install-root",
            str(tmp_path / "install"),
            "--state-root",
            str(tmp_path / "state"),
            "--database-url",
            "",
            "--owner-run-id",
            "row1-repro",
            "--payload-source",
            str(tmp_path / "payload"),
        ]
    )
    assert code == 40
    assert "upgrade outcome: unexpected fault" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# PostgreSQL client-executable wiring (Sandbox run 22 / run 16 defect)
# ---------------------------------------------------------------------------


def _expected_pg_bin_dir(tmp_path) -> str:
    """The staged server-binaries bin directory D2 extracts and verifies.

    Built as a STRING (backslash-joined), exactly the way
    ``civiccast.native.provision.__main__.resolve_provision_paths`` builds
    ``initdb_path`` -- so this expectation is byte-identical on a Linux test
    runner and on the Windows install host.
    """

    install_root = str(tmp_path / "install")
    return rf"{install_root}\packs\native-server-binaries\payload\bin"


def test_seams_receive_absolute_pg_client_paths_not_bare_names(tmp_path, monkeypatch) -> None:
    """Sandbox run 22 (2026-07-31), the D3 defect this test pins closed.

    The engine aborted at step 3 (BACKUP_VERIFIED) and rolled back on every
    real machine -- journal ``"error": "[WinError 2] The system cannot find
    the file specified"``, history ``interlock_acquired -> writers_drained ->
    rolled_back`` -- because ``main`` called ``build_default_seams`` WITHOUT
    the four ``*_command`` arguments, so ``civiccast.dr.backup`` fell back to
    the bare names ``pg_dump``/``pg_dumpall``/``pg_restore``/``psql`` and
    resolved them through PATH. Those executables ship inside the
    native-server-binaries pack tree; the installer writes no PATH entry, so
    the bare names never resolve.

    Asserts at the ``build_default_seams`` call boundary (the same
    call-boundary style as ``tests/native/test_upgrade_seams.py``): every one
    of the four commands must be the ABSOLUTE staged path, derived from the
    install layout the same way ``pg_ctl.exe`` already is.
    """

    import civiccast.native.upgrade.__main__ as cli

    captured: dict[str, object] = {}
    real_build = cli.build_default_seams

    def _spy(context, **kwargs):
        captured.update(kwargs)
        return real_build(context, **kwargs)

    def _stop(plan, context, seams):
        raise RuntimeError("stop before real orchestration")

    monkeypatch.setattr(cli, "build_default_seams", _spy)
    monkeypatch.setattr(cli, "run_upgrade", _stop)
    cli.main(_base_args(tmp_path))

    bin_dir = _expected_pg_bin_dir(tmp_path)
    assert captured["pg_dump_command"] == [rf"{bin_dir}\pg_dump.exe"]
    assert captured["pg_dumpall_command"] == [rf"{bin_dir}\pg_dumpall.exe"]
    assert captured["pg_restore_command"] == [rf"{bin_dir}\pg_restore.exe"]
    assert captured["psql_command"] == [rf"{bin_dir}\psql.exe"]


@pytest.mark.windows_only
@_WINDOWS_PATH_TEST
def test_resolve_pg_client_commands_is_a_sibling_of_the_pg_ctl_convention(tmp_path) -> None:
    """The resolver must reuse D4 provisioning's single path convention
    (``resolve_provision_paths().initdb_path``'s directory), the same source
    ``derive_pg_lifecycle_paths`` uses for ``pg_ctl.exe`` -- never a second,
    independently invented binary location."""

    from civiccast.native.upgrade.__main__ import (
        _PG_CLIENT_EXECUTABLES,
        _resolve_pg_client_commands,
    )
    from civiccast.native.upgrade.models import UpgradeContext
    from civiccast.native.upgrade.pg_lifecycle import derive_pg_lifecycle_paths

    context = UpgradeContext(
        install_root=str(tmp_path / "install"),
        state_root=str(tmp_path / "state"),
        database_url="postgresql://u@localhost/db",
        owner_run_id="run-1",
    )

    commands = _resolve_pg_client_commands(context)
    bin_dir = _expected_pg_bin_dir(tmp_path)

    assert set(commands) == set(_PG_CLIENT_EXECUTABLES)
    assert all(commands[name] == rf"{bin_dir}\{name}" for name in _PG_CLIENT_EXECUTABLES)
    # Same directory pg_ctl.exe is resolved into, by construction.
    assert derive_pg_lifecycle_paths(context).pg_ctl_path.rsplit("\\", 1)[0] == bin_dir


def test_missing_pg_client_binary_raises_a_step_identifying_error(tmp_path) -> None:
    """Fail LOUD, naming the step and the absolute path -- never a silent
    fall back to the bare name, which is precisely what hid this defect
    across two full sandbox runs."""

    from civiccast.native.upgrade.__main__ import (
        _PG_CLIENT_EXECUTABLES,
        PgClientBinariesMissingError,
        _require_pg_client_binaries,
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    commands = {name: str(bin_dir / name) for name in _PG_CLIENT_EXECUTABLES}
    for name in _PG_CLIENT_EXECUTABLES:
        if name != "pg_restore.exe":
            (bin_dir / name).write_bytes(b"MZ")

    # All four present -> no raise.
    (bin_dir / "pg_restore.exe").write_bytes(b"MZ")
    _require_pg_client_binaries(commands)

    (bin_dir / "pg_restore.exe").unlink()
    with pytest.raises(PgClientBinariesMissingError) as excinfo:
        _require_pg_client_binaries(commands)

    message = str(excinfo.value)
    assert "BACKUP_VERIFIED" in message, "the error must identify the D3 step that needs them"
    assert str(bin_dir / "pg_restore.exe") in message, "the error must name the missing path"
    assert "pg_dump.exe" not in message, "only the MISSING executables may be reported"


def test_backup_seam_is_guarded_so_a_missing_binary_stops_before_the_backup_runs(
    tmp_path,
) -> None:
    """The guard fires at step 3 (where the executables are first needed), so
    a phase-0 refusal (REFUSED_NON_RESTORABLE, exit 30) is still reached on a
    machine whose pack tree is incomplete."""

    from civiccast.native.upgrade.__main__ import (
        _PG_CLIENT_EXECUTABLES,
        PgClientBinariesMissingError,
        _guard_pg_client_binaries,
    )
    from civiccast.native.upgrade.models import UpgradeSeams

    invoked: list[str] = []
    seams = UpgradeSeams(
        acquire_interlock=lambda: None,
        release_interlock=lambda: None,
        drain_and_verify_quiescence=lambda: True,
        backup=lambda backup_dir: invoked.append(backup_dir),  # type: ignore[arg-type,func-returns-value]
        restore_backup=lambda backup: None,
        lay_tree=lambda new_version: "unused",
        flip_junction=lambda target: None,
        read_junction=lambda: None,
        migrate=lambda: None,
        health_gate=lambda: True,
        schema_revision=lambda: None,
        stop_service=lambda: None,
    )
    commands = {name: str(tmp_path / "absent" / name) for name in _PG_CLIENT_EXECUTABLES}

    guarded = _guard_pg_client_binaries(seams, commands)

    # Wrapping is inert -- nothing is checked until the seam is invoked.
    assert guarded.backup is not seams.backup
    assert invoked == []

    with pytest.raises(PgClientBinariesMissingError):
        guarded.backup("some-backup-dir")
    assert invoked == [], "the real backup must not run once the guard has failed"
