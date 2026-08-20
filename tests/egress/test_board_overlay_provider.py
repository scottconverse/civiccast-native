# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for build_board_overlay_provider (S15 §5 CG-lite engine overlay leg).

Gate audit gap: the provider that rasters a channel's active board into a
cached PNG for the GStreamer overlay leg had no direct coverage of its four
observable contracts: no-board -> None, render-and-cache, cache-hit (no
re-render), and fail-open-on-render-error (logged, never raised). Uses the
same sqlite session-factory fixture pattern as tests/cg/test_board_api.py so
the provider's real store wiring (CgBoardStore, PostgresCgBulletinStore,
PostgresAssetStore) runs against a real (in-memory) schema rather than mocks.

The provider takes ``(channel_id, config)`` -- geometry for the raster comes
from ``config.canonical_profile`` (the same source the filler renders
against), not from the channel's branding lineup.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.cg.board_service import CgBoardService
from civiccast.cg.board_store import CgBoardStore
from civiccast.db import Base
from civiccast.egress.bulletin_filler import build_board_overlay_provider
from civiccast.egress.models import CanonicalProfile, EgressConfig, EgressSinkSpec
from civiccast.stream._ffmpeg import FfmpegResult

_CHANNEL_ID = "public"


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id=_CHANNEL_ID,
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        canonical_profile=CanonicalProfile(width=640, height=360, video_bitrate_kbps=1200),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


@pytest.fixture
def factory() -> Iterator[Callable[[], Session]]:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        with contextlib.suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        Base.metadata.create_all(conn)
        conn.commit()

    @contextmanager
    def _factory() -> Iterator[Session]:
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    try:
        yield _factory
    finally:
        engine.dispose()


def _activate_board(factory, *, channel_id: str = _CHANNEL_ID) -> None:  # type: ignore[no-untyped-def]
    CgBoardService(CgBoardStore(factory)).create_board(
        channel_id, template_id="standard-community-board", operator_id="test-op"
    )


def _ok_runner(calls: list[list[str]]) -> Callable[[list[str]], FfmpegResult]:
    def run_ffmpeg(args: list[str]) -> FfmpegResult:
        calls.append(args)
        out_path = Path(args[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"PNG")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    return run_ffmpeg


def _raising_runner(calls: list[list[str]]) -> Callable[[list[str]], FfmpegResult]:
    def run_ffmpeg(args: list[str]) -> FfmpegResult:
        calls.append(args)
        raise RuntimeError("ffmpeg exploded")

    return run_ffmpeg


class TestBoardOverlayProvider:
    def test_no_active_board_returns_none_without_rendering(self, factory, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        calls: list[list[str]] = []
        provider = build_board_overlay_provider(
            factory, work_dir=tmp_path, ffmpeg_runner=_ok_runner(calls)
        )

        assert provider(_CHANNEL_ID, _config()) is None
        assert calls == []

    def test_active_board_renders_and_returns_cached_png_path(
        self, factory, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        _activate_board(factory)
        calls: list[list[str]] = []
        provider = build_board_overlay_provider(
            factory, work_dir=tmp_path, ffmpeg_runner=_ok_runner(calls)
        )

        out_path = provider(_CHANNEL_ID, _config())

        assert out_path is not None
        assert out_path.is_file()
        assert out_path.read_bytes() == b"PNG"
        assert "board-overlay" in out_path.parts
        assert len(calls) == 1

    def test_second_call_is_a_cache_hit_and_does_not_re_render(
        self, factory, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        _activate_board(factory)
        calls: list[list[str]] = []
        # Pin the clock. A board with a clock zone folds the current minute into
        # its cache key by design, so two live calls that straddle a minute
        # boundary legitimately produce two different keys and this assertion
        # fails at random -- observed on CI run 32317219308. Freezing wall time
        # tests the caching behaviour this test is actually about, and leaves
        # the per-minute re-render (covered by
        # test_board_compositor.py::TestCacheKey::test_clock_zone_buckets_by_minute)
        # to the test that owns it.
        frozen = datetime(2026, 8, 20, 12, 30, 0, tzinfo=UTC)
        provider = build_board_overlay_provider(
            factory,
            work_dir=tmp_path,
            ffmpeg_runner=_ok_runner(calls),
            clock=lambda: frozen,
        )

        first = provider(_CHANNEL_ID, _config())
        second = provider(_CHANNEL_ID, _config())

        assert first == second
        assert len(calls) == 1, "an unchanged board must not re-render on the second call"

    def test_render_failure_fails_open_and_logs(
        self, factory, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:  # type: ignore[no-untyped-def]
        _activate_board(factory)
        calls: list[list[str]] = []
        provider = build_board_overlay_provider(
            factory, work_dir=tmp_path, ffmpeg_runner=_raising_runner(calls)
        )

        with caplog.at_level(logging.ERROR, logger="civiccast.egress.bulletin_filler"):
            result = provider(_CHANNEL_ID, _config())

        assert result is None, "a render failure must fail open (no overlay), never raise"
        assert len(calls) == 1
        assert any(
            record.levelno >= logging.ERROR and _CHANNEL_ID in record.getMessage()
            for record in caplog.records
        ), "the fail-open path must log the failure naming the channel, not swallow it silently"
