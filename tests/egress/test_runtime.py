# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.cg.service import build_overlay_contract
from civiccast.egress.branding import build_branding_filter_plan
from civiccast.egress.caption_embed import SidecarCaptionEmbedder
from civiccast.egress.errors import EgressError
from civiccast.egress.models import (
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.runtime import (
    EgressLoudnessError,
    build_persistent_encoder_args,
    write_concat_plan,
)


def _source_plan(path: Path) -> EgressSourcePlan:
    source = path / "source-a.ts"
    source.write_text("fake", encoding="utf-8")
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(label="Council meeting", path=str(source), duration_seconds=1)
        ],
    )


def test_write_concat_plan_for_preconformed_segments(tmp_path: Path) -> None:
    plan = _source_plan(tmp_path)
    concat = tmp_path / "plan.ffconcat"

    write_concat_plan(concat, plan)

    assert concat.read_text(encoding="utf-8").splitlines() == [
        "ffconcat version 1.0",
        f"file '{Path(plan.segments[0].path).resolve().as_posix()}'",
    ]


def test_write_concat_plan_escapes_single_quotes(tmp_path: Path) -> None:
    source = tmp_path / "source's.ts"
    source.write_text("fake", encoding="utf-8")
    concat = tmp_path / "plan.ffconcat"

    write_concat_plan(
        concat,
        EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(label="Quoted", path=str(source), duration_seconds=1),
            ],
        ),
    )

    assert "\\'" in concat.read_text(encoding="utf-8")


def test_write_concat_plan_preserves_live_input_urls(tmp_path: Path) -> None:
    concat = tmp_path / "plan.ffconcat"
    write_concat_plan(
        concat,
        EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(
                    label="Live chamber",
                    path="srt://127.0.0.1:19002",
                    duration_seconds=60,
                    kind="live",
                    source_ref="gov:relay",
                )
            ],
        ),
    )

    assert "file 'srt://127.0.0.1:19002'" in concat.read_text(encoding="utf-8")


def test_write_concat_plan_includes_trim_points(tmp_path: Path) -> None:
    source = tmp_path / "source.ts"
    source.write_text("fake", encoding="utf-8")
    concat = tmp_path / "plan.ffconcat"

    write_concat_plan(
        concat,
        EgressSourcePlan(
            channel_id="gov",
            segments=[
                EgressSourceSegment(
                    label="Trimmed",
                    path=str(source),
                    duration_seconds=55,
                    inpoint_seconds=5,
                    outpoint_seconds=60,
                ),
            ],
        ),
    )

    assert concat.read_text(encoding="utf-8").splitlines()[-2:] == [
        "inpoint 5",
        "outpoint 60",
    ]


def test_build_persistent_encoder_args_paces_srt_and_resolves_secret(tmp_path: Path) -> None:
    concat = tmp_path / "plan.ffconcat"
    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        sinks=[
            EgressSinkSpec(
                kind="srt",
                label="Headend",
                uri="srt://headend.example:9000",
                secret_ref="EGRESS_SRT_PASSPHRASE",
            )
        ],
    )

    args = build_persistent_encoder_args(
        concat_plan=concat,
        config=config,
        resolve_secret=lambda ref: "station-passphrase" if ref else None,
    )

    assert "-re" in args
    assert str(concat) in args
    assert (
        args[-2:]
        == [
            "-f",
            "mpegts",
            "srt://headend.example:9000?mode=caller&latency=2000000&linger=5&passphrase=station-passphrase",
        ][-2:]
    )
    assert args[-1].endswith("passphrase=station-passphrase")


def test_build_persistent_encoder_args_does_not_pace_file_sink(tmp_path: Path) -> None:
    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[EgressSinkSpec(kind="file", label="Proof", uri=str(tmp_path / "out.ts"))],
        ),
    )

    assert "-re" not in args
    assert args[-3:] == ["-f", "mpegts", str(tmp_path / "out.ts")]


def test_build_persistent_encoder_args_supports_rtmp_sink_secret(tmp_path: Path) -> None:
    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[
                EgressSinkSpec(
                    kind="rtmp",
                    label="Platform",
                    uri="rtmps://stream.example/live",
                    secret_ref="EGRESS_RTMP_STREAM_KEY",
                )
            ],
        ),
        resolve_secret=lambda ref: "station-stream-key" if ref else None,
    )

    assert "-re" in args
    assert args[-3:] == ["-f", "flv", "rtmps://stream.example/live/station-stream-key"]


