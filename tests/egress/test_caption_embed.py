# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.captions.models import CaptionCue
from civiccast.egress.caption_embed import (
    CAPTION_EMBED_PROOF_BOUNDARY,
    PassThroughCaptionEmbedder,
    SidecarCaptionEmbedder,
    evaluate_caption_decode_back,
    parse_caption_cues_from_timed_text,
)


def _cue(
    cue_id: str,
    *,
    start: float = 1.0,
    end: float = 2.0,
    text: str = "Motion carries.",
) -> CaptionCue:
    return CaptionCue(
        cue_id=cue_id,
        start_seconds=start,
        end_seconds=end,
        text=text,
        confidence=0.99,
    )


def test_pass_through_caption_embedder_keeps_status_not_verified() -> None:
    plan = PassThroughCaptionEmbedder().build_plan(
        channel_id="gov",
        cues=[_cue("cue-1")],
    )

    assert plan.status == "not-verified"
    assert plan.mode == "passthrough"
    assert plan.cue_count == 1
    assert plan.ffmpeg_args == []
    assert plan.proof_boundary == CAPTION_EMBED_PROOF_BOUNDARY
    assert any("does not claim CEA-708" in claim for claim in plan.not_claimed)


def test_sidecar_caption_embedder_builds_ffmpeg_plan_without_claiming_on(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "captions.vtt"
    sidecar.write_text("WEBVTT\n", encoding="utf-8")

    plan = SidecarCaptionEmbedder(sidecar_path=sidecar).build_plan(
        channel_id="gov",
        cues=[_cue("cue-1")],
    )

    assert plan.status == "not-verified"
    assert plan.mode == "sidecar"
    assert plan.cue_count == 1
    assert plan.input_args == ["-i", str(sidecar)]
    assert plan.stream_args == ["-map", "1:s:0?", "-c:s", "copy"]
    assert plan.ffmpeg_args == [*plan.input_args, *plan.stream_args]
    assert any("captions survived" in claim for claim in plan.not_claimed)


def test_caption_decode_back_pass_flips_caption_status_on(tmp_path: Path) -> None:
    proof = evaluate_caption_decode_back(
        channel_id="gov",
        emitted_stream_path=tmp_path / "egress.ts",
        expected_cues=[_cue("cue-1"), _cue("cue-2", start=3.0, end=4.0, text="Second cue.")],
        decoded_cues=[
            _cue("decoded-1", start=1.1, end=2.1, text=" motion   carries. "),
            _cue("decoded-2", start=3.2, end=4.1, text="Second cue."),
        ],
        decoder_name="ffmpeg-cc-decode",
    )

    assert proof.status == "PASS"
    assert proof.caption_status == "on"
    assert proof.blocker is None
    assert proof.expected_cue_count == 2
    assert proof.decoded_cue_count == 2
    assert proof.matched_cue_count == 2
    assert proof.max_timing_delta_seconds == pytest.approx(0.2)


def test_caption_decode_back_mismatch_keeps_status_not_verified(tmp_path: Path) -> None:
    proof = evaluate_caption_decode_back(
        channel_id="gov",
        emitted_stream_path=tmp_path / "egress.ts",
        expected_cues=[_cue("cue-1")],
        decoded_cues=[_cue("decoded-1", text="Different caption.")],
        decoder_name="ffmpeg-cc-decode",
    )

    assert proof.status == "FAIL"
    assert proof.caption_status == "not-verified"
    assert proof.blocker == "EGRESS_CAPTION_DECODE_BACK_MISMATCH"


def test_caption_decode_back_requires_expected_cues(tmp_path: Path) -> None:
    proof = evaluate_caption_decode_back(
        channel_id="gov",
        emitted_stream_path=tmp_path / "egress.ts",
        expected_cues=[],
        decoded_cues=[_cue("decoded-1")],
        decoder_name="ffmpeg-cc-decode",
    )

    assert proof.status == "FAIL"
    assert proof.caption_status == "not-verified"
    assert proof.blocker == "EGRESS_CAPTION_DECODE_BACK_NO_EXPECTED_CUES"


def test_parse_caption_cues_from_webvtt_and_srt_text() -> None:
    cues = parse_caption_cues_from_timed_text(
        """WEBVTT

cue-a
00:00:01.000 --> 00:00:02.250
Motion <i>carries</i>.

2
00:00:03,000 --> 00:00:04,500
Second cue.
""",
        source_id="decoded-captions",
    )

    assert [cue.cue_id for cue in cues] == ["decoded-captions-cue-a", "decoded-captions-000002"]
    assert cues[0].start_seconds == 1.0
    assert cues[0].end_seconds == 2.25
    assert cues[0].text == "Motion carries."
    assert cues[1].start_seconds == 3.0
    assert cues[1].end_seconds == 4.5
