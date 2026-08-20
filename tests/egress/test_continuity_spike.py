# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "egress-continuity-spike.py"
SPEC = importlib.util.spec_from_file_location("egress_continuity_spike", SCRIPT_PATH)
assert SPEC is not None
spike = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = spike
SPEC.loader.exec_module(spike)


def test_write_concat_plan_records_expected_boundaries(tmp_path: Path) -> None:
    source_a = tmp_path / "source-a.ts"
    source_b = tmp_path / "source-b.ts"
    source_a.write_text("a", encoding="utf-8")
    source_b.write_text("b", encoding="utf-8")
    plan = tmp_path / "concat.ffconcat"

    events = spike.write_concat_plan(
        plan,
        [source_a, source_b],
        boundary_count=3,
        segment_seconds=1.5,
    )

    assert plan.read_text(encoding="utf-8").splitlines() == [
        "ffconcat version 1.0",
        f"file '{source_a.resolve().as_posix()}'",
        f"file '{source_b.resolve().as_posix()}'",
        f"file '{source_a.resolve().as_posix()}'",
        f"file '{source_b.resolve().as_posix()}'",
    ]
    assert [event.expected_start_seconds for event in events] == [1.5, 3.0, 4.5]
    assert [event.source_label for event in events] == ["source-b", "source-a", "source-b"]


def test_secret_bearing_srt_urls_are_rejected() -> None:
    assert spike._looks_secret_bearing("srt://example.test:9000?passphrase=secret")
    assert spike._looks_secret_bearing("rtmp://user:token@example.test/live")
    assert not spike._looks_secret_bearing("srt://example.test:9000?mode=caller&latency=2000000")


def test_srt_receiver_requires_srt_sink_and_output(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="only valid with --sink srt"):
        spike.run_spike(
            output_dir=tmp_path,
            boundary_count=1,
            segment_seconds=0.1,
            sink="file",
            srt_receiver_url="srt://127.0.0.1:19001?mode=listener",
            srt_receiver_output=tmp_path / "receiver.ts",
        )

    with pytest.raises(ValueError, match="--srt-receiver-output is required"):
        spike.run_spike(
            output_dir=tmp_path,
            boundary_count=1,
            segment_seconds=0.1,
            sink="srt",
            srt_url="srt://127.0.0.1:19001?mode=caller",
            srt_receiver_url="srt://127.0.0.1:19001?mode=listener",
        )


def test_secret_bearing_srt_receiver_urls_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="receiver URL appears to include a secret"):
        spike.run_spike(
            output_dir=tmp_path,
            boundary_count=1,
            segment_seconds=0.1,
            sink="srt",
            srt_url="srt://127.0.0.1:19001?mode=caller",
            srt_receiver_url="srt://127.0.0.1:19001?mode=listener&passphrase=secret",
            srt_receiver_output=tmp_path / "receiver.ts",
        )


def test_srt_receiver_mode_query_is_normalized_to_ffmpeg_option() -> None:
    mode, url = spike.split_srt_receiver_options(
        "srt://127.0.0.1:19001?mode=listener&latency=200000"
    )

    assert mode == "listener"
    assert url == "srt://127.0.0.1:19001"


def test_start_srt_receiver_passes_mode_as_ffmpeg_option(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    class FakeProcess:
        pass

    def fake_popen(args: list[str], **kwargs: object) -> FakeProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(spike.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(spike.subprocess, "Popen", fake_popen)

    process = spike.start_srt_receiver(
        receiver_url="srt://127.0.0.1:19001?mode=listener&latency=200000",
        output_path=tmp_path / "receiver.ts",
    )

    assert isinstance(process, FakeProcess)
    args = captured["args"]
    assert isinstance(args, list)
    assert "-mode" in args
    assert args[args.index("-mode") + 1] == "listener"
    assert "srt://127.0.0.1:19001" in args
    assert not any("mode=listener" in arg for arg in args)


def test_srt_sender_default_linger_is_added_once() -> None:
    assert (
        spike.with_srt_default_linger("srt://127.0.0.1:19001?mode=caller&latency=200000")
        == "srt://127.0.0.1:19001?mode=caller&latency=200000&linger=5"
    )
    assert (
        spike.with_srt_default_linger("srt://127.0.0.1:19001?mode=caller&latency=200000&linger=9")
        == "srt://127.0.0.1:19001?mode=caller&latency=200000&linger=9"
    )


def test_srt_sender_is_paced_without_slowing_file_sink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[list[str]] = []

    def fake_run_ffmpeg(args: list[str]) -> spike.FfmpegResult:
        captured.append(args)
        return spike.FfmpegResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(spike, "run_ffmpeg", fake_run_ffmpeg)

    spike.run_persistent_concat_encoder(
        concat_plan=tmp_path / "concat.ffconcat",
        output_target="srt://127.0.0.1:19001?mode=caller",
        sink="srt",
    )
    spike.run_persistent_concat_encoder(
        concat_plan=tmp_path / "concat.ffconcat",
        output_target=str(tmp_path / "out.ts"),
        sink="file",
    )

    assert "-re" in captured[0]
    assert "-re" not in captured[1]


def test_sender_only_srt_is_not_accepted_as_continuity_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spike, "generate_conformed_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        spike,
        "run_persistent_concat_encoder",
        lambda *args, **kwargs: spike.FfmpegResult(returncode=0, stdout="", stderr=""),
    )

    result = spike.run_spike(
        output_dir=tmp_path,
        boundary_count=2,
        segment_seconds=0.1,
        sink="srt",
        srt_url="srt://127.0.0.1:19001?mode=caller",
    )

    assert not result.passed
    assert result.ffmpeg_returncode == 0
    assert result.receiver_metrics is None
    assert "sender-only SRT output is not accepted" in result.operator_action


def test_failed_file_sink_run_does_not_probe_stale_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stale_output = tmp_path / "egress-continuity-output.ts"
    stale_output.write_text("old output", encoding="utf-8")
    monkeypatch.setattr(spike, "generate_conformed_source", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        spike,
        "run_persistent_concat_encoder",
        lambda *args, **kwargs: spike.FfmpegResult(returncode=1, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        spike,
        "probe_duration",
        lambda *args, **kwargs: pytest.fail("stale output should not be probed"),
    )

    result = spike.run_spike(
        output_dir=tmp_path,
        boundary_count=2,
        segment_seconds=0.1,
    )

    assert not result.passed
    assert result.measured_duration_seconds is None


def test_failed_environment_result_makes_no_headend_claim(tmp_path: Path) -> None:
    result = spike.failed_environment_result(
        output_dir=tmp_path,
        boundary_count=5,
        reason="ffmpeg not found",
    )

    assert not result.passed
    assert result.ffmpeg_returncode == -1
    assert "No headend, SRT, caption, EAS, SDI, or compliance claim is made." in result.not_claimed
    assert result.operator_action == "ffmpeg not found"


def test_keep_going_writes_failed_json_when_gpl_preflight_cannot_find_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "result.json"
    monkeypatch.setattr(spike.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--output-dir",
            str(tmp_path),
            "--json-output",
            str(output),
            "--keep-going-on-ffmpeg-missing",
        ],
    )

    assert spike.main() == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert result["operator_action"] == "ffmpeg not found on PATH"


def test_gpl_preflight_normalizes_probe_spawn_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "result.json"

    def cannot_execute(*args: object, **kwargs: object) -> None:
        raise OSError("cannot execute")

    monkeypatch.setattr(spike.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(spike.subprocess, "run", cannot_execute)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT_PATH),
            "--output-dir",
            str(tmp_path),
            "--json-output",
            str(output),
            "--keep-going-on-ffmpeg-missing",
        ],
    )

    assert spike.main() == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert result["operator_action"].startswith("could not run ffmpeg encoder probe:")


