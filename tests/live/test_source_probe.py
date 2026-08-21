# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the real ffprobe-backed live source probe (bug B2).

``civiccast.live.source_probe.probe_live_source`` is the ``SourceProbe``
implementation wired into every real station's ``PreflightEvaluator`` (see
``civiccast/app.py``'s ``_resolve_preflight_evaluator``). Before this
module existed, ``_resolve_preflight_evaluator`` built the evaluator with
no probe at all, so the live_source pre-flight check always fell into
``REASON_LIVE_SOURCE_NOT_PROBED`` and go-on-air always 409'd -- even for a
correctly configured, currently-streaming source. These tests mock the
ffprobe subprocess boundary (no real encoder / real ffprobe binary
required) and assert:

* ffprobe missing -> fails closed with an actionable message.
* an unrecognized source shape (empty endpoint) -> fails closed, never
  silently "passes."
* rtmp/rtsp/srt sources probe via ``ffprobe -i <endpoint_url>``; ndi
  sources probe via ``ffprobe -f libndi_newtek -i <name>`` (the same
  demuxer ``civiccast.cable.ndi`` uses for NDI output readiness).
* a stream reported as video and/or audio -> ready True, with a message
  naming the source.
* zero streams in an otherwise-successful response -> ready False.
* non-zero ffprobe exit -> ready False, message carries the stderr detail
  (truncated), so the go-on-air 409 is actionable.
* a hung probe is killed at the bound (``subprocess.TimeoutExpired``) ->
  ready False with a timeout-specific message; the probe never blocks
  past its budget.
* ``build_source_probe`` reads
  ``CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS``, falls back to the
  documented default on an unset/invalid value, and an explicit
  ``timeout_seconds`` argument wins over the env var.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from civiccast.live.models import LiveSource
from civiccast.live.source_probe import (
    DEFAULT_SOURCE_PROBE_TIMEOUT_SECONDS,
    build_source_probe,
    probe_live_source,
)


def _source(
    *,
    source_type: str = "rtmp",
    endpoint_url: str = "rtmp://camera.example/live",
    live_source_id: str = "room-a-rtmp",
    name: str = "Council Room A RTMP",
    channel_id: str = "gov-ch12",
) -> LiveSource:
    return LiveSource(
        live_source_id=live_source_id,
        channel_id=channel_id,
        name=name,
        source_type=source_type,
        endpoint_url=endpoint_url,
    )


def _ffprobe_json(*, video: bool = False, audio: bool = False) -> str:
    streams: list[dict[str, Any]] = []
    if video:
        streams.append({"codec_type": "video", "codec_name": "h264"})
    if audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return json.dumps({"streams": streams, "format": {}})


class _FakeCompleted:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# Fails closed: no ffprobe, no recognizable source shape
# ---------------------------------------------------------------------------


class TestFailsClosed:
    def test_ffprobe_missing_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("civiccast.live.source_probe.shutil.which", lambda _exe: None)
        ready, message = probe_live_source(_source(), timeout_seconds=5.0)
        assert ready is False
        assert message is not None
        assert "ffprobe is not installed" in message

    def test_empty_endpoint_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        called = False

        def _boom(*args: Any, **kwargs: Any) -> Any:
            nonlocal called
            called = True
            raise AssertionError("subprocess.run must not be called for an unrecognized source")

        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _boom)
        ready, message = probe_live_source(_source(endpoint_url="   "), timeout_seconds=5.0)
        assert ready is False
        assert called is False
        assert message is not None
        assert "not recognized by the server-side probe" in message

    def test_empty_ndi_name_after_prefix_strip_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        ready, message = probe_live_source(
            _source(source_type="ndi", endpoint_url="ndi://"), timeout_seconds=5.0
        )
        assert ready is False
        assert message is not None
        assert "not recognized" in message


# ---------------------------------------------------------------------------
# Command construction per source type
# ---------------------------------------------------------------------------


class TestCommandConstruction:
    def test_rtmp_probes_endpoint_url_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)

        ready, _ = probe_live_source(
            _source(source_type="rtmp", endpoint_url="rtmp://camera.example/live"),
            timeout_seconds=5.0,
        )
        assert ready is True
        cmd = captured["cmd"]
        assert cmd[0] == "ffprobe"
        assert "-i" in cmd
        assert cmd[cmd.index("-i") + 1] == "rtmp://camera.example/live"
        assert captured["kwargs"]["timeout"] == 5.0

    def test_srt_probes_endpoint_url_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            captured["cmd"] = cmd
            return _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)

        probe_live_source(
            _source(source_type="srt", endpoint_url="srt://encoder.example:9000"),
            timeout_seconds=5.0,
        )
        cmd = captured["cmd"]
        assert cmd[cmd.index("-i") + 1] == "srt://encoder.example:9000"

    def test_ndi_probes_via_libndi_newtek_demuxer_with_bare_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, Any] = {}

        def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            captured["cmd"] = cmd
            return _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)

        probe_live_source(
            _source(source_type="ndi", endpoint_url="ndi://Council Room A"),
            timeout_seconds=5.0,
        )
        cmd = captured["cmd"]
        assert "-f" in cmd
        assert cmd[cmd.index("-f") + 1] == "libndi_newtek"
        assert cmd[cmd.index("-i") + 1] == "Council Room A"

    def test_bounded_analysis_options_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            captured["cmd"] = cmd
            return _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)

        probe_live_source(_source(), timeout_seconds=5.0)
        cmd = captured["cmd"]
        assert "-analyzeduration" in cmd
        assert "-probesize" in cmd


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


