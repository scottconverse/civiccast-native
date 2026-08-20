# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Journal state-machine + durable-persistence tests for the provisioning
engine. These pin the transition grammar and the fail-loud/atomic
persistence behavior that makes a resume trustworthy after a power-loss
kill. Pure -- no Windows, no Postgres, no NATS."""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.native.provision.journal import (
    JournalError,
    advance,
    journal_path,
    load_journal,
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
        nats_store_dir=str(tmp_path / "nats" / "store"),
        nats_config_path=str(tmp_path / "nats" / "nats-server.conf"),
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


def test_load_schema_drifted_journal_raises(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    journal_path(state_root).write_text(
        '{"schema_version": 1, "unexpected_field": true}', encoding="utf-8"
    )
    with pytest.raises(JournalError):
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
