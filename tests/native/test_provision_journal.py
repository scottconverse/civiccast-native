# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Journal state-machine + durable-persistence tests for the provisioning
engine. These pin the transition grammar and the fail-loud/atomic
persistence behavior that makes a resume trustworthy after a power-loss
kill. Pure -- no Windows, no Postgres."""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.native.provision.journal import (
    JournalError,
    advance,
    ignored_journal_keys,
    journal_path,
    load_journal,
    load_journal_with_ignored_keys,
    write_journal,
)
from civiccast.native.provision.models import (
    ProvisionContext,
    ProvisionJournal,
    ProvisionPhase,
    ProvisionPlan,
)


def _plan() -> ProvisionPlan:
    return ProvisionPlan(
        postgres_major_version="17",
        database_name="civiccast",
        database_username="civiccast_svc",
        server_pack_product_version="1.0.0",
        server_pack_compatible_core="1.0.0",
        server_pack_signing_key_id="key-1",
    )


def _context(tmp_path: Path, *, database_password: str = "hunter2") -> ProvisionContext:
    return ProvisionContext(
        postgres_data_dir=str(tmp_path / "pgdata"),
        postgres_config_path=str(tmp_path / "pgdata" / "postgresql.conf"),
        postgres_hba_path=str(tmp_path / "pgdata" / "pg_hba.conf"),
        database_password=database_password,
        server_pack_path=str(tmp_path / "server-binaries.ccpack"),
        state_root=str(tmp_path / "state"),
        owner_run_id="run-1",
    )


def _journal(tmp_path: Path) -> ProvisionJournal:
    return ProvisionJournal(plan=_plan(), context=_context(tmp_path), phase=ProvisionPhase.INIT)


# --- transition grammar -------------------------------------------------------


def test_advance_one_forward_boundary_ok(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    j2 = advance(j, ProvisionPhase.PACK_VERIFIED, "pack verified")
    assert j2.phase is ProvisionPhase.PACK_VERIFIED
    assert j2.history[-1][0] == ProvisionPhase.PACK_VERIFIED.value


def test_advance_skipping_a_forward_boundary_is_rejected(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    with pytest.raises(JournalError, match="illegal forward transition"):
        advance(j, ProvisionPhase.POSTGRES_CLUSTER_READY, "skipped a boundary")


def test_advance_to_terminal_from_any_phase_ok(tmp_path: Path) -> None:
    j = advance(_journal(tmp_path), ProvisionPhase.PACK_VERIFIED, "verified")
    failed = advance(j, ProvisionPhase.FAILED, "halted")
    assert failed.phase is ProvisionPhase.FAILED


def test_cannot_advance_from_a_terminal_phase(tmp_path: Path) -> None:
    j = advance(_journal(tmp_path), ProvisionPhase.FAILED, "halted")
    with pytest.raises(JournalError, match="terminal"):
        advance(j, ProvisionPhase.PACK_VERIFIED, "should not be allowed")


def test_history_is_append_only(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    j = advance(j, ProvisionPhase.PACK_VERIFIED, "a")
    j = advance(j, ProvisionPhase.POSTGRES_CLUSTER_READY, "b")
    assert [h[0] for h in j.history] == [
        ProvisionPhase.PACK_VERIFIED.value,
        ProvisionPhase.POSTGRES_CLUSTER_READY.value,
    ]


# --- durable persistence ------------------------------------------------------


def test_write_then_load_roundtrips(tmp_path: Path) -> None:
    j = advance(_journal(tmp_path), ProvisionPhase.PACK_VERIFIED, "verified")
    write_journal(j)
    loaded = load_journal(j.context.state_root)
    assert loaded is not None
    assert loaded.phase is ProvisionPhase.PACK_VERIFIED
    assert loaded.plan.database_name == "civiccast"


def test_load_missing_journal_returns_none(tmp_path: Path) -> None:
    assert load_journal(str(tmp_path / "nonexistent")) is None


def test_load_corrupt_journal_raises_fail_loud(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    journal_path(state_root).write_text("{ this is not valid json", encoding="utf-8")
    with pytest.raises(JournalError, match=r"corrupt|unparseable"):
        load_journal(str(state_root))


def test_load_journal_missing_required_sections_raises(tmp_path: Path) -> None:
    """``plan`` and ``context`` are required. (Before beta.5.1 this case also
    failed on ``unexpected_field``; unknown keys are tolerated now, so the
    ONLY thing keeping this journal unparseable is the missing sections --
    pinned by matching the message on them.)"""

    state_root = tmp_path / "state"
    state_root.mkdir()
    journal_path(state_root).write_text(
        '{"schema_version": 1, "unexpected_field": true}', encoding="utf-8"
    )
    with pytest.raises(JournalError, match=r"(?s)corrupt/unparseable.*\bplan\b.*\bcontext\b"):
        load_journal(str(state_root))


def test_write_leaves_no_temp_files_behind(tmp_path: Path) -> None:
    j = _journal(tmp_path)
    write_journal(j)
    leftovers = [p.name for p in Path(j.context.state_root).glob("*.tmp")]
    assert leftovers == []


def test_write_journal_survives_a_simulated_kill_leaving_only_the_prior_complete_file(
    tmp_path: Path,
) -> None:
    # Write once, then simulate a kill mid-second-write by leaving a stale
    # temp file around; the loader must never see it (only *.tmp is glob'd
    # by the writer's own unique-name scheme, and the real journal path is
    # untouched until the atomic replace).
    j = _journal(tmp_path)
    write_journal(j)
    state_root = Path(j.context.state_root)
    stale_tmp = state_root / f"{journal_path(state_root).name}.999999.tmp"
    stale_tmp.write_text("not a real journal", encoding="utf-8")

    loaded = load_journal(str(state_root))
    assert loaded is not None
    assert loaded.phase is ProvisionPhase.INIT


# --- security fix (2026-07-30): password redaction + state-root ACL hardening -


def test_write_journal_never_persists_the_plaintext_password(tmp_path: Path) -> None:
    """The core of the (A) fix: a distinctive password must not appear
    ANYWHERE in the serialized bytes on disk, and the in-memory object the
    caller still holds must be untouched (only the on-disk copy is
    redacted)."""

    distinctive_password = "TEST-ONLY-DISTINCTIVE-PW-9f3c7a1e6b2d"
    context = _context(tmp_path, database_password=distinctive_password)
    j = ProvisionJournal(plan=_plan(), context=context, phase=ProvisionPhase.INIT)

    path = write_journal(j)

    raw_bytes = path.read_bytes()
    assert distinctive_password.encode("utf-8") not in raw_bytes, (
        "the plaintext database password must never be written to the journal file"
    )
    assert b"REDACTED" in raw_bytes, "a redaction marker must stand in for the password"
    # The caller's own in-memory object is a separate concern from the disk
    # copy -- redaction happens only in write_journal's serialized payload.
    assert j.context.database_password == distinctive_password


def test_loading_a_redacted_journal_still_succeeds(tmp_path: Path) -> None:
    """A loaded (resumed) journal must still validate cleanly against
    :class:`ProvisionContext`'s ``Field(min_length=1)`` constraint on
    ``database_password`` -- the redaction marker is non-empty, so a resume
    over a redacted journal is not itself broken by this fix."""

    j = _journal(tmp_path)
    write_journal(j)
    loaded = load_journal(j.context.state_root)
    assert loaded is not None
    assert loaded.context.database_password  # non-empty; schema still valid
    assert loaded.context.database_password != "hunter2"


def test_write_journal_invokes_state_root_acl_hardening(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The core of the (B) fix's "hardening code path is invoked when the
    location is created" requirement -- cross-platform (no real Win32 call
    here; see ``test_provision_journal_win.py`` for the REAL DACL-content
    proof, Windows-only). Spies on the real hardening function so this
    passes/fails on the actual wiring, not a restated assumption."""

    import civiccast.native.provision.journal as journal_module

    calls: list[Path] = []
    monkeypatch.setattr(
        journal_module,
        "_harden_state_root_acl",
        lambda state_root: calls.append(state_root),
    )

    j = _journal(tmp_path)
    write_journal(j)

    assert calls == [Path(j.context.state_root)]


