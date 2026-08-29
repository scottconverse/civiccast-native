# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CLI contract tests for ``python -m civiccast.native.provision`` (WP2
provision-execution wiring).

Covers ONLY pure logic and the two main() paths that return BEFORE touching
any real seam (no-op reuse, fail-loud repair-needed) -- the SAME boundary
``tests/native/test_upgrade_cli.py`` draws for the upgrade engine's CLI
("the refusal path is exercised end-to-end because it returns BEFORE any
service-control seam is needed"). The RUN path (fresh password generation +
``run_provision`` against the real ``build_default_seams_for`` bundle) is
proven at the level of its individual pure builders here (path derivation,
plan/context assembly, password generation, handoff formatting); actually
invoking it would need a real ``initdb`` binary, which the HARD RULE for
this task forbids in the unit suite -- that proof belongs to the WP2/WP5
live lifecycle matrix, same as the rest of ``civiccast.native.provision``.

HARD RULE: no real PostgreSQL process is ever spawned here.
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.native.provision.__main__ import (
    EXIT_PROVISIONING_FAILED,
    EXIT_REPAIR_NEEDED,
    EXIT_SCHEMA_ACL_NORMALIZATION_FAILED,
    EXIT_SCHEMA_MIGRATION_FAILED,
    EXIT_SUCCESS,
    EXIT_UNEXPECTED,
    HANDOFF_MARKER_PREFIX,
    ProvisionCliAction,
    build_arg_parser,
    build_plan_and_context,
    decide_provision_cli_action,
    decode_pack_public_key,
    format_handoff_line,
    generate_database_password,
    journal_stale_reason,
    main,
    parse_handoff_line,
    probe_cluster_exists,
    probe_credential_lost_journal,
    probe_resumable_journal,
    resolve_provision_paths,
)
from civiccast.native.provision.journal import JournalError, journal_path, write_journal
from civiccast.native.provision.models import (
    ProvisionContext,
    ProvisionJournal,
    ProvisionPhase,
    ProvisionPlan,
)

# ---------------------------------------------------------------------------
# Password generation
# ---------------------------------------------------------------------------


def test_generate_database_password_has_adequate_length_and_safe_charset() -> None:
    password = generate_database_password()
    assert len(password) >= 32
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert set(password) <= allowed


def test_generate_database_password_is_not_repeated_across_calls() -> None:
    # Not a security proof -- a basic randomness sanity check that two
    # generated passwords are not trivially identical.
    passwords = {generate_database_password() for _ in range(5)}
    assert len(passwords) == 5


def test_generate_database_password_rejects_inadequate_entropy() -> None:
    with pytest.raises(ValueError, match="entropy_bytes"):
        generate_database_password(entropy_bytes=8)


# ---------------------------------------------------------------------------
# Handoff marker (stdout -> Rust caller)
# ---------------------------------------------------------------------------


def test_format_and_parse_handoff_line_round_trip() -> None:
    url = "postgresql://civiccast_svc:hunter2%40x@127.0.0.1:5432/civiccast"
    line = format_handoff_line(url)
    assert line == f"{HANDOFF_MARKER_PREFIX}{url}"
    assert parse_handoff_line(line) == url


def test_format_handoff_line_rejects_embedded_newlines() -> None:
    with pytest.raises(ValueError, match="newline"):
        format_handoff_line("postgresql://a\nb")
    with pytest.raises(ValueError, match="newline"):
        format_handoff_line("postgresql://a\rb")


def test_parse_handoff_line_finds_the_marker_among_noise() -> None:
    captured = "\n".join(
        [
            "some unrelated diagnostic line",
            "another line with no marker",
            f"{HANDOFF_MARKER_PREFIX}postgresql://u:p@127.0.0.1:5432/civiccast",
            "trailing noise",
        ]
    )
    assert parse_handoff_line(captured) == "postgresql://u:p@127.0.0.1:5432/civiccast"


def test_parse_handoff_line_returns_none_when_absent() -> None:
    assert parse_handoff_line("nothing here\nor here\n") is None
    assert parse_handoff_line("") is None


# ---------------------------------------------------------------------------
# Idempotency / no-op / fail-loud decision matrix
# ---------------------------------------------------------------------------


def test_decide_provision_cli_action_fresh_install_always_runs() -> None:
    assert (
        decide_provision_cli_action(cluster_exists=False, existing_database_url=None)
        is ProvisionCliAction.RUN
    )
    assert (
        decide_provision_cli_action(cluster_exists=False, existing_database_url="postgresql://x")
        is ProvisionCliAction.RUN
    )


def test_decide_provision_cli_action_reinstall_with_registry_value_is_noop() -> None:
    assert (
        decide_provision_cli_action(
            cluster_exists=True, existing_database_url="postgresql://u:p@h:5432/civiccast"
        )
        is ProvisionCliAction.NOOP_REUSE_EXISTING
    )


@pytest.mark.parametrize("blank", [None, "", "   ", "\t"])
def test_decide_provision_cli_action_reinstall_without_registry_value_adopts(
    blank: str | None,
) -> None:
    """N-15: an existing cluster with NO registry value (and no in-flight
    journal) is the exact state uninstall leaves behind BY DESIGN -- chain M /
    security fix F-02 deletes the DatabaseUrl credential while PRESERVING the
    product data directory. This USED to FAIL_LOUD_MISSING_REGISTRY (aborting
    every uninstall-then-reinstall over preserved data); it now ADOPTS the
    surviving cluster, re-establishing a fresh credential on it without
    re-initializing or dropping any data. The 'is this genuinely our cluster
    or a foreign one?' question is answered by a LIVE ownership check inside
    the adoption seam, not guessed here."""

    assert (
        decide_provision_cli_action(cluster_exists=True, existing_database_url=blank)
        is ProvisionCliAction.ADOPT_EXISTING
    )


def test_probe_cluster_exists_reflects_the_pg_version_file(tmp_path) -> None:
    data_dir = tmp_path / "pgdata"
    assert probe_cluster_exists(str(data_dir)) is False
    data_dir.mkdir()
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")
    assert probe_cluster_exists(str(data_dir)) is True


# ---------------------------------------------------------------------------
# Task #55 (audit-lite FINDING-003): resume-vs-repair journal classification
# ---------------------------------------------------------------------------


def _seeded_journal(tmp_path, *, phase: ProvisionPhase) -> ProvisionJournal:
    """A schema-valid ProvisionJournal at ``phase``, standing in for a PRIOR
    (possibly interrupted) provisioning invocation's own journal -- its
    plan/context content is irrelevant to probe_resumable_journal (which
    only reads ``.phase``), so these are simple fixed values, not the same
    plan/context the CALLING test's own ``main()`` invocation builds."""

    plan = ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )
    context = ProvisionContext(
        postgres_data_dir=str(tmp_path / "pgdata"),
        postgres_config_path=str(tmp_path / "pgdata" / "postgresql.conf"),
        postgres_hba_path=str(tmp_path / "pgdata" / "pg_hba.conf"),
        database_password="prior-run-password",
        server_pack_path=str(tmp_path / "server-binaries.ccpack"),
        state_root=str(tmp_path / "state"),
        owner_run_id="prior-run-1",
    )
    return ProvisionJournal(plan=plan, context=context, phase=phase)


def test_probe_resumable_journal_false_when_no_journal_exists(tmp_path) -> None:
    assert probe_resumable_journal(str(tmp_path / "state")) is False


def test_probe_resumable_journal_true_for_a_non_terminal_phase(tmp_path) -> None:
    journal = _seeded_journal(tmp_path, phase=ProvisionPhase.PACK_VERIFIED)
    write_journal(journal)
    assert probe_resumable_journal(str(tmp_path / "state")) is True


