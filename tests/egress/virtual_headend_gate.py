# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Test-only virtual-headend analyzer primitives for the E.2 gate.

This module intentionally lives under ``tests/``. It is not station runtime
code; it is the first slice of the hostile receiver gate that will judge the
shipping playout supervisor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

VIRTUAL_HEADEND_NOT_CLAIMED: tuple[str, ...] = (
    "This report does not validate a real cable headend.",
    "This report does not validate QAM modulation, SDI output, EAS, or a specific operator box.",
    "This report validates only CivicCast's software handoff boundary for the tested profile.",
)


@dataclass(frozen=True)
class ExpectedOnAirWindow:
    """Expected content for a bounded interval in the scenario timeline."""

    start_seconds: float
    end_seconds: float
    source_label: str
    marker: str
    profile_id: str = "canonical-v1"
    allow_black: bool = False
    allow_silence: bool = False
    allow_freeze: bool = False

    def contains(self, pts_seconds: float) -> bool:
        return self.start_seconds <= pts_seconds < self.end_seconds


@dataclass(frozen=True)
class ObservedHeadendSample:
    """One decoded observation on the encoder output timeline."""

    pts_seconds: float
    marker: str
    profile_id: str = "canonical-v1"
    black: bool = False
    frozen: bool = False
    audio_rms: float = 0.50
    connected: bool = True


@dataclass(frozen=True)
class VirtualHeadendFinding:
    """One hostile-headend analyzer finding."""

    code: str
    pts_seconds: float | None
    detail: str
    expected_source_label: str | None = None
    observed_marker: str | None = None


@dataclass(frozen=True)
class VirtualHeadendReport:
    """Machine-readable E.2 analyzer report slice."""

    status: Literal["PASS", "FAIL"]
    boundary_count: int
    findings: tuple[VirtualHeadendFinding, ...]
    not_claimed: tuple[str, ...] = VIRTUAL_HEADEND_NOT_CLAIMED


