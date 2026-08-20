# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Media-integrity scan worker tests (4.0 media-library-hardening).

Mirrors ``tests/schedule/test_retention_worker.py``'s structure and
fixture style — the two workers share the same shape
(env-gated settings, ``run_once``/``run_forever``, SQLite session-factory
fixture) by design.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.media_integrity_worker import (
    MediaIntegrityWorker,
    MediaIntegrityWorkerSettings,
)
from civiccast.schedule.models import Asset

_NOW = datetime(2026, 6, 10, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    eng = eng.execution_options(schema_translate_map={"civiccast": None})
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


def _seed_asset(
    engine: Engine,
    asset_id: str,
    *,
    file_path: str | None,
    file_status: str = "ok",
) -> None:
    with Session(bind=engine) as session:
        session.add(
            Asset(
                asset_id=asset_id,
                title=f"Asset {asset_id}",
                state="validated",
                manifest_url=None,
                file_path=file_path,
                file_status=file_status,
            )
        )
        session.commit()


def _worker(session_factory) -> MediaIntegrityWorker:  # type: ignore[no-untyped-def]
    return MediaIntegrityWorker(
        session_factory,
        settings=MediaIntegrityWorkerSettings(mode="inline", poll_seconds=3600.0),
    )


class TestScanning:
    def test_asset_with_missing_file_is_flagged(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        gone_path = tmp_path / "gone.mp4"  # never created
        _seed_asset(engine, "asset-1", file_path=str(gone_path))
        worker = _worker(session_factory)

        changed = worker.run_once(now=_NOW)

        assert [c.asset_id for c in changed] == ["asset-1"]
        assert changed[0].file_status == "missing"

    def test_asset_with_existing_file_is_not_flagged(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        present_path = tmp_path / "present.mp4"
        present_path.write_bytes(b"fake video bytes")
        _seed_asset(engine, "asset-1", file_path=str(present_path))
        worker = _worker(session_factory)

        assert worker.run_once(now=_NOW) == []

    def test_assets_without_a_file_path_are_skipped(self, engine: Engine, session_factory) -> None:
        _seed_asset(engine, "manifest-only", file_path=None)
        worker = _worker(session_factory)

        assert worker.run_once(now=_NOW) == []

    def test_scan_is_idempotent_once_flagged(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        gone_path = tmp_path / "gone.mp4"
        _seed_asset(engine, "asset-1", file_path=str(gone_path))
        worker = _worker(session_factory)

        first = worker.run_once(now=_NOW)
        second = worker.run_once(now=_NOW)

        assert len(first) == 1
        assert second == [], "already-missing asset must not be re-flagged as changed"

    def test_file_status_checked_at_is_stamped(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        gone_path = tmp_path / "gone.mp4"
        _seed_asset(engine, "asset-1", file_path=str(gone_path))
        _worker(session_factory).run_once(now=_NOW)

        with Session(bind=engine) as session:
            row = session.get(Asset, "asset-1")
            assert row is not None
            checked_at = row.file_status_checked_at
            if checked_at is not None and checked_at.tzinfo is None:
                checked_at = checked_at.replace(tzinfo=UTC)  # SQLite drops tz
            assert checked_at == _NOW

    def test_file_reappearing_clears_the_missing_flag(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        """A file restored to its recorded path (e.g. NAS reconnected) clears
        automatically on the next scan — no manual relink needed."""
        path = tmp_path / "flaky.mp4"
        _seed_asset(engine, "asset-1", file_path=str(path), file_status="missing")
        worker = _worker(session_factory)

        path.write_bytes(b"the file is back")
        changed = worker.run_once(now=_NOW)

        assert [c.asset_id for c in changed] == ["asset-1"]
        assert changed[0].file_status == "ok"

    def test_never_deletes_or_mutates_other_columns(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        gone_path = tmp_path / "gone.mp4"
        _seed_asset(engine, "asset-1", file_path=str(gone_path))
        _worker(session_factory).run_once(now=_NOW)

        with Session(bind=engine) as session:
            row = session.get(Asset, "asset-1")
            assert row is not None
            assert row.title == "Asset asset-1"
            assert row.file_path == str(gone_path)


class TestMassMissingGuard:
    """A transient storage outage (unmounted NAS, disconnected drive) must
    not flag the entire library missing in one pass."""

    def test_mass_missing_pass_writes_nothing(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        """All 4 assets vanish at once (simulated unmounted root) — the
        guard (>50% newly missing AND >= floor of 3) vetoes the pass;
        every row keeps its prior 'ok' status."""
        vanished_root = tmp_path / "unmounted-share"  # never created
        for i in range(4):
            _seed_asset(engine, f"asset-{i}", file_path=str(vanished_root / f"{i}.mp4"))

        changed = _worker(session_factory).run_once(now=_NOW)

        assert changed == []
        with Session(bind=engine) as session:
            for i in range(4):
                row = session.get(Asset, f"asset-{i}")
                assert row is not None
                assert row.file_status == "ok", "guard must leave prior state intact"

    def test_single_missing_among_many_still_flags(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        """Ordinary individual file loss is below both guard thresholds
        and must be flagged exactly as before."""
        for i in range(3):
            present = tmp_path / f"present-{i}.mp4"
            present.write_bytes(b"still here")
            _seed_asset(engine, f"ok-{i}", file_path=str(present))
        _seed_asset(engine, "gone-1", file_path=str(tmp_path / "gone.mp4"))

        changed = _worker(session_factory).run_once(now=_NOW)

        assert [c.asset_id for c in changed] == ["gone-1"]
        assert changed[0].file_status == "missing"

    def test_guard_floor_keeps_small_libraries_flaggable(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        """2 of 2 missing is 100% but below the absolute floor (3) — a
        small station's genuinely deleted files still get flagged rather
        than being mistaken for a storage outage forever."""
        _seed_asset(engine, "gone-a", file_path=str(tmp_path / "a.mp4"))
        _seed_asset(engine, "gone-b", file_path=str(tmp_path / "b.mp4"))

        changed = _worker(session_factory).run_once(now=_NOW)

        assert sorted(c.asset_id for c in changed) == ["gone-a", "gone-b"]

    def test_recovery_after_guarded_pass_proceeds_normally(
        self, engine: Engine, session_factory, tmp_path
    ) -> None:
        """Mount returns after a guarded pass: the next pass sees the
        files again and nothing was ever flagged — prior state was
        preserved through the outage (self-heal behavior unchanged)."""
        root = tmp_path / "share"
        for i in range(4):
            _seed_asset(engine, f"asset-{i}", file_path=str(root / f"{i}.mp4"))
        worker = _worker(session_factory)

        assert worker.run_once(now=_NOW) == []  # outage pass: guard trips

        root.mkdir()
        for i in range(4):
            (root / f"{i}.mp4").write_bytes(b"back online")

        assert worker.run_once(now=_NOW) == []  # all ok, nothing to change
        with Session(bind=engine) as session:
            for i in range(4):
                row = session.get(Asset, f"asset-{i}")
                assert row is not None
                assert row.file_status == "ok"


class TestSettings:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("CIVICCAST_MEDIA_INTEGRITY_WORKER", "CIVICCAST_MEDIA_INTEGRITY_POLL_SECONDS"):
            monkeypatch.delenv(name, raising=False)
        settings = MediaIntegrityWorkerSettings.from_env()
        assert settings.mode == "inline"
        assert settings.poll_seconds == 3600.0

    def test_invalid_mode_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_MEDIA_INTEGRITY_WORKER", "sometimes")
        with pytest.raises(ValueError, match="CIVICCAST_MEDIA_INTEGRITY_WORKER"):
            MediaIntegrityWorkerSettings.from_env()

    def test_invalid_poll_seconds_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_MEDIA_INTEGRITY_POLL_SECONDS", "not-a-number")
        with pytest.raises(ValueError, match="CIVICCAST_MEDIA_INTEGRITY_POLL_SECONDS"):
            MediaIntegrityWorkerSettings.from_env()
