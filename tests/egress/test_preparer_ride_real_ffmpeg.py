# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U25 answer 12 section 3: the real ride, end to end, through the preparer.

Every other U25 preparer test substitutes ``window_leveler`` with a double: they
prove the *decisions* (which method label is recorded, what is written where,
what happens when the ride refuses) but not that a real ``level_window`` and a
real program mux produce a real program at the level the target asks for.  This
module runs the whole thing -- lavfi asset in, ridden canonical program out --
and asserts on the artifact the station would put on air: its method label, its
length, and its own measured loudness.

The second half of the module is U42's, and measures the guard's *second* lever:
the encoder re-emit (``EncoderVariant``).  A double can prove that ``level_window``
walks the variants in order; only a real encoder can show that a variant actually
lands the emitted artifact inside the hard bound, and only a real mux can show that
the artifact still airs bit-for-bit when the profile says 192 kbps and the artifact
says 256.

**The ride needs an FFmpeg with soxr.**  Its true-peak ceiling is 4x oversampled
through ``aresample=192000:resampler=soxr:precision=28``
(:func:`civiccast.egress.loudness_ride.resample_filter`).  A build without soxr
fails that filter with ``Requested resampling engine is unavailable`` and
``-22 (Invalid argument)`` as soon as the trim stage starts, ``level_window``
raises, and the preparer correctly degrades to loudnorm -- so on such a host this
module would be asserting against the fallback path and proving nothing about
the ride.  It skips instead, on a probe built from the module's own filter
builder so the guard cannot drift from the filter the ride really runs.  The
station's shipped FFmpeg does carry soxr; a stock Windows PATH build may not.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from civiccast.egress import loudness_ride as lr
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.preparer import SourcePreparer
from civiccast.stream._ffmpeg import (
    probe_has_decodable_stream,
    probe_media_duration_seconds,
    resolve_h264_encoder,
    run_ffmpeg,
)
from civiccast.stream.loudness import check_streaming_loudness

_TARGET_LUFS = -24.0
_TOLERANCE_LUFS = 1.0
_ASSET_DURATION_S = 8.0
_WINDOW_INPOINT_S = 1.0
_WINDOW_DURATION_S = 4.0
#: A window shorter than the ride's 240 s acceptance window still gates as a
#: whole program: the same measurement the product's own loudness gate makes.
_OVERSAMPLE_HZ = 192_000


def _soxr_available() -> bool:
    """Does the FFmpeg the ride will resolve actually build its oversampler?

    Cheap (0.1 s of lavfi) and run once, at import, because every test here is
    meaningless without it.  The filter string is the module's own.
    """
    probe = subprocess.run(  # fixed argv; the binary is the ride's own resolver
        [
            lr._ffmpeg_binary(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.1",
            "-af",
            lr.resample_filter(_OVERSAMPLE_HZ, lr.RideParams(target_lufs=_TARGET_LUFS)),
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None
    or shutil.which("ffprobe") is None
    or importlib.util.find_spec("numpy") is None
    or not _soxr_available(),
    reason=(
        "needs ffmpeg+ffprobe+numpy and an FFmpeg built with soxr (the ride's limiter "
        "oversampler); without soxr the ride degrades to loudnorm and this module would "
        "prove nothing about it."
    ),
)


def _config() -> EgressConfig:
    return EgressConfig(
        channel_id="gov",
        enabled=True,
        slate_message="CivicCast is preparing the channel.",
        loudness_target_lufs=_TARGET_LUFS,
        loudness_tolerance_lufs=_TOLERANCE_LUFS,
        canonical_profile=CanonicalProfile(width=320, height=240, video_bitrate_kbps=600),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri="build/out.ts")],
    )