# --- legacy / unknown keys (beta.5.1, 2026-09-09) -----------------------------

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "provision"
_LEGACY_AUGUST_JOURNAL = _FIXTURES / "provision-journal-2026-08-15-beta1-nats.json"
_LEGACY_NATS_KEYS = [
    "context.nats_config_path",
    "context.nats_host",
    "context.nats_port",
    "context.nats_store_dir",
    "context.nats_tls",
]


def _stage_raw_journal(tmp_path: Path, raw: str) -> Path:
    """Put ``raw`` on disk exactly as a prior installer would have left it
    (NOT through write_journal, which only ever serialises declared fields)."""

    state_root = tmp_path / "state"
    state_root.mkdir()
    path = journal_path(state_root)
    path.write_text(raw, encoding="utf-8")
    return state_root


def test_load_journal_tolerates_the_august_beta1_nats_context_fields(
    tmp_path: Path, caplog
) -> None:
    """The measured upgrade halt: a valid ``phase: complete`` journal written
    by the August 2026 installer carries five ``context.nats_*`` keys the
    model dropped in 85ffe6c0. It must LOAD (so the upgrade adopts the
    station), drop the keys, and say so once at INFO."""

    import logging

    state_root = _stage_raw_journal(tmp_path, _LEGACY_AUGUST_JOURNAL.read_text(encoding="utf-8"))

    with caplog.at_level(logging.INFO, logger="civiccast.native.provision.journal"):
        loaded = load_journal(state_root)

    assert loaded is not None
    assert loaded.phase is ProvisionPhase.COMPLETE
    assert loaded.schema_version == 1
    assert loaded.history[-1][2] == "provisioning complete"
    # The legacy history phases are plain strings and load unchanged.
    assert [entry[0] for entry in loaded.history[4:6]] == [
        "nats_store_ready",
        "nats_config_written",
    ]
    for key in _LEGACY_NATS_KEYS:
        assert not hasattr(loaded.context, key.removeprefix("context.")), key
    assert loaded.context.postgres_data_dir.endswith(r"\data\pgdata")

    info_lines = [
        r for r in caplog.records if r.levelno == logging.INFO and "ignored" in r.getMessage()
    ]
    assert len(info_lines) == 1, caplog.text
    message = info_lines[0].getMessage()
    assert "5 field(s)" in message
    for key in _LEGACY_NATS_KEYS:
        assert key in message