class TestOutcomes:
    def test_video_stream_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr(
            "civiccast.live.source_probe.subprocess.run",
            lambda *a, **kw: _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True)),
        )
        ready, message = probe_live_source(_source(), timeout_seconds=5.0)
        assert ready is True
        assert message is not None
        assert "room-a-rtmp" in message
        assert "video" in message

    def test_audio_only_stream_passes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr(
            "civiccast.live.source_probe.subprocess.run",
            lambda *a, **kw: _FakeCompleted(returncode=0, stdout=_ffprobe_json(audio=True)),
        )
        ready, message = probe_live_source(_source(), timeout_seconds=5.0)
        assert ready is True
        assert message is not None
        assert "audio" in message

    def test_no_streams_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr(
            "civiccast.live.source_probe.subprocess.run",
            lambda *a, **kw: _FakeCompleted(returncode=0, stdout=_ffprobe_json()),
        )
        ready, message = probe_live_source(_source(), timeout_seconds=5.0)
        assert ready is False
        assert message is not None
        assert "no video or audio stream" in message

    def test_nonzero_exit_fails_with_stderr_detail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr(
            "civiccast.live.source_probe.subprocess.run",
            lambda *a, **kw: _FakeCompleted(
                returncode=1, stderr="Connection refused connecting to camera.example:1935"
            ),
        )
        ready, message = probe_live_source(_source(), timeout_seconds=5.0)
        assert ready is False
        assert message is not None
        assert "Connection refused" in message
        assert "room-a-rtmp" in message

    def test_stderr_detail_is_truncated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        huge = "x" * 5000
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr(
            "civiccast.live.source_probe.subprocess.run",
            lambda *a, **kw: _FakeCompleted(returncode=1, stderr=huge),
        )
        ready, message = probe_live_source(_source(), timeout_seconds=5.0)
        assert ready is False
        assert message is not None
        assert len(message) < 1000

    def test_invalid_json_output_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr(
            "civiccast.live.source_probe.subprocess.run",
            lambda *a, **kw: _FakeCompleted(returncode=0, stdout="not json"),
        )
        ready, message = probe_live_source(_source(), timeout_seconds=5.0)
        assert ready is False
        assert message is not None
        assert "unreadable output" in message

    def test_timeout_fails_with_actionable_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_timeout(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout", 5.0))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _raise_timeout)

        ready, message = probe_live_source(_source(), timeout_seconds=3.0)
        assert ready is False
        assert message is not None
        assert "3s" in message
        assert "rtmp://camera.example/live" in message

    def test_oserror_starting_ffprobe_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _raise_os_error(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            raise OSError("no such file or directory")

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _raise_os_error)

        ready, message = probe_live_source(_source(), timeout_seconds=5.0)
        assert ready is False
        assert message is not None
        assert "Could not start ffprobe" in message


# ---------------------------------------------------------------------------
# build_source_probe: env var + explicit override wiring
# ---------------------------------------------------------------------------


class TestBuildSourceProbe:
    def test_default_timeout_used_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS", raising=False)
        captured: dict[str, Any] = {}

        def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            captured["timeout"] = kwargs.get("timeout")
            return _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)

        probe = build_source_probe()
        probe(_source())
        assert captured["timeout"] == DEFAULT_SOURCE_PROBE_TIMEOUT_SECONDS

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS", "2.5")
        captured: dict[str, Any] = {}

        def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            captured["timeout"] = kwargs.get("timeout")
            return _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)

        probe = build_source_probe()
        probe(_source())
        assert captured["timeout"] == 2.5

    def test_invalid_env_var_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS", "not-a-number")
        captured: dict[str, Any] = {}

        def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            captured["timeout"] = kwargs.get("timeout")
            return _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)

        probe = build_source_probe()
        probe(_source())
        assert captured["timeout"] == DEFAULT_SOURCE_PROBE_TIMEOUT_SECONDS

    def test_explicit_timeout_wins_over_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_LIVE_SOURCE_PROBE_TIMEOUT_SECONDS", "99")
        captured: dict[str, Any] = {}

        def _fake_run(cmd: list[str], **kwargs: Any) -> _FakeCompleted:
            captured["timeout"] = kwargs.get("timeout")
            return _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True))

        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr("civiccast.live.source_probe.subprocess.run", _fake_run)

        probe = build_source_probe(timeout_seconds=1.5)
        probe(_source())
        assert captured["timeout"] == 1.5

    def test_returned_probe_matches_source_probe_contract(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The evaluator calls ``source_probe(source_row)`` positionally
        (see PreflightEvaluator.evaluate); the built probe must accept
        that shape."""
        monkeypatch.setattr(
            "civiccast.live.source_probe.shutil.which", lambda _exe: "/usr/bin/ffprobe"
        )
        monkeypatch.setattr(
            "civiccast.live.source_probe.subprocess.run",
            lambda *a, **kw: _FakeCompleted(returncode=0, stdout=_ffprobe_json(video=True)),
        )
        probe = build_source_probe()
        ready, message = probe(_source())
        assert ready is True
        assert isinstance(message, str)