@pytest.mark.parametrize("phase", [ProvisionPhase.COMPLETE, ProvisionPhase.FAILED])
def test_probe_resumable_journal_false_for_a_terminal_phase(tmp_path, phase) -> None:
    journal = _seeded_journal(tmp_path, phase=phase)
    write_journal(journal)
    assert probe_resumable_journal(str(tmp_path / "state")) is False


@pytest.mark.parametrize(
    "phase",
    [
        ProvisionPhase.POSTGRES_CLUSTER_READY,
        ProvisionPhase.POSTGRES_CONFIG_WRITTEN,
        ProvisionPhase.DATABASE_READY,
    ],
)
def test_probe_resumable_journal_false_at_or_past_the_credential_boundary(tmp_path, phase) -> None:
    """Task #57 (disclosed in commit abdba55b): a non-terminal journal AT OR
    PAST POSTGRES_CLUSTER_READY is no longer "resumable" -- initdb already
    baked a real credential into the cluster, so resuming (which regenerates
    a FRESH password) would authenticate with the wrong one."""

    journal = _seeded_journal(tmp_path, phase=phase)
    write_journal(journal)
    assert probe_resumable_journal(str(tmp_path / "state")) is False


def test_probe_resumable_journal_propagates_journal_error_for_a_corrupt_journal(
    tmp_path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True)
    journal_path(state_root).write_text("{not valid json", encoding="utf-8")
    with pytest.raises(JournalError):
        probe_resumable_journal(str(state_root))


# ---------------------------------------------------------------------------
# Task #57 (disclosed in commit abdba55b): resume-past-credential-boundary
# collision -- probe_credential_lost_journal
# ---------------------------------------------------------------------------


def test_probe_credential_lost_journal_none_when_no_journal_exists(tmp_path) -> None:
    assert probe_credential_lost_journal(str(tmp_path / "state")) is None


def test_probe_credential_lost_journal_none_for_a_safely_resumable_phase(tmp_path) -> None:
    journal = _seeded_journal(tmp_path, phase=ProvisionPhase.PACK_VERIFIED)
    write_journal(journal)
    assert probe_credential_lost_journal(str(tmp_path / "state")) is None


@pytest.mark.parametrize("phase", [ProvisionPhase.COMPLETE, ProvisionPhase.FAILED])
def test_probe_credential_lost_journal_none_for_a_terminal_phase(tmp_path, phase) -> None:
    journal = _seeded_journal(tmp_path, phase=phase)
    write_journal(journal)
    assert probe_credential_lost_journal(str(tmp_path / "state")) is None


@pytest.mark.parametrize(
    "phase",
    [ProvisionPhase.POSTGRES_CLUSTER_READY, ProvisionPhase.DATABASE_READY],
)
def test_probe_credential_lost_journal_returns_the_journal_at_or_past_the_boundary(
    tmp_path, phase
) -> None:
    journal = _seeded_journal(tmp_path, phase=phase)
    write_journal(journal)
    found = probe_credential_lost_journal(str(tmp_path / "state"))
    assert found is not None
    assert found.phase is phase


def test_probe_credential_lost_journal_propagates_journal_error_for_a_corrupt_journal(
    tmp_path,
) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir(parents=True)
    journal_path(state_root).write_text("{not valid json", encoding="utf-8")
    with pytest.raises(JournalError):
        probe_credential_lost_journal(str(state_root))


def test_decide_provision_cli_action_resumes_via_journal_when_registry_missing() -> None:
    assert (
        decide_provision_cli_action(
            cluster_exists=True, existing_database_url="", journal_resumable=True
        )
        is ProvisionCliAction.RUN
    )


def test_decide_provision_cli_action_registry_value_wins_over_resumable_journal() -> None:
    # A completed prior run (registry populated) is never re-routed through a
    # resumable-journal check just because one happens to still be present.
    assert (
        decide_provision_cli_action(
            cluster_exists=True,
            existing_database_url="postgresql://u:p@h:5432/civiccast",
            journal_resumable=True,
        )
        is ProvisionCliAction.NOOP_REUSE_EXISTING
    )


def test_decide_provision_cli_action_adopts_without_a_resumable_journal() -> None:
    # N-15: cluster_exists=True, no registry value, and no resumable journal
    # is the uninstall-then-reinstall-over-preserved-data case -- now ADOPTED
    # (credential re-established on the surviving cluster) rather than
    # fail-loud-refused. Whether the cluster is genuinely product-owned or a
    # foreign one at the same path is decided by the adoption seam's LIVE
    # ownership check, which fails loud on a foreign cluster.
    assert (
        decide_provision_cli_action(
            cluster_exists=True, existing_database_url="", journal_resumable=False
        )
        is ProvisionCliAction.ADOPT_EXISTING
    )


def test_decide_provision_cli_action_fails_loud_credential_lost_when_flagged() -> None:
    assert (
        decide_provision_cli_action(
            cluster_exists=True,
            existing_database_url="",
            journal_resumable=False,
            credential_lost=True,
        )
        is ProvisionCliAction.FAIL_LOUD_CREDENTIAL_LOST
    )


def test_decide_provision_cli_action_registry_value_wins_over_credential_lost() -> None:
    # A completed prior run (registry populated) is never re-routed through
    # the credential-lost check just because a stale non-terminal journal
    # happens to still be present.
    assert (
        decide_provision_cli_action(
            cluster_exists=True,
            existing_database_url="postgresql://u:p@h:5432/civiccast",
            credential_lost=True,
        )
        is ProvisionCliAction.NOOP_REUSE_EXISTING
    )


def test_main_resumes_via_journal_instead_of_fail_loud_missing_registry(tmp_path, capsys) -> None:
    """RED-first (task #55 / audit-lite FINDING-003): before the fix, this
    exact setup -- an existing PG_VERSION file (cluster_exists=True), a
    resumable non-terminal provisioning journal at this run's OWN
    state_root, and a blank --existing-database-url -- was misclassified
    identically to a genuinely foreign cluster (FAIL_LOUD_MISSING_REGISTRY /
    EXIT_REPAIR_NEEDED) instead of resuming the interrupted run.

    After the fix, main() takes the RUN branch instead. It then reaches
    decode_pack_public_key with this test's deliberately-invalid placeholder
    key (``_required_args``'s ``"AAAA"``, 3 raw bytes -- rejected by the
    32-byte Ed25519 length check) and exits EXIT_UNEXPECTED there -- never
    reaching a real seam (this file's own HARD RULE: no real pg_ctl/initdb
    spawned in this suite). What this test proves is WHICH BRANCH main()
    took: the exit code is no longer EXIT_REPAIR_NEEDED.
    """

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    import pathlib

    data_dir = pathlib.Path(paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")

    prior_plan = ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )
    prior_context = ProvisionContext(
        postgres_data_dir=paths.postgres_data_dir,
        postgres_config_path=paths.postgres_config_path,
        postgres_hba_path=paths.postgres_hba_path,
        database_password="prior-run-password",
        server_pack_path=paths.server_pack_path,
        state_root=paths.state_root,
        owner_run_id="prior-run-1",
    )
    write_journal(
        ProvisionJournal(plan=prior_plan, context=prior_context, phase=ProvisionPhase.PACK_VERIFIED)
    )

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
            },
        )
    )

    assert code == EXIT_UNEXPECTED
    out = capsys.readouterr().out
    assert HANDOFF_MARKER_PREFIX not in out