def test_load_journal_with_ignored_keys_returns_the_keys_from_the_single_read(
    tmp_path: Path, monkeypatch
) -> None:
    """The ignored-key list comes back with the journal from ONE read of the
    file (round-3 F2: main() used to re-read the file unguarded to compute
    it). Prove the single read by counting, and prove the read failure is a
    JournalError rather than a bare OSError."""

    state_root = _stage_raw_journal(tmp_path, _LEGACY_AUGUST_JOURNAL.read_text(encoding="utf-8"))
    reads: list[Path] = []
    real_read_text = Path.read_text

    def counting_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.name == "provision-journal.json":
            reads.append(self)
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting_read_text)
    journal, ignored = load_journal_with_ignored_keys(state_root)
    assert journal is not None
    assert journal.phase is ProvisionPhase.COMPLETE
    assert ignored == _LEGACY_NATS_KEYS
    assert len(reads) == 1, reads

    assert load_journal_with_ignored_keys(tmp_path / "nowhere") == (None, [])

    def yanked_read_text(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise OSError("file yanked between exists() and read")

    monkeypatch.setattr(Path, "read_text", yanked_read_text)
    with pytest.raises(JournalError, match="cannot read journal"):
        load_journal_with_ignored_keys(state_root)


def test_ignored_journal_keys_names_exactly_the_undeclared_keys() -> None:
    raw = _LEGACY_AUGUST_JOURNAL.read_text(encoding="utf-8")
    assert ignored_journal_keys(raw) == _LEGACY_NATS_KEYS
    assert ignored_journal_keys("{not json") == []
    assert ignored_journal_keys("[1, 2]") == []


def test_load_journal_tolerates_a_genuinely_unknown_future_field(tmp_path: Path, caplog) -> None:
    """A journal from a NEWER installer (a downgrade/reinstall over preserved
    ProgramData) may carry keys this version has never heard of. Same rule:
    load, drop, log -- never halt."""

    import json
    import logging

    data = json.loads(_LEGACY_AUGUST_JOURNAL.read_text(encoding="utf-8"))
    for key in ("nats_config_path", "nats_host", "nats_port", "nats_store_dir", "nats_tls"):
        del data["context"][key]
    data["future_top_level_field"] = {"anything": True}
    data["context"]["future_context_field"] = "x"
    data["plan"]["future_plan_field"] = 7
    state_root = _stage_raw_journal(tmp_path, json.dumps(data))

    with caplog.at_level(logging.INFO, logger="civiccast.native.provision.journal"):
        loaded = load_journal(state_root)

    assert loaded is not None
    assert loaded.phase is ProvisionPhase.COMPLETE
    assert ignored_journal_keys(json.dumps(data)) == [
        "context.future_context_field",
        "future_top_level_field",
        "plan.future_plan_field",
    ]
    assert (
        "context.future_context_field, future_top_level_field, plan.future_plan_field"
        in caplog.text
    )


def test_load_journal_logs_nothing_about_ignored_keys_for_a_current_journal(
    tmp_path: Path, caplog
) -> None:
    import logging

    write_journal(_journal(tmp_path))
    with caplog.at_level(logging.INFO, logger="civiccast.native.provision.journal"):
        assert load_journal(tmp_path / "state") is not None
    assert "ignored" not in caplog.text


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.__setitem__("phase", "nats_store_ready"), "phase"),
        (
            lambda d: d["context"].__setitem__("postgres_port", "five-four-three-two"),
            "postgres_port",
        ),
        (lambda d: d["plan"].pop("postgres_major_version"), "postgres_major_version"),
    ],
    ids=["unknown-phase", "type-drift", "missing-required"],
)
def test_load_journal_still_fails_loud_on_real_corruption(tmp_path: Path, mutate, match) -> None:
    """Tolerance is for unknown KEY NAMES only. An unknown phase value, a
    wrong type, or a missing required field is still a value we cannot
    trust, and still a JournalError (never a silent fresh start)."""

    import json

    data = json.loads(_LEGACY_AUGUST_JOURNAL.read_text(encoding="utf-8"))
    mutate(data)
    state_root = _stage_raw_journal(tmp_path, json.dumps(data))
    with pytest.raises(JournalError, match=match):
        load_journal(state_root)


