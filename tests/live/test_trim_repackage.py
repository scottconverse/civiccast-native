# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Repackage-on-trim-update tests (Beta sprint B3, decision #4).

Until this stage, an operator trim saved fine but the published video never
re-rendered — residents kept seeing the untrimmed recording (audit ENG-004:
"trim is decorative"). The worker now tracks WHAT trim each package was
rendered with (`packaged_trim_*`, migration 0029); when the asset's trim
diverges, the completed job re-enters the queue and the package is re-rendered
through the normal attempt machinery (same retries, backoff, failure codes).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401 - register Asset tables on Base
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.live.finalization_worker import LiveFinalizationWorker
from civiccast.live.models import (
    FINALIZATION_STATE_COMPLETED,
    FINALIZATION_STATE_FAILED,
    LIVE_SESSION_STATE_ENDING,
    LiveFinalizationJob,
    LiveSession,
    RecordingTarget,
)
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.models import Asset

_T0 = datetime(2026, 6, 10, 18, 0, tzinfo=UTC)


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


def _probe() -> FfprobeResult:
    return FfprobeResult(
        duration_seconds=120,
        codec_video="h264",
        codec_audio="aac",
        width_px=1280,
        height_px=720,
        bitrate_bps=800_000,
        format_name="mov,mp4,m4a,3gp,3g2,mj2",
    )


def _recording_packager(calls: list[dict[str, object]]):  # type: ignore[no-untyped-def]
    def packager(input_path, output_dir, *, trim_in_seconds=None, trim_out_seconds=None):  # type: ignore[no-untyped-def]
        manifest = output_dir / "playlist.m3u8"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(
            f"#EXTM3U\n#TRIM {trim_in_seconds} {trim_out_seconds}\n", encoding="utf-8"
        )
        calls.append({"trim_in": trim_in_seconds, "trim_out": trim_out_seconds})
        return SimpleNamespace(manifest_path=manifest)

    return packager


def _seed_session(engine: Engine, target_dir: Path) -> Path:
    recording = target_dir / "trim-session.mp4"
    recording.write_bytes(b"recording")
    with Session(bind=engine) as session:
        session.add(
            LiveSession(
                live_session_id="trim-session",
                channel_id="gov-ch12",
                title="Trim repackage test",
                state=LIVE_SESSION_STATE_ENDING,
                ended_at=_T0,
            )
        )
        session.add(
            RecordingTarget(
                recording_target_id="fs-trim",
                name="Trim recordings",
                target_uri=target_dir.as_uri(),
            )
        )
        session.commit()
    return recording


def _set_asset_trim(engine: Engine, trim_in: float | None, trim_out: float | None) -> None:
    with Session(bind=engine) as session:
        asset = session.execute(select(Asset).where(Asset.asset_id == "trim-session")).scalar_one()
        asset.trim_in_seconds = trim_in
        asset.trim_out_seconds = trim_out
        session.commit()


def _worker(session_factory, calls):  # type: ignore[no-untyped-def]
    return LiveFinalizationWorker(
        session_factory,
        packager=_recording_packager(calls),
        probe=lambda _: _probe(),
        settle_seconds=0,
        backoff_seconds=0,
        max_attempts=3,
    )


