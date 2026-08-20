# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from pathlib import Path

from civiccast.egress.encoder_strategy import ConcatEncoderStrategy, EncoderStartRequest
from civiccast.egress.models import (
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)


class _FakeProcess:
    pid = 4242

    def poll(self) -> None:
        return None


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


def _source_plan(tmp_path: Path) -> EgressSourcePlan:
    source = tmp_path / "source.ts"
    source.write_text("fake", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(label="Program", path=str(source), duration_seconds=1),
        ],
    )


def test_concat_encoder_strategy_writes_plan_and_starts_ffmpeg(tmp_path: Path) -> None:
    captured: dict[str, list[str]] = {}
    process = _FakeProcess()
    strategy = ConcatEncoderStrategy()

    result = strategy.start(
        EncoderStartRequest(
            channel_id="gov",
            source_plan=_source_plan(tmp_path),
            config=_config(),
            work_dir=tmp_path / "work",
            ffmpeg_starter=lambda args: captured.setdefault("args", args) and process,
        )
    )

    assert result.process is process
    assert result.concat_plan_path.read_text(encoding="utf-8").startswith("ffconcat version 1.0")
    assert result.stderr_path == tmp_path / "work" / "gov" / "logs" / "ffmpeg.stderr.log"
    assert "-f" in captured["args"]
    assert str(result.concat_plan_path) in captured["args"]