def test_build_persistent_encoder_args_supports_local_ts_udp_sink(tmp_path: Path) -> None:
    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[EgressSinkSpec(kind="local-ts", label="LAN", uri="udp://239.0.0.1:5000")],
        ),
    )

    assert "-re" in args
    assert args[-3:] == ["-f", "mpegts", "udp://239.0.0.1:5000"]


def test_build_persistent_encoder_args_supports_udp_ts_headend_sink(tmp_path: Path) -> None:
    # CA-6: the headend SPTS sink is realtime and carries its CBR mux args.
    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[
                EgressSinkSpec(
                    kind="udp-ts",
                    label="Headend",
                    uri="udp://239.255.0.1:5000",
                    extra_output_args=["-muxrate", "3750k"],
                )
            ],
        ),
    )

    assert "-re" in args
    assert args[-3:] == ["-f", "mpegts", "udp://239.255.0.1:5000?pkt_size=1316"]
    muxrate_idx = args.index("-muxrate")
    assert args[muxrate_idx + 1] == "3750k"


def test_build_persistent_encoder_args_applies_branding_filter_plan(tmp_path: Path) -> None:
    branding_plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        snapshot_base_url="http://127.0.0.1:8000",
    )

    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[EgressSinkSpec(kind="file", label="Proof", uri=str(tmp_path / "out.ts"))],
        ),
        branding_plan=branding_plan,
    )

    assert "-filter_complex" in args
    assert branding_plan.filter_complex in args
    assert args[args.index("-map") + 1] == f"[{branding_plan.output_video_label}]"
    assert "-c" not in args
    assert args[args.index("-c:v") + 1] == "h264"
    assert args[args.index("-b:v") + 1] == "6000k"
    assert args[-3:] == ["-f", "mpegts", str(tmp_path / "out.ts")]


def test_branding_with_baseline_ott_sink_builds_and_tone_strips(tmp_path: Path) -> None:
    # Close re-audit regression: a branded channel with a baseline OTT (srt) sink must
    # BUILD — the tone-strip need must NOT trip the loudness-divergence+branding refusal —
    # and the shared branding audio is re-encoded through the EAS notch.
    branding_plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        snapshot_base_url="http://127.0.0.1:8000",
    )
    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="x",
            loudness_target_lufs=-16.0,
            sinks=[
                EgressSinkSpec(
                    kind="srt",
                    label="CDN",
                    uri="srt://cdn.example:9000",
                    loudness_regime="streaming",
                )
            ],
        ),
        branding_plan=branding_plan,
    )
    assert branding_plan.filter_complex in args  # branding video still applied
    assert "bandreject=f=853:width_type=h:w=40,bandreject=f=960:width_type=h:w=40" in args


def test_branding_with_divergent_tone_strip_raises(tmp_path: Path) -> None:
    # Close re-audit regression: a branded channel with an OTT sink that strips the EAS
    # tone alongside a cable sink that must pass it through is unexpressible on the single
    # shared branding audio mapping — it must FAIL CLOSED, not silently ship the tone on
    # the OTT sink (FCC Sec. 11.31).
    branding_plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        snapshot_base_url="http://127.0.0.1:8000",
    )
    with pytest.raises(EgressLoudnessError, match="tone-strip"):
        build_persistent_encoder_args(
            concat_plan=tmp_path / "plan.ffconcat",
            config=EgressConfig(
                channel_id="gov",
                enabled=True,
                slate_message="x",
                loudness_target_lufs=-16.0,
                sinks=[
                    EgressSinkSpec(
                        kind="srt",
                        label="CDN",
                        uri="srt://cdn.example:9000",
                        loudness_regime="streaming",
                    ),
                    EgressSinkSpec(kind="udp-ts", label="cable", uri="udp://239.0.0.1:5000"),
                ],
            ),
            branding_plan=branding_plan,
        )


