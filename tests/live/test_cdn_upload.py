# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CDN upload wiring tests (Beta sprint B4, decision #7 option A).

Until this stage the Bunny/R2/stub adapters were `real component ->
implemented but not wired`: nothing in the product uploaded through them.
The finalization worker now publishes the packaged HLS tree through the
config-selected CDN adapter — segments first, manifest last — and the asset's
``manifest_url`` becomes the CDN public URL only after the upload succeeds
(manifest honesty preserved). Upload failures flow through the normal
classified-failure retry machinery (``cdn.upload_failed``).
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
    FAILURE_CODE_CDN_UPLOAD_FAILED,
    FINALIZATION_STATE_COMPLETED,
    FINALIZATION_STATE_FAILED,
    LIVE_SESSION_STATE_ENDING,
    LiveSession,
    RecordingTarget,
)
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.models import Asset
from civiccast.stream.cdn.stub import StubCDNAdapter

_T0 = datetime(2026, 6, 10, 19, 0, tzinfo=UTC)
_SESSION_ID = "cdn-session"


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


def _segmenting_packager(input_path, output_dir, *, trim_in_seconds=None, trim_out_seconds=None):  # type: ignore[no-untyped-def]
    """Fake packager that writes a manifest plus two segment files."""

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "segment-000.ts").write_bytes(b"segment zero")
    (output_dir / "segment-001.ts").write_bytes(b"segment one")
    manifest = output_dir / "playlist.m3u8"
    manifest.write_text(
        f"#EXTM3U\n#TRIM {trim_in_seconds} {trim_out_seconds}\nsegment-000.ts\nsegment-001.ts\n",
        encoding="utf-8",
    )
    return SimpleNamespace(manifest_path=manifest)


class _RecordingAdapter:
    """Wraps an adapter and records every upload key in call order."""

    def __init__(self, inner) -> None:  # type: ignore[no-untyped-def]
        self._inner = inner
        self.uploaded_keys: list[str] = []

    def upload_file(self, local_path: Path, remote_key: str) -> str:
        self.uploaded_keys.append(remote_key)
        return self._inner.upload_file(local_path, remote_key)

    def delete_file(self, remote_key: str) -> None:
        self._inner.delete_file(remote_key)

    def public_url(self, remote_key: str) -> str:
        return self._inner.public_url(remote_key)


class _ExplodingAdapter:
    def upload_file(self, local_path: Path, remote_key: str) -> str:
        raise RuntimeError("cdn unreachable")

    def delete_file(self, remote_key: str) -> None:  # pragma: no cover - unused
        pass

    def public_url(self, remote_key: str) -> str:  # pragma: no cover - unused
        return remote_key


def _seed_session(engine: Engine, target_dir: Path) -> None:
    (target_dir / f"{_SESSION_ID}.mp4").write_bytes(b"recording")
    with Session(bind=engine) as session:
        session.add(
            LiveSession(
                live_session_id=_SESSION_ID,
                channel_id="gov-ch12",
                title="CDN upload test",
                state=LIVE_SESSION_STATE_ENDING,
                ended_at=_T0,
            )
        )
        session.add(
            RecordingTarget(
                recording_target_id="fs-cdn",
                name="CDN recordings",
                target_uri=target_dir.as_uri(),
            )
        )
        session.commit()


def _worker(session_factory, cdn_adapter=None, **kwargs):  # type: ignore[no-untyped-def]
    return LiveFinalizationWorker(
        session_factory,
        packager=_segmenting_packager,
        probe=lambda _: _probe(),
        settle_seconds=0,
        backoff_seconds=0,
        max_attempts=3,
        cdn_adapter=cdn_adapter,
        **kwargs,
    )


