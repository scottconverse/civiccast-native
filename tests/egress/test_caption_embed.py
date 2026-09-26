# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.captions.models import CaptionCue
from civiccast.egress import caption_embed
from civiccast.egress.caption_embed import (
    _ACTIVE_VTT_READ_ATTEMPTS,
    _ACTIVE_VTT_READ_BACKOFF_SECONDS,
    CAPTION_EMBED_PROOF_BOUNDARY,
    PassThroughCaptionEmbedder,
    SidecarCaptionEmbedder,
    evaluate_caption_decode_back,
    load_caption_cues_from_timed_text,
    parse_caption_cues_from_timed_text,
)


def _cue(
    cue_id: str,
    *,
    start: float = 1.0,
    end: float = 2.0,
    text: str = "Motion carries.",
) -> CaptionCue:
    return CaptionCue(
        cue_id=cue_id,
        start_seconds=start,
        end_seconds=end,
        text=text,
        confidence=0.99,
    )


def test_pass_through_caption_embedder_keeps_status_not_verified() -> None:
    plan = PassThroughCaptionEmbedder().build_plan(
        channel_id="gov",
        cues=[_cue("cue-1")],
    )

    assert plan.status == "not-verified"
    assert plan.mode == "passthrough"
    assert plan.cue_count == 1
    assert plan.ffmpeg_args == []
    assert plan.proof_boundary == CAPTION_EMBED_PROOF_BOUNDARY
    assert any("does not claim CEA-708" in claim for claim in plan.not_claimed)


def test_sidecar_caption_embedder_builds_ffmpeg_plan_without_claiming_on(
    tmp_path: Path,
) -> None:
    sidecar = tmp_path / "captions.vtt"
    sidecar.write_text("WEBVTT\n", encoding="utf-8")

    plan = SidecarCaptionEmbedder(sidecar_path=sidecar).build_plan(
        channel_id="gov",
        cues=[_cue("cue-1")],
    )

    assert plan.status == "not-verified"
    assert plan.mode == "sidecar"
    assert plan.cue_count == 1
    assert plan.input_args == ["-i", str(sidecar)]
    assert plan.stream_args == ["-map", "1:s:0?", "-c:s", "copy"]
    assert plan.ffmpeg_args == [*plan.input_args, *plan.stream_args]
    assert any("captions survived" in claim for claim in plan.not_claimed)


def test_caption_decode_back_pass_flips_caption_status_on(tmp_path: Path) -> None:
    proof = evaluate_caption_decode_back(
        channel_id="gov",
        emitted_stream_path=tmp_path / "egress.ts",
        expected_cues=[_cue("cue-1"), _cue("cue-2", start=3.0, end=4.0, text="Second cue.")],
        decoded_cues=[
            _cue("decoded-1", start=1.1, end=2.1, text=" motion   carries. "),
            _cue("decoded-2", start=3.2, end=4.1, text="Second cue."),
        ],
        decoder_name="ffmpeg-cc-decode",
    )

    assert proof.status == "PASS"
    assert proof.caption_status == "on"
    assert proof.blocker is None
    assert proof.expected_cue_count == 2
    assert proof.decoded_cue_count == 2
    assert proof.matched_cue_count == 2
    assert proof.max_timing_delta_seconds == pytest.approx(0.2)


def test_caption_decode_back_mismatch_keeps_status_not_verified(tmp_path: Path) -> None:
    proof = evaluate_caption_decode_back(
        channel_id="gov",
        emitted_stream_path=tmp_path / "egress.ts",
        expected_cues=[_cue("cue-1")],
        decoded_cues=[_cue("decoded-1", text="Different caption.")],
        decoder_name="ffmpeg-cc-decode",
    )

    assert proof.status == "FAIL"
    assert proof.caption_status == "not-verified"
    assert proof.blocker == "EGRESS_CAPTION_DECODE_BACK_MISMATCH"


def test_caption_decode_back_requires_expected_cues(tmp_path: Path) -> None:
    proof = evaluate_caption_decode_back(
        channel_id="gov",
        emitted_stream_path=tmp_path / "egress.ts",
        expected_cues=[],
        decoded_cues=[_cue("decoded-1")],
        decoder_name="ffmpeg-cc-decode",
    )

    assert proof.status == "FAIL"
    assert proof.caption_status == "not-verified"
    assert proof.blocker == "EGRESS_CAPTION_DECODE_BACK_NO_EXPECTED_CUES"