def analyze_virtual_headend_output(
    *,
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    samples: tuple[ObservedHeadendSample, ...],
    max_output_gap_seconds: float = 1.25,
    silence_threshold_rms: float = 0.01,
    marker_transition_grace_seconds: float = 0.50,
    tail_grace_seconds: float = 0.25,
) -> VirtualHeadendReport:
    """Classify received output samples against a schedule-aware timeline.

    The continuity contract is the encoder's received output timeline. The
    caller must pass samples in decode order; this function rejects timestamp
    resets/discontinuities on that output timeline while allowing legitimate
    static or quiet windows when the expected schedule says they are allowed.
    """

    findings: list[VirtualHeadendFinding] = []
    previous_pts: float | None = None
    for sample in samples:
        expected = _expected_at(expected_timeline, sample.pts_seconds)
        if previous_pts is not None:
            if sample.pts_seconds <= previous_pts:
                findings.append(
                    VirtualHeadendFinding(
                        code="OUTPUT_PTS_DISCONTINUITY",
                        pts_seconds=sample.pts_seconds,
                        detail=(
                            f"output PTS moved from {previous_pts:.3f}s to "
                            f"{sample.pts_seconds:.3f}s"
                        ),
                    )
                )
            elif sample.pts_seconds - previous_pts > max_output_gap_seconds:
                findings.append(
                    VirtualHeadendFinding(
                        code="CONNECTION_DROP_OR_DEAD_AIR",
                        pts_seconds=sample.pts_seconds,
                        detail=(
                            f"output timeline gap was {sample.pts_seconds - previous_pts:.3f}s"
                        ),
                        expected_source_label=expected.source_label if expected else None,
                        observed_marker=sample.marker,
                    )
                )
        previous_pts = sample.pts_seconds

        if not sample.connected:
            findings.append(
                VirtualHeadendFinding(
                    code="CONNECTION_DROP_OR_DEAD_AIR",
                    pts_seconds=sample.pts_seconds,
                    detail="receiver reported a closed or missing connection",
                    expected_source_label=expected.source_label if expected else None,
                    observed_marker=sample.marker,
                )
            )
        if expected is None:
            if _within_tail_grace(
                expected_timeline=expected_timeline,
                sample=sample,
                tail_grace_seconds=tail_grace_seconds,
            ):
                continue
            findings.append(
                VirtualHeadendFinding(
                    code="UNEXPECTED_OUTPUT_OUTSIDE_SCHEDULE",
                    pts_seconds=sample.pts_seconds,
                    detail="received media outside the expected scenario timeline",
                    observed_marker=sample.marker,
                )
            )
            continue
        if sample.profile_id != expected.profile_id:
            findings.append(
                VirtualHeadendFinding(
                    code="CODEC_OR_PROFILE_SWITCH",
                    pts_seconds=sample.pts_seconds,
                    detail=f"expected {expected.profile_id!r}, observed {sample.profile_id!r}",
                    expected_source_label=expected.source_label,
                    observed_marker=sample.marker,
                )
            )
        if sample.marker != expected.marker and not _within_marker_transition_grace(
            expected_timeline=expected_timeline,
            expected=expected,
            sample=sample,
            marker_transition_grace_seconds=marker_transition_grace_seconds,
        ):
            findings.append(
                VirtualHeadendFinding(
                    code="MARKER_MISMATCH",
                    pts_seconds=sample.pts_seconds,
                    detail=f"expected marker {expected.marker!r}, observed {sample.marker!r}",
                    expected_source_label=expected.source_label,
                    observed_marker=sample.marker,
                )
            )
        if sample.black and not expected.allow_black:
            findings.append(
                VirtualHeadendFinding(
                    code="UNEXPECTED_BLACK_VIDEO",
                    pts_seconds=sample.pts_seconds,
                    detail="black video was not expected for this scheduled source",
                    expected_source_label=expected.source_label,
                    observed_marker=sample.marker,
                )
            )
        if sample.frozen and not expected.allow_freeze:
            findings.append(
                VirtualHeadendFinding(
                    code="UNEXPECTED_FREEZE",
                    pts_seconds=sample.pts_seconds,
                    detail="frozen video was not expected for this scheduled source",
                    expected_source_label=expected.source_label,
                    observed_marker=sample.marker,
                )
            )
        if sample.audio_rms <= silence_threshold_rms and not expected.allow_silence:
            findings.append(
                VirtualHeadendFinding(
                    code="UNEXPECTED_AUDIO_SILENCE",
                    pts_seconds=sample.pts_seconds,
                    detail="audio silence was not expected for this scheduled source",
                    expected_source_label=expected.source_label,
                    observed_marker=sample.marker,
                )
            )

    return VirtualHeadendReport(
        status="FAIL" if findings else "PASS",
        boundary_count=max(0, len(expected_timeline) - 1),
        findings=tuple(findings),
    )


def _expected_at(
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    pts_seconds: float,
) -> ExpectedOnAirWindow | None:
    return next(
        (window for window in expected_timeline if window.contains(pts_seconds)),
        None,
    )


def _within_marker_transition_grace(
    *,
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    expected: ExpectedOnAirWindow,
    sample: ObservedHeadendSample,
    marker_transition_grace_seconds: float,
) -> bool:
    if marker_transition_grace_seconds <= 0:
        return False
    if sample.pts_seconds - expected.start_seconds > marker_transition_grace_seconds:
        return False
    previous = _previous_expected(expected_timeline, expected)
    return previous is not None and sample.marker == previous.marker


def _previous_expected(
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    expected: ExpectedOnAirWindow,
) -> ExpectedOnAirWindow | None:
    previous: ExpectedOnAirWindow | None = None
    for window in expected_timeline:
        if window is expected:
            return previous
        previous = window
    return None


def _within_tail_grace(
    *,
    expected_timeline: tuple[ExpectedOnAirWindow, ...],
    sample: ObservedHeadendSample,
    tail_grace_seconds: float,
) -> bool:
    if tail_grace_seconds <= 0 or not expected_timeline:
        return False
    final_end = max(window.end_seconds for window in expected_timeline)
    return final_end <= sample.pts_seconds <= final_end + tail_grace_seconds