class TestCdnUploadWiring:
    def test_completed_job_publishes_the_package_through_the_cdn(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        recordings = tmp_path / "recordings"
        recordings.mkdir()
        cdn_root = tmp_path / "cdn"
        _seed_session(engine, recordings)
        worker = _worker(session_factory, cdn_adapter=StubCDNAdapter(cdn_root))

        status = worker.run_once(now=_T0 + timedelta(minutes=1))[0]

        assert status.state == FINALIZATION_STATE_COMPLETED
        expected_url = (cdn_root / f"live/{_SESSION_ID}/playlist.m3u8").as_uri()
        assert status.package_manifest_url == expected_url
        # Segments landed on the CDN alongside the manifest.
        assert (cdn_root / f"live/{_SESSION_ID}/segment-000.ts").read_bytes() == b"segment zero"
        assert (cdn_root / f"live/{_SESSION_ID}/segment-001.ts").read_bytes() == b"segment one"
        with Session(bind=engine) as session:
            asset = session.execute(select(Asset).where(Asset.asset_id == _SESSION_ID)).scalar_one()
            assert asset.manifest_url == expected_url

    def test_segments_upload_before_the_manifest(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        recordings = tmp_path / "recordings"
        recordings.mkdir()
        _seed_session(engine, recordings)
        adapter = _RecordingAdapter(StubCDNAdapter(tmp_path / "cdn"))
        worker = _worker(session_factory, cdn_adapter=adapter)

        worker.run_once(now=_T0 + timedelta(minutes=1))

        assert adapter.uploaded_keys, "the package must upload through the adapter"
        assert adapter.uploaded_keys[-1] == f"live/{_SESSION_ID}/playlist.m3u8", (
            "the manifest must upload last so residents never fetch a manifest "
            "whose segments are not on the CDN yet"
        )
        assert set(adapter.uploaded_keys[:-1]) == {
            f"live/{_SESSION_ID}/segment-000.ts",
            f"live/{_SESSION_ID}/segment-001.ts",
        }

    def test_cdn_failure_is_classified_and_recovers_through_normal_retries(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        recordings = tmp_path / "recordings"
        recordings.mkdir()
        _seed_session(engine, recordings)
        failing = _worker(session_factory, cdn_adapter=_ExplodingAdapter())

        first = failing.run_once(now=_T0 + timedelta(minutes=1))[0]

        assert first.state == FINALIZATION_STATE_FAILED
        assert first.failure_code == FAILURE_CODE_CDN_UPLOAD_FAILED
        assert first.package_manifest_url is None, (
            "manifest honesty: no public URL may be recorded for a failed upload"
        )

        cdn_root = tmp_path / "cdn"
        healthy = _worker(session_factory, cdn_adapter=StubCDNAdapter(cdn_root))
        recovered = healthy.run_once(now=_T0 + timedelta(minutes=10))[0]

        assert recovered.state == FINALIZATION_STATE_COMPLETED
        assert (
            recovered.package_manifest_url
            == (cdn_root / f"live/{_SESSION_ID}/playlist.m3u8").as_uri()
        )

    def test_no_cdn_adapter_keeps_existing_manifest_url_behavior(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        recordings = tmp_path / "recordings"
        recordings.mkdir()
        _seed_session(engine, recordings)
        worker = _worker(
            session_factory,
            public_manifest_base_url="https://vod.example.org/live",
        )

        status = worker.run_once(now=_T0 + timedelta(minutes=1))[0]

        assert status.state == FINALIZATION_STATE_COMPLETED
        assert status.package_manifest_url == (
            f"https://vod.example.org/live/{_SESSION_ID}/playlist.m3u8"
        )

    def test_cdn_url_wins_over_the_local_manifest_base_url(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        recordings = tmp_path / "recordings"
        recordings.mkdir()
        cdn_root = tmp_path / "cdn"
        _seed_session(engine, recordings)
        worker = _worker(
            session_factory,
            cdn_adapter=StubCDNAdapter(cdn_root),
            public_manifest_base_url="https://vod.example.org/live",
        )

        status = worker.run_once(now=_T0 + timedelta(minutes=1))[0]

        assert (
            status.package_manifest_url == (cdn_root / f"live/{_SESSION_ID}/playlist.m3u8").as_uri()
        )

    def test_trim_repackage_reuploads_through_the_cdn(
        self, engine: Engine, session_factory, tmp_path: Path
    ) -> None:
        recordings = tmp_path / "recordings"
        recordings.mkdir()
        _seed_session(engine, recordings)
        adapter = _RecordingAdapter(StubCDNAdapter(tmp_path / "cdn"))
        worker = _worker(session_factory, cdn_adapter=adapter)
        worker.run_once(now=_T0 + timedelta(minutes=1))
        first_round = len(adapter.uploaded_keys)

        with Session(bind=engine) as session:
            asset = session.execute(select(Asset).where(Asset.asset_id == _SESSION_ID)).scalar_one()
            asset.trim_in_seconds = 5.0
            asset.trim_out_seconds = 90.0
            session.commit()

        repackaged = worker.run_once(now=_T0 + timedelta(minutes=10))

        assert repackaged[0].state == FINALIZATION_STATE_COMPLETED
        assert len(adapter.uploaded_keys) == first_round * 2, (
            "a trim repackage must re-upload the re-rendered package"
        )
        cdn_manifest = tmp_path / "cdn" / f"live/{_SESSION_ID}/playlist.m3u8"
        assert "#TRIM 5.0 90.0" in cdn_manifest.read_text(encoding="utf-8")

    def test_env_selected_stub_provider_flows_through_build_worker(
        self, engine: Engine, session_factory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The config path end-to-end: CIVICCAST_CDN_PROVIDER=stub selects the
        adapter via the Stage C factory and build_worker hands it to the
        worker — the same wiring the app lifespan and external entrypoint use."""

        from civiccast.live.finalization_worker import (
            FinalizationWorkerSettings,
            build_worker,
        )
        from civiccast.stream.cdn.factory import CdnSettings, build_cdn_adapter

        recordings = tmp_path / "recordings"
        recordings.mkdir()
        cdn_root = tmp_path / "cdn"
        _seed_session(engine, recordings)

        monkeypatch.setenv("CIVICCAST_CDN_PROVIDER", "stub")
        monkeypatch.setenv("CIVICCAST_CDN_STUB_ROOT", str(cdn_root))
        monkeypatch.setenv("CIVICCAST_FINALIZATION_SETTLE_SECONDS", "0")
        monkeypatch.setenv("CIVICCAST_FINALIZATION_BACKOFF_SECONDS", "0")
        adapter = build_cdn_adapter(CdnSettings.from_env())
        worker = build_worker(
            session_factory,
            FinalizationWorkerSettings.from_env(),
            cdn_adapter=adapter,
        )
        # The real ffmpeg packager is not under test here; swap in the fake.
        worker._packager = _segmenting_packager
        worker._probe = lambda _: _probe()

        status = worker.run_once(now=_T0 + timedelta(minutes=1))[0]

        assert status.state == FINALIZATION_STATE_COMPLETED
        assert (
            status.package_manifest_url == (cdn_root / f"live/{_SESSION_ID}/playlist.m3u8").as_uri()
        )