class TestRepackageOnTrimUpdate:
    def test_trim_change_re_renders_the_package_with_the_new_trim(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        _seed_session(engine, tmp_path)
        calls: list[dict[str, object]] = []
        worker = _worker(session_factory, calls)

        first = worker.run_once(now=_T0 + timedelta(minutes=1))[0]
        assert first.state == FINALIZATION_STATE_COMPLETED
        assert calls == [{"trim_in": None, "trim_out": None}]

        # Operator trims the asset after reviewing the recording.
        _set_asset_trim(engine, 5.0, 90.0)

        repackaged = worker.run_once(now=_T0 + timedelta(minutes=10))
        assert len(repackaged) == 1
        assert repackaged[0].state == FINALIZATION_STATE_COMPLETED
        assert calls[-1] == {"trim_in": 5.0, "trim_out": 90.0}
        manifest = tmp_path / "trim-session-hls" / "playlist.m3u8"
        assert "#TRIM 5.0 90.0" in manifest.read_text(encoding="utf-8")

    def test_no_trim_change_means_no_repackage(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        _seed_session(engine, tmp_path)
        calls: list[dict[str, object]] = []
        worker = _worker(session_factory, calls)
        worker.run_once(now=_T0 + timedelta(minutes=1))

        statuses = worker.run_once(now=_T0 + timedelta(minutes=10))

        assert statuses == [], "a completed job with matching trim stays out of the scan"
        assert len(calls) == 1

    def test_repackage_records_the_packaged_trim_on_the_job(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        _seed_session(engine, tmp_path)
        calls: list[dict[str, object]] = []
        worker = _worker(session_factory, calls)
        worker.run_once(now=_T0 + timedelta(minutes=1))
        _set_asset_trim(engine, 5.0, 90.0)
        worker.run_once(now=_T0 + timedelta(minutes=10))

        with Session(bind=engine) as session:
            job = session.get(LiveFinalizationJob, "trim-session")
            assert job is not None
            assert job.packaged_trim_in_seconds == 5.0
            assert job.packaged_trim_out_seconds == 90.0

    def test_clearing_the_trim_also_repackages(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        _seed_session(engine, tmp_path)
        calls: list[dict[str, object]] = []
        worker = _worker(session_factory, calls)
        worker.run_once(now=_T0 + timedelta(minutes=1))
        _set_asset_trim(engine, 5.0, 90.0)
        worker.run_once(now=_T0 + timedelta(minutes=10))

        _set_asset_trim(engine, None, None)
        statuses = worker.run_once(now=_T0 + timedelta(minutes=20))

        assert statuses[0].state == FINALIZATION_STATE_COMPLETED
        assert calls[-1] == {"trim_in": None, "trim_out": None}

    def test_operator_trim_edit_through_the_api_triggers_repackage(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        request: pytest.FixtureRequest,
    ) -> None:
        """The full operator path: PATCH the asset's trim over HTTP (the trim
        editor's call) and the worker re-renders the package."""

        from fastapi.testclient import TestClient
        from sqlalchemy.pool import StaticPool

        from civiccast.app import create_app
        from civiccast.schedule.router import get_postgres_store
        from civiccast.schedule.store import PostgresAssetStore

        eng = create_engine(
            "sqlite:///:memory:",
            future=True,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        ).execution_options(schema_translate_map={"civiccast": None})
        request.addfinalizer(eng.dispose)
        Base.metadata.create_all(eng)

        @contextmanager
        def factory() -> Iterator[Session]:
            with Session(bind=eng) as session:
                yield session

        recording = tmp_path / "trim-session.mp4"
        recording.write_bytes(b"recording")
        with Session(bind=eng) as session:
            session.add(
                LiveSession(
                    live_session_id="trim-session",
                    channel_id="gov-ch12",
                    title="Trim via API",
                    state=LIVE_SESSION_STATE_ENDING,
                    ended_at=_T0,
                )
            )
            session.add(
                RecordingTarget(
                    recording_target_id="fs-trim",
                    name="Trim recordings",
                    target_uri=tmp_path.as_uri(),
                )
            )
            session.commit()

        calls: list[dict[str, object]] = []
        worker = _worker(factory, calls)
        assert worker.run_once(now=_T0 + timedelta(minutes=1))[0].state == (
            FINALIZATION_STATE_COMPLETED
        )

        monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
        monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
        monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
        monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
        app = create_app()
        app.dependency_overrides[get_postgres_store] = lambda: PostgresAssetStore(factory)
        with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as client:
            current = client.get("/api/staff/assets/trim-session")
            assert current.status_code == 200, current.text
            response = client.patch(
                "/api/staff/assets/trim-session",
                json={
                    "trim_in_seconds": 5.0,
                    "trim_out_seconds": 90.0,
                    "expected_version": current.json()["version"],
                },
            )
            assert response.status_code == 200, response.text

        repackaged = worker.run_once(now=_T0 + timedelta(minutes=10))
        assert repackaged[0].state == FINALIZATION_STATE_COMPLETED
        assert calls[-1] == {"trim_in": 5.0, "trim_out": 90.0}

    def test_repackage_failure_uses_the_normal_retry_machinery(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        _seed_session(engine, tmp_path)
        good_calls: list[dict[str, object]] = []
        worker = _worker(session_factory, good_calls)
        worker.run_once(now=_T0 + timedelta(minutes=1))
        _set_asset_trim(engine, 5.0, 90.0)

        def exploding_packager(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("encode failed")

        failing_worker = LiveFinalizationWorker(
            session_factory,
            packager=exploding_packager,
            probe=lambda _: _probe(),
            settle_seconds=0,
            backoff_seconds=0,
            max_attempts=2,
        )
        first = failing_worker.run_once(now=_T0 + timedelta(minutes=10))[0]
        assert first.state == FINALIZATION_STATE_FAILED
        assert first.failure_code == "package.failed"

        # A healthy packager on the next scan completes the repackage.
        recovered = worker.run_once(now=_T0 + timedelta(minutes=20))[0]
        assert recovered.state == FINALIZATION_STATE_COMPLETED
        assert good_calls[-1] == {"trim_in": 5.0, "trim_out": 90.0}