def test_parse_caption_cues_from_webvtt_and_srt_text() -> None:
    cues = parse_caption_cues_from_timed_text(
        """WEBVTT

cue-a
00:00:01.000 --> 00:00:02.250
Motion <i>carries</i>.

2
00:00:03,000 --> 00:00:04,500
Second cue.
""",
        source_id="decoded-captions",
    )

    assert [cue.cue_id for cue in cues] == ["decoded-captions-cue-a", "decoded-captions-000002"]
    assert cues[0].start_seconds == 1.0
    assert cues[0].end_seconds == 2.25
    assert cues[0].text == "Motion carries."
    assert cues[1].start_seconds == 3.0
    assert cues[1].end_seconds == 4.5


def test_parse_caption_cues_strips_ass_position_tags_from_real_ffmpeg_srt() -> None:
    """ffmpeg's eia_608/cc_dec CEA-608/708 decoder always wraps decoded SRT text in
    an ASS override block (``{\\an7}``) plus a ``<font>`` tag for on-screen position
    -- discovered building the CEA-708 decode-back fixture (2026-08-25): the
    pre-existing decode-back proof had never actually been run against real
    ffmpeg-decoded closed-caption output, only hand-written SRT text in tests, so
    this residual tag would have made every real decode-back comparison mismatch
    even when captions embedded and decoded correctly."""
    cues = parse_caption_cues_from_timed_text(
        '1\n00:00:00,000 --> 00:00:01,600\n<font face="Monospace">{\\an7}CIVICCAST CEA708 TEST.</font>\n',
        source_id="ffmpeg-subcc",
    )
    assert [cue.text for cue in cues] == ["CIVICCAST CEA708 TEST."]


def test_parse_caption_cues_skips_degenerate_timings_without_aborting_the_scan() -> None:
    """ffmpeg's CEA-608/708 decoders can emit instantaneous caption events
    (``00:00:02,000 --> 00:00:02,000``), which are legitimate output but are not
    valid cues. The parser must skip them instead of feeding them to the
    CaptionCue validator, where one ValidationError would abort the whole proof
    scan rather than isolating the bad cue."""
    cues = parse_caption_cues_from_timed_text(
        """1
00:00:01,000 --> 00:00:02,500
First valid cue.

2
00:00:02,000 --> 00:00:02,000
Instantaneous cue.

3
00:00:03,000 --> 00:00:02,000
Reversed cue.

4
00:00:04,000 --> 00:00:05,500
Second valid cue.
""",
        source_id="ffmpeg-subcc",
    )

    assert [cue.text for cue in cues] == ["First valid cue.", "Second valid cue."]
    assert [cue.start_seconds for cue in cues] == [1.0, 4.0]
    assert [cue.end_seconds for cue in cues] == [2.5, 5.5]


# --- U21 B3: reading a live sidecar while the tap republishes it --------------------
#
# The caption tap publishes ``captions/active.vtt`` with an atomic replace
# (``LiveWebVttPublisher`` -> ``live_sidecar._atomic_write_text``). On Windows a
# reader whose open lands inside that rename window is refused with
# ``PermissionError`` rather than serialized against it, which is the live
# 23:44:45 / 23:45:29 defect: the file was there, being swapped, and the read
# failed. These tests pin the bounded retry and, just as importantly, its bound.


_WEBVTT = "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nMotion carries.\n"


def _sharing_violation() -> PermissionError:
    return PermissionError(
        32, "The process cannot access the file because it is being used by another process"
    )


def test_load_caption_cues_retries_a_sharing_violation_and_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sidecar = tmp_path / "active.vtt"
    sidecar.write_text(_WEBVTT, encoding="utf-8")
    real_read_text = Path.read_text
    attempts: list[Path] = []

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        attempts.append(self)
        if len(attempts) < _ACTIVE_VTT_READ_ATTEMPTS:
            raise _sharing_violation()
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", read_text)
    sleeps: list[float] = []
    monkeypatch.setattr(caption_embed.time, "sleep", sleeps.append)

    cues = load_caption_cues_from_timed_text(sidecar, source_id="gov")

    assert [cue.text for cue in cues] == ["Motion carries."]
    assert len(attempts) == _ACTIVE_VTT_READ_ATTEMPTS
    assert attempts == [sidecar] * _ACTIVE_VTT_READ_ATTEMPTS
    assert sleeps == [_ACTIVE_VTT_READ_BACKOFF_SECONDS] * (_ACTIVE_VTT_READ_ATTEMPTS - 1)


