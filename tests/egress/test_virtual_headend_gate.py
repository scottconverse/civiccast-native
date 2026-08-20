# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import pytest

from tests.egress.virtual_headend_gate import (
    ExpectedOnAirWindow,
    ObservedHeadendSample,
    analyze_virtual_headend_output,
)


def _timeline() -> tuple[ExpectedOnAirWindow, ...]:
    return (
        ExpectedOnAirWindow(
            start_seconds=0.0,
            end_seconds=4.0,
            source_label="Program 001",
            marker="SEGMENT 001",
        ),
        ExpectedOnAirWindow(
            start_seconds=4.0,
            end_seconds=8.0,
            source_label="Fallback slate",
            marker="SLATE",
            allow_freeze=True,
            allow_silence=True,
        ),
        ExpectedOnAirWindow(
            start_seconds=8.0,
            end_seconds=12.0,
            source_label="Program 002",
            marker="SEGMENT 002",
        ),
    )


def _good_samples() -> tuple[ObservedHeadendSample, ...]:
    return (
        ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
        ObservedHeadendSample(pts_seconds=1.0, marker="SEGMENT 001"),
        ObservedHeadendSample(pts_seconds=2.0, marker="SEGMENT 001"),
        ObservedHeadendSample(pts_seconds=3.0, marker="SEGMENT 001"),
        ObservedHeadendSample(pts_seconds=4.0, marker="SLATE", frozen=True, audio_rms=0.0),
        ObservedHeadendSample(pts_seconds=5.0, marker="SLATE", frozen=True, audio_rms=0.0),
        ObservedHeadendSample(pts_seconds=6.0, marker="SLATE", frozen=True, audio_rms=0.0),
        ObservedHeadendSample(pts_seconds=7.0, marker="SLATE", frozen=True, audio_rms=0.0),
        ObservedHeadendSample(pts_seconds=8.0, marker="SEGMENT 002"),
        ObservedHeadendSample(pts_seconds=9.0, marker="SEGMENT 002"),
        ObservedHeadendSample(pts_seconds=10.0, marker="SEGMENT 002"),
        ObservedHeadendSample(pts_seconds=11.0, marker="SEGMENT 002"),
    )


def test_virtual_headend_analyzer_is_schedule_aware_for_legitimate_slate() -> None:
    report = analyze_virtual_headend_output(
        expected_timeline=_timeline(),
        samples=_good_samples(),
    )

    assert report.status == "PASS"
    assert report.boundary_count == 2
    assert report.findings == ()
    assert "does not validate a real cable headend" in report.not_claimed[0]


def test_analyzer_allows_previous_marker_only_during_transition_grace() -> None:
    report = analyze_virtual_headend_output(
        expected_timeline=_timeline(),
        samples=(
            ObservedHeadendSample(pts_seconds=3.0, marker="SEGMENT 001"),
            ObservedHeadendSample(pts_seconds=4.0, marker="SEGMENT 001"),
            ObservedHeadendSample(pts_seconds=4.1, marker="SLATE", frozen=True, audio_rms=0.0),
        ),
    )

    assert report.status == "PASS"
    assert report.findings == ()


def test_analyzer_rejects_previous_marker_after_transition_grace() -> None:
    report = analyze_virtual_headend_output(
        expected_timeline=_timeline(),
        samples=(
            ObservedHeadendSample(pts_seconds=3.0, marker="SEGMENT 001"),
            ObservedHeadendSample(pts_seconds=4.6, marker="SEGMENT 001"),
        ),
    )

    assert report.status == "FAIL"
    assert "MARKER_MISMATCH" in {finding.code for finding in report.findings}


def test_analyzer_allows_receiver_tail_inside_tail_grace() -> None:
    report = analyze_virtual_headend_output(
        expected_timeline=_timeline(),
        samples=(
            ObservedHeadendSample(pts_seconds=11.0, marker="SEGMENT 002"),
            ObservedHeadendSample(pts_seconds=12.1, marker="UNKNOWN"),
        ),
    )

    assert report.status == "PASS"
    assert report.findings == ()


def test_analyzer_rejects_receiver_tail_after_tail_grace() -> None:
    report = analyze_virtual_headend_output(
        expected_timeline=_timeline(),
        samples=(
            ObservedHeadendSample(pts_seconds=11.0, marker="SEGMENT 002"),
            ObservedHeadendSample(pts_seconds=12.5, marker="UNKNOWN"),
        ),
    )

    assert report.status == "FAIL"
    assert "UNEXPECTED_OUTPUT_OUTSIDE_SCHEDULE" in {finding.code for finding in report.findings}


@pytest.mark.parametrize(
    ("name", "samples", "expected_code"),
    [
        (
            "black gap",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=1.0, marker="SEGMENT 001", black=True),
                ObservedHeadendSample(pts_seconds=2.0, marker="SEGMENT 001", black=True),
            ),
            "UNEXPECTED_BLACK_VIDEO",
        ),
        (
            "codec switch",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(
                    pts_seconds=1.0,
                    marker="SEGMENT 001",
                    profile_id="wrong-profile",
                ),
            ),
            "CODEC_OR_PROFILE_SWITCH",
        ),
        (
            "connection drop",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=1.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=4.0, marker="SLATE", connected=False),
            ),
            "CONNECTION_DROP_OR_DEAD_AIR",
        ),
        (
            "audio silence",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=1.0, marker="SEGMENT 001", audio_rms=0.0),
            ),
            "UNEXPECTED_AUDIO_SILENCE",
        ),
        (
            "output pts discontinuity",
            (
                ObservedHeadendSample(pts_seconds=0.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=1.0, marker="SEGMENT 001"),
                ObservedHeadendSample(pts_seconds=0.5, marker="SEGMENT 001"),
            ),
            "OUTPUT_PTS_DISCONTINUITY",
        ),
    ],
)
def test_negative_controls_are_rejected(
    name: str,
    samples: tuple[ObservedHeadendSample, ...],
    expected_code: str,
) -> None:
    report = analyze_virtual_headend_output(
        expected_timeline=_timeline(),
        samples=samples,
    )

    assert report.status == "FAIL", name
    assert expected_code in {finding.code for finding in report.findings}