def test_write_journal_serialises_only_declared_fields_over_a_loaded_legacy_journal(
    tmp_path: Path,
) -> None:
    """A UNIT property of write_journal, not a CLI path: a journal loaded
    from the legacy file and written back contains only declared fields, so
    the nats_* keys are gone and the next load has nothing to ignore.
    Neither real CLI path over such a station exercises this -- ADOPT_EXISTING
    unlinks the journal before the engine writes a fresh one, and
    NOOP_REUSE_EXISTING never writes it (see
    tests/native/test_provision_cli.py)."""

    import json

    data = json.loads(_LEGACY_AUGUST_JOURNAL.read_text(encoding="utf-8"))
    state_root = tmp_path / "state"
    for key in (
        "postgres_data_dir",
        "postgres_config_path",
        "postgres_hba_path",
        "server_pack_path",
    ):
        data["context"][key] = str(tmp_path / key)
    data["context"]["state_root"] = str(state_root)
    _stage_raw_journal(tmp_path, json.dumps(data))

    loaded = load_journal(state_root)
    assert loaded is not None
    path = write_journal(loaded)
    rewritten = path.read_text(encoding="utf-8")
    rewritten_context = json.loads(rewritten)["context"]
    assert not [k for k in rewritten_context if k.startswith("nats_")], rewritten_context
    assert ignored_journal_keys(rewritten) == []
    reloaded = load_journal(state_root)
    assert reloaded is not None and reloaded.phase is ProvisionPhase.COMPLETE
