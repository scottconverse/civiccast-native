# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.egress.continuity import (
    CONTINUITY_PROOF_BOUNDARY,
    build_boundary_events,
    run_filesink_continuity_proof,
    run_srt_receiver_continuity_proof,
    split_srt_receiver_options,
)
from civiccast.egress.models import (
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.stream._ffmpeg import FfmpegResult
from civiccast.stream.loudness import LoudnessGateResult


def _source_plan(tmp_path: Path, *, segments: int = 3) -> EgressSourcePlan:
    source_paths = []
    for index in range(segments):
        path = tmp_path / f"source-{index}.ts"
        path.write_bytes(b"not real media for unit tests")
        source_paths.append(path)
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label=f"Program {index}",
                path=str(path),
                duration_seconds=2.0,
            )
            for index, path in enumerate(source_paths, start=1)
        ],
    )


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        sinks=[EgressSinkSpec(kind="srt", label="Headend", uri="srt://127.0.0.1:19001")],
        slate_message="Local government programming will resume shortly.",
    )


def test_build_boundary_events_uses_expected_segment_offsets(tmp_path: Path) -> None:
    events = build_boundary_events(_source_plan(tmp_path, segments=4))

    assert [event.index for event in events] == [1, 2, 3]
    assert [event.source_label for event in events] == ["Program 2", "Program 3", "Program 4"]
    assert [event.expected_start_seconds for event in events] == [2.0, 4.0, 6.0]


def test_filesink_continuity_proof_passes_with_duration_and_loudness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "proof.ts"

    def fake_runner(args: list[str]) -> FfmpegResult:
        assert "-f" in args
        assert str(output_path) in args
        output_path.write_bytes(b"transport stream")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("civiccast.egress.continuity.probe_duration", lambda _path: 6.0)
    monkeypatch.setattr(
        "civiccast.egress.continuity.check_streaming_loudness",
        lambda **_kwargs: LoudnessGateResult(
            status="ok",
            standard="ITU-R BS.1770 / EBU R128",
            target_lufs=-16.0,
            used_ffmpeg_wrapper=True,
            measured_lufs=-16.2,
            operator_action="Loudness is within tolerance.",
        ),
    )

    proof = run_filesink_continuity_proof(
        source_plan=_source_plan(tmp_path),
        config=_config(),
        output_path=output_path,
        work_dir=tmp_path / "work",
        ffmpeg_runner=fake_runner,
    )

    assert proof.status == "PASS"
    assert proof.proof_boundary == CONTINUITY_PROOF_BOUNDARY
    assert proof.boundary_count == 2
    assert proof.measured_duration_seconds == 6.0
    assert proof.measured_lufs == -16.2
    assert proof.blocker is None
    assert "not downstream acceptance" in proof.not_claimed[2]


def test_filesink_continuity_proof_rejects_channel_mismatch(tmp_path: Path) -> None:
    config = _config().model_copy(update={"channel_id": "education"})

    with pytest.raises(ValueError, match="does not match"):
        run_filesink_continuity_proof(
            source_plan=_source_plan(tmp_path),
            config=config,
            output_path=tmp_path / "proof.ts",
            work_dir=tmp_path / "work",
            ffmpeg_runner=lambda _args: pytest.fail("FFmpeg should not run for mismatched input"),
        )


def test_filesink_continuity_proof_fails_closed_when_loudness_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "proof.ts"

    def fake_runner(_args: list[str]) -> FfmpegResult:
        output_path.write_bytes(b"transport stream")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("civiccast.egress.continuity.probe_duration", lambda _path: 6.0)
    monkeypatch.setattr(
        "civiccast.egress.continuity.check_streaming_loudness",
        lambda **_kwargs: LoudnessGateResult(
            status="failed",
            standard="ITU-R BS.1770 / EBU R128",
            target_lufs=-16.0,
            used_ffmpeg_wrapper=True,
            measured_lufs=-21.0,
            operator_action="Normalize stream audio to -16 LUFS and rerun the loudness gate.",
        ),
    )

    proof = run_filesink_continuity_proof(
        source_plan=_source_plan(tmp_path),
        config=_config(),
        output_path=output_path,
        work_dir=tmp_path / "work",
        ffmpeg_runner=fake_runner,
    )

    assert proof.status == "FAIL"
    assert proof.blocker == "EGRESS_CONTINUITY_LOUDNESS_OUT_OF_TOLERANCE"
    assert proof.measured_lufs == -21.0


def test_split_srt_receiver_options_moves_mode_out_of_url() -> None:
    mode, url = split_srt_receiver_options("srt://127.0.0.1:19001?mode=listener&latency=200000")

    assert mode == "listener"
    assert url == "srt://127.0.0.1:19001"


