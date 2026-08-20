# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from civiccast.native.installed_gstreamer_smoke import (
    InstalledGstreamerSmokeError,
    discoverer_command,
    require_clean_worker_result,
    require_discoverer_evidence,
    worker_command,
)

_DISCOVERER_VERBOSE_MPEG_TS = """\
Analyzing file:///C:/installed/smoke.ts
Done discovering file:///C:/installed/smoke.ts
container #0: MPEG-2 Transport Stream
  video #0: video/x-h264, stream-format=(string)byte-stream, alignment=(string)au
  audio #1: audio/mpeg, mpegversion=(int)4, stream-format=(string)raw
"""


def test_smoke_runs_the_actual_product_worker_module() -> None:
    command = worker_command(python=Path("C:/installed/python.exe"), graph=Path("C:/smoke.json"))
    assert command[1:3] == ["-m", "civiccast.egress.gst.worker"]


def test_smoke_uses_verbose_discoverer_records() -> None:
    command = discoverer_command(version_root=Path("C:/installed"), output=Path("C:/smoke.ts"))
    assert command[1:] == ["--verbose", str(Path("C:/smoke.ts"))]


def test_smoke_accepts_real_discoverer_container_and_caps_records() -> None:
    evidence = require_discoverer_evidence(
        subprocess.CompletedProcess([], 0, _DISCOVERER_VERBOSE_MPEG_TS, "")
    )
    assert evidence["discovered_container_record"] == "container #0: MPEG-2 Transport Stream"
    assert evidence["discovered_video_record"].startswith("video #0: video/x-h264")
    assert evidence["discovered_audio_record"].startswith("audio #1: audio/mpeg")
    assert evidence["raw_discoverer_stdout"] == _DISCOVERER_VERBOSE_MPEG_TS
    assert evidence["raw_discoverer_stderr"] == ""


_DISCOVERER_VERBOSE_CAPS_FORM = """\
Analyzing file:///C:/installed/smoke.ts
Done discovering file:///C:/installed/smoke.ts

Properties:
  Duration: 0:00:00.000000000
  container #0: video/mpegts, systemstream=(boolean)true, packetsize=(int)188
    video #1: video/x-h264, stream-format=(string)avc, width=(int)320, height=(int)180
    audio #2: audio/mpeg, framed=(boolean)true, mpegversion=(int)4, rate=(int)48000
"""


def test_smoke_accepts_the_caps_form_container_record_gst_1_28_emits() -> None:
    # Candidate run 31198785853: the worker produced real MPEG-TS bytes and
    # the discoverer identified them, but printed the container line in CAPS
    # form -- reproduced verbatim against the pinned 1.28.5 closure tools.
    # The fixture lines above are copied from that local repro's output.
    evidence = require_discoverer_evidence(
        subprocess.CompletedProcess([], 0, _DISCOVERER_VERBOSE_CAPS_FORM, "")
    )
    assert evidence["discovered_container_record"].startswith("container #0: video/mpegts")
    assert "systemstream=(boolean)true" in evidence["discovered_container_record"]
    assert evidence["discovered_video_record"].startswith("video #1: video/x-h264")
    assert evidence["discovered_audio_record"].startswith("audio #2: audio/mpeg")


def test_smoke_rejects_a_caps_form_container_that_is_not_a_transport_stream() -> None:
    stdout = _DISCOVERER_VERBOSE_CAPS_FORM.replace(
        "container #0: video/mpegts, systemstream=(boolean)true, packetsize=(int)188",
        "container #0: video/quicktime, variant=(string)iso",
    )
    with pytest.raises(InstalledGstreamerSmokeError, match="MPEG-TS container"):
        require_discoverer_evidence(subprocess.CompletedProcess([], 0, stdout, ""))


def test_smoke_rejects_a_caps_form_mpegts_line_without_systemstream_true() -> None:
    stdout = _DISCOVERER_VERBOSE_CAPS_FORM.replace(
        "container #0: video/mpegts, systemstream=(boolean)true, packetsize=(int)188",
        "container #0: video/mpegts, systemstream=(boolean)false, packetsize=(int)188",
    )
    with pytest.raises(InstalledGstreamerSmokeError, match="MPEG-TS container"):
        require_discoverer_evidence(subprocess.CompletedProcess([], 0, stdout, ""))


def test_smoke_rejects_discoverer_without_audio_or_video_evidence() -> None:
    result = subprocess.CompletedProcess(
        args=["gst-discoverer-1.0.exe"], returncode=0, stdout="MPEG-TS video stream", stderr=""
    )
    with pytest.raises(InstalledGstreamerSmokeError, match="MPEG-TS container"):
        require_discoverer_evidence(result)


@pytest.mark.parametrize(
    "stdout,stderr",
    [
        ("Container: MPEG-TS\nNo streams found.\n", "warning: video audio unavailable"),
        ("container #0: MPEG-2 Transport Stream\n  video #0: video/x-h264\n", ""),
        ("container #0: MPEG-2 Transport Stream\n  audio #1: audio/mpeg\n", ""),
        ("container #0: MPEG-2 Transport Stream\n  video #0: H.264\n  audio #1: AAC\n", ""),
    ],
)
def test_smoke_rejects_false_or_malformed_discoverer_records(stdout: str, stderr: str) -> None:
    with pytest.raises(InstalledGstreamerSmokeError):
        require_discoverer_evidence(subprocess.CompletedProcess([], 0, stdout, stderr))


def test_smoke_rejects_a_missing_discoverer_binary() -> None:
    result = subprocess.CompletedProcess(
        args=["gst-discoverer-1.0.exe"], returncode=1, stdout="", stderr="not found"
    )
    with pytest.raises(InstalledGstreamerSmokeError, match="gst-discoverer failed"):
        require_discoverer_evidence(result)


def test_smoke_rejects_a_worker_receipt_without_clean_teardown() -> None:
    with pytest.raises(InstalledGstreamerSmokeError, match="clean teardown"):
        require_clean_worker_result("WORKER_RESULT {'error': None, 'teardown_clean': False}")