def test_main_fails_loud_honestly_instead_of_resuming_past_the_credential_boundary(
    tmp_path, capsys
) -> None:
    """RED-first (task #57, disclosed in commit abdba55b): a journal killed
    AT OR PAST POSTGRES_CLUSTER_READY must never be silently resumed with a
    freshly generated password -- the already-initialized cluster's real
    credential (baked in by initdb) would reject it. Before the fix, this
    exact setup took the RUN branch (like
    test_main_resumes_via_journal_instead_of_fail_loud_missing_registry
    above) and would have gone on to generate a NEW password and attempt to
    drive the interrupted run forward with it. After the fix, main() halts
    immediately with EXIT_REPAIR_NEEDED, writes an honest recovery document
    (never claiming a repair install would help), and never reaches
    decode_pack_public_key/generate_database_password at all.
    """

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    import pathlib

    data_dir = pathlib.Path(paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")

    prior_plan = ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )
    prior_context = ProvisionContext(
        postgres_data_dir=paths.postgres_data_dir,
        postgres_config_path=paths.postgres_config_path,
        postgres_hba_path=paths.postgres_hba_path,
        database_password="prior-run-password",
        server_pack_path=paths.server_pack_path,
        state_root=paths.state_root,
        owner_run_id="prior-run-1",
    )
    write_journal(
        ProvisionJournal(
            plan=prior_plan, context=prior_context, phase=ProvisionPhase.DATABASE_READY
        )
    )

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
            },
        )
    )

    assert code == EXIT_REPAIR_NEEDED
    out = capsys.readouterr().out
    assert HANDOFF_MARKER_PREFIX not in out

    recovery_doc = pathlib.Path(paths.state_root) / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), "an honest recovery document must be written, not just stderr"
    content = recovery_doc.read_text(encoding="utf-8")
    assert "NOT a generic 'needs a repair install' situation" in content
    assert "will not recover the missing credential" in content
    assert paths.postgres_data_dir in content
    assert "--existing-database-url" in content

    reloaded = ProvisionJournal.model_validate_json(
        (pathlib.Path(paths.state_root) / "provision-journal.json").read_text(encoding="utf-8")
    )
    assert reloaded.phase is ProvisionPhase.FAILED
    assert reloaded.context.database_password != "prior-run-password"


# ---------------------------------------------------------------------------
# Path derivation
# ---------------------------------------------------------------------------


def test_resolve_provision_paths_derives_the_program_data_tree() -> None:
    paths = resolve_provision_paths(
        install_root=r"C:\Program Files\CivicCast (Native)",
        program_data_root=r"C:\ProgramData",
    )
    assert paths.program_data_root == r"C:\ProgramData"
    assert paths.state_root == r"C:\ProgramData\CivicCast\provision"
    assert paths.postgres_data_dir == r"C:\ProgramData\CivicCast\data\pgdata"
    assert (
        paths.server_pack_path
        == r"C:\Program Files\CivicCast (Native)\packs\native-server-binaries.ccpack"
    )
    assert paths.initdb_path == (
        r"C:\Program Files\CivicCast (Native)\packs\native-server-binaries"
        r"\payload\bin\initdb.exe"
    )


def test_resolve_provision_paths_config_files_live_inside_the_data_dir() -> None:
    # pg_ctl start -D <data_dir> -w (civiccast.native.supervisor.children.
    # postgres_child_spec) passes no -c config_file= override, so PostgreSQL
    # only ever reads its default $PGDATA/postgresql.conf + $PGDATA/pg_hba.conf
    # -- writing the provisioned config anywhere else is silently ignored by
    # the real server. This is a correctness constraint, not a style choice.
    paths = resolve_provision_paths(install_root=r"C:\INSTDIR", program_data_root=r"C:\ProgramData")
    assert paths.postgres_config_path == paths.postgres_data_dir + "\\postgresql.conf"
    assert paths.postgres_hba_path == paths.postgres_data_dir + "\\pg_hba.conf"


def test_resolve_provision_paths_defaults_program_data_root_from_env(monkeypatch) -> None:
    monkeypatch.setenv("PROGRAMDATA", r"D:\PD")
    paths = resolve_provision_paths(install_root=r"C:\INSTDIR")
    assert paths.program_data_root == r"D:\PD"
    assert paths.state_root == r"D:\PD\CivicCast\provision"


def test_resolve_provision_paths_overrides_win_over_derived_defaults() -> None:
    paths = resolve_provision_paths(
        install_root=r"C:\INSTDIR",
        program_data_root=r"C:\ProgramData",
        server_pack_path=r"C:\custom\pack.ccpack",
        initdb_path=r"C:\custom\bin\initdb.exe",
    )
    assert paths.server_pack_path == r"C:\custom\pack.ccpack"
    assert paths.initdb_path == r"C:\custom\bin\initdb.exe"


# ---------------------------------------------------------------------------
# Pack public key decoding
# ---------------------------------------------------------------------------


def test_decode_pack_public_key_round_trips_a_real_ed25519_key() -> None:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    raw = public_key.public_bytes_raw()
    encoded = base64.b64encode(raw).decode("ascii")

    decoded = decode_pack_public_key(encoded)
    assert decoded.public_bytes_raw() == raw


def test_decode_pack_public_key_rejects_wrong_length() -> None:
    encoded = base64.b64encode(b"too-short").decode("ascii")
    with pytest.raises(ValueError, match="32 bytes"):
        decode_pack_public_key(encoded)


def test_decode_pack_public_key_rejects_invalid_base64() -> None:
    with pytest.raises(Exception):  # noqa: B017 - any decode failure is acceptable
        decode_pack_public_key("not-valid-base64!!!")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _required_args(tmp_path, **overrides: str) -> list[str]:
    args = {
        "--install-root": str(tmp_path / "install"),
        "--owner-run-id": "run-1",
        "--pack-signing-key-id": "key-1",
        "--pack-public-key-base64": "AAAA",
        "--pack-product-version": "1.0.0",
        "--pack-compatible-core": "1.0.0",
    }
    args.update(overrides)
    flat: list[str] = []
    for key, value in args.items():
        flat.extend([key, value])
    return flat


def test_build_arg_parser_requires_core_args() -> None:
    parser = build_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_arg_parser_accepts_full_required_set_with_expected_defaults(tmp_path) -> None:
    args = build_arg_parser().parse_args(_required_args(tmp_path))
    assert args.existing_database_url == ""
    assert args.postgres_host == "127.0.0.1"
    assert args.postgres_port == 5432
    assert args.database_name == "civiccast"
    assert args.database_username == "civiccast_svc"
    assert args.postgres_major_version == "17"


# ---------------------------------------------------------------------------
# Plan/context assembly
# ---------------------------------------------------------------------------


def test_build_plan_and_context_assembles_expected_fields(tmp_path) -> None:
    paths = resolve_provision_paths(
        install_root=str(tmp_path / "install"), program_data_root=str(tmp_path / "pd")
    )
    args = build_arg_parser().parse_args(_required_args(tmp_path))
    plan, context = build_plan_and_context(
        paths=paths, args=args, database_password="a-generated-password"
    )

    assert plan.postgres_major_version == "17"
    assert plan.database_name == "civiccast"
    assert plan.database_username == "civiccast_svc"
    assert plan.server_pack_product_version == "1.0.0"
    assert plan.server_pack_compatible_core == "1.0.0"
    assert plan.server_pack_signing_key_id == "key-1"

    assert context.postgres_data_dir == paths.postgres_data_dir
    assert context.postgres_config_path == paths.postgres_config_path
    assert context.postgres_hba_path == paths.postgres_hba_path
    assert context.database_password == "a-generated-password"
    assert context.server_pack_path == paths.server_pack_path
    assert context.state_root == paths.state_root
    assert context.owner_run_id == "run-1"


