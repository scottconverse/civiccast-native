# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Select the egress encoder strategy (ffmpeg-concat vs the GStreamer engine).

A deployment-level choice during the ffmpeg→GStreamer transition, via the
``CIVICCAST_EGRESS_ENGINE`` environment variable (matching the project's other
``CIVICCAST_*`` flags). Default is the legacy ffmpeg concat strategy, so existing
deployments are unaffected unless they opt in.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from civiccast.egress.encoder_strategy import ConcatEncoderStrategy, EncoderStrategy

_DEFAULT = "ffmpeg-concat"
_FFMPEG_ALIASES = {"ffmpeg-concat", "ffmpeg", "concat", ""}
_GSTREAMER_ALIASES = {"gstreamer", "gst"}


def selected_engine_name(engine: str | None = None) -> str:
    """The normalized engine name (explicit arg, else ``CIVICCAST_EGRESS_ENGINE``)."""
    return (engine or os.environ.get("CIVICCAST_EGRESS_ENGINE", _DEFAULT)).strip().lower()


def gstreamer_engine_selected(engine: str | None = None) -> bool:
    """True when the GStreamer engine is selected (it alone muxes secondary audio PIDs
    and embeds CEA-708). Lets surfaces avoid advertising capabilities the default
    ffmpeg engine cannot emit (e.g. a SAP audio-track toggle)."""
    return selected_engine_name(engine) in _GSTREAMER_ALIASES


def build_encoder_strategy(
    engine: str | None = None,
    *,
    audio_tracks_provider: Callable[[str], list[Any]] | None = None,
) -> EncoderStrategy:
    """Build the configured ``EncoderStrategy``.

    ``CIVICCAST_EGRESS_ENGINE=gstreamer`` → the GStreamer engine (a per-channel
    worker process); anything else (default) → the ffmpeg concat strategy. Raises on
    an unrecognized value rather than silently falling back, so a typo is caught.
    ``audio_tracks_provider`` (S11 gap 9) is passed to the gst engine so it can mux a
    channel's secondary audio (SAP/descriptive) PIDs; ignored on the ffmpeg path.
    """
    name = selected_engine_name(engine)
    if name in _GSTREAMER_ALIASES:
        # Imported lazily so the ffmpeg path never pulls in the gst package.
        from civiccast.egress.gst.strategy import GstPlayoutStrategy

        return GstPlayoutStrategy(audio_tracks_provider=audio_tracks_provider)
    if name in _FFMPEG_ALIASES:
        return ConcatEncoderStrategy()
    raise ValueError(
        f"unknown CIVICCAST_EGRESS_ENGINE={name!r} — use 'ffmpeg-concat' (default) or 'gstreamer'"
    )
