# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Operator retry surface for terminal finalization failures (Beta B2, #3).

The Stage B+D audit named "status without recourse" as a systemic gap: a
terminal `failed` finalization told the operator their meeting recording did
not get packaged and offered nothing but database surgery. The retry endpoint
re-queues the job through the same worker machinery; the worker's next scan
re-attempts it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401 - register Asset tables on Base
from civiccast.app import create_app
from civiccast.db import Base
from civiccast.live.finalization_worker import LiveFinalizationWorker
from civiccast.live.models import (
    FINALIZATION_STATE_COMPLETED,
    FINALIZATION_STATE_FAILED,
    FINALIZATION_STATE_PENDING,
    FINALIZATION_STATE_RUNNING,
    LIVE_SESSION_STATE_ENDING,
    LiveFinalizationJob,
    LiveSession,
    RecordingTarget,
)
from civiccast.live.router import get_live_finalization_worker


@pytest.fixture
def engine() -> Iterator[Engine]:
    # TestClient serves requests on a worker thread; a StaticPool shares the
    # single in-memory connection across threads, and the translate map keeps
    # the civiccast schema unqualified on SQLite (matching the app's own
    # engine wiring) so all threads see the same tables.
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(schema_translate_map={"civiccast": None})
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


@pytest.fixture
def worker(session_factory) -> LiveFinalizationWorker:  # type: ignore[no-untyped-def]
    def packager(input_path, output_dir, *, trim_in_seconds=None, trim_out_seconds=None):  # type: ignore[no-untyped-def]
        manifest = output_dir / "playlist.m3u8"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("#EXTM3U\n", encoding="utf-8")
        return SimpleNamespace(manifest_path=manifest)

    from civiccast.schedule.ingest import FfprobeResult

    return LiveFinalizationWorker(
        session_factory,
        packager=packager,
        probe=lambda _: FfprobeResult(
            duration_seconds=120,
            codec_video="h264",
            codec_audio="aac",
            width_px=1280,
            height_px=720,
            bitrate_bps=800_000,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
        ),
        settle_seconds=0,
    )


@pytest.fixture
def client(worker: LiveFinalizationWorker, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    monkeypatch.setenv("CIVICCAST_ALLOW_EPHEMERAL_STORES", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    app = create_app()
    app.dependency_overrides[get_live_finalization_worker] = lambda: worker
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as test_client:
        yield test_client


def _seed_job(
    engine: Engine,
    state: str,
    *,
    attempts: int = 3,
    recording: Path | None = None,
) -> None:
    with Session(bind=engine) as session:
        session.add(
            LiveSession(
                live_session_id="retry-session",
                channel_id="gov-ch12",
                title="Retry test",
                state=LIVE_SESSION_STATE_ENDING,
                ended_at=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
            )
        )
        if recording is not None:
            session.add(
                RecordingTarget(
                    recording_target_id="fs-retry",
                    name="Retry recordings",
                    target_uri=recording.parent.as_uri(),
                )
            )
        session.add(
            LiveFinalizationJob(
                live_session_id="retry-session",
                state=state,
                attempts=attempts,
                max_attempts=3,
                failure_reason="Packaging for playback failed." if state == "failed" else None,
                failure_code="package.failed" if state == "failed" else None,
                recording_uri=recording.as_uri() if recording is not None else None,
                recording_size_bytes=recording.stat().st_size if recording is not None else None,
                last_observed_size_bytes=(
                    recording.stat().st_size if recording is not None else None
                ),
                last_observed_at=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
            )
        )
        session.commit()


class TestRetryEndpoint:
    def test_retry_requeues_a_terminal_failure_and_worker_completes_it(
        self, client: TestClient, engine: Engine, worker: LiveFinalizationWorker, tmp_path: Path
    ) -> None:
        recording = tmp_path / "retry-session.mp4"
        recording.write_bytes(b"recording")
        _seed_job(engine, FINALIZATION_STATE_FAILED, attempts=3, recording=recording)

        response = client.post("/api/staff/live/sessions/retry-session/finalization/retry")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == FINALIZATION_STATE_PENDING
        assert body["attempts"] == 0
        assert body["failure_reason"] is None
        assert body["failure_code"] is None
        assert body["terminal"] is False

        status = worker.run_once(now=datetime(2026, 6, 10, 19, 0, tzinfo=UTC))[0]
        assert status.state == FINALIZATION_STATE_COMPLETED

    def test_retry_unknown_session_is_404(self, client: TestClient) -> None:
        response = client.post("/api/staff/live/sessions/missing/finalization/retry")
        assert response.status_code == 404

    @pytest.mark.parametrize(
        ("state", "attempts"),
        [(FINALIZATION_STATE_RUNNING, 1), (FINALIZATION_STATE_COMPLETED, 1)],
    )
    def test_retry_conflicts_for_running_and_completed(
        self, client: TestClient, engine: Engine, state: str, attempts: int
    ) -> None:
        _seed_job(engine, state, attempts=attempts)
        response = client.post("/api/staff/live/sessions/retry-session/finalization/retry")
        assert response.status_code == 409
        assert state in response.text

    def test_retry_requires_auth(self, client: TestClient, engine: Engine, tmp_path: Path) -> None:
        recording = tmp_path / "retry-session.mp4"
        recording.write_bytes(b"recording")
        _seed_job(engine, FINALIZATION_STATE_FAILED, recording=recording)
        response = client.post(
            "/api/staff/live/sessions/retry-session/finalization/retry",
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert response.status_code == 401