def test_branding_with_loudness_divergence_still_raises(tmp_path: Path) -> None:
    # The branding refusal is for LOUDNESS divergence specifically — a divergent cable
    # sink under branding still fails closed (unchanged).
    branding_plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        snapshot_base_url="http://127.0.0.1:8000",
    )
    with pytest.raises(EgressLoudnessError):
        build_persistent_encoder_args(
            concat_plan=tmp_path / "plan.ffconcat",
            config=EgressConfig(
                channel_id="gov",
                enabled=True,
                slate_message="x",
                loudness_target_lufs=-16.0,
                sinks=[
                    EgressSinkSpec(
                        kind="udp-ts",
                        label="cable",
                        uri="udp://239.0.0.1:5000",
                        loudness_regime="atsc-a85",
                    )
                ],
            ),
            branding_plan=branding_plan,
        )


def test_build_persistent_encoder_args_places_caption_sidecar_before_mapping(
    tmp_path: Path,
) -> None:
    concat = tmp_path / "plan.ffconcat"
    sidecar = tmp_path / "captions.vtt"
    caption_plan = SidecarCaptionEmbedder(sidecar_path=sidecar).build_plan(
        channel_id="gov",
        cues=[],
    )

    args = build_persistent_encoder_args(
        concat_plan=concat,
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[EgressSinkSpec(kind="file", label="Proof", uri=str(tmp_path / "out.ts"))],
        ),
        caption_plan=caption_plan,
    )

    concat_index = args.index(str(concat))
    sidecar_index = args.index(str(sidecar))
    subtitle_map_index = args.index("1:s:0?")
    output_index = args.index(str(tmp_path / "out.ts"))
    assert concat_index < sidecar_index < subtitle_map_index < output_index
    assert args[sidecar_index - 1] == "-i"
    assert args[subtitle_map_index - 1] == "-map"
    assert args[subtitle_map_index + 1 : subtitle_map_index + 3] == ["-c:s", "copy"]


def test_build_persistent_encoder_args_reencodes_only_the_divergent_sink(tmp_path: Path) -> None:
    # S11b: a cable atsc-a85 sink (-24) diverges from the -16 channel baseline and
    # is re-normalised with loudnorm; the streaming sink matches and copies.
    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            loudness_target_lufs=-16.0,
            sinks=[
                EgressSinkSpec(
                    kind="udp-ts",
                    label="Cable",
                    uri="udp://239.0.0.1:5000",
                    loudness_regime="atsc-a85",
                ),
                EgressSinkSpec(
                    kind="srt",
                    label="CDN",
                    uri="srt://cdn.example:9000",
                    loudness_regime="streaming",
                ),
            ],
        ),
    )

    # One complete output group per sink (no shared single-mapping group).
    assert args.count("-map") == 4  # video + audio map per sink
    assert args.count("-c:v") == 2
    assert "-re" in args  # realtime sinks present
    # The divergent cable sink re-normalises to -24 LKFS; the OTT (srt) CDN sink
    # tone-strips the EAS attention tone (S11c gap-B) so it also re-encodes — only
    # non-OTT baseline sinks (udp-ts/file) stay stream-copied.
    assert "-filter:a" in args
    assert "loudnorm=I=-24:LRA=11:TP=-1.5" in args
    assert "bandreject=f=853:width_type=h:w=40,bandreject=f=960:width_type=h:w=40" in args

    def _has_subseq(seq: list[str], a: str, b: str) -> bool:
        return any(seq[i] == a and seq[i + 1] == b for i in range(len(seq) - 1))

    assert _has_subseq(args, "-c:a", "aac"), "the divergent cable sink re-encodes audio"
    # The OTT CDN sink no longer stream-copies — it re-encodes for the EAS tone notch.
    assert not _has_subseq(args, "-c:a", "copy"), "the OTT CDN sink tone-strips (re-encodes)"
    # Both destinations are present.
    assert any("udp://239.0.0.1:5000" in a for a in args)
    assert any("srt://cdn.example:9000" in a for a in args)
    # The cable loudnorm precedes the cable target (its own output group).
    loudnorm_index = args.index("loudnorm=I=-24:LRA=11:TP=-1.5")
    cable_index = next(i for i, a in enumerate(args) if a.startswith("udp://239.0.0.1:5000"))
    assert loudnorm_index < cable_index


def _has_subseq(seq: list[str], a: str, b: str) -> bool:
    return any(seq[i] == a and seq[i + 1] == b for i in range(len(seq) - 1))