# ---------------------------------------------------------------------------
# main(): only the two paths that return before touching a real seam
# ---------------------------------------------------------------------------


def test_main_noop_path_exits_success_without_generating_a_password_or_journal(
    tmp_path, capsys
) -> None:
    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    import pathlib

    data_dir = pathlib.Path(paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "postgresql://u:p@127.0.0.1:5432/civiccast",
            },
        )
    )

    assert code == EXIT_SUCCESS
    out = capsys.readouterr().out
    assert HANDOFF_MARKER_PREFIX not in out
    assert not pathlib.Path(paths.state_root, "provision-journal.json").exists()


def test_main_adopts_surviving_cluster_instead_of_fail_loud(tmp_path, capsys, monkeypatch) -> None:
    """N-15 (BLOCKER, RED at base tip e231e9c8): the exact
    uninstall-then-reinstall-over-preserved-data setup -- an existing
    PG_VERSION cluster, a blank --existing-database-url (chain M deleted the
    credential), and a TERMINAL COMPLETE journal from the prior provision
    (which uninstall may leave behind) -- USED to exit EXIT_REPAIR_NEEDED
    (FAIL_LOUD_MISSING_REGISTRY) and abort the whole install with installer
    exit 116.

    After the fix, main() ADOPTS the surviving cluster: it re-establishes a
    fresh credential ON that cluster (reset_cluster_credential), then drives
    the engine to COMPLETE over the SAME data directory and prints the
    DatabaseUrl handoff -- a working station, station data preserved. This
    also proves the stale TERMINAL journal no longer short-circuits the run
    (run_provision is actually invoked), and that the credential reset happens
    BEFORE the engine (so every downstream connection authenticates)."""

    import civiccast.native.provision.__main__ as provision_main
    import civiccast.native.provision.seams as seams_module
    from civiccast.native.provision.seams import CredentialAdoptionResult

    # Pack verification is proven by test_provision_pack_verification.py; here
    # we exercise the adoption decision/flow, so the pack signature check is a
    # no-op (there is no real .ccpack on the test host).
    monkeypatch.setattr(seams_module, "verify_server_binaries_pack", lambda *a, **k: None)

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    scratch_url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    import pathlib

    data_dir = pathlib.Path(paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")

    # A TERMINAL COMPLETE journal from the prior (successful) provision -- the
    # kind uninstall preserves. Under the OLD behavior this classified as
    # FAIL_LOUD_MISSING_REGISTRY; it must not block adoption now.
    prior_plan = ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )
    prior_context = ProvisionContext(
        postgres_data_dir=paths.postgres_data_dir,
        postgres_config_path=paths.postgres_config_path,
        postgres_hba_path=paths.postgres_hba_path,
        database_password="old-run-password",
        server_pack_path=paths.server_pack_path,
        state_root=paths.state_root,
        owner_run_id="old-run-1",
    )
    write_journal(
        ProvisionJournal(plan=prior_plan, context=prior_context, phase=ProvisionPhase.COMPLETE)
    )

    call_order: list[str] = []
    reset_calls: list[tuple[str, str]] = []

    def fake_reset(context, plan, *, pg_ctl_path, psql_path):
        call_order.append("reset")
        reset_calls.append((context.postgres_data_dir, context.database_password))
        # The real seam re-establishes the fresh password ON the surviving
        # cluster; the fake just records that it ran and with which password.
        return CredentialAdoptionResult(detail="re-established credential (faked)")

    monkeypatch.setattr(provision_main, "reset_cluster_credential", fake_reset)

    # Fake the engine + pg_ctl (HARD RULE: no real postgres). Wrap the engine
    # fake to also record ordering relative to the reset.
    engine_calls = _wire_fresh_install_run_path(monkeypatch, scratch_url)
    real_engine_fake = provision_main.run_provision

    def ordered_engine(plan, context, seams):
        call_order.append("engine")
        return real_engine_fake(plan, context, seams)

    monkeypatch.setattr(provision_main, "run_provision", ordered_engine)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_SUCCESS, "a reinstall over preserved data must produce a working station"
    out = capsys.readouterr().out
    assert f"{HANDOFF_MARKER_PREFIX}{scratch_url}" in out, (
        "the adopted station must get a DatabaseUrl"
    )
    assert reset_calls, "the surviving cluster's credential must be re-established"
    assert reset_calls[0][0] == paths.postgres_data_dir
    # The credential written to the cluster is THIS run's fresh password, never
    # the (unrecoverable) old one.
    assert reset_calls[0][1] != "old-run-password"
    # The stale TERMINAL journal did not short-circuit the run.
    assert engine_calls, "the engine must actually run over the adopted cluster"
    # Reset happens BEFORE the engine, so every downstream connection uses the
    # freshly-established password.
    assert call_order == ["reset", "engine"]


def test_main_adopt_refuses_a_foreign_cluster_honestly(tmp_path, capsys, monkeypatch) -> None:
    """N-15 safety half: adoption must NEVER take over a cluster the product
    did not create. When reset_cluster_credential's LIVE ownership check
    refuses the cluster (AdoptionForeignClusterError), main() halts loud with
    EXIT_REPAIR_NEEDED, prints NO DatabaseUrl handoff, and writes an HONEST
    recovery document naming the foreign cluster at the exact data directory
    -- never claiming a plain repair install would help. The journal ends
    terminal FAILED."""

    import civiccast.native.provision.__main__ as provision_main
    import civiccast.native.provision.seams as seams_module
    from civiccast.native.provision.seams import AdoptionForeignClusterError

    # Pack verification runs before the reset; no-op it (proven elsewhere).
    monkeypatch.setattr(seams_module, "verify_server_binaries_pack", lambda *a, **k: None)

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    import pathlib

    data_dir = pathlib.Path(paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")

    def foreign_reset(context, plan, *, pg_ctl_path, psql_path):
        raise AdoptionForeignClusterError(
            f"role {plan.database_username!r} is absent on the cluster at "
            f"{context.postgres_data_dir!r}; refusing to adopt a cluster the product "
            "did not create (fail-closed)"
        )

    monkeypatch.setattr(provision_main, "reset_cluster_credential", foreign_reset)
    _fake_port_resolver_always_available(monkeypatch)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_REPAIR_NEEDED
    captured = capsys.readouterr()
    assert HANDOFF_MARKER_PREFIX not in captured.out

    recovery_doc = pathlib.Path(paths.state_root) / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), "a foreign-cluster refusal must write an honest recovery document"
    content = recovery_doc.read_text(encoding="utf-8")
    assert paths.postgres_data_dir in content
    assert (
        "did NOT" in content or "not a CivicCast" in content.lower() or "did not create" in content
    )

    reloaded = ProvisionJournal.model_validate_json(
        (pathlib.Path(paths.state_root) / "provision-journal.json").read_text(encoding="utf-8")
    )
    assert reloaded.phase is ProvisionPhase.FAILED


# ---------------------------------------------------------------------------
# N-16 (fleet-tester candidate 99db2c6, soak/INSTALL-FAILED.md /
# soak/evidence-provision-failure/): adopted-journal staleness (BUG 1) and
# every provisioning-failure path must actually write PROVISION-RECOVERY.md
# before the installer's own static message references it (BUG 2).
# ---------------------------------------------------------------------------


