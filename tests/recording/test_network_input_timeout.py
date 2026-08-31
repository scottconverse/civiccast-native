# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""MAJOR regression: a network recording source must fail fast and bounded.

Before this fix, ``FfmpegScheduledCapturePipeline._input_args`` passed
``-i <uri>`` with no connect/read timeout for RTSP/SRT/HLS/RTMP/MPEG-TS
sources, so an unreachable source hung the ffmpeg child for whatever the OS
TCP stack decided (commonly minutes on Windows) on every single arm attempt.
These tests prove every network scheme now carries an explicit, correctly
named ffmpeg timeout flag, that device (sdi/hdmi/ndi) sources are
unaffected (no network I/O, no timeout flag), and that the flag actually
reaches the launched ffmpeg process argv end to end through ``arm``/``start``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.live.models import RecordingTarget
from civiccast.live.recording_paths import REHEARSAL_RECORDING_TARGET_ID
from civiccast.recording.models import RecordingSource
from civiccast.recording.runtime import (
    _NETWORK_IO_TIMEOUT_MICROSECONDS,
    FfmpegScheduledCapturePipeline,
    ScheduledRecordingSettings,
)

_NOW_DIRS_MINUTE = 1

_ENGINES_TO_DISPOSE: list = []


@pytest.fixture(autouse=True)
def _dispose_test_engines() -> Iterator[None]:
    yield
    while _ENGINES_TO_DISPOSE:
        _ENGINES_TO_DISPOSE.pop().dispose()


def _uri_for(kind: str) -> str:
    """A URI whose scheme satisfies ``RecordingSource``'s own kind/scheme
    validation (e.g. ``hls`` sources are validated as real http(s) URLs,
    ``mpegts`` as udp/rtp) — see ``civiccast.recording.models``."""
    scheme = {
        "rtsp": "rtsp",
        "srt": "srt",
        "hls": "https",
        "rtmp": "rtmp",
        "mpegts": "udp",
    }[kind]
    return f"{scheme}://example.test/live"


def _make_pipeline(tmp_path: Path, **kwargs) -> FfmpegScheduledCapturePipeline:
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.db'}")
    _ENGINES_TO_DISPOSE.append(engine)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return FfmpegScheduledCapturePipeline(
        factory, settings=ScheduledRecordingSettings(mode="off"), **kwargs
    )


@pytest.mark.parametrize(
    ("kind", "expected_flag"),
    [
        ("rtsp", "-timeout"),
        ("srt", "-timeout"),
        ("hls", "-rw_timeout"),
        ("rtmp", "-rw_timeout"),
        ("mpegts", "-rw_timeout"),
    ],
)
def test_network_source_input_args_carry_a_bounded_io_timeout(
    tmp_path: Path, kind: str, expected_flag: str
) -> None:
    pipeline = _make_pipeline(tmp_path)
    source = RecordingSource(kind=kind, uri=_uri_for(kind))

    args = pipeline._input_args(source)

    assert expected_flag in args, f"{kind} source is missing {expected_flag!r}: {args}"
    value_index = args.index(expected_flag) + 1
    assert args[value_index] == str(_NETWORK_IO_TIMEOUT_MICROSECONDS)
    # The value must be a positive, finite number of microseconds — not "0"
    # (which several ffmpeg protocols treat as "no timeout") and not blank.
    assert int(args[value_index]) > 0


@pytest.mark.parametrize("kind", ["rtsp", "srt", "hls", "rtmp", "mpegts"])
def test_network_source_still_reaches_the_uri(tmp_path: Path, kind: str) -> None:
    """The timeout flag must be additive, never replacing the real ``-i`` arg."""
    pipeline = _make_pipeline(tmp_path)
    uri = _uri_for(kind)
    source = RecordingSource(kind=kind, uri=uri)

    args = pipeline._input_args(source)

    assert "-i" in args
    assert args[args.index("-i") + 1] == uri


@pytest.mark.parametrize(
    ("kind", "kwargs"),
    [
        ("sdi", {"input_id": "cam-1"}),
        ("hdmi", {"input_id": "cam-1"}),
        ("ndi", {"input_id": "studio-a"}),
    ],
)
def test_device_sources_carry_no_network_timeout_flag(
    tmp_path: Path, kind: str, kwargs: dict
) -> None:
    """Device sources are local hardware inputs, not network I/O — no
    connect/read timeout applies and none should be added."""
    pipeline = _make_pipeline(tmp_path)
    source = RecordingSource(kind=kind, **kwargs)

    args = pipeline._input_args(source)

    assert "-timeout" not in args
    assert "-rw_timeout" not in args


class _ScriptedHandle:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"")
        self.returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self, *, grace_seconds: float = 5.0) -> int:
        self.returncode = 0
        return 0

    def close(self) -> None:
        return None


def test_arm_and_start_pass_the_timeout_flag_through_to_the_real_ffmpeg_argv(
    tmp_path: Path,
) -> None:
    """End-to-end: the flag set in ``_input_args`` must actually reach the
    argv the process handle is launched with, not just a unit-level
    ``_input_args`` call."""
    from datetime import UTC, datetime, timedelta

    captured_args: list[list[str]] = []

    def fake_start_ffmpeg(args: list[str], **_kwargs) -> _ScriptedHandle:
        captured_args.append(list(args))
        return _ScriptedHandle(Path(args[-1]))

    engine = create_engine(f"sqlite:///{tmp_path / 'runtime.db'}")
    _ENGINES_TO_DISPOSE.append(engine)
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    with factory() as session:
        session.add_all(
            [
                RecordingTarget(
                    recording_target_id=REHEARSAL_RECORDING_TARGET_ID,
                    name="Installer rehearsal recordings",
                    target_uri=(tmp_path / "private-rehearsals").as_uri(),
                    created_at=now - timedelta(minutes=2),
                ),
                RecordingTarget(
                    recording_target_id="local",
                    name="Local recordings",
                    target_uri=(tmp_path / "recordings").as_uri(),
                    created_at=now - timedelta(minutes=_NOW_DIRS_MINUTE),
                ),
            ]
        )
        session.commit()

    pipeline = FfmpegScheduledCapturePipeline(
        factory,
        settings=ScheduledRecordingSettings(mode="off"),
        ffmpeg_starter=fake_start_ffmpeg,
    )
    source = RecordingSource(kind="rtsp", uri="rtsp://example.test/cam1")
    pipeline.arm(job_id="job-timeout", source=source, encoder_profile="copy", loudness_regime="inherit")
    pipeline.start("job-timeout")

    assert len(captured_args) == 1
    args = captured_args[0]
    assert "-timeout" in args
    assert args[args.index("-timeout") + 1] == str(_NETWORK_IO_TIMEOUT_MICROSECONDS)
    assert "-rtsp_transport" in args and args[args.index("-rtsp_transport") + 1] == "tcp"