def test_srt_receiver_continuity_proof_passes_with_receiver_metrics(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver_output = tmp_path / "receiver.ts"
    captured: dict[str, object] = {}

    class _FakeProcess:
        returncode = 0

        def wait(self, *, timeout: float) -> int:
            captured["wait_timeout"] = timeout
            return 0

    class _FakeHandle:
        process = _FakeProcess()

        def close(self) -> None:
            captured["closed"] = True

    def fake_start_ffmpeg(args: list[str], **kwargs: object) -> _FakeHandle:
        captured["receiver_args"] = args
        captured["receiver_kwargs"] = kwargs
        return _FakeHandle()

    def fake_runner(args: list[str]) -> FfmpegResult:
        captured["sender_args"] = args
        receiver_output.write_bytes(b"transport stream")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("civiccast.egress.continuity.start_ffmpeg", fake_start_ffmpeg)
    monkeypatch.setattr("civiccast.egress.continuity.probe_duration", lambda _path: 6.0)
    monkeypatch.setattr(
        "civiccast.egress.continuity.check_streaming_loudness",
        lambda **_kwargs: LoudnessGateResult(
            status="ok",
            standard="ITU-R BS.1770 / EBU R128",
            target_lufs=-16.0,
            used_ffmpeg_wrapper=True,
            measured_lufs=-16.0,
            operator_action="Loudness is within tolerance.",
        ),
    )

    proof = run_srt_receiver_continuity_proof(
        source_plan=_source_plan(tmp_path),
        config=_config(),
        sender_url="srt://127.0.0.1:19001",
        receiver_url="srt://127.0.0.1:19001?mode=listener&latency=200000",
        receiver_output_path=receiver_output,
        work_dir=tmp_path / "work",
        receiver_startup_seconds=0,
        ffmpeg_runner=fake_runner,
    )

    assert proof.status == "PASS"
    assert proof.sink_kind == "srt"
    assert proof.receiver_returncode == 0
    assert proof.receiver_output_path == str(receiver_output)
    assert proof.boundary_count == 2
    assert captured["closed"] is True
    receiver_args = captured["receiver_args"]
    assert isinstance(receiver_args, list)
    assert "-mode" in receiver_args
    assert "srt://127.0.0.1:19001" in receiver_args


def test_srt_receiver_continuity_proof_preserves_configured_srt_latency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver_output = tmp_path / "receiver.ts"
    captured: dict[str, object] = {}

    class _FakeProcess:
        returncode = 0

        def wait(self, *, timeout: float) -> int:
            return 0

    class _FakeHandle:
        process = _FakeProcess()

        def close(self) -> None:
            return None

    def fake_start_ffmpeg(_args: list[str], **_kwargs: object) -> _FakeHandle:
        return _FakeHandle()

    def fake_runner(args: list[str]) -> FfmpegResult:
        captured["sender_args"] = args
        receiver_output.write_bytes(b"transport stream")
        return FfmpegResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("civiccast.egress.continuity.start_ffmpeg", fake_start_ffmpeg)
    monkeypatch.setattr("civiccast.egress.continuity.probe_duration", lambda _path: 6.0)
    monkeypatch.setattr(
        "civiccast.egress.continuity.check_streaming_loudness",
        lambda **_kwargs: LoudnessGateResult(
            status="ok",
            standard="ITU-R BS.1770 / EBU R128",
            target_lufs=-16.0,
            used_ffmpeg_wrapper=True,
            measured_lufs=-16.0,
            operator_action="Loudness is within tolerance.",
        ),
    )
    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        sinks=[
            EgressSinkSpec(
                kind="srt",
                label="Loopback",
                uri="srt://127.0.0.1:19001",
                latency_ms=120,
            )
        ],
        slate_message="Local government programming will resume shortly.",
    )

    proof = run_srt_receiver_continuity_proof(
        source_plan=_source_plan(tmp_path),
        config=config,
        sender_url="srt://127.0.0.1:19001",
        receiver_url="srt://127.0.0.1:19001?mode=listener",
        receiver_output_path=receiver_output,
        work_dir=tmp_path / "work",
        receiver_startup_seconds=0,
        ffmpeg_runner=fake_runner,
    )

    assert proof.status == "PASS"
    sender_args = captured["sender_args"]
    assert isinstance(sender_args, list)
    assert "srt://127.0.0.1:19001?mode=caller&latency=120000&linger=5" in sender_args
    assert all("latency=2000000" not in arg for arg in sender_args)


def test_srt_receiver_continuity_proof_fails_closed_on_receiver_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receiver_output = tmp_path / "receiver.ts"

    class _FakeProcess:
        returncode = 1

        def wait(self, *, timeout: float) -> int:
            return 1

    class _FakeHandle:
        process = _FakeProcess()

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        "civiccast.egress.continuity.start_ffmpeg",
        lambda *args, **kwargs: _FakeHandle(),
    )
    monkeypatch.setattr(
        "civiccast.egress.continuity.probe_duration",
        lambda _path: pytest.fail("receiver output should not be trusted"),
    )

    proof = run_srt_receiver_continuity_proof(
        source_plan=_source_plan(tmp_path),
        config=_config(),
        sender_url="srt://127.0.0.1:19001",
        receiver_url="srt://127.0.0.1:19001?mode=listener",
        receiver_output_path=receiver_output,
        work_dir=tmp_path / "work",
        receiver_startup_seconds=0,
        ffmpeg_runner=lambda _args: FfmpegResult(returncode=0, stdout="", stderr=""),
    )

    assert proof.status == "FAIL"
    assert proof.blocker == "EGRESS_CONTINUITY_SRT_RECEIVER_FAILED"
    assert proof.receiver_returncode == 1