def test_journal_stale_reason_none_when_server_pack_path_matches(tmp_path) -> None:
    paths = resolve_provision_paths(
        install_root=str(tmp_path / "install"), program_data_root=str(tmp_path / "pd")
    )
    journal = _seeded_journal(tmp_path, phase=ProvisionPhase.COMPLETE)
    # _seeded_journal's own context.server_pack_path is an unrelated fixed
    # value; rebuild one whose server_pack_path genuinely matches paths, the
    # only case journal_stale_reason must call trustworthy.
    matching = journal.model_copy(
        update={
            "context": journal.context.model_copy(
                update={"server_pack_path": paths.server_pack_path}
            )
        }
    )
    assert journal_stale_reason(matching, paths=paths) is None


def test_journal_stale_reason_flags_a_mismatched_server_pack_path(tmp_path) -> None:
    """N-16 root cause: an adopted journal from a PRIOR install_root (e.g. the
    default Program Files location) recorded a server_pack_path that no
    longer describes THIS run's install root (e.g. a custom /D= directory).
    journal_stale_reason must say so, naming both paths."""

    old_paths = resolve_provision_paths(
        install_root=r"C:\Program Files\CivicCast (Native)",
        program_data_root=str(tmp_path / "pd"),
    )
    new_paths = resolve_provision_paths(
        install_root=r"C:\CivicCastHostStore\install",
        program_data_root=str(tmp_path / "pd"),
    )
    journal = _seeded_journal(tmp_path, phase=ProvisionPhase.COMPLETE)
    stale = journal.model_copy(
        update={
            "context": journal.context.model_copy(
                update={"server_pack_path": old_paths.server_pack_path}
            )
        }
    )
    reason = journal_stale_reason(stale, paths=new_paths)
    assert reason is not None
    assert repr(old_paths.server_pack_path) in reason
    assert repr(new_paths.server_pack_path) in reason


def test_main_resets_a_stale_adopted_journal_and_still_adopts_the_cluster(
    tmp_path, capsys, monkeypatch
) -> None:
    """N-16 (root cause, BUG 1): the EXACT fleet-tester shape -- an uninstall
    preserved ProgramData (and its provisioning journal) at the OLD
    install_root's server_pack_path, then a fresh install ran against a
    DIFFERENT install_root (a custom /D= directory). Before the fix, the
    stale COMPLETE journal was adopted as-is (harmless only by accident, since
    the ADOPT_EXISTING branch always rebuilds a throwaway fresh context for
    its own seams -- but a non-terminal/FAILED stale journal from the old
    root would otherwise wedge every future run's classification on a path
    that can never be revalidated). After the fix, main() detects the
    mismatch up front, resets the journal bookkeeping file (never touching
    the preserved PostgreSQL data directory), and the run proceeds to adopt
    the surviving cluster and re-derive every path from the CURRENT install
    root."""

    import pathlib

    import civiccast.native.provision.__main__ as provision_main
    import civiccast.native.provision.seams as seams_module
    from civiccast.native.provision.seams import CredentialAdoptionResult

    monkeypatch.setattr(seams_module, "verify_server_binaries_pack", lambda *a, **k: None)

    old_install_root = tmp_path / "old-install"
    new_install_root = tmp_path / "new-install"
    program_data_root = tmp_path / "pd"
    scratch_url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"

    old_paths = resolve_provision_paths(
        install_root=str(old_install_root), program_data_root=str(program_data_root)
    )
    new_paths = resolve_provision_paths(
        install_root=str(new_install_root), program_data_root=str(program_data_root)
    )
    # Both installs share the SAME ProgramData (that is exactly what
    # uninstall preserves) -- state_root and postgres_data_dir must be
    # identical between the two derivations.
    assert old_paths.state_root == new_paths.state_root
    assert old_paths.postgres_data_dir == new_paths.postgres_data_dir
    assert old_paths.server_pack_path != new_paths.server_pack_path

    data_dir = pathlib.Path(new_paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")
    # A marker file standing in for "station data" -- untouched by a stale-
    # journal reset, which only ever removes provision-journal.json.
    (data_dir / "station-marker.txt").write_text("preserved\n", encoding="utf-8")

    prior_plan = ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )
    stale_context = ProvisionContext(
        postgres_data_dir=old_paths.postgres_data_dir,
        postgres_config_path=old_paths.postgres_config_path,
        postgres_hba_path=old_paths.postgres_hba_path,
        database_password="old-run-password",
        server_pack_path=old_paths.server_pack_path,  # the STALE, OLD path
        state_root=old_paths.state_root,
        owner_run_id="old-run-1",
    )
    write_journal(
        ProvisionJournal(plan=prior_plan, context=stale_context, phase=ProvisionPhase.COMPLETE)
    )

    def fake_reset(context, plan, *, pg_ctl_path, psql_path):
        return CredentialAdoptionResult(detail="re-established credential (faked)")

    monkeypatch.setattr(provision_main, "reset_cluster_credential", fake_reset)
    engine_calls = _wire_fresh_install_run_path(monkeypatch, scratch_url)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(new_install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_SUCCESS, "adoption must still succeed once the stale journal is reset"
    captured = capsys.readouterr()
    assert f"{HANDOFF_MARKER_PREFIX}{scratch_url}" in captured.out
    assert "STALE" in captured.err

    # Station data (the preserved data directory and everything in it) was
    # NEVER touched by the reset.
    assert (data_dir / "station-marker.txt").read_text(encoding="utf-8") == "preserved\n"

    # The engine actually ran (proves the stale COMPLETE journal no longer
    # short-circuits run_provision), and it did so against the CURRENT
    # install root's re-derived server_pack_path, never the stale one.
    assert engine_calls
    _, engine_context = engine_calls[0]
    assert engine_context.server_pack_path == new_paths.server_pack_path
    assert engine_context.server_pack_path != old_paths.server_pack_path


def test_main_does_not_reset_a_matching_adopted_journal(tmp_path, capsys, monkeypatch) -> None:
    """Journal valid (server_pack_path matches THIS run's install root) ->
    unchanged behavior: no staleness reset, no "STALE" breadcrumb, and the
    prior journal's un-related history is not disturbed before adoption
    proceeds. This is the control case for
    test_main_resets_a_stale_adopted_journal_and_still_adopts_the_cluster."""

    import pathlib

    import civiccast.native.provision.__main__ as provision_main
    import civiccast.native.provision.seams as seams_module
    from civiccast.native.provision.seams import CredentialAdoptionResult

    monkeypatch.setattr(seams_module, "verify_server_binaries_pack", lambda *a, **k: None)

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    scratch_url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )

    data_dir = pathlib.Path(paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")

    prior_plan = ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )
    matching_context = ProvisionContext(
        postgres_data_dir=paths.postgres_data_dir,
        postgres_config_path=paths.postgres_config_path,
        postgres_hba_path=paths.postgres_hba_path,
        database_password="old-run-password",
        server_pack_path=paths.server_pack_path,  # matches THIS run exactly
        state_root=paths.state_root,
        owner_run_id="old-run-1",
    )
    write_journal(
        ProvisionJournal(plan=prior_plan, context=matching_context, phase=ProvisionPhase.COMPLETE)
    )

    monkeypatch.setattr(
        provision_main,
        "reset_cluster_credential",
        lambda context, plan, *, pg_ctl_path, psql_path: CredentialAdoptionResult(
            detail="re-established credential (faked)"
        ),
    )
    _wire_fresh_install_run_path(monkeypatch, scratch_url)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_SUCCESS
    captured = capsys.readouterr()
    assert "STALE" not in captured.err