@pytest.mark.parametrize("keep_going", [False, True])
def test_cli_rejects_failed_probe_even_if_output_lists_libx264(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    keep_going: bool,
) -> None:
    output = tmp_path / "result.json"
    monkeypatch.setattr(spike.shutil, "which", lambda name: "ffmpeg")
    monkeypatch.setattr(
        spike.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=1, stdout="libx264", stderr="probe failed"
        ),
    )
    argv = [
        str(SCRIPT_PATH),
        "--output-dir",
        str(tmp_path),
        "--json-output",
        str(output),
    ]
    if keep_going:
        argv.append("--keep-going-on-ffmpeg-missing")
    monkeypatch.setattr(sys, "argv", argv)

    if not keep_going:
        with pytest.raises(spike.FfmpegNotFoundError, match="probe exited 1: probe failed"):
            spike.main()
        assert not output.exists()
        return

    assert spike.main() == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["passed"] is False
    assert result["operator_action"] == "ffmpeg encoder probe exited 1: probe failed"
    assert "No headend, SRT, caption, EAS, SDI, or compliance claim is made." in result[
        "not_claimed"
    ]


def test_success_result_shape_keeps_file_sink_claim_boundary() -> None:
    result = spike.ContinuitySpikeResult(
        passed=True,
        strategy="concat-demuxer-single-ffmpeg-process",
        sink_kind="file",
        boundary_count=2,
        expected_duration_seconds=3.0,
        measured_duration_seconds=3.0,
        duration_within_tolerance=True,
        ffmpeg_returncode=0,
        output_path="out.ts",
        concat_plan_path="concat.ffconcat",
        boundary_events=[
            spike.BoundaryEvent(index=1, source_label="source-b", expected_start_seconds=1.0)
        ],
        not_claimed=[
            "A FileSink or loopback SRT PASS is not equivalent to real downstream receiver proof."
        ],
        operator_action="Proceed to real-or-representative SRT receiver testing.",
    )

    rendered = result.to_json()
    assert '"passed": true' in rendered
    assert "not equivalent to real downstream receiver proof" in rendered


def test_success_result_shape_includes_optional_receiver_metrics() -> None:
    result = spike.ContinuitySpikeResult(
        passed=True,
        strategy="concat-demuxer-single-ffmpeg-process",
        sink_kind="srt",
        boundary_count=2,
        expected_duration_seconds=3.0,
        measured_duration_seconds=3.0,
        duration_within_tolerance=True,
        ffmpeg_returncode=0,
        output_path="srt://127.0.0.1:19001?mode=caller",
        concat_plan_path="concat.ffconcat",
        boundary_events=[],
        not_claimed=[
            "A FileSink or loopback SRT PASS is not equivalent to real downstream receiver proof."
        ],
        operator_action="Proceed to real-or-representative SRT receiver testing.",
        receiver_metrics=spike.ReceiverMetrics(
            output_path="receiver.ts",
            returncode=0,
            measured_duration_seconds=3.0,
            duration_within_tolerance=True,
            stderr_tail="",
        ),
    )

    rendered = result.to_json()
    assert '"receiver_metrics"' in rendered
    assert '"output_path": "receiver.ts"' in rendered