@pytest.fixture
def real_asset(tmp_path: Path) -> Path:
    """A short MP4 with real audio, loud enough that the ride has to move it."""
    sample = tmp_path / "asset.mp4"
    result = subprocess.run(  # fixed argv on a lavfi source, into tmp_path
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=15:duration={_ASSET_DURATION_S:g}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={_ASSET_DURATION_S:g}",
            "-c:v",
            resolve_h264_encoder(),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(sample),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return sample


def _preparer(work_dir: Path, *, playout_trim_supported: bool) -> SourcePreparer:
    return SourcePreparer(
        work_dir=work_dir,
        ffmpeg_runner=run_ffmpeg,
        loudness_checker=check_streaming_loudness,
        warm_scheduler=lambda job: job(),  # synchronous: any warm completes inline
        playout_trim_supported=playout_trim_supported,
    )


def _plan(
    source: Path,
    *,
    duration_seconds: float,
    label: str,
    inpoint_seconds: float | None = None,
    outpoint_seconds: float | None = None,
) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id="gov",
        segments=[
            EgressSourceSegment(
                label=label,
                path=str(source),
                duration_seconds=duration_seconds,
                inpoint_seconds=inpoint_seconds,
                outpoint_seconds=outpoint_seconds,
            )
        ],
    )


def _measured_loudness(path: Path) -> float:
    gate = check_streaming_loudness(
        media_path=path, target_lufs=_TARGET_LUFS, tolerance_lufs=_TOLERANCE_LUFS
    )
    assert gate.measured_lufs is not None, gate
    return gate.measured_lufs


def test_a_full_asset_conform_is_ridden_and_lands_on_the_target(
    tmp_path: Path, real_asset: Path
) -> None:
    """The whole-asset path (the conform-cache unit), end to end.

    Before answer 12's wiring this conform was loudnorm's, and the prepared
    program was the source level with a loudnorm offset applied to the average
    -- the case the "every 4-minute stretch" target exists because it gets
    wrong.  What is asserted here is the shipped artifact: the ride recorded on
    the segment AND in the promoted cache entry the next airing will read, the
    asset's real length, and a loudness the product's own gate accepts.
    """
    work = tmp_path / "work"
    report = _preparer(work, playout_trim_supported=True).prepare(
        _plan(real_asset, duration_seconds=_ASSET_DURATION_S, label="full-airing"), _config()
    )

    record = report.records[0]
    assert record.loudness_method == "ride", record
    prepared = Path(report.source_plan.segments[0].path)
    assert prepared.exists()
    measured_duration = probe_media_duration_seconds(prepared)
    assert measured_duration is not None
    assert measured_duration == pytest.approx(_ASSET_DURATION_S, abs=1.0)

    metas = list((work / "conform-cache").glob("*.json"))
    assert metas, "a full-asset conform promotes into the cache"
    promoted = [json.loads(path.read_text(encoding="utf-8")) for path in metas]
    assert [meta["loudness_method"] for meta in promoted if meta.get("full_asset_conform")] == [
        "ride"
    ]

    measured_lufs = _measured_loudness(prepared)
    assert abs(measured_lufs - _TARGET_LUFS) <= _TOLERANCE_LUFS, measured_lufs


def test_a_windowed_conform_is_ridden_and_keeps_the_window_length(
    tmp_path: Path, real_asset: Path
) -> None:
    """The bounded per-segment path, end to end -- and the length it must keep.

    The window here is a join-in-progress airing: 4 s out of the middle of an
    8 s asset.  Its length assertion is a regression guard with a specific
    history: the program mux used to place ``-t`` between its two ``-i``
    operands, where FFmpeg binds it to the SECOND input (the ride's own audio,
    already the window's length) instead of bounding the output.  The source
    video then ran unbounded past the in-point and this 4 s window shipped as a
    7 s program -- 3 s of video with no audio on it -- against 3.97 s of audio.
    ``build_video_from_source_args`` now emits the bound after both inputs.
    """
    work = tmp_path / "work"
    report = _preparer(work, playout_trim_supported=False).prepare(
        _plan(
            real_asset,
            duration_seconds=_WINDOW_DURATION_S,
            label="trimmed-airing",
            inpoint_seconds=_WINDOW_INPOINT_S,
            outpoint_seconds=_WINDOW_INPOINT_S + _WINDOW_DURATION_S,
        ),
        _config(),
    )

    record = report.records[0]
    assert record.loudness_method == "ride", record
    prepared = Path(report.source_plan.segments[0].path)
    assert prepared.exists()
    measured_duration = probe_media_duration_seconds(prepared)
    assert measured_duration is not None
    assert measured_duration == pytest.approx(_WINDOW_DURATION_S, abs=0.5), measured_duration

    measured_lufs = _measured_loudness(prepared)
    assert abs(measured_lufs - _TARGET_LUFS) <= _TOLERANCE_LUFS, measured_lufs