def test_main_stale_journal_reset_also_protects_the_run_branch(
    tmp_path, capsys, monkeypatch
) -> None:
    """N-16, the OTHER hazard the general staleness check closes: a stale
    TERMINAL (here FAILED) journal at this state_root, found when
    ``cluster_exists`` is FALSE (no PG_VERSION -- e.g. an operator cleared
    the data directory but the provisioning bookkeeping file survived).
    Before this fix, ``run_provision`` would have loaded that OLD, terminal
    journal and returned it UNCHANGED (its own documented "terminal phases
    are left alone on rerun" contract) WITHOUT ever calling ``verify_pack``
    against the CURRENT install root -- a stale FAILED journal from a
    different install_root would then wedge every future run at that same
    terminal phase forever, never re-attempted. After the fix, the
    staleness check resets it before ``run_provision`` ever sees it, so a
    genuinely fresh run (RUN branch, since cluster_exists is False here)
    proceeds normally."""

    old_install_root = tmp_path / "old-install"
    new_install_root = tmp_path / "new-install"
    program_data_root = tmp_path / "pd"
    scratch_url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"

    old_paths = resolve_provision_paths(
        install_root=str(old_install_root), program_data_root=str(program_data_root)
    )
    new_paths = resolve_provision_paths(
        install_root=str(new_install_root), program_data_root=str(program_data_root)
    )
    assert old_paths.server_pack_path != new_paths.server_pack_path

    prior_plan = ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )
    stale_context = ProvisionContext(
        postgres_data_dir=old_paths.postgres_data_dir,
        postgres_config_path=old_paths.postgres_config_path,
        postgres_hba_path=old_paths.postgres_hba_path,
        database_password="old-run-password",
        server_pack_path=old_paths.server_pack_path,
        state_root=old_paths.state_root,
        owner_run_id="old-run-1",
    )
    write_journal(
        ProvisionJournal(plan=prior_plan, context=stale_context, phase=ProvisionPhase.FAILED)
    )

    engine_calls = _wire_fresh_install_run_path(monkeypatch, scratch_url)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(new_install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_SUCCESS, (
        "a stale FAILED journal from a DIFFERENT install root must not permanently "
        "wedge a fresh run at that data directory"
    )
    captured = capsys.readouterr()
    assert f"{HANDOFF_MARKER_PREFIX}{scratch_url}" in captured.out
    assert "STALE" in captured.err
    assert engine_calls
    _, engine_context = engine_calls[0]
    assert engine_context.server_pack_path == new_paths.server_pack_path


def test_main_adopt_pack_verification_failure_writes_recovery_document(
    tmp_path, capsys, monkeypatch
) -> None:
    """BUG 2: the ADOPT_EXISTING pre-check's own pack-verification failure
    (before reset_cluster_credential ever runs) must write
    PROVISION-RECOVERY.md -- the NSIS hook chain shows the SAME static "see
    ... PROVISION-RECOVERY.md" message for every nonzero exit this CLI can
    produce (every one collapses to installer exit 75), so every one of
    them must leave that file behind."""

    import pathlib

    import civiccast.native.provision.seams as seams_module

    def failing_verify(*a, **k):
        raise RuntimeError("signature mismatch")

    monkeypatch.setattr(seams_module, "verify_server_binaries_pack", failing_verify)
    _fake_port_resolver_always_available(monkeypatch)

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    data_dir = pathlib.Path(paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_PROVISIONING_FAILED
    captured = capsys.readouterr()
    assert HANDOFF_MARKER_PREFIX not in captured.out

    recovery_doc = pathlib.Path(paths.state_root) / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), (
        "a pre-adoption pack verification failure must still write the recovery "
        "document the installer's failure message references"
    )
    content = recovery_doc.read_text(encoding="utf-8")
    assert "pack" in content.lower()


def test_main_adopt_credential_reset_fault_writes_recovery_document(
    tmp_path, capsys, monkeypatch
) -> None:
    """BUG 2: a real (non-foreign-cluster) fault while re-establishing the
    adoption credential -- e.g. pg_ctl/psql execution failure -- must also
    write PROVISION-RECOVERY.md, distinct from the foreign-cluster refusal
    path (already covered by test_main_adopt_refuses_a_foreign_cluster_honestly),
    which already wrote one via halt_adopt_foreign_cluster."""

    import pathlib

    import civiccast.native.provision.__main__ as provision_main
    import civiccast.native.provision.seams as seams_module

    monkeypatch.setattr(seams_module, "verify_server_binaries_pack", lambda *a, **k: None)

    def faulting_reset(context, plan, *, pg_ctl_path, psql_path):
        raise RuntimeError("pg_ctl start failed (exit 1): could not bind port 5432")

    monkeypatch.setattr(provision_main, "reset_cluster_credential", faulting_reset)
    _fake_port_resolver_always_available(monkeypatch)

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    data_dir = pathlib.Path(paths.postgres_data_dir)
    data_dir.mkdir(parents=True)
    (data_dir / "PG_VERSION").write_text("17\n", encoding="utf-8")

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--existing-database-url": "",
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_PROVISIONING_FAILED
    captured = capsys.readouterr()
    assert HANDOFF_MARKER_PREFIX not in captured.out

    recovery_doc = pathlib.Path(paths.state_root) / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), (
        "a real credential-reset fault must still write the recovery document "
        "the installer's failure message references"
    )
    content = recovery_doc.read_text(encoding="utf-8")
    assert paths.postgres_data_dir in content


def test_main_pack_key_decode_failure_writes_recovery_document(tmp_path, capsys) -> None:
    """BUG 2: even the earliest RUN/ADOPT_EXISTING-shared failure point
    (decoding the embedded pack public key, before any plan/context/journal
    exists) must leave PROVISION-RECOVERY.md behind."""

    import pathlib

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--pack-public-key-base64": "not-valid-base64!!!",
            },
        )
    )

    assert code == EXIT_UNEXPECTED
    captured = capsys.readouterr()
    assert HANDOFF_MARKER_PREFIX not in captured.out

    recovery_doc = pathlib.Path(paths.state_root) / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), (
        "a pack-public-key decode failure must still write the recovery document"
    )


def test_main_corrupt_adopted_journal_writes_recovery_document(tmp_path, capsys) -> None:
    """BUG 2: a present-but-corrupt adopted journal is fail-loud
    (EXIT_UNEXPECTED, never silently treated as absent) -- but it must still
    leave an operator recovery document, since this exit ALSO collapses to
    installer exit 75 with the SAME static "see ... PROVISION-RECOVERY.md"
    message."""

    import pathlib

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    state_root = pathlib.Path(paths.state_root)
    state_root.mkdir(parents=True)
    (state_root / "provision-journal.json").write_text("{not valid json", encoding="utf-8")

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
            },
        )
    )

    assert code == EXIT_UNEXPECTED
    captured = capsys.readouterr()
    assert HANDOFF_MARKER_PREFIX not in captured.out

    recovery_doc = state_root / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), "a corrupt adopted journal must still write the recovery document"


def test_exit_codes_are_distinct() -> None:
    codes = {
        EXIT_SUCCESS,
        EXIT_PROVISIONING_FAILED,
        EXIT_REPAIR_NEEDED,
        EXIT_SCHEMA_MIGRATION_FAILED,
        EXIT_UNEXPECTED,
        EXIT_SCHEMA_ACL_NORMALIZATION_FAILED,
    }
    assert len(codes) == 6


# ---------------------------------------------------------------------------
# C1 (2026-07-31): a fresh install must leave the provisioned database's
# schema at alembic head. On a first-ever install the NSIS chain SKIPS the
# D3 upgrade engine (fresh-install gate) -- provisioning is the only place
# the tables can ever be created.
# ---------------------------------------------------------------------------


