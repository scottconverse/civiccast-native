# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Headend delivery profile tests (cable automation CA-6).

Profiles are GENERIC, built from published vendor/spec documentation
(Comcast MTD, TelVue KB, Harmonic datasheets, Leightronix, CableLabs VOD
encoding profiles) — never tailored to any one station.
"""

from __future__ import annotations

import pytest

from civiccast.egress.headend import (
    HEADEND_PROFILES,
    apply_headend_profile,
    get_headend_profile,
    list_headend_profiles,
)
from civiccast.egress.models import EgressConfig, EgressSinkSpec

EXPECTED_PROFILE_IDS = {
    "generic-udp-spts",
    "comcast-mtd-sd",
    "comcast-mtd-hd",
    "telvue-hypercaster-ip",
    "harmonic-spectrum-ts",
    "leightronix-file-drop",
}


def _base_config(channel_id: str = "public") -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/proof.ts")],
    )


def test_registry_serves_generic_citable_profiles() -> None:
    assert {p.profile_id for p in list_headend_profiles()} == EXPECTED_PROFILE_IDS
    for profile in HEADEND_PROFILES.values():
        # Every number must be traceable to a published document.
        assert profile.source_urls, profile.profile_id
        # Honesty boundary: built from specs, not field-proven at a headend.
        assert any("field" in claim.lower() for claim in profile.not_claimed), profile.profile_id
        assert profile.canonical_profile.container == "mpegts"


def test_comcast_mtd_sd_matches_cablelabs_sd_numbers() -> None:
    profile = get_headend_profile("comcast-mtd-sd")
    assert profile is not None
    # CableLabs VOD SD: MPEG-2 MP@ML, aggregate SPTS <= 3.75 Mbps, GOP 15
    # closed, Dolby Digital 192 kbps stereo at 48 kHz.
    assert profile.canonical_profile.video_codec == "mpeg2video"
    assert (profile.canonical_profile.width, profile.canonical_profile.height) == (720, 480)
    assert profile.canonical_profile.gop_size == 15
    assert profile.muxrate_kbps == 3750
    assert profile.canonical_profile.video_bitrate_kbps < 3750
    assert profile.canonical_profile.audio_codec == "ac3"
    assert profile.canonical_profile.audio_bitrate_kbps == 192
    assert profile.canonical_profile.audio_sample_rate == 48_000
    assert profile.transport == "udp-multicast"


def test_comcast_mtd_hd_is_h264_with_ac3() -> None:
    profile = get_headend_profile("comcast-mtd-hd")
    assert profile is not None
    # Comcast MTD: HD = MPEG-2 or MPEG-4; we ship the MPEG-4/H.264 lane.
    assert profile.canonical_profile.video_codec == "h264"
    assert (profile.canonical_profile.width, profile.canonical_profile.height) == (1920, 1080)
    assert profile.canonical_profile.audio_codec == "ac3"
    assert profile.canonical_profile.audio_bitrate_kbps == 384
    assert profile.muxrate_kbps > profile.canonical_profile.video_bitrate_kbps
    # The real rate comes from the station's carriage agreement.
    assert any("carriage" in item.lower() for item in profile.operator_must_supply)


def test_unknown_profile_returns_none() -> None:
    assert get_headend_profile("nope") is None


def test_apply_profile_builds_cbr_spts_udp_sink() -> None:
    profile = get_headend_profile("comcast-mtd-sd")
    assert profile is not None

    config = apply_headend_profile(
        _base_config(),
        profile,
        destination_uri="udp://239.255.0.1:5000",
    )

    assert config.canonical_profile == profile.canonical_profile
    # Default replaces prior sinks: the headend feed becomes the output.
    assert len(config.sinks) == 1
    sink = config.sinks[0]
    assert sink.kind == "udp-ts"
    assert sink.uri == "udp://239.255.0.1:5000"
    # Mux-level CBR: the mpegts muxer null-pads to the constant rate.
    muxrate_idx = sink.extra_output_args.index("-muxrate")
    assert sink.extra_output_args[muxrate_idx + 1] == "3750k"


def test_apply_profile_respects_muxrate_override_and_keeps_existing_sinks() -> None:
    profile = get_headend_profile("comcast-mtd-hd")
    assert profile is not None
    config = apply_headend_profile(
        # The base config's proof-file sink stays alongside the headend feed.
        _base_config(),
        profile,
        destination_uri="udp://239.1.2.3:6000",
        muxrate_kbps_override=15_000,
        keep_existing_sinks=True,
    )

    labels = [sink.label for sink in config.sinks]
    assert "Proof" in labels
    headend_sink = next(sink for sink in config.sinks if sink.kind == "udp-ts")
    muxrate_idx = headend_sink.extra_output_args.index("-muxrate")
    assert headend_sink.extra_output_args[muxrate_idx + 1] == "15000k"


def test_apply_multicast_profile_rejects_unicast_destination() -> None:
    profile = get_headend_profile("comcast-mtd-sd")
    assert profile is not None
    with pytest.raises(ValueError, match="multicast"):
        apply_headend_profile(
            _base_config(),
            profile,
            destination_uri="udp://10.0.0.5:5000",
        )


def test_apply_udp_profile_rejects_non_udp_destination() -> None:
    profile = get_headend_profile("generic-udp-spts")
    assert profile is not None
    with pytest.raises(ValueError, match="udp"):
        apply_headend_profile(
            _base_config(),
            profile,
            destination_uri="srt://10.0.0.5:5000",
        )


def test_unicast_profile_accepts_both_unicast_and_multicast() -> None:
    profile = get_headend_profile("telvue-hypercaster-ip")
    assert profile is not None
    # TelVue accepts unicast and multicast TS inputs (feed-setup KB).
    for destination in ("udp://10.1.2.3:5000", "udp://239.10.0.1:5000"):
        config = apply_headend_profile(_base_config(), profile, destination_uri=destination)
        assert config.sinks[0].uri == destination


def test_telvue_port_range_enforced_from_kb() -> None:
    profile = get_headend_profile("telvue-hypercaster-ip")
    assert profile is not None
    # TelVue KB: IP port must be between 1024 and 65535.
    with pytest.raises(ValueError, match="1024"):
        apply_headend_profile(_base_config(), profile, destination_uri="udp://10.1.2.3:900")


def test_file_drop_profile_builds_file_sink() -> None:
    profile = get_headend_profile("leightronix-file-drop")
    assert profile is not None

    config = apply_headend_profile(
        _base_config(),
        profile,
        destination_uri="file:///D:/headend-drop/public.ts",
    )

    sink = config.sinks[0]
    assert sink.kind == "file"
    assert profile.muxrate_kbps == 0
    assert "-muxrate" not in sink.extra_output_args


def test_apply_headend_profile_normalises_channel_to_atsc_a85() -> None:
    # S11b parity decision 1: a cable delivery profile sets the channel target to
    # -24 LKFS (ATSC A/85, CALM Act) and tags the headend sink with that regime,
    # so the conform produces a -24 program the sink copies (branding-compatible).
    profile = get_headend_profile("comcast-mtd-hd")
    assert profile is not None
    assert profile.recommended_loudness_regime == "atsc-a85"

    config = apply_headend_profile(
        _base_config(),
        profile,
        destination_uri="udp://239.20.30.40:5000",
    )

    assert config.loudness_target_lufs == -24.0
    headend_sink = next(sink for sink in config.sinks if sink.kind == "udp-ts")
    assert headend_sink.loudness_regime == "atsc-a85"

    # The headend sink matches the new -24 channel baseline -> no re-encode.
    from civiccast.egress.loudness_plan import build_loudness_plan

    plan = build_loudness_plan(config)
    cable = next(s for s in plan.sinks if s.label == headend_sink.label)
    assert cable.effective_target_lufs == -24.0
    assert cable.requires_reencode is False
