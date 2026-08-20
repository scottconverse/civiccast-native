# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The egress engine-selection flag (CIVICCAST_EGRESS_ENGINE)."""

from __future__ import annotations

import pytest

from civiccast.egress.encoder_strategy import ConcatEncoderStrategy
from civiccast.egress.engine_select import build_encoder_strategy, selected_engine_name
from civiccast.egress.gst.strategy import GstPlayoutStrategy


def test_default_is_ffmpeg_concat(monkeypatch) -> None:
    monkeypatch.delenv("CIVICCAST_EGRESS_ENGINE", raising=False)
    assert selected_engine_name() == "ffmpeg-concat"
    assert isinstance(build_encoder_strategy(), ConcatEncoderStrategy)


def test_gstreamer_selected(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_ENGINE", "gstreamer")
    strategy = build_encoder_strategy()
    assert isinstance(strategy, GstPlayoutStrategy)
    assert strategy.supports_live_swap is True


def test_explicit_arg_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_ENGINE", "gstreamer")
    assert isinstance(build_encoder_strategy("ffmpeg-concat"), ConcatEncoderStrategy)


def test_unknown_engine_raises(monkeypatch) -> None:
    monkeypatch.setenv("CIVICCAST_EGRESS_ENGINE", "potato")
    with pytest.raises(ValueError, match="unknown CIVICCAST_EGRESS_ENGINE"):
        build_encoder_strategy()