def _valid_pack_key_b64() -> str:
    return base64.b64encode(Ed25519PrivateKey.generate().public_key().public_bytes_raw()).decode(
        "ascii"
    )


def _fake_port_resolver_always_available(monkeypatch) -> None:
    """Fake ``civiccast.native.provision.__main__.resolve_provision_port`` to
    a deterministic "the preferred port is available" result.

    Every RUN/ADOPT_EXISTING test in this file reaches this real-seam call
    (real-world LPM deployment fix, 2026-08-27) before it ever reaches
    ``run_provision``/``reset_cluster_credential``. This file's HARD RULE is
    no real postgres/pg_ctl/initdb -- a real TCP bind + ``netsh`` probe is
    NOT postgres, but it is still real host-dependent I/O this shared test
    suite should not depend on (and, on a box already carrying the same
    Hyper-V/WSL port-reservation posture the LPM failure was caused by, the
    real probe can behave unpredictably). See test_provision_port_select.py
    for direct, thorough coverage of the real ``port_select`` module."""

    import civiccast.native.provision.__main__ as provision_main
    from civiccast.native.provision.port_select import PortSelectionResult

    monkeypatch.setattr(
        provision_main,
        "resolve_provision_port",
        lambda *, host, preferred_port, candidates=None: PortSelectionResult(
            outcome="selected", port=preferred_port, detail="faked: preferred port available"
        ),
    )


def _wire_fresh_install_run_path(monkeypatch, scratch_url: str):
    """Fake ONLY the engine + pg_ctl (this file's HARD RULE: no real
    postgres/initdb spawn); everything after the engine runs REAL code.
    Returns the recorded fake-engine invocations."""

    from pathlib import Path

    import civiccast.native.provision.__main__ as provision_main
    import civiccast.native.provision.seams as seams_module
    from civiccast.native.pg_ctl_exec import PgCtlResult
    from civiccast.native.provision.models import ProvisionOutcome

    engine_calls: list[tuple[ProvisionPlan, ProvisionContext]] = []

    def fake_run_provision(plan, context, seams):
        engine_calls.append((plan, context))
        # The REAL engine's initdb step creates the data directory; the code
        # AFTER the engine (migrate_provisioned_schema -> row-4b pgdata ACL
        # normalization, which is deliberately fail-loud on a missing data
        # dir) runs for real here, so the fake must leave the same postcondition.
        Path(context.postgres_data_dir).mkdir(parents=True, exist_ok=True)
        journal = ProvisionJournal(plan=plan, context=context, phase=ProvisionPhase.COMPLETE)
        return ProvisionOutcome(phase=ProvisionPhase.COMPLETE, journal=journal)

    monkeypatch.setattr(provision_main, "run_provision", fake_run_provision)
    # Route the migration at a scratch database this test can inspect (the
    # REAL resolve_database_url would name a postgres server that does not
    # exist on the test host).
    monkeypatch.setattr(
        provision_main, "resolve_database_url", lambda *, plan, context: scratch_url
    )
    _fake_port_resolver_always_available(monkeypatch)
    # pg_ctl start/stop around the migration: bounded executor faked; the
    # alembic run itself stays REAL.
    monkeypatch.setattr(
        seams_module,
        "run_pg_ctl_argv",
        lambda argv, *, timeout_seconds, runner=None: PgCtlResult(returncode=0, output_tail=""),
    )
    return engine_calls


def test_main_fresh_install_brings_the_schema_to_alembic_head(
    tmp_path, capsys, monkeypatch
) -> None:
    """RED at HEAD 1ec943b0 (C1, BLOCKER): before the fix, main()'s RUN path
    exited EXIT_SUCCESS having created cluster/role/database but ZERO
    tables -- no alembic runner anywhere under provision/, and the NSIS
    chain's D3 engine (the only other runner) is skipped by design on a
    first-ever install. The control plane then served over an empty schema
    and the first alert INSERT crashed the supervisor.

    Proof standard (grounded in external truth, not a pin of main()'s own
    output): provision against a SCRATCH database, then assert that
    database's live revision (read_db_revision) equals the code's migration
    head (expected_migration_head, read from the script directory)."""

    from civiccast.schema_check import expected_migration_head, read_db_revision

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    scratch_url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"
    _wire_fresh_install_run_path(monkeypatch, scratch_url)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_SUCCESS
    out = capsys.readouterr().out
    assert f"{HANDOFF_MARKER_PREFIX}{scratch_url}" in out  # handoff still printed
    assert read_db_revision(scratch_url) == expected_migration_head(), (
        "a fresh install must leave the provisioned database at alembic head -- "
        "an empty schema kills every table-touching product function"
    )


# ---------------------------------------------------------------------------
# Real-world LPM deployment fix (2026-08-27, candidate 75cc13f): port
# pre-check + fallback wiring. Both live installer runs failed identically at
# d4-provision because pg_ctl could not bind 127.0.0.1:5432 ("Permission
# denied" / Windows-excluded TCP port range). resolve_provision_port itself
# is proven directly in test_provision_port_select.py; these tests prove
# main() actually WIRES it in -- honest failure when no port is available,
# and the fallback port flowing into the context every downstream seam (and
# therefore the DatabaseUrl handoff) uses.
# ---------------------------------------------------------------------------


def test_main_writes_an_honest_recovery_document_when_no_port_is_available(
    tmp_path, capsys, monkeypatch
) -> None:
    """Regression for the exact LPM failure shape: every candidate port
    rejected. main() must halt BEFORE touching any real seam (no password
    generated, no journal-driving engine call), write PROVISION-RECOVERY.md
    naming the Windows-excluded ranges and the winnat fix commands, print no
    DatabaseUrl handoff, and exit EXIT_PROVISIONING_FAILED -- never let a bare
    pg_ctl crash reach the operator."""

    import pathlib

    import civiccast.native.provision.__main__ as provision_main
    from civiccast.native.provision.port_select import PortAttempt, PortSelectionResult

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )

    netsh_text = "      5432        5432     *\n     50000       50059     *\n"
    fake_result = PortSelectionResult(
        outcome="no_candidate_available",
        port=None,
        attempts=tuple(
            PortAttempt(
                port=port,
                outcome="bind_failed",
                detail=f"bind failed on 127.0.0.1:{port} (winerror=10013): Permission denied",
            )
            for port in (5432, 5433, 5434, 5435, 5544)
        ),
        detail="no usable port on host '127.0.0.1'; every candidate was rejected",
        netsh_raw_output=netsh_text,
    )
    monkeypatch.setattr(provision_main, "resolve_provision_port", lambda **kwargs: fake_result)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("must not run any real seam once port selection fails")

    monkeypatch.setattr(provision_main, "run_provision", fail_if_called)
    monkeypatch.setattr(provision_main, "generate_database_password", fail_if_called)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_PROVISIONING_FAILED
    captured = capsys.readouterr()
    assert HANDOFF_MARKER_PREFIX not in captured.out
    assert "no usable PostgreSQL port" in captured.err

    recovery_doc = pathlib.Path(paths.state_root) / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), "the no-port-available halt must write the recovery document"
    content = recovery_doc.read_text(encoding="utf-8")
    for port in (5432, 5433, 5434, 5435, 5544):
        assert str(port) in content
    assert "winnat" in content
    assert "net stop winnat" in content and "net start winnat" in content
    assert "netsh int ipv4 show excludedportrange" in content
    # The raw netsh output is quoted verbatim, not just summarized.
    assert "50000" in content and "5432        5432" in content