# ---------------------------------------------------------------------------
# U42: the guard's second lever -- the encoder re-emit -- against a real encoder.
# ---------------------------------------------------------------------------

#: The guard's encoder lever is only reachable on material that is STILL over the
#: hard bound once the limiter has done its work, so the material has to be hot.
#: Generated rather than read from disk, so the test is hermetic: white noise at
#: these amplitudes is what a real AAC encoder overshoots on.  The seed is pinned
#: because ``anoisesrc`` is seed-dependent across generations -- the same
#: amplitude without a seed does not reproduce the same peaks, and the assertions
#: below sit on which side of the bound each arm lands.
_GUARD_MATERIAL_SECONDS = 20.0
_GUARD_MATERIAL_SEED = 20_260_926
#: The ride's own true-peak ceiling, the one ``_config``'s loudness target implies.
_GUARD_LIMIT_DBTP = -1.0
_GUARD_TIMEOUT_S = 300.0
#: The headroom answer 11's ceiling rule left under the target it was aiming at.
#: Deleted from the module with the rule U43 replaced; kept here as the number
#: this module's pad test compares the pad against.
_OLD_CEILING_MARGIN_DB = 0.3


def _guard_params() -> lr.RideParams:
    return lr.RideParams(target_lufs=_TARGET_LUFS, limit_dbtp=_GUARD_LIMIT_DBTP)


