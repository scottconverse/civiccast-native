# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""App-factory integration tests for the finalization worker wiring.

TEST-002 (Stage B+D audit): the flagship flow — "an ended broadcast becomes a
recorded, packaged asset in the running application" — must be proven through
the app's own wiring, not by hand-constructing a worker. The end-to-end test
here drives create → start-preflight → go-on-air → end-broadcast over HTTP
against ``create_app()`` and asserts the inline worker thread (started by the
app lifespan per Scott's hybrid architecture decision, ENG-002 option 3)
processes the session to ``completed`` / ``recorded``.

These tests fail on commit 610c75e (nothing ran the worker; sessions stranded
in ``ending`` forever — walkthrough W-2). Their failing-on-HEAD state was
verified before the wiring fix landed; that is the proof they test the seam
that shipped broken.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.live.router import get_preflight_evaluator
from civiccast.stream._ffmpeg import resolve_h264_encoder, run_ffmpeg

_TOKEN = "wiring-test-token"  # deterministic local test fixture token, not a secret
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Configure a file-backed SQLite app environment with inline worker."""

    db_path = tmp_path / "wiring.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv(
        "CIVICCAST_STAFF_TOKENS",
        f"{_TOKEN}:wiring-op:Wiring Operator:meeting_operator,setup_admin,publish_operator",
    )
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "inline")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_SETTLE_SECONDS", "0")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_POLL_SECONDS", "0.05")
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    _migrate(db_path)
    yield tmp_path


def _migrate(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


def _write_real_mp4(path: Path) -> None:
    result = run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=160x90:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "1",
            "-c:v",
            resolve_h264_encoder(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    )
    assert result.returncode == 0, result.stderr


def _configure_test_source_probe(app: FastAPI) -> None:
    """Give this synthetic integration fixture an explicit passing media probe."""

    resolver = app.dependency_overrides[get_preflight_evaluator]
    evaluator = resolver()
    evaluator._source_probe = lambda _source: (True, "Synthetic test source ready")
    app.dependency_overrides[get_preflight_evaluator] = lambda: evaluator


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH; app-wired finalization proof skipped",
)
def test_end_broadcast_reaches_completed_via_app_wired_worker(app_env: Path) -> None:
    """End-broadcast over HTTP is finalized by the app's own worker thread."""

    recordings_dir = app_env / "recordings"
    recordings_dir.mkdir()
    app = create_app()
    _configure_test_source_probe(app)
    with TestClient(app) as client:
        created = client.post(
            "/api/staff/live/recording-targets",
            json={
                "recording_target_id": "fs-primary",
                "name": "Primary recordings",
                "target_uri": recordings_dir.as_uri(),
            },
            headers=_HEADERS,
        )
        assert created.status_code == 201, created.text
        source = client.post(
            "/api/staff/live/sources",
            json={
                "live_source_id": "synthetic-camera",
                "channel_id": "gov-ch12",
                "name": "Synthetic camera",
                "source_type": "rtmp",
                "endpoint_url": "rtmp://127.0.0.1/test",
            },
            headers=_HEADERS,
        )
        assert source.status_code == 201, source.text
        session = client.post(
            "/api/staff/live/sessions",
            json={
                "live_session_id": "wired-session",
                "channel_id": "gov-ch12",
                "title": "Wired meeting",
            },
            headers=_HEADERS,
        )
        assert session.status_code == 201, session.text
        for action in ("start-preflight", "go-on-air", "end-broadcast"):
            body = None
            if action == "go-on-air":
                body = {
                    "live_session_id": "wired-session",
                    "live_source_id": "synthetic-camera",
                    "network_reachable": True,
                    "storage_free_bytes": 200 * (1024**3),
                    "ai_runtime_ready": True,
                    "operator_confirmed": True,
                }
            response = client.post(
                f"/api/staff/live/sessions/wired-session/{action}",
                headers=_HEADERS,
                json=body,
            )
            assert response.status_code == 200, f"{action}: {response.text}"

        _write_real_mp4(recordings_dir / "wired-session.mp4")

        deadline = time.monotonic() + 60.0
        final_state = None
        while time.monotonic() < deadline:
            status = client.get(
                "/api/staff/live/sessions/wired-session/finalization",
                headers=_HEADERS,
            )
            if status.status_code == 200:
                final_state = status.json()["state"]
                if final_state in {"completed", "failed"}:
                    break
            time.sleep(0.1)

        assert final_state == "completed", (
            f"App-wired worker never completed finalization; last observed "
            f"state={final_state!r}. On 610c75e this is None/'pending' forever "
            f"because nothing runs the worker loop (W-2)."
        )
        session_after = client.get(
            "/api/staff/live/sessions/wired-session",
            headers=_HEADERS,
        )
        assert session_after.status_code == 200
        assert session_after.json()["state"] == "recorded"


def test_worker_off_mode_never_starts_thread(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`CIVICCAST_FINALIZATION_WORKER=off` boots the app with no worker thread."""

    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
    app = create_app()
    with TestClient(app):
        supervisor = getattr(app.state, "finalization_worker_supervisor", None)
        assert supervisor is not None, (
            "create_app() must register a finalization worker supervisor when "
            "durable storage is active"
        )
        assert supervisor.running is False


def test_inline_worker_thread_starts_and_stops_with_lifespan(app_env: Path) -> None:
    """Inline mode starts the worker thread on lifespan enter, stops on exit."""

    app = create_app()
    with TestClient(app):
        supervisor = getattr(app.state, "finalization_worker_supervisor", None)
        assert supervisor is not None
        assert supervisor.running is True
    assert supervisor.running is False


def test_invalid_worker_mode_fails_app_startup(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo'd CIVICCAST_FINALIZATION_WORKER value fails fast, not silently."""

    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "background")
    with pytest.raises(ValueError, match="CIVICCAST_FINALIZATION_WORKER"):
        create_app()


def test_settings_from_env_reads_all_knobs(monkeypatch: pytest.MonkeyPatch) -> None:
    from civiccast.live.finalization_worker import FinalizationWorkerSettings

    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "external")
    monkeypatch.setenv("CIVICCAST_LIVE_MANIFEST_BASE_URL", "https://media.example.org/live")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_SETTLE_SECONDS", "45")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_BACKOFF_SECONDS", "60")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_POLL_SECONDS", "2.5")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_RUNNING_LEASE_SECONDS", "1200")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_NEVER_APPEARED_SECONDS", "3600")

    settings = FinalizationWorkerSettings.from_env()

    assert settings.mode == "external"
    assert settings.public_manifest_base_url == "https://media.example.org/live"
    assert settings.settle_seconds == 45.0
    assert settings.max_attempts == 5
    assert settings.backoff_seconds == 60.0
    assert settings.poll_seconds == 2.5
    assert settings.running_lease_seconds == 1200.0
    assert settings.never_appeared_seconds == 3600.0