def test_main_uses_the_fallback_port_and_it_flows_into_the_provisioned_context(
    tmp_path, capsys, monkeypatch
) -> None:
    """When resolve_provision_port falls back off the preferred 5432 (the
    excluded-range/bind-refusal case both real installer runs hit), the
    FALLBACK port -- not 5432 -- must be what lands in context.postgres_port,
    the single field every downstream seam (config render, pg_ctl argv,
    resolve_database_url's DatabaseUrl) derives the port from."""

    import civiccast.native.provision.__main__ as provision_main
    from civiccast.native.provision.port_select import PortAttempt, PortSelectionResult

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    scratch_url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"
    engine_calls = _wire_fresh_install_run_path(monkeypatch, scratch_url)

    fake_result = PortSelectionResult(
        outcome="selected",
        port=5433,
        attempts=(
            PortAttempt(
                port=5432,
                outcome="bind_failed",
                detail="bind failed on 127.0.0.1:5432 (winerror=10013): Permission denied",
            ),
            PortAttempt(port=5433, outcome="available", detail="bind succeeded on 127.0.0.1:5433"),
        ),
        detail="selected port 5433: bind succeeded on 127.0.0.1:5433",
    )
    # Overrides _wire_fresh_install_run_path's own default (preferred-port-
    # available) fake -- this test proves the FALLBACK path specifically.
    monkeypatch.setattr(provision_main, "resolve_provision_port", lambda **kwargs: fake_result)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_SUCCESS
    assert engine_calls, "the engine must still run, against the fallback port"
    _, engine_context = engine_calls[0]
    assert engine_context.postgres_port == 5433, (
        "the fallback port selection must flow into the provisioned context -- the "
        "single source of truth every downstream consumer reads the port from"
    )
    captured = capsys.readouterr()
    assert "postgres port 5432 was unavailable" in captured.err
    assert "selected fallback port 5433" in captured.err


def test_main_migration_failure_exits_its_own_code_and_never_leaks_the_password(
    tmp_path, capsys, monkeypatch
) -> None:
    """A migration failure after a successful engine run must be LOUD and
    step-identifying (EXIT_SCHEMA_MIGRATION_FAILED=30, distinct from the
    engine's 10 / repair's 20 / unexpected's 40, decade-spaced like
    upgrade.__main__'s _EXIT_CODES), must NOT print the handoff line (no
    registry value for a schema-less database), and must never let the
    generated credential reach stderr even when the exception text embeds
    the connection URL."""

    import pathlib

    import civiccast.native.provision.__main__ as provision_main

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    scratch_url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    _wire_fresh_install_run_path(monkeypatch, scratch_url)

    generated: list[str] = []

    def failing_migrate(context, *, pg_ctl_path, database_url, install_root):
        generated.append(context.database_password)
        raise RuntimeError(
            f"alembic exploded connecting to {database_url} as {context.database_password}"
        )

    monkeypatch.setattr(provision_main, "migrate_provisioned_schema", failing_migrate)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_SCHEMA_MIGRATION_FAILED == 30
    captured = capsys.readouterr()
    assert HANDOFF_MARKER_PREFIX not in captured.out
    assert "schema_migration_failed" in captured.err
    assert generated, "the failing migrate seam must have observed the run's password"
    assert generated[0] not in captured.err, "the generated password reached stderr"

    # BUG 2: a schema-migration failure ALSO collapses to the installer's
    # generic "see ... PROVISION-RECOVERY.md" exit-75 message -- it must
    # leave that document behind too, not just an in-engine journal halt.
    recovery_doc = pathlib.Path(paths.state_root) / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), (
        "a post-provision schema-migration failure must write the recovery document"
    )
    content = recovery_doc.read_text(encoding="utf-8")
    assert generated[0] not in content, "the generated password reached the recovery document"


def test_main_pgdata_acl_failure_inside_migrate_exits_its_own_code_not_alembics(
    tmp_path, capsys, monkeypatch
) -> None:
    """F6 (audit follow-up): migrate_provisioned_schema's OWN
    normalize_pgdata_acl call (inside _start_provisioned_cluster,
    re-starting the just-provisioned cluster to run the migration) can raise
    PgDataAclError before alembic is ever reached. Before this fix that fell
    into the same generic ``except Exception`` as a real alembic failure and
    was misreported as EXIT_SCHEMA_MIGRATION_FAILED with "'alembic upgrade
    head' did not complete" -- the wrong step name for a failure that never
    got that far. This must be caught DISTINCTLY: its own step-identifying
    exit code (EXIT_SCHEMA_ACL_NORMALIZATION_FAILED=50, the next unused value
    in the decade-spaced band), its own message naming the ACL step (not
    alembic), the handoff line still correctly suppressed (a machine whose
    pgdata ACL could not be normalized must not advertise a DatabaseUrl --
    that suppression is CORRECT here, unlike the wrong step name), and the
    generated credential must still never reach stderr."""

    import pathlib

    import civiccast.native.provision.__main__ as provision_main
    from civiccast.native.pgdata_acl import FAILURE_STEP, PgDataAclError

    install_root = tmp_path / "install"
    program_data_root = tmp_path / "pd"
    scratch_url = f"sqlite:///{(tmp_path / 'scratch.db').as_posix()}"
    paths = resolve_provision_paths(
        install_root=str(install_root), program_data_root=str(program_data_root)
    )
    _wire_fresh_install_run_path(monkeypatch, scratch_url)

    generated: list[str] = []

    def failing_migrate(context, *, pg_ctl_path, database_url, install_root):
        generated.append(context.database_password)
        raise PgDataAclError(
            f"{FAILURE_STEP}: could not apply the normalized DACL to "
            f"{context.postgres_data_dir!r}: access denied writing the DACL"
        )

    monkeypatch.setattr(provision_main, "migrate_provisioned_schema", failing_migrate)

    code = main(
        _required_args(
            tmp_path,
            **{
                "--install-root": str(install_root),
                "--program-data-root": str(program_data_root),
                "--pack-public-key-base64": _valid_pack_key_b64(),
            },
        )
    )

    assert code == EXIT_SCHEMA_ACL_NORMALIZATION_FAILED == 50
    captured = capsys.readouterr()
    assert HANDOFF_MARKER_PREFIX not in captured.out, (
        "a machine whose pgdata ACL could not be normalized must not advertise a "
        "DatabaseUrl -- the handoff line must still be suppressed"
    )
    assert "schema_acl_normalization_failed" in captured.err
    assert "did not complete" not in captured.err, (
        "this must not be reported with the alembic-failure wording -- it never "
        "reached alembic at all"
    )
    assert "'alembic upgrade head' was never attempted" in captured.err
    assert FAILURE_STEP in captured.err, "the ACL step's own breadcrumb must be preserved"
    assert generated, "the failing migrate seam must have observed the run's password"
    assert generated[0] not in captured.err, "the generated password reached stderr"

    # BUG 2: this ALSO collapses to the installer's generic exit-75 message.
    recovery_doc = pathlib.Path(paths.state_root) / "PROVISION-RECOVERY.md"
    assert recovery_doc.exists(), "an ACL-normalization failure must write the recovery document"
    content = recovery_doc.read_text(encoding="utf-8")
    assert generated[0] not in content, "the generated password reached the recovery document"


# Setup-nonce generation + handoff (native front door) was retired
# 2026-08-29 (owner decision): the control plane binds 127.0.0.1 only, so
# first setup is unreachable from the network by construction and the nonce
# was a redundant gate that produced repeated field failures. First setup is
# now admitted by loopback alone
# (civiccast.installer.router._require_local_setup_request). The tests that
# used to live in this section covered civiccast.native.setup_nonce and the
# provision CLI's SETUP_NONCE_MARKER_PREFIX handoff line, both removed.
