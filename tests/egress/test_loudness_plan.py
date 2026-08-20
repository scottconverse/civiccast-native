# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S11b per-sink loudness resolution + plan."""

from __future__ import annotations

from typing import Any

from civiccast.egress.loudness_plan import (
    build_loudness_plan,
    resolve_sink_loudness,
    standard_label_for_target,
)
from civiccast.egress.models import EgressConfig, EgressSinkSpec


def _sink(**kw: Any) -> EgressSinkSpec:
    base: dict[str, Any] = {"kind": "srt", "label": "S", "uri": "srt://h.example:9000"}
    base.update(kw)
    return EgressSinkSpec(**base)


def test_inherit_uses_channel_target_and_does_not_reencode() -> None:
    res = resolve_sink_loudness(_sink(), channel_target_lufs=-16.0, channel_tolerance_lufs=2.0)
    assert res.regime == "inherit"
    assert res.effective_target_lufs == -16.0
    assert res.tolerance_lufs == 2.0
    assert res.explicit is False
    assert res.requires_reencode is False
    assert res.short_label == "Inherit"


def test_atsc_a85_resolves_to_minus_24_and_reencodes_off_minus16_baseline() -> None:
    res = resolve_sink_loudness(
        _sink(kind="udp-ts", label="Cable", uri="udp://239.0.0.1:5000", loudness_regime="atsc-a85"),
        channel_target_lufs=-16.0,
        channel_tolerance_lufs=2.0,
    )
    assert res.effective_target_lufs == -24.0
    assert res.standard_label == "ATSC A/85 -24 LKFS (CALM Act)"
    assert res.short_label == "Cable -24"
    assert res.explicit is True
    assert res.requires_reencode is True


def test_streaming_matches_minus16_baseline_no_reencode() -> None:
    res = resolve_sink_loudness(
        _sink(loudness_regime="streaming"),
        channel_target_lufs=-16.0,
        channel_tolerance_lufs=2.0,
    )
    assert res.effective_target_lufs == -16.0
    assert res.requires_reencode is False


def test_explicit_target_overrides_regime_default_but_keeps_regime_label() -> None:
    res = resolve_sink_loudness(
        _sink(loudness_regime="atsc-a85", loudness_target_lufs=-23.0, loudness_tolerance_lufs=1.0),
        channel_target_lufs=-16.0,
        channel_tolerance_lufs=2.0,
    )
    assert res.effective_target_lufs == -23.0
    assert res.tolerance_lufs == 1.0
    assert res.standard_label == "ATSC A/85 -24 LKFS (CALM Act)"


def test_inherit_with_explicit_target_is_explicit() -> None:
    res = resolve_sink_loudness(
        _sink(loudness_target_lufs=-23.0),
        channel_target_lufs=-16.0,
        channel_tolerance_lufs=2.0,
    )
    assert res.regime == "inherit"
    assert res.effective_target_lufs == -23.0
    assert res.explicit is True
    assert res.standard_label == "EBU R128 -23 LUFS"
    assert res.requires_reencode is True


def test_standard_label_for_target_reverse_lookup_and_generic() -> None:
    assert standard_label_for_target(-24.0) == "ATSC A/85 -24 LKFS (CALM Act)"
    assert standard_label_for_target(-16.0) == "Streaming -16 LUFS (ITU-R BS.1770)"
    assert "target -18 LUFS" in standard_label_for_target(-18.0)


def test_build_loudness_plan_covers_every_sink() -> None:
    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=-24.0,
        loudness_tolerance_lufs=2.0,
        sinks=[
            _sink(
                kind="udp-ts",
                label="Cable",
                uri="udp://239.0.0.1:5000",
                loudness_regime="atsc-a85",
            ),
            _sink(
                kind="srt", label="CDN", uri="srt://cdn.example:9000", loudness_regime="streaming"
            ),
            _sink(kind="file", label="Proof", uri="build/proof.ts"),
        ],
    )
    plan = build_loudness_plan(config)
    assert plan.baseline_target_lufs == -24.0
    by_label = {s.label: s for s in plan.sinks}
    # Cable matches the -24 channel baseline -> no re-encode; streaming differs -> re-encode.
    assert by_label["Cable"].effective_target_lufs == -24.0
    assert by_label["Cable"].requires_reencode is False
    assert by_label["CDN"].effective_target_lufs == -16.0
    assert by_label["CDN"].requires_reencode is True
    assert by_label["Proof"].regime == "inherit"
    assert by_label["Proof"].effective_target_lufs == -24.0
