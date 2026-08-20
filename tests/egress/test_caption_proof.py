# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11a caption decode-back proof + the fail-closed caption_status gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from civiccast.captions.models import CaptionCue
from civiccast.egress.caption_proof import (
    GST_CC_ELEMENTS,
    build_caption_status_provider,
    caption_lane_report,
    decode_embedded_captions,
    sample_caption_decode_back,
)
from civiccast.egress.models import EgressCaptionProofSample
from civiccast.egress.store import InMemoryEgressStore


def _result(returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    return type("R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()


def _cue(n: int, start: float, end: float, text: str) -> CaptionCue:
    return CaptionCue(
        cue_id=f"c{n}",
        start_seconds=start,
        end_seconds=end,
        text=text,
        confidence=1.0,
        low_confidence=False,
    )


_SRT = """1
00:00:00,200 --> 00:00:01,500
HELLO CIVICCAST

2
00:00:01,800 --> 00:00:02,800
CAPTION TEST TWO
"""


def test_decode_embedded_captions_parses_subcc_srt() -> None:
    cues = decode_embedded_captions(Path("out.ts"), runner=lambda _a: _result(stdout=_SRT))
    assert [c.text for c in cues] == ["HELLO CIVICCAST", "CAPTION TEST TWO"]


def test_decode_embedded_captions_escapes_windows_drive_colon_through_both_parsers() -> None:
    # The lavfi ``movie=`` filename crosses two escape-consuming ffmpeg parsers, so a
    # drive colon must be double-escaped (``C\\:``). Single-level ``\:`` made ffmpeg
    # split ``C:/...`` at the colon and open the file ``C`` — captions were embedded
    # but the proof always read not-verified on native Windows.
    seen: list[list[str]] = []

    def runner(args: list[str]) -> Any:
        seen.append(args)
        return _result(stdout=_SRT)

    decode_embedded_captions(Path("C:/tmp/out.ts"), runner=runner)
    movie_arg = seen[0][seen[0].index("-i") + 1]
    assert movie_arg == "movie=C\\\\:/tmp/out.ts[out0+subcc]"


def test_decode_embedded_captions_empty_when_no_captions_or_error() -> None:
    assert decode_embedded_captions(Path("out.ts"), runner=lambda _a: _result(stdout="")) == []
    assert (
        decode_embedded_captions(
            Path("out.ts"), runner=lambda _a: _result(returncode=1, stdout=_SRT)
        )
        == []
    )


def test_sample_decode_back_pass_when_captions_match() -> None:
    expected = [_cue(1, 0.2, 1.5, "HELLO CIVICCAST"), _cue(2, 1.8, 2.8, "CAPTION TEST TWO")]
    sample = sample_caption_decode_back(
        channel_id="gov",
        emitted_stream_path=Path("out.ts"),
        expected_cues=expected,
        mode="cea-708",
        runner=lambda _a: _result(stdout=_SRT),
        clock=lambda: datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert sample.status == "PASS"
    assert sample.caption_status == "on"
    assert sample.matched_cue_count == 2
    assert sample.mode == "cea-708"


def test_sample_decode_back_fail_when_no_captions_survive() -> None:
    expected = [_cue(1, 0.2, 1.5, "HELLO CIVICCAST")]
    sample = sample_caption_decode_back(
        channel_id="gov",
        emitted_stream_path=Path("out.ts"),
        expected_cues=expected,
        mode="cea-708",
        runner=lambda _a: _result(stdout=""),
        clock=lambda: datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
    )
    assert sample.status == "FAIL"
    assert sample.caption_status == "not-verified"
    assert sample.blocker == "EGRESS_CAPTION_DECODE_BACK_MISMATCH"


def _append(
    store: InMemoryEgressStore, *, sampled_at: datetime, status: str, caption_status: str
) -> None:
    store.append_caption_proof_sample(
        EgressCaptionProofSample(
            channel_id="gov",
            sampled_at=sampled_at,
            status=status,  # type: ignore[arg-type]
            caption_status=caption_status,  # type: ignore[arg-type]
            mode="cea-708",
            decoder_name="ffmpeg-subcc",
            expected_cue_count=1,
            decoded_cue_count=1 if status == "PASS" else 0,
            matched_cue_count=1 if status == "PASS" else 0,
            proof_boundary="egress-caption-embed-to-emitted-stream-decode-back",
        )
    )


def test_caption_status_provider_on_only_for_fresh_pass() -> None:
    store = InMemoryEgressStore()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    provider = build_caption_status_provider(store, freshness_seconds=120, clock=lambda: now)
    assert provider("gov") == "not-verified"  # no sample
    _append(store, sampled_at=now - timedelta(seconds=10), status="PASS", caption_status="on")
    assert provider("gov") == "on"


def test_caption_status_provider_not_verified_when_stale() -> None:
    store = InMemoryEgressStore()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _append(store, sampled_at=now - timedelta(seconds=600), status="PASS", caption_status="on")
    provider = build_caption_status_provider(store, freshness_seconds=120, clock=lambda: now)
    assert provider("gov") == "not-verified"


def test_caption_status_provider_not_verified_for_fail() -> None:
    store = InMemoryEgressStore()
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    _append(store, sampled_at=now, status="FAIL", caption_status="not-verified")
    provider = build_caption_status_provider(store, freshness_seconds=120, clock=lambda: now)
    assert provider("gov") == "not-verified"


def test_caption_lane_report_capability_summary() -> None:
    full = caption_lane_report(
        ffmpeg_filters="... readeia608 V->V ... ebur128 ...",
        gst_elements=set(GST_CC_ELEMENTS),
    )
    assert full.decode_back_capable is True
    assert full.gst_embed_available is True
    assert full.ffmpeg_embed == "sidecar-only"

    none = caption_lane_report(ffmpeg_filters="loudnorm ebur128", gst_elements=set())
    assert none.decode_back_capable is False
    assert none.gst_embed_available is False

    # decode-back ready but the gst embed lane is only partially installed.
    partial = caption_lane_report(ffmpeg_filters="readeia608", gst_elements={"cccombiner"})
    assert partial.decode_back_capable is True
    assert partial.gst_embed_available is False
