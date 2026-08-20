# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Encoder strategy seam for egress playout supervision."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from civiccast.captions.tap import AudioTapPlan
from civiccast.egress.branding import EgressBrandingPlan
from civiccast.egress.caption_embed import EgressCaptionEmbeddingPlan
from civiccast.egress.models import EgressConfig, EgressSourcePlan
from civiccast.egress.runtime import (
    FfmpegStarter,
    build_persistent_encoder_args,
    start_persistent_encoder,
    write_concat_plan,
)
from civiccast.egress.sinks import SecretResolver


@dataclass(frozen=True)
class EncoderStartRequest:
    """Inputs needed to start one persistent egress encoder."""

    channel_id: str
    source_plan: EgressSourcePlan
    config: EgressConfig
    work_dir: Path
    resolve_secret: SecretResolver | None = None
    branding_plan: EgressBrandingPlan | None = None
    caption_plan: EgressCaptionEmbeddingPlan | None = None
    audio_tap_plan: AudioTapPlan | None = None
    ffmpeg_starter: FfmpegStarter | None = None
    # S15 §5 CG-lite: pre-rendered board raster composited over the output half
    # by the GStreamer engine (gdkpixbufoverlay). None = no board overlay.
    cg_overlay_image: Path | None = None


@dataclass(frozen=True)
class EncoderStartResult:
    """Started encoder process plus local evidence paths."""

    process: object
    concat_plan_path: Path
    stdout_path: Path
    stderr_path: Path
    args: tuple[str, ...]


class EncoderStrategy(Protocol):
    """Strategy contract for persistent egress output ownership."""

    name: str
    # True if the strategy can swap the active source IN PLACE (no encoder restart)
    # — the GStreamer engine. The ffmpeg concat strategy leaves this False, so the
    # daemon/supervisor keep their existing terminate+restart reload path.
    supports_live_swap: bool
    # True if the strategy can rebuild the PROGRAM content in place (no restart) when
    # a newly-due program arrives — the GStreamer engine's seamless content-reload
    # (D-S1-6). False leaves the daemon's terminate+restart reload path in force.
    supports_content_reload: bool

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        """Start one encoder for the requested source plan."""

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:
        """Swap the active source role (``program``/``slate``/``live``) in place.
        Only called when ``supports_live_swap`` is True."""

    def reload_content(self, channel_id: str, work_dir: Path, request: EncoderStartRequest) -> bool:
        """Rebuild the running program's content from ``request`` in place, with no
        encoder restart. Returns True on success (the swap was dispatched), False if
        it could not be applied (e.g. the worker control channel is not ready) so the
        caller can fall back to terminate+restart. Only called when
        ``supports_content_reload`` is True."""


class ConcatEncoderStrategy:
    """Persistent concat-demuxer strategy from ADR-0015 Option A."""

    name = "concat-demuxer-single-ffmpeg-process"
    supports_live_swap = False  # ffmpeg reload = terminate + restart (the daemon's job)
    supports_content_reload = False  # same: ffmpeg reload = terminate + restart

    def swap_role(self, channel_id: str, work_dir: Path, role: str) -> None:
        raise NotImplementedError("ConcatEncoderStrategy does not support in-place swap")

    def reload_content(self, channel_id: str, work_dir: Path, request: EncoderStartRequest) -> bool:
        raise NotImplementedError("ConcatEncoderStrategy does not support content-reload")

    def start(self, request: EncoderStartRequest) -> EncoderStartResult:
        concat_plan = request.work_dir / request.channel_id / "egress-source-plan.ffconcat"
        write_concat_plan(concat_plan, request.source_plan)
        args = build_persistent_encoder_args(
            concat_plan=concat_plan,
            config=request.config,
            resolve_secret=request.resolve_secret,
            branding_plan=request.branding_plan,
            caption_plan=request.caption_plan,
            audio_tap_plan=request.audio_tap_plan,
        )
        log_dir = request.work_dir / request.channel_id / "logs"
        stdout_path = log_dir / "ffmpeg.stdout.log"
        stderr_path = log_dir / "ffmpeg.stderr.log"
        if request.ffmpeg_starter is None:
            process = start_persistent_encoder(
                args,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        else:
            process = request.ffmpeg_starter(args)
        return EncoderStartResult(
            process=process,
            concat_plan_path=concat_plan,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            args=tuple(args),
        )