def test_build_persistent_encoder_args_tone_strips_baseline_ott_sink(tmp_path: Path) -> None:
    # S11c gap-B routing fix: a single OTT (srt) sink AT the channel baseline (no
    # loudness divergence) with eas_tone_strip_enabled (the default) must still route
    # through the per-sink path so the 853/960 Hz notch is applied — not stream-copied.
    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="x",
            loudness_target_lufs=-16.0,
            sinks=[
                EgressSinkSpec(
                    kind="srt",
                    label="CDN",
                    uri="srt://cdn.example:9000",
                    loudness_regime="streaming",
                )
            ],
        ),
    )
    assert "bandreject=f=853:width_type=h:w=40,bandreject=f=960:width_type=h:w=40" in args
    assert not _has_subseq(args, "-c:a", "copy"), "baseline OTT sink must tone-strip, not copy"


def test_build_persistent_encoder_args_single_cable_sink_not_tone_stripped(tmp_path: Path) -> None:
    # A single non-OTT (udp-ts cable) baseline sink is never tone-stripped — it stays
    # the historical byte-identical single-mapping path (no bandreject notch).
    args = build_persistent_encoder_args(
        concat_plan=tmp_path / "plan.ffconcat",
        config=EgressConfig(
            channel_id="gov",
            enabled=True,
            slate_message="x",
            loudness_target_lufs=-16.0,
            sinks=[EgressSinkSpec(kind="udp-ts", label="cable", uri="udp://239.0.0.1:5000")],
        ),
    )
    assert "bandreject" not in " ".join(args)


def test_eas_tone_strip_only_applies_to_ott_sinks() -> None:
    """S11c gap-B: OTT (srt/rtmp) sinks with eas_tone_strip_enabled get the 853/960 Hz
    notch (re-encode); cable/file sinks are never tone-stripped (stay stream-copied)."""
    from civiccast.egress.loudness_plan import resolve_sink_loudness
    from civiccast.egress.models import CanonicalProfile, EgressSinkSpec
    from civiccast.egress.runtime import _EAS_TONE_NOTCH, _per_sink_audio_args

    profile = CanonicalProfile(
        width=1280, height=720, fps=30, video_codec="libx264", video_bitrate_kbps=4000, gop_size=60
    )

    def _res(kind: str, uri: str, *, tone: bool = True):
        sink = EgressSinkSpec(kind=kind, label="x", uri=uri, eas_tone_strip_enabled=tone)
        return resolve_sink_loudness(sink, channel_target_lufs=-16.0, channel_tolerance_lufs=2.0)

    # cable (udp-ts) at baseline → byte-identical copy, never tone-stripped
    assert _per_sink_audio_args(_res("udp-ts", "udp://239.0.0.1:5000"), profile) == ["-c:a", "copy"]
    # OTT srt at baseline + tone-strip on → notch re-encode (no copy)
    srt_args = _per_sink_audio_args(_res("srt", "srt://cdn.example:9000"), profile)
    assert "-filter:a" in srt_args
    assert _EAS_TONE_NOTCH in srt_args
    assert "copy" not in srt_args
    # OTT srt with tone-strip explicitly disabled → copy
    assert _per_sink_audio_args(_res("srt", "srt://cdn.example:9000", tone=False), profile) == [
        "-c:a",
        "copy",
    ]


def test_build_persistent_encoder_args_refuses_per_sink_loudness_with_branding(
    tmp_path: Path,
) -> None:
    # Per-sink loudness divergence + a single filter_complex branding video cannot
    # be expressed on the copy path; refuse rather than emit an unprovable graph.
    branding_plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        snapshot_base_url="http://127.0.0.1:8000",
    )
    config = EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=-16.0,
        sinks=[
            EgressSinkSpec(
                kind="udp-ts",
                label="Cable",
                uri="udp://239.0.0.1:5000",
                loudness_regime="atsc-a85",
            )
        ],
    )
    # It must subclass EgressError so the daemon's start guard catches it and
    # writes a clean ERROR state rather than crashing the encode loop.
    assert issubclass(EgressLoudnessError, EgressError)
    with pytest.raises(EgressLoudnessError):
        build_persistent_encoder_args(
            concat_plan=tmp_path / "plan.ffconcat",
            config=config,
            branding_plan=branding_plan,
        )
