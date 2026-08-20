# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Session↔recording-target provenance tests (Beta sprint B1, decision #5).

The worker previously *guessed* where a session's recording lives by scanning
the global ordered bag of recording targets — wrong the moment a station has
more than one target (audit ENG-005; the rehearsal-target exclusion was an
interim patch). Provenance by construction: ``go_on_air`` stamps the resolved
recording target onto the session, and the finalization worker uses the stamp
instead of guessing. Legacy sessions without a stamp keep the scan fallback.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401 - register Asset tables on Base
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.finalization_worker import LiveFinalizationWorker
from civiccast.live.models import (
    FINALIZATION_STATE_COMPLETED,
    LiveSession,
    LiveSessionCreate,
    RecordingTarget,
)
from civiccast.live.store import LiveSessionStore
from civiccast.schedule.models import Asset


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


def _add_target(engine: Engine, target_id: str, uri: str, *, created: datetime) -> None:
    with Session(bind=engine) as session:
        session.add(
            RecordingTarget(
                recording_target_id=target_id,
                name=target_id,
                target_uri=uri,
                created_at=created,
            )
        )
        session.commit()


def _drive_to_on_air(store: LiveSessionStore, session_id: str = "prov-session") -> None:
    store.create_session(
        LiveSessionCreate(
            live_session_id=session_id,
            channel_id="gov-ch12",
            title="Provenance test session",
        )
    )
    store.start_preflight(session_id)
    store.go_on_air(session_id)


class TestGoOnAirStampsTarget:
    def test_stamps_first_resolvable_non_rehearsal_target(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        rehearsal = tmp_path / "private-rehearsals"
        real = tmp_path / "real"
        rehearsal.mkdir()
        real.mkdir()
        _add_target(
            engine,
            "local-rehearsal-recordings",
            rehearsal.as_uri(),
            created=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
        )
        _add_target(
            engine, "fs-real", real.as_uri(), created=datetime(2026, 6, 10, 10, 0, tzinfo=UTC)
        )

        store = LiveSessionStore(session_factory)
        _drive_to_on_air(store)

        with Session(bind=engine) as session:
            row = session.execute(
                select(LiveSession).where(LiveSession.live_session_id == "prov-session")
            ).scalar_one()
            assert row.recording_target_id == "fs-real"
            assert row.recording_target_uri == real.as_uri()

    def test_no_resolvable_target_stamps_nothing(self, engine: Engine, session_factory) -> None:
        store = LiveSessionStore(session_factory)
        _drive_to_on_air(store)

        with Session(bind=engine) as session:
            row = session.execute(
                select(LiveSession).where(LiveSession.live_session_id == "prov-session")
            ).scalar_one()
            assert row.recording_target_id is None
            assert row.recording_target_uri is None


class TestWorkerUsesStampedTarget:
    def _probe(self):  # type: ignore[no-untyped-def]
        from civiccast.schedule.ingest import FfprobeResult

        return FfprobeResult(
            duration_seconds=120,
            codec_video="h264",
            codec_audio="aac",
            width_px=1280,
            height_px=720,
            bitrate_bps=800_000,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
        )

    def _fake_packager(self, calls: list[dict[str, object]]):  # type: ignore[no-untyped-def]
        from types import SimpleNamespace

        def packager(input_path, output_dir, *, trim_in_seconds=None, trim_out_seconds=None):
            manifest = output_dir / "playlist.m3u8"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text("#EXTM3U\n", encoding="utf-8")
            calls.append({"input_path": input_path})
            return SimpleNamespace(manifest_path=manifest)

        return packager

    def test_worker_prefers_the_stamped_target_over_the_scan(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        """The legacy scan would pick target A (older); the stamp says B."""

        target_a = tmp_path / "a"
        target_b = tmp_path / "b"
        target_a.mkdir()
        target_b.mkdir()
        _add_target(
            engine, "fs-a", target_a.as_uri(), created=datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
        )
        store = LiveSessionStore(session_factory)
        _drive_to_on_air(store, "stamped-session")
        # Station re-points its recording target AFTER this session went on
        # air: a new target B is added and the session's stamp is B (simulate
        # the stamp directly — the point is the worker trusts the stamp).
        _add_target(
            engine, "fs-b", target_b.as_uri(), created=datetime(2026, 6, 10, 11, 0, tzinfo=UTC)
        )
        with Session(bind=engine) as session:
            row = session.execute(
                select(LiveSession).where(LiveSession.live_session_id == "stamped-session")
            ).scalar_one()
            row.recording_target_id = "fs-b"
            row.recording_target_uri = target_b.as_uri()
            session.commit()
        store.end_broadcast("stamped-session")
        # The recording exists under BOTH targets; only the stamped one is
        # correct (the scan-with-exists fallback would otherwise mask this).
        (target_a / "stamped-session.mp4").write_bytes(b"wrong recording")
        (target_b / "stamped-session.mp4").write_bytes(b"right recording")

        calls: list[dict[str, object]] = []
        worker = LiveFinalizationWorker(
            session_factory,
            packager=self._fake_packager(calls),
            probe=lambda _: self._probe(),
            settle_seconds=0,
        )
        status = worker.run_once(now=datetime(2026, 6, 10, 12, 0, tzinfo=UTC))[0]

        assert status.state == FINALIZATION_STATE_COMPLETED
        assert calls[0]["input_path"] == target_b / "stamped-session.mp4"
        with Session(bind=engine) as session:
            asset = session.execute(select(Asset)).scalars().first()
            assert asset is not None and asset.asset_id == "stamped-session"

    def test_unstamped_session_falls_back_to_the_scan(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        """Sessions that predate the stamp keep working via the scan."""

        target = tmp_path / "legacy"
        target.mkdir()
        with Session(bind=engine) as session:
            session.add(
                LiveSession(
                    live_session_id="legacy-session",
                    channel_id="gov-ch12",
                    title="Pre-provenance session",
                    state="ending",
                    ended_at=datetime(2026, 6, 10, 11, 0, tzinfo=UTC),
                )
            )
            session.commit()
        _add_target(
            engine, "fs-legacy", target.as_uri(), created=datetime(2026, 6, 10, 9, 0, tzinfo=UTC)
        )
        (target / "legacy-session.mp4").write_bytes(b"recording")

        calls: list[dict[str, object]] = []
        worker = LiveFinalizationWorker(
            session_factory,
            packager=self._fake_packager(calls),
            probe=lambda _: self._probe(),
            settle_seconds=0,
        )
        status = worker.run_once(now=datetime(2026, 6, 10, 12, 0, tzinfo=UTC))[0]

        assert status.state == FINALIZATION_STATE_COMPLETED
        assert calls[0]["input_path"] == target / "legacy-session.mp4"
