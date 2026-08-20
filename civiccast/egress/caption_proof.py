# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CEA-608/708 caption decode-back proof + caption_status gate (S11a).

Embedding is engine-specific (GStreamer-native ``cccombiner`` on the 3.0 engine;
the ffmpeg-concat default ships the sidecar). This decode-back is engine-AGNOSTIC:
it decodes whatever captions actually survived to the *emitted* TS (via ffmpeg's
``movie=...[out0+subcc]`` source, which exposes in-band closed captions as a
subtitle stream), compares them to the expected cues, and persists a proof sample.

``caption_status`` only ever becomes ``on`` when a real PASS lands within a
freshness window — stale, missing, or FAIL all read ``not-verified`` (fail-closed,
so the operator chip never claims captions it cannot prove).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from civiccast.captions.models import CaptionCue
from civiccast.egress.caption_embed import (
    evaluate_caption_decode_back,
    parse_caption_cues_from_timed_text,
)
from civiccast.egress.models import CaptionStatus, EgressCaptionProofSample
from civiccast.egress.store import EgressStore
from civiccast.stream._ffmpeg import FfmpegResult, run_ffmpeg

DECODE_BACK_DECODER = "ffmpeg-subcc"
DEFAULT_CAPTION_FRESHNESS_SECONDS = 120.0

FfmpegRunner = Callable[[list[str]], FfmpegResult]
Clock = Callable[[], datetime]
CaptionMode = Literal["passthrough", "cea-708", "sidecar"]


# The GStreamer elements the native CC embed lane needs (gst-plugins-bad +
# gst-plugins-rs). Probed by `civiccast doctor` on the gst engine.
GST_CC_ELEMENTS = ("cccombiner", "tttocea608", "h264ccinserter")


@dataclass(frozen=True)
class CaptionLaneReport:
    """The shipped build's caption capability, for ``civiccast doctor`` (S11a).

    ``decode_back_capable`` = the bundled ffmpeg can read embedded captions back
    (``readeia608``) so the decode-back proof can run. ``ffmpeg_embed`` is always
    ``sidecar-only`` — no ffmpeg build encodes CEA-608/708 from text — so embedding
    is the GStreamer engine's job (``gst_embed_available``).
    """

    decode_back_capable: bool
    gst_embed_available: bool
    ffmpeg_embed: str = "sidecar-only"


def caption_lane_report(*, ffmpeg_filters: str | None, gst_elements: set[str]) -> CaptionLaneReport:
    """Pure capability summary from probed ffmpeg filters + present gst elements."""
    return CaptionLaneReport(
        decode_back_capable="readeia608" in (ffmpeg_filters or ""),
        gst_embed_available=set(GST_CC_ELEMENTS).issubset(gst_elements),
    )


def _escape_movie_path(path: Path) -> str:
    # The lavfi ``movie`` filename crosses TWO escape-consuming parsers: the
    # filtergraph parser and then the movie filter's own option parser (which splits
    # on ``:``). Each level consumes one ``\``, so a literal ``:`` needs ``\\:`` and a
    # literal ``\`` needs ``\\\\`` in the graph string. Single-level ``\:`` reaches
    # the option parser as a bare ``:`` — ffmpeg then splits a Windows ``C:/...``
    # path at the drive colon and tries to open ``C`` (verified natively 2026-08-19).
    return path.as_posix().replace("\\", "\\\\\\\\").replace(":", "\\\\:")


def decode_embedded_captions(
    emitted_stream_path: Path,
    *,
    runner: FfmpegRunner = run_ffmpeg,
    source_id: str = "decode-back",
) -> list[CaptionCue]:
    """Extract embedded CEA-608/708 captions from an emitted TS as cues.

    Uses ffmpeg's ``movie=<path>[out0+subcc]`` lavfi source — the in-band closed
    captions are exposed as a subtitle pad, transcoded to SRT and parsed with the
    same timed-text parser used for the expected cues. Returns ``[]`` when no
    captions are present or extraction fails, so the gate reports not-verified
    rather than a false PASS.
    """

    result = runner(
        [
            "-hide_banner",
            "-nostats",
            "-f",
            "lavfi",
            "-i",
            f"movie={_escape_movie_path(emitted_stream_path)}[out0+subcc]",
            "-map",
            "0:1",
            "-f",
            "srt",
            "-",
        ]
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return parse_caption_cues_from_timed_text(result.stdout, source_id=source_id)


def sample_caption_decode_back(
    *,
    channel_id: str,
    emitted_stream_path: Path,
    expected_cues: list[CaptionCue],
    mode: CaptionMode,
    runner: FfmpegRunner = run_ffmpeg,
    clock: Clock = lambda: datetime.now(UTC),
) -> EgressCaptionProofSample:
    """Decode the emitted stream, compare to expected cues, build a proof sample."""

    decoded = decode_embedded_captions(emitted_stream_path, runner=runner)
    proof = evaluate_caption_decode_back(
        channel_id=channel_id,
        emitted_stream_path=emitted_stream_path,
        expected_cues=expected_cues,
        decoded_cues=decoded,
        decoder_name=DECODE_BACK_DECODER,
    )
    return EgressCaptionProofSample(
        channel_id=channel_id,
        sampled_at=clock(),
        status=proof.status,
        caption_status=proof.caption_status,
        mode=mode,
        decoder_name=proof.decoder_name,
        expected_cue_count=proof.expected_cue_count,
        decoded_cue_count=proof.decoded_cue_count,
        matched_cue_count=proof.matched_cue_count,
        max_timing_delta_seconds=proof.max_timing_delta_seconds,
        proof_boundary=proof.proof_boundary,
        blocker=proof.blocker,
    )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def build_caption_status_provider(
    store: EgressStore,
    *,
    freshness_seconds: float = DEFAULT_CAPTION_FRESHNESS_SECONDS,
    clock: Clock = lambda: datetime.now(UTC),
) -> Callable[[str], CaptionStatus]:
    """A ``caption_status_provider`` that returns ``on`` iff the channel's latest
    proof sample is a PASS within the freshness window — else ``not-verified``
    (fail-closed: stale, missing, or FAIL all read not-verified)."""

    def _provider(channel_id: str) -> CaptionStatus:
        sample = store.latest_caption_proof_sample(channel_id)
        if sample is None or sample.status != "PASS" or sample.caption_status != "on":
            return "not-verified"
        age = clock() - _as_utc(sample.sampled_at)
        if age < timedelta(0) or age > timedelta(seconds=freshness_seconds):
            return "not-verified"
        return "on"

    return _provider