def _guard_material(tmp_path: Path, *, amplitude: float) -> Path:
    """Seed-pinned white noise, as 48 kHz stereo float PCM -- the ride's own feed."""
    pcm = tmp_path / f"guard-material-a{amplitude:g}.pcm"
    result = subprocess.run(  # fixed argv on a lavfi source, into tmp_path
        [
            lr._ffmpeg_binary(),
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=amplitude={amplitude:g}:color=white:seed={_GUARD_MATERIAL_SEED}",
            "-t",
            f"{_GUARD_MATERIAL_SECONDS:g}",
            "-f",
            "f32le",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(pcm),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    return pcm


def _guard_arms(profile: CanonicalProfile) -> list[tuple[str, lr.EncoderVariant | None]]:
    """The arms the guard would spend, in the guard's own order and labelling.

    Round 1 is the profile's nominal emit (no variant); then every variant
    ``encoder_variants_for`` yields, labelled by the product's own helper, so an
    assertion on a label is an assertion on what the operator's WARNING would say.
    """
    arms: list[tuple[str, lr.EncoderVariant | None]] = [(lr.encoder_settings_label(profile), None)]
    arms.extend(
        (lr.encoder_settings_label(profile, variant), variant)
        for variant in lr.encoder_variants_for(profile)
    )
    return arms


def _audio_bit_rate_bps(path: Path) -> int:
    """The bitrate ffprobe reports for the audio stream of ``path``.

    JSON rather than the flat writer: an MPEG-TS program lists its audio stream
    more than once, so the value-keyed writer emits the same number on several
    lines and a plain ``int(stdout)`` cannot parse it.  Every audio stream must
    agree -- a disagreement means the program carries audio the test does not
    understand, which is a finding, not something to average away.
    """
    completed = subprocess.run(  # fixed argv
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,bit_rate",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    streams = json.loads(completed.stdout).get("streams", [])
    rates = [s.get("bit_rate") for s in streams if s.get("codec_type") == "audio"]
    assert rates, f"ffprobe reported no audio stream for {path}: {completed.stdout!r}"
    assert len(set(rates)) == 1, f"ffprobe reported {rates!r} for {path}"
    value = rates[0]
    assert isinstance(value, str) and value.isdigit(), f"ffprobe reported {value!r} for {path}"
    return int(value)


def test_a_variant_re_encode_moves_the_encoder_and_nothing_else(tmp_path: Path) -> None:
    """The variant is the encoder axis only -- same PCM, same filter, same sink.

    U42's item 1 is a *re-encode*, not a re-render: the guard re-emits from the
    already-limited PCM the nominal attempt teed, so nothing about the ride's
    work changes.  What makes that true in code is that the nominal emit and the
    variant emit are the same builder (``_encode_sink_tail``) called with one
    different argument, and this pins the consequence: identical argument lists
    up to the sink tail, and inside the tail the only tokens that move are the
    encoder's own (the bitrate and the appended encoder options).
    """
    profile = _config().canonical_profile
    params = _guard_params()
    variants = lr.encoder_variants_for(profile)
    assert variants, "a profile whose codec is AAC must offer the guard its encoder lever"
    first = variants[0]
    pcm = tmp_path / "in.pcm"
    out = tmp_path / "out.ts"
    trim_db = -0.5

    nominal = lr.build_reencode_args(pcm, out, trim_db=trim_db, params=params, profile=profile)
    varied = lr.build_reencode_args(
        pcm, out, trim_db=trim_db, params=params, profile=profile, variant=first
    )

    tail = lr._encode_sink_tail(out, trim_db, params=params, profile=profile)
    head = len(nominal) - len(tail)
    assert nominal[:head] == varied[:head], "the input side must be the same argument list"
    assert f"{profile.audio_bitrate_kbps}k" in nominal
    assert f"{first.bitrate_kbps}k" in varied

    encoder_tokens = {"-b:a", f"{profile.audio_bitrate_kbps}k", f"{first.bitrate_kbps}k"}
    encoder_tokens.update(first.extra_args)
    assert [a for a in nominal if a not in encoder_tokens] == [
        a for a in varied if a not in encoder_tokens
    ], (nominal, varied)
    # ... because the only tokens that filter above removes are the encoder's:
    assert varied.count("-b:a") == 1, varied
    assert [a for a in varied if a in first.extra_args] == list(first.extra_args), varied


@pytest.mark.parametrize(
    ("amplitude", "expected_first_meeting"),
    [
        pytest.param(1.0, "aac 256k", id="first-variant-meets-the-bound"),
        pytest.param(0.9, "aac 256k (-aac_coder fast)", id="guard-walks-to-the-encoder-options"),
    ],
)
def test_the_guard_walks_its_encoder_variants_until_one_meets_the_bound(
    tmp_path: Path, amplitude: float, expected_first_meeting: str
) -> None:
    """U42 item 1: the encoder lever, on a real encode, meeting the real bound.

    Two hermetic materials, one per shape the guard has:

    * amplitude 1.0 -- the nominal emit is over the bound and the FIRST variant
      (``-b:a 256k``) lands inside it, so the guard must stop there and never
      spend ``-aac_coder fast``;
    * amplitude 0.9 -- the first variant is *still* over and the second
      (``-b:a 256k -aac_coder fast``) meets the bound, so the walk has to reach
      the end of the list.  This is the case that proves the order is the
      product's and not a coincidence of one material.

    Every arm is the guard's own two calls -- ``run_reencode`` then
    ``scan_peak_dbfs`` on the emitted artifact.  If this host's encoder keeps the
    nominal inside the bound the guard's encoder lever has nothing to fix, and
    the test skips loudly rather than asserting a shape the material cannot show.
    """
    profile = _config().canonical_profile
    params = _guard_params()
    bound = lr.TP_GUARD_MAX_PEAK_DBFS
    arms = _guard_arms(profile)
    pcm = _guard_material(tmp_path, amplitude=amplitude)

    walk: list[tuple[str, float]] = []
    for index, (label, variant) in enumerate(arms):
        artifact = tmp_path / f"attempt-{index}.ts"
        lr.run_reencode(
            pcm_path=pcm,
            output_path=artifact,
            trim_db=0.0,
            params=params,
            profile=profile,
            variant=variant,
            timeout_s=_GUARD_TIMEOUT_S,
        )
        peak = lr.scan_peak_dbfs(artifact, params=params, timeout_s=_GUARD_TIMEOUT_S)
        assert peak is not None, f"no peak could be measured for {label}"
        walk.append((label, peak))
        if peak <= bound:
            if index == 0:
                pytest.skip(
                    f"this host's AAC encoder already keeps {amplitude:g}-amplitude white "
                    f"noise inside the +{bound:g} dBFS bound ({label}: {peak:+.6f} dBFS), "
                    "so the guard's encoder lever cannot be exercised on it"
                )
            break

    assert walk[-1][0] == expected_first_meeting, walk
    assert walk[-1][1] <= bound, walk
    for label, peak in walk[:-1]:
        assert peak > bound, f"{label} was already inside the bound ({peak:+.6f} dBFS)"
    if expected_first_meeting == arms[1][0]:
        # The guard stops at the first attempt that meets the bound.
        assert [label for label, _ in walk] == [arms[0][0], arms[1][0]], walk
    else:
        assert len(walk) == len(arms), walk


def _guard_arm(
    pcm: Path,
    artifact: Path,
    *,
    trim_db: float,
    limit_dbtp: float,
    params: lr.RideParams,
    profile: CanonicalProfile,
) -> lr.LeveledAttempt:
    """One guard arm, measured: the guard's own re-encode, then its own scoring.

    Both calls are the production ones, in the production order -- ``run_reencode``
    at the ceiling this arm is trying, then ``measure_artifact`` on the file that
    came out.  ``params`` reaches the measurement unmodified, as ``level_window``
    passes it: an attempt *carries* the ceiling it ran at (``limit_dbtp``) rather
    than carrying a mutated copy of the ride's parameters.
    """
    lr.run_reencode(
        pcm_path=pcm,
        output_path=artifact,
        trim_db=trim_db,
        params=replace(params, limit_dbtp=limit_dbtp),
        profile=profile,
        timeout_s=_GUARD_TIMEOUT_S,
    )
    return lr.measure_artifact(
        artifact,
        params=params,
        round_index=0,
        limit_dbtp=limit_dbtp,
        target_lufs=params.target_lufs,
        duration_s=_GUARD_MATERIAL_SECONDS,
        timeout_s=_GUARD_TIMEOUT_S,
    )


def test_the_pad_round_pays_the_peak_bound_in_drive_not_in_level(tmp_path: Path) -> None:
    """U43: the round that fixes the hard bound hands the drive back what it takes.

    The nominal emit is hot -- white noise at this amplitude is what this host's
    AAC encoder overshoots on -- so the guard owes a round.  What U42 measured on
    the live feed is that paying for the bound out of the ceiling *alone* also
    pays for it out of the audience's level: at the lowered ceiling the artifact
    was quiet and still over the bound.  U43 spends the round on the *decoded
    sample peak* -- which is what the bound is about -- and returns the same
    number of dB to the drive:

        pad         = decoded_peak_dbfs - TP_GUARD_MAX_PEAK_DBFS + margin (capped)
        new ceiling = the kept attempt's ceiling - pad
        new drive   = the kept attempt's drive   + pad

    That drive is the pad round's first *guess*.  Answer 2's round measures the
    settings it is about to spend -- one limited pass at (ceiling - pad, drive +
    pad), no encode -- and corrects the drive by the loudness error it measured,
    because a harder limit hands back less loudness than the pad spends (the live
    sweep measured +0.53 LU and -0.28 LU on two cells).  The arms below are built
    by hand, so this test measures the pad's arithmetic; the *corrected* drive is
    ``level_window``'s and is measured on the live cells, not here.

    Three arms on one hermetic material, all re-encoded from the same PCM:

    * **nominal** -- over the bound, so the round is owed;
    * **pad** -- drive + pad, ceiling - pad: inside the bound, with the drive and
      the ceiling moved by exactly the pad, read off the argv that ran rather
      than off the arithmetic that asked for it;
    * **uncompensated** -- the ceiling moves and the drive does not, which is
      what the round would be without the compensation.

    The round this replaces is measured on the same three arms, not asserted: on
    this material answer 11's emitted-true-peak rule would have pulled the ceiling
    2.6 dB -- more than twice the pad -- because the AAC overshoot it reads is
    larger than the sample-peak overshoot the bound is actually about.  That rule
    also missed the bound where the artifact was live (U42's log line 18797: hot
    at the nominal ceiling, quiet *and* still over at the lowered one), which is
    the case no hermetic material here reproduces; the live three-cell sweep is
    what measures it.

    The loudness claim here is a *direction*, and the magnitude is material-
    dependent: uniform noise sits deep in the limiter, so most of the returned
    drive is absorbed and the compensated arm keeps only ~0.1 LU more of the
    nominal's loudness than the uncompensated one.  Where the programme sits on
    the limiter's knee -- the live feed -- U43's sweep is what measures the
    magnitude.  The peak claim is not material-dependent: it is the decoded
    sample peak of the artifact that runs, against the bound the selector judges
    the attempt by.
    """
    profile = _config().canonical_profile
    params = _guard_params()
    bound = lr.TP_GUARD_MAX_PEAK_DBFS
    pcm = _guard_material(tmp_path, amplitude=1.0)
    trim_db = 0.0

    nominal = _guard_arm(
        pcm,
        tmp_path / "nominal.ts",
        trim_db=trim_db,
        limit_dbtp=params.limit_dbtp,
        params=params,
        profile=profile,
    )
    if not nominal.over_hard_bound():
        pytest.skip(
            f"this host's AAC encoder keeps {trim_db:g} dB-trimmed white noise inside the "
            f"+{bound:g} dBFS bound ({nominal.decoded_peak_dbfs!r} dBFS), so the pad round "
            "cannot be exercised on it"
        )
    assert nominal.decoded_peak_dbfs is not None
    assert nominal.emitted_dbtp is not None
    assert nominal.whole_err_lu is not None

    pad = lr.guard_pad_db(nominal)
    assert pad is not None, nominal
    assert pad == pytest.approx(
        nominal.decoded_peak_dbfs - bound + lr.TP_GUARD_PAD_MARGIN_DB, abs=1e-3
    ), pad
    assert 0 < pad <= lr.TP_GUARD_MAX_PAD_DB, pad

    pad_ceiling = nominal.limit_dbtp - pad
    # Answer 11's rule paid for the same overshoot out of the ceiling, measured
    # from the *emitted true peak* -- on this material a deeper drop than the pad,
    # which is the trade U43 exists to stop making.
    old_ceiling = round(
        nominal.limit_dbtp
        - (nominal.emitted_dbtp - lr.TP_GUARD_TARGET_DBTP + _OLD_CEILING_MARGIN_DB),
        3,
    )
    assert old_ceiling < pad_ceiling, (old_ceiling, pad_ceiling)

    padded = _guard_arm(
        pcm,
        tmp_path / "padded.ts",
        trim_db=trim_db + pad,
        limit_dbtp=pad_ceiling,
        params=params,
        profile=profile,
    )
    assert not padded.over_hard_bound(), padded
    assert padded.decoded_peak_dbfs is not None
    assert padded.decoded_peak_dbfs <= bound, padded

    # The encode that ran moved the drive by exactly the pad and the ceiling by
    # exactly the pad: one token in the filter chain each, and nothing else.
    argv = lr.build_reencode_args(
        pcm,
        tmp_path / "padded.ts",
        trim_db=trim_db + pad,
        params=replace(params, limit_dbtp=pad_ceiling),
        profile=profile,
    )
    chain = argv[argv.index("-af") + 1]
    assert chain.startswith(f"volume={trim_db + pad:.3f}dB,"), chain
    assert f"limit={lr.limit_value(pad_ceiling):.6f}" in chain, chain
    nominal_chain = lr.build_reencode_args(
        pcm,
        tmp_path / "nominal.ts",
        trim_db=trim_db,
        params=params,
        profile=profile,
    )
    nominal_chain = nominal_chain[nominal_chain.index("-af") + 1]
    assert f"volume={trim_db:.3f}dB," in nominal_chain, nominal_chain

    uncompensated = _guard_arm(
        pcm,
        tmp_path / "uncompensated.ts",
        trim_db=trim_db,
        limit_dbtp=pad_ceiling,
        params=params,
        profile=profile,
    )
    assert uncompensated.whole_err_lu is not None

    # Same ceiling, drive returned or not.  The returned drive keeps more of the
    # nominal's loudness: measured 0.1 LU of the 1.205 dB pad on this host, and
    # the sign is the claim -- see the docstring for the magnitude.
    held = padded.whole_err_lu - nominal.whole_err_lu
    lost = uncompensated.whole_err_lu - nominal.whole_err_lu
    assert abs(held) < abs(lost), (held, lost)


def test_a_variant_bitrate_artifact_airs_like_a_nominal_one(
    tmp_path: Path, real_asset: Path
) -> None:
    """U42 item 2: a 256 kbps artifact inside a 192 kbps profile, on the air path.

    The guard reaches for the encoder only when the nominal emit missed the hard
    bound, so the artifact the air path would really be handed is one encoded
    from this hot, already-limited PCM.  What this asserts is that nothing
    downstream treats that artifact differently from a nominal one:

    * the program mux stream-copies it.  ``build_video_from_source_args`` emits
      ``-c:a copy`` (loudness_ride.py:1027), so the program's audio stream
      reports the artifact's own bitrate -- ~256k, NOT the profile's 192k, which
      is what a re-encode would have left there.  Nothing decodes and re-encodes
      the audio on this path.
    * the product's own acceptance surfaces give it the same answers: the
      decodability probe answers ``True`` and
      ``SourcePreparer._prepared_segment_rejection`` (the U36 item 7 gate every
      prepared segment passes) returns ``None``.
    * the loudness gate returns the same verdict, and the same level within the
      gate's own tolerance.

    Neither program is at the -24 LUFS target: the material is hot by
    construction, which is the only condition under which the guard reaches for
    the encoder at all.  The claim is that the bitrate changes neither the
    verdict nor the delivered level -- not that either artifact passes the gate.
    """
    profile = _config().canonical_profile
    params = _guard_params()
    arms = _guard_arms(profile)[:2]
    nominal_label, variant_label = arms[0][0], arms[1][0]
    pcm = _guard_material(tmp_path, amplitude=1.0)

    artifacts: dict[str, Path] = {}
    for label, variant in arms:
        artifact = tmp_path / f"artifact-{label.replace(' ', '_')}.ts"
        lr.run_reencode(
            pcm_path=pcm,
            output_path=artifact,
            trim_db=0.0,
            params=params,
            profile=profile,
            variant=variant,
            timeout_s=_GUARD_TIMEOUT_S,
        )
        artifacts[label] = artifact

    programs: dict[str, Path] = {}
    program_bitrates: dict[str, int] = {}
    artifact_bitrates: dict[str, int] = {}
    for label, _ in arms:
        artifact = artifacts[label]
        segment = EgressSourceSegment(
            label=f"{label} airing", path=str(real_asset), duration_seconds=_ASSET_DURATION_S
        )
        program = tmp_path / f"program-{label.replace(' ', '_')}.ts"
        result = run_ffmpeg(
            lr.build_video_from_source_args(
                source_path=real_asset,
                audio_path=artifact,
                output_path=program,
                segment=segment,
                profile=profile,
            ),
            timeout=_GUARD_TIMEOUT_S,
        )
        assert result.returncode == 0, result.stderr
        programs[label] = program
        artifact_bitrates[label] = _audio_bit_rate_bps(artifact)
        program_bitrates[label] = _audio_bit_rate_bps(program)

    # The two artifacts really are two bitrates, and the nominal's is the profile's.
    assert artifact_bitrates[variant_label] > artifact_bitrates[nominal_label] * 1.2, (
        artifact_bitrates
    )
    assert artifact_bitrates[nominal_label] == pytest.approx(
        profile.audio_bitrate_kbps * 1000, rel=0.1
    ), artifact_bitrates

    # The mux copied the artifact's audio, whatever its bitrate: the program's
    # audio stream reports the artifact's bitrate, and for the variant that is
    # not the profile's 192k (which is what a re-encode would have produced).
    for label, _ in arms:
        assert program_bitrates[label] == pytest.approx(artifact_bitrates[label], rel=0.02), (
            label,
            program_bitrates,
            artifact_bitrates,
        )
    assert program_bitrates[variant_label] > profile.audio_bitrate_kbps * 1000 * 1.2, (
        program_bitrates
    )

    gates = {}
    for label, _ in arms:
        program = programs[label]
        assert probe_has_decodable_stream(program) is True
        emitted = EgressSourceSegment(
            label=f"{label} emitted", path=str(program), duration_seconds=_ASSET_DURATION_S
        )
        assert SourcePreparer._prepared_segment_rejection(emitted) is None
        gates[label] = check_streaming_loudness(
            media_path=program, target_lufs=_TARGET_LUFS, tolerance_lufs=_TOLERANCE_LUFS
        )

    assert gates[variant_label].status == gates[nominal_label].status, gates
    assert gates[nominal_label].measured_lufs is not None, gates
    assert gates[variant_label].measured_lufs is not None, gates
    assert (
        abs(gates[variant_label].measured_lufs - gates[nominal_label].measured_lufs)
        <= _TOLERANCE_LUFS
    ), gates