def test_settings_defaults_are_production_honest(monkeypatch: pytest.MonkeyPatch) -> None:
    from civiccast.live.finalization_worker import FinalizationWorkerSettings

    for name in (
        "CIVICCAST_FINALIZATION_WORKER",
        "CIVICCAST_LIVE_MANIFEST_BASE_URL",
        "CIVICCAST_FINALIZATION_SETTLE_SECONDS",
        "CIVICCAST_FINALIZATION_MAX_ATTEMPTS",
        "CIVICCAST_FINALIZATION_BACKOFF_SECONDS",
        "CIVICCAST_FINALIZATION_POLL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = FinalizationWorkerSettings.from_env()

    assert settings.mode == "inline"
    assert settings.public_manifest_base_url is None
    # ENG-006: the deployment default must exceed realistic recorder flush
    # gaps; 2 s was a test-friendly value that risks packaging a growing file.
    assert settings.settle_seconds >= 30.0
    assert settings.max_attempts == 3


def test_external_entrypoint_once_runs_single_scan(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`python -m civiccast.live.finalization_worker --once` scans and exits."""

    from civiccast.live.finalization_worker import main

    assert main(["--once"]) == 0


def test_external_entrypoint_requires_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from civiccast.live.finalization_worker import main

    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        main(["--once"])
    assert excinfo.value.code == 2


def test_external_entrypoint_module_smoke(app_env: Path) -> None:
    """The documented `python -m` invocation works as a real subprocess."""

    import os

    result = subprocess.run(
        [sys.executable, "-m", "civiccast.live.finalization_worker", "--once"],
        capture_output=True,
        text=True,
        timeout=120,
        env=os.environ.copy(),
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, result.stderr


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


class _BackgroundUvicorn:
    """Runs a real ASGI server on a real socket, for tools (ffprobe) that
    cannot speak to an in-process ASGI transport (TestClient)."""

    def __init__(self, app: FastAPI, port: int) -> None:
        self.base_url = f"http://127.0.0.1:{port}"
        # ws="none": this test only needs plain HTTP; skips uvicorn's
        # websockets.legacy import, which raises under this repo's pytest
        # filterwarnings=error (DeprecationWarning) config.
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="none")
        self._server = uvicorn.Server(config)
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            self._server.run()
        except BaseException as exc:  # surfaced to the main thread via __enter__
            self._error = exc

    def __enter__(self) -> _BackgroundUvicorn:
        self._thread.start()
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if getattr(self._server, "started", False):
                return self
            if self._error is not None:
                raise RuntimeError(f"uvicorn failed to start: {self._error!r}") from self._error
            time.sleep(0.05)
        raise RuntimeError("uvicorn did not report started within 15s")

    def __exit__(self, *exc: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=10.0)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH; VOD local-serve playability proof skipped",
)
def test_finalized_recording_is_playable_hls_over_local_serve(
    app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The anti-theater bar: a real browser player can actually play the
    output. Package a real recording through the live app-wired worker with
    NO CDN and NO CIVICCAST_LIVE_MANIFEST_BASE_URL configured (the stock-
    install case), fetch the resulting manifest_url over real HTTP from a
    real server, and run ffprobe on it — proving hls.js/native <video> would
    actually resolve segments and see a real stream, not a 200 with nothing
    playable behind it.
    """
    port = _free_port()
    monkeypatch.setenv("CIVICCAST_LOCAL_MEDIA_BASE_URL", f"http://127.0.0.1:{port}")
    monkeypatch.delenv("CIVICCAST_LIVE_MANIFEST_BASE_URL", raising=False)
    monkeypatch.delenv("CIVICCAST_CDN_PROVIDER", raising=False)

    recordings_dir = app_env / "recordings"
    recordings_dir.mkdir()
    app = create_app()
    _configure_test_source_probe(app)

    with _BackgroundUvicorn(app, port) as server:
        with TestClient(app) as client:
            created = client.post(
                "/api/staff/live/recording-targets",
                json={
                    "recording_target_id": "fs-primary",
                    "name": "Primary recordings",
                    "target_uri": recordings_dir.as_uri(),
                },
                headers=_HEADERS,
            )
            assert created.status_code == 201, created.text
            source = client.post(
                "/api/staff/live/sources",
                json={
                    "live_source_id": "synthetic-camera",
                    "channel_id": "gov-ch12",
                    "name": "Synthetic camera",
                    "source_type": "rtmp",
                    "endpoint_url": "rtmp://127.0.0.1/test",
                },
                headers=_HEADERS,
            )
            assert source.status_code == 201, source.text
            session = client.post(
                "/api/staff/live/sessions",
                json={
                    "live_session_id": "playable-session",
                    "channel_id": "gov-ch12",
                    "title": "Playable meeting",
                },
                headers=_HEADERS,
            )
            assert session.status_code == 201, session.text
            for action in ("start-preflight", "go-on-air", "end-broadcast"):
                body = None
                if action == "go-on-air":
                    body = {
                        "live_session_id": "playable-session",
                        "live_source_id": "synthetic-camera",
                        "network_reachable": True,
                        "storage_free_bytes": 200 * (1024**3),
                        "ai_runtime_ready": True,
                        "operator_confirmed": True,
                    }
                response = client.post(
                    f"/api/staff/live/sessions/playable-session/{action}",
                    headers=_HEADERS,
                    json=body,
                )
                assert response.status_code == 200, f"{action}: {response.text}"

            _write_real_mp4(recordings_dir / "playable-session.mp4")

            deadline = time.monotonic() + 90.0
            manifest_url = None
            while time.monotonic() < deadline:
                status = client.get(
                    "/api/staff/live/sessions/playable-session/finalization",
                    headers=_HEADERS,
                )
                if status.status_code == 200:
                    body = status.json()
                    if body["state"] == "completed":
                        manifest_url = body["package_manifest_url"]
                        break
                    if body["state"] == "failed":
                        pytest.fail(f"finalization failed: {body}")
                time.sleep(0.1)
            assert manifest_url is not None, "finalization never completed"

            # Packaging must not leak the recording before an operator's
            # explicit publication decision.
            unpublished = client.get("/api/public/assets/playable-session")
            assert unpublished.status_code == 404
            unpublished_media = client.get("/media/vod/playable-session/playlist.m3u8")
            assert unpublished_media.status_code == 404

            approved = client.post(
                "/api/staff/publish/assets/playable-session/approve",
                json={
                    "operator_id": "wiring-op",
                    "operator_display_name": "Wiring Operator",
                    "approved_surface_ids": ["portal"],
                },
                headers=_HEADERS,
            )
            assert approved.status_code == 200, approved.text

            asset = client.get("/api/public/assets/playable-session")
            assert asset.status_code == 200, asset.text
            served_manifest_url = asset.json()["manifest_url"]

        # manifest_url populates by default (mission bar: not route-exists-only).
        assert served_manifest_url == "/media/vod/playable-session/playlist.m3u8"
        playable_manifest_url = urljoin(server.base_url, served_manifest_url)

        # Fetch it for real, over a real socket — proves the mount actually
        # serves (not just that the DB has a URL string in it).
        manifest_response = httpx.get(playable_manifest_url, timeout=10.0)
        assert manifest_response.status_code == 200
        assert manifest_response.headers["content-type"] == "application/vnd.apple.mpegurl"
        assert manifest_response.text.startswith("#EXTM3U")

        # The real acceptance bar: ffprobe reads the served manifest over
        # HTTP, resolves the segment URIs (relative to the manifest URL,
        # exactly as a browser would), and reports a real playable stream.
        ffprobe_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration,format_name:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                playable_manifest_url,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert ffprobe_result.returncode == 0, (
            f"ffprobe could not read the served HLS manifest: {ffprobe_result.stderr}"
        )
        import json

        probe_json = json.loads(ffprobe_result.stdout)
        codec_types = {stream["codec_type"] for stream in probe_json["streams"]}
        assert "video" in codec_types, f"ffprobe found no video stream: {probe_json}"
        assert "audio" in codec_types, f"ffprobe found no audio stream: {probe_json}"
        assert float(probe_json["format"]["duration"]) > 0

        print("FFPROBE PROOF:", ffprobe_result.stdout)
