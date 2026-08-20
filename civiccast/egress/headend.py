# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Named cable-headend delivery profiles (cable automation CA-6).

Every number here is traceable to published vendor or standards
documentation (each profile lists its sources); none of it is tailored to
any one station. The operator supplies only what their carriage agreement
dictates: the destination address/port and, where the agreement sets one,
the constant multiplex rate.

How the pieces map onto the existing egress pipeline:

- Codec, resolution, GOP, and audio land on :class:`CanonicalProfile` —
  sources are conformed to it at prepare time, so the persistent encoder
  can stream-copy.
- The constant multiplex rate (what cable plants actually require — TelVue
  documents that the *mux* must be constant, not the video elementary
  stream) rides the sink's allowlisted ``-muxrate`` extra arg; the mpegts
  muxer null-pads to that rate even over ``-c copy``.
- Datagram sizing (1316 = 7 x 188-byte TS packets) is owned by the
  ``udp-ts`` sink.
"""

from __future__ import annotations

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from civiccast.egress.loudness_plan import REGIME_DEFAULTS
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    LoudnessRegime,
)

HeadendTransport = Literal["udp-unicast", "udp-multicast", "file-drop"]

_FIELD_PROOF_BOUNDARY = (
    "Built from published vendor documentation; not field-proven against a "
    "real cable headend until the first-station beta."
)

_HEADEND_SINK_LABEL = "Cable headend"


class HeadendProfile(BaseModel):
    """One named, citable cable-delivery preset."""

    model_config = ConfigDict(extra="forbid")

    profile_id: Annotated[str, Field(min_length=1, max_length=80)]
    label: Annotated[str, Field(min_length=1, max_length=120)]
    vendor: Annotated[str, Field(min_length=1, max_length=120)]
    source_urls: list[str]
    canonical_profile: CanonicalProfile
    muxrate_kbps: Annotated[int, Field(ge=0)]
    transport: HeadendTransport
    # S11b: the cable loudness regime a station normalises to for this delivery
    # (ATSC A/85 -24 LKFS, CALM Act). Applied to the headend sink + the channel
    # target at apply time so the conform produces a -24 LKFS program.
    recommended_loudness_regime: LoudnessRegime = "atsc-a85"
    pkt_size: Annotated[int, Field(gt=0)] = 1316
    min_port: Annotated[int, Field(ge=1, le=65_535)] = 1
    mpegts_extra_args: list[str] = Field(default_factory=list)
    operator_must_supply: list[str] = Field(default_factory=list)
    not_claimed: list[str] = Field(default_factory=lambda: [_FIELD_PROOF_BOUNDARY])


def _profiles() -> dict[str, HeadendProfile]:
    generic_operator_inputs = [
        "Destination address and UDP port from your cable operator or headend integrator.",
        "Constant multiplex rate (muxrate) if your carriage agreement sets one.",
    ]
    return {
        profile.profile_id: profile
        for profile in (
            HeadendProfile(
                profile_id="generic-udp-spts",
                label="Generic CBR SPTS over UDP",
                vendor="Any headend that ingests a constant-rate MPEG transport stream",
                source_urls=[
                    "https://telvue.com/knowledgebase/feed-setup-encoder-configuration/",
                    "https://www.pixeltools.com/tech_tip_cablelabs.html",
                ],
                canonical_profile=CanonicalProfile(
                    width=1280,
                    height=720,
                    fps=30,
                    video_codec="h264",
                    video_bitrate_kbps=5000,
                    gop_size=30,
                    audio_codec="ac3",
                    audio_bitrate_kbps=192,
                    audio_sample_rate=48_000,
                    audio_channels=2,
                ),
                muxrate_kbps=8000,
                transport="udp-unicast",
                operator_must_supply=generic_operator_inputs,
            ),
            HeadendProfile(
                profile_id="comcast-mtd-sd",
                label="Comcast MTD - SD (MPEG-2, CableLabs SD numbers)",
                vendor="Comcast Technology Solutions, Managed Terrestrial Distribution",
                source_urls=[
                    "https://www.comcasttechnologysolutions.com/managed-terrestrial-distribution",
                    "https://www.pixeltools.com/tech_tip_cablelabs.html",
                ],
                # CableLabs VOD SD: MPEG-2 MP@ML, aggregate SPTS (PAT+PMT+
                # video+one audio+data) <= 3.75 Mbps, GOP nominally 15 for
                # 30 fps material and closed to start, Dolby Digital 192 kbps
                # two-channel at 48 kHz.
                canonical_profile=CanonicalProfile(
                    width=720,
                    height=480,
                    fps=30,
                    video_codec="mpeg2video",
                    video_bitrate_kbps=3180,
                    gop_size=15,
                    audio_codec="ac3",
                    audio_bitrate_kbps=192,
                    audio_sample_rate=48_000,
                    audio_channels=2,
                ),
                muxrate_kbps=3750,
                transport="udp-multicast",
                operator_must_supply=[
                    "Multicast group address and UDP port assigned by Comcast.",
                ],
            ),
            HeadendProfile(
                profile_id="comcast-mtd-hd",
                label="Comcast MTD - HD (H.264)",
                vendor="Comcast Technology Solutions, Managed Terrestrial Distribution",
                source_urls=[
                    "https://www.comcasttechnologysolutions.com/managed-terrestrial-distribution",
                ],
                # Comcast MTD lists HD as MPEG-2 or MPEG-4; this preset ships
                # the MPEG-4/H.264 lane. The default muxrate is a placeholder
                # ceiling - the real rate comes from the carriage agreement.
                canonical_profile=CanonicalProfile(
                    width=1920,
                    height=1080,
                    fps=30,
                    video_codec="h264",
                    video_bitrate_kbps=10_000,
                    gop_size=30,
                    audio_codec="ac3",
                    audio_bitrate_kbps=384,
                    audio_sample_rate=48_000,
                    audio_channels=2,
                ),
                muxrate_kbps=12_000,
                transport="udp-multicast",
                operator_must_supply=[
                    "Multicast group address and UDP port assigned by Comcast.",
                    "Constant multiplex rate from your carriage agreement (the 12 Mbps default is a placeholder).",
                ],
            ),
            HeadendProfile(
                profile_id="telvue-hypercaster-ip",
                label="TelVue HyperCaster - IP transport stream input",
                vendor="TelVue HyperCaster",
                source_urls=[
                    "https://telvue.com/knowledgebase/feed-setup-encoder-configuration/",
                    "https://telvue.com/knowledgebase/preparing-content-for-the-hypercaster/",
                    "https://telvue.com/knowledgebase/configure-inout-ports/",
                ],
                # TelVue KB: TS over UDP, unicast or multicast (224.0.0.0 to
                # 239.255.255.255), IP port 1024-65535, constant multiplex
                # rate, MPEG-2 or H.264 video, MPEG-1 Layer II / AC-3 / AAC
                # audio.
                canonical_profile=CanonicalProfile(
                    width=1280,
                    height=720,
                    fps=30,
                    video_codec="h264",
                    video_bitrate_kbps=5000,
                    gop_size=30,
                    audio_codec="ac3",
                    audio_bitrate_kbps=192,
                    audio_sample_rate=48_000,
                    audio_channels=2,
                ),
                muxrate_kbps=8000,
                transport="udp-unicast",
                min_port=1024,
                operator_must_supply=[
                    "HyperCaster feed address and port (1024-65535) configured on the receiving feed.",
                    "Match the feed's Max Bit Rate to this muxrate.",
                ],
            ),
            HeadendProfile(
                profile_id="harmonic-spectrum-ts",
                label="Harmonic Spectrum - transport stream ingest",
                vendor="Harmonic Spectrum X / XE",
                source_urls=[
                    "https://www.harmonicinc.com/hubfs/datasheet/spectrum-x.pdf",
                    "https://www.harmonicinc.com/hubfs/datasheet/spectrum-xe.pdf",
                ],
                # Harmonic datasheets: TS ingest over IP, MPEG-2 / MPEG-4 AVC
                # (HEVC also listed), CBR encode supported.
                canonical_profile=CanonicalProfile(
                    width=1920,
                    height=1080,
                    fps=30,
                    video_codec="h264",
                    video_bitrate_kbps=8000,
                    gop_size=30,
                    audio_codec="ac3",
                    audio_bitrate_kbps=192,
                    audio_sample_rate=48_000,
                    audio_channels=2,
                ),
                muxrate_kbps=10_000,
                transport="udp-unicast",
                operator_must_supply=generic_operator_inputs,
            ),
            HeadendProfile(
                profile_id="leightronix-file-drop",
                label="Leightronix UltraNEXUS - file handoff",
                vendor="Leightronix UltraNEXUS-HD",
                source_urls=[
                    "https://www.leightronix.com/ultranexus-hd-series.html",
                    "https://support.leightronix.com/ultranexus-hd",
                ],
                # UltraNEXUS-HD decodes H.264 HD/SD and MPEG-2 SD from files;
                # delivery is a watched-folder/file handoff, so there is no
                # network mux rate to hold.
                canonical_profile=CanonicalProfile(
                    width=1280,
                    height=720,
                    fps=30,
                    video_codec="h264",
                    video_bitrate_kbps=8000,
                    gop_size=30,
                    audio_codec="ac3",
                    audio_bitrate_kbps=192,
                    audio_sample_rate=48_000,
                    audio_channels=2,
                ),
                muxrate_kbps=0,
                transport="file-drop",
                operator_must_supply=[
                    "Drop-folder path the UltraNEXUS ingests from.",
                ],
            ),
        )
    }


HEADEND_PROFILES: dict[str, HeadendProfile] = _profiles()


def list_headend_profiles() -> list[HeadendProfile]:
    """All named profiles, stable order."""

    return [HEADEND_PROFILES[key] for key in sorted(HEADEND_PROFILES)]


def get_headend_profile(profile_id: str) -> HeadendProfile | None:
    return HEADEND_PROFILES.get(profile_id)


def apply_headend_profile(
    config: EgressConfig,
    profile: HeadendProfile,
    *,
    destination_uri: str,
    muxrate_kbps_override: int | None = None,
    keep_existing_sinks: bool = False,
    label: str = _HEADEND_SINK_LABEL,
) -> EgressConfig:
    """Return a new config carrying the profile's encode + delivery sink.

    Validates the destination against the profile's transport before
    anything is persisted, so a typo'd address fails loudly instead of
    silently streaming into the void.
    """

    _validate_destination(profile, destination_uri)
    muxrate_kbps = muxrate_kbps_override or profile.muxrate_kbps
    if profile.transport == "file-drop":
        sink = EgressSinkSpec(
            kind="file",
            label=label,
            uri=destination_uri,
            extra_output_args=list(profile.mpegts_extra_args),
            loudness_regime=profile.recommended_loudness_regime,
        )
    else:
        sink = EgressSinkSpec(
            kind="udp-ts",
            label=label,
            uri=destination_uri,
            extra_output_args=[
                "-muxrate",
                f"{muxrate_kbps}k",
                *profile.mpegts_extra_args,
            ],
            loudness_regime=profile.recommended_loudness_regime,
        )
    kept = (
        [existing for existing in config.sinks if existing.label != label]
        if keep_existing_sinks
        else []
    )
    # S11b parity decision 1: normalise the channel to the cable destination's
    # loudness (ATSC A/85 -24 LKFS). The headend sink then matches this baseline
    # (no per-sink re-encode needed, so channel branding still stream-copies),
    # while any kept streaming sink can still declare its own -16 LUFS regime.
    channel_target = REGIME_DEFAULTS.get(
        profile.recommended_loudness_regime, config.loudness_target_lufs
    )
    return config.model_copy(
        update={
            "canonical_profile": profile.canonical_profile.model_copy(),
            "loudness_target_lufs": channel_target,
            "sinks": [*kept, sink],
        }
    )


def _validate_destination(profile: HeadendProfile, destination_uri: str) -> None:
    parsed = urlsplit(destination_uri)
    scheme = parsed.scheme.lower()
    if profile.transport == "file-drop":
        if scheme not in {"", "file"}:
            raise ValueError(
                f"profile {profile.profile_id} delivers files; "
                "the destination must be a filesystem path or file:// uri"
            )
        return
    if scheme != "udp":
        raise ValueError(
            f"profile {profile.profile_id} streams over udp://; got {scheme or 'no scheme'!r}"
        )
    port = parsed.port
    if port is None:
        raise ValueError("destination must include an explicit UDP port")
    if port < profile.min_port:
        raise ValueError(
            f"profile {profile.profile_id} requires a destination port between "
            f"{profile.min_port} and 65535 (vendor-documented range)"
        )
    multicast = _is_multicast_host(parsed.hostname or "")
    if profile.transport == "udp-multicast" and not multicast:
        raise ValueError(
            f"profile {profile.profile_id} expects a multicast group (224.0.0.0 to 239.255.255.255)"
        )


def _is_multicast_host(host: str) -> bool:
    first_octet = host.split(".", 1)[0]
    return first_octet.isdigit() and 224 <= int(first_octet) <= 239