def test_load_caption_cues_raises_a_permanent_sharing_violation_instead_of_reporting_no_cues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retry is bounded, and a permanent refusal must not read as "no cues"."""
    sidecar = tmp_path / "active.vtt"
    sidecar.write_text(_WEBVTT, encoding="utf-8")
    attempts: list[Path] = []

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        attempts.append(self)
        raise _sharing_violation()

    monkeypatch.setattr(Path, "read_text", read_text)
    sleeps: list[float] = []
    monkeypatch.setattr(caption_embed.time, "sleep", sleeps.append)

    with pytest.raises(PermissionError) as raised:
        load_caption_cues_from_timed_text(sidecar, source_id="gov")

    assert "being used by another process" in str(raised.value)
    assert len(attempts) == _ACTIVE_VTT_READ_ATTEMPTS
    assert sleeps == [_ACTIVE_VTT_READ_BACKOFF_SECONDS] * (_ACTIVE_VTT_READ_ATTEMPTS - 1)


def test_load_caption_cues_does_not_retry_a_non_sharing_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a sharing violation is a one-rename-wide race. Any other read failure
    is a real answer about the file and must surface on the first attempt."""
    sidecar = tmp_path / "active.vtt"
    attempts: list[Path] = []

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        attempts.append(self)
        raise IsADirectoryError(13, "Permission denied")

    monkeypatch.setattr(Path, "read_text", read_text)
    sleeps: list[float] = []
    monkeypatch.setattr(caption_embed.time, "sleep", sleeps.append)

    with pytest.raises(IsADirectoryError):
        load_caption_cues_from_timed_text(sidecar, source_id="gov")

    assert len(attempts) == 1
    assert sleeps == []


def test_parse_caption_cues_reads_sidecar_clock_hours_past_one_hundred(tmp_path: Path) -> None:
    """A station runs 24/7 and the live sidecar's program clock is an absolute,
    unbounded second count -- ``format_webvtt_timestamp`` renders it with
    ``divmod(total_ms, 3_600_000)``, so the hours field is only two digits wide
    for the first 100 hours of uptime (U46, 2026-09-26).

    The measured live failure: public's sidecar at 112:59:50.000 matched 0 of its
    2088 timing windows, ``load_caption_cues_from_timed_text`` returned 0 cues,
    and the channel emitted a caption-free stream while its sidecar grew. The
    same defect sat one step behind on government (87 h) and education (91 h).
    """
    sidecar = tmp_path / "active.vtt"
    sidecar.write_text(
        """WEBVTT

public-cue-101697
112:59:50.000 --> 112:59:54.240
Good evening, the public meeting is called to order.

public-cue-101698
116:14:40.310 --> 116:14:41.450
Motion carries.
""",
        encoding="utf-8",
    )

    cues = load_caption_cues_from_timed_text(sidecar, source_id="public")

    assert [cue.cue_id for cue in cues] == ["public-public-cue-101697", "public-public-cue-101698"]
    assert cues[0].start_seconds == 112 * 3600 + 59 * 60 + 50.0
    assert cues[0].end_seconds == 112 * 3600 + 59 * 60 + 54.24
    assert cues[1].start_seconds == 116 * 3600 + 14 * 60 + 40.310
    assert cues[1].end_seconds == 116 * 3600 + 14 * 60 + 41.450
    assert cues[1].text == "Motion carries."


def test_parse_caption_cues_crosses_the_hundred_hour_boundary() -> None:
    """The cliff is exact: 99:59:59 matches, 100:00:00 did not. Ninety-nine hours
    is the last sidecar state that produced embedded captions; one second later
    the channel went dark for viewers with no error anywhere."""
    cues = parse_caption_cues_from_timed_text(
        """WEBVTT

cue-3580
99:59:59.000 --> 99:59:59.920
Last cue before the boundary.

cue-3600
100:00:00.000 --> 100:00:00.920
First cue past the boundary.
""",
        source_id="public",
    )

    assert [cue.text for cue in cues] == [
        "Last cue before the boundary.",
        "First cue past the boundary.",
    ]
    assert cues[0].start_seconds == 359999.0
    assert cues[1].start_seconds == 360000.0


def test_parse_caption_cues_still_reads_two_digit_hours() -> None:
    """The unbounded hours field must not regress the ordinary two-digit form
    (both the WebVTT ``hh:mm:ss.mmm`` and the SRT ``h:mm:ss,mmm`` spellings)."""
    cues = parse_caption_cues_from_timed_text(
        """WEBVTT

cue-a
87:19:25.000 --> 87:19:29.240
Government at hour eighty-seven.

2
1:02:03,400 --> 1:02:04,500
SRT single-digit hour.
""",
        source_id="decoded-captions",
    )

    assert [cue.text for cue in cues] == [
        "Government at hour eighty-seven.",
        "SRT single-digit hour.",
    ]
    assert cues[0].start_seconds == 87 * 3600 + 19 * 60 + 25.0
    assert cues[1].start_seconds == 3723.4
