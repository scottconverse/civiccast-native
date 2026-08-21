# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""B2 app-wiring proof: ``create_app()`` must build the live go-on-air
``PreflightEvaluator`` with a REAL source probe, not the no-probe default
that fails every ``live_source`` check closed.

The gap this closes: ``civiccast/app.py``'s ``_resolve_preflight_evaluator``
used to call ``PreflightEvaluator(_session_factory)`` with no
``source_probe`` argument at all. Every existing router-level test
(``tests/live/test_router.py``) overrides ``get_preflight_evaluator`` with
its own hand-built evaluator carrying a fake probe, so none of them ever
exercised what ``create_app()`` itself wires when ``DATABASE_URL`` is set
-- the exact path a real running station takes. That gap is why the bug
shipped invisibly: the test suite was green while every real station's
go-on-air 409'd unconditionally.

These tests follow the durable-app-wiring pattern established in
``tests/ai_models/test_app_factory_wiring.py`` (real ``create_app()``,
real ``DATABASE_URL``, resolving the dependency-override callable
directly rather than fighting the staff-auth HTTP boundary, which is out
of scope for this fix). The ffprobe subprocess boundary is mocked (see
``tests/live/test_source_probe.py`` for the probe's own unit coverage);
no real ffmpeg/encoder is required here.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.live.models import LiveSession, LiveSource, RecordingTarget
from civiccast.live.preflight import (
    PREFLIGHT_CHECK_LIVE_SOURCE,
    PREFLIGHT_STATUS_FAIL,
    PREFLIGHT_STATUS_PASS,
    REASON_LIVE_SOURCE_UNAVAILABLE,
    PreflightInputs,
)
from civiccast.live.router import get_preflight_evaluator


def _migrate(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    repo_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(repo_root / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(cfg, "head")


@pytest.fixture
def durable_app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    db_path = tmp_path / "preflight-wiring.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("CIVICCAST_AUTH_ACK", "1")
    monkeypatch.setenv("CIVICCAST_FINALIZATION_WORKER", "off")
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    _migrate(db_path)
    yield tmp_path


def _engine_over_db() -> Engine:
    """A plain engine over the same sqlite file ``DATABASE_URL`` points at.

    Mirrors ``civiccast.app._create_database_engine``'s sqlite handling
    (``schema_translate_map={"civiccast": None}``) -- alembic's env.py
    creates sqlite tables unscoped (``use_schema`` is False for sqlite),
    so ORM code built against the schema-qualified ``civiccast.*`` model
    metadata needs the same translate map to see those tables, matching
    the pattern in ``tests/ai_models/test_app_factory_wiring.py``.
    """
    import os

    database_url = os.environ["DATABASE_URL"]
    engine = create_engine(database_url, future=True)
    if database_url.startswith("sqlite"):
        engine = engine.execution_options(schema_translate_map={"civiccast": None})
    return engine


def _seed_session_source_and_target(engine: Engine) -> None:
    with Session(bind=engine) as sess:
        sess.add(
            LiveSession(
                live_session_id="council-2026-05-15",
                channel_id="gov-ch12",
                title="City Council Meeting",
                state="idle",
            )
        )
        sess.add(
            LiveSource(
                live_source_id="room-a-rtmp",
                channel_id="gov-ch12",
                name="Council Room A RTMP",
                source_type="rtmp",
                endpoint_url="rtmp://camera.example/live",
            )
        )
        sess.add(
            RecordingTarget(
                recording_target_id="nas-primary",
                name="NAS Primary",
                target_uri="/srv/civiccast/recordings",
            )
        )
        sess.commit()


def _inputs() -> PreflightInputs:
    return PreflightInputs(
        live_session_id="council-2026-05-15",
        live_source_id="room-a-rtmp",
        network_reachable=True,
        storage_free_bytes=200 * (1024**3),
        ai_runtime_ready=True,
        operator_confirmed=True,
    )


class _FakeCompleted:
    def __init__(self, *, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_create_app_wires_a_real_source_probe(durable_app_env: Path) -> None:
    """The regression lock: ``source_probe_configured`` must be True.

    Before the fix, ``app.dependency_overrides[get_preflight_evaluator]()``
    returned an evaluator with ``source_probe_configured is False`` --
    every live_source check failed REASON_LIVE_SOURCE_NOT_PROBED no
    matter how the station's sources were configured.
    """
    from civiccast.app import create_app

    app = create_app()
    assert get_preflight_evaluator in app.dependency_overrides

    evaluator = app.dependency_overrides[get_preflight_evaluator]()
    assert evaluator.source_probe_configured is True


def test_go_on_air_allowed_when_the_real_probe_finds_media(
    durable_app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from civiccast.app import create_app

    engine = _engine_over_db()
    _seed_session_source_and_target(engine)

    def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
        return _FakeCompleted(
            returncode=0,
            stdout='{"streams": [{"codec_type": "video", "codec_name": "h264"}], "format": {}}',
        )

    monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)
    monkeypatch.setattr("civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe")

    app = create_app()
    evaluator = app.dependency_overrides[get_preflight_evaluator]()
    result = evaluator.evaluate(_inputs())

    assert result.ready is True
    check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_LIVE_SOURCE]
    assert check.status == PREFLIGHT_STATUS_PASS


def test_go_on_air_blocked_with_actionable_detail_when_the_real_probe_fails(
    durable_app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 409 the go-on-air router builds pulls ``check.message`` verbatim
    into ``failed_checks`` (``civiccast/live/router.py``'s ``go_on_air``,
    unchanged by this fix). Locking that the wired probe's failure message
    names both the source and the concrete reason is what makes that 409
    actionable instead of a bare 'source unavailable.'"""
    from civiccast.app import create_app

    engine = _engine_over_db()
    _seed_session_source_and_target(engine)

    def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
        return _FakeCompleted(
            returncode=1,
            stderr="Connection refused connecting to camera.example:1935",
        )

    monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)
    monkeypatch.setattr("civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe")

    app = create_app()
    evaluator = app.dependency_overrides[get_preflight_evaluator]()
    result = evaluator.evaluate(_inputs())

    assert result.ready is False
    check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_LIVE_SOURCE]
    assert check.status == PREFLIGHT_STATUS_FAIL
    assert check.reason_code == REASON_LIVE_SOURCE_UNAVAILABLE
    assert check.message is not None
    assert "room-a-rtmp" in check.message
    assert "Connection refused" in check.message


def test_go_on_air_still_fails_closed_when_ffprobe_itself_is_missing(
    durable_app_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A station missing ffprobe entirely must still fail closed through the
    wired probe -- never silently pass because the probe itself couldn't
    run."""
    from civiccast.app import create_app

    engine = _engine_over_db()
    _seed_session_source_and_target(engine)

    monkeypatch.setattr("civiccast.live.source_probe.shutil.which", lambda _exe: None)

    app = create_app()
    evaluator = app.dependency_overrides[get_preflight_evaluator]()
    result = evaluator.evaluate(_inputs())

    assert result.ready is False
    check = {c.name: c for c in result.checks}[PREFLIGHT_CHECK_LIVE_SOURCE]
    assert check.status == PREFLIGHT_STATUS_FAIL
    assert check.message is not None
    assert "ffprobe is not installed" in check.message
