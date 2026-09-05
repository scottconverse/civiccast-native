# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the caption tap's per-channel overload backoff.

The state machine is what makes "captions are best effort, playout wins"
true on a station that cannot transcribe in real time, so it is tested on
its own, with an injected clock and no filesystem.
"""

from __future__ import annotations

import pytest

from civiccast.captions.tap_backoff import (
    DEFAULT_BASE_BACKOFF_SECONDS,
    DEFAULT_MAX_BACKOFF_SECONDS,
    CaptionBackoffPolicy,
)


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _policy(clock: _FakeClock, **kwargs: float | int) -> CaptionBackoffPolicy:
    return CaptionBackoffPolicy(monotonic=clock, **kwargs)  # type: ignore[arg-type]


class TestCaptionBackoffPolicy:
    def test_an_unseen_channel_is_never_paused(self) -> None:
        policy = _policy(_FakeClock())

        assert policy.is_paused("government") is False
        assert policy.remaining_seconds("government") == 0.0
        assert policy.state("government").consecutive_overloads == 0

    def test_the_first_overload_opens_the_base_window(self) -> None:
        clock = _FakeClock()
        policy = _policy(clock, base_seconds=60.0)

        state = policy.record_overload("government")

        assert state.consecutive_overloads == 1
        assert state.pause_seconds == 60.0
        assert policy.is_paused("government") is True
        assert policy.remaining_seconds("government") == 60.0

    def test_consecutive_overloads_double_the_window_up_to_the_ceiling(self) -> None:
        clock = _FakeClock()
        policy = _policy(clock, base_seconds=60.0, max_seconds=300.0)

        observed = []
        for _ in range(6):
            state = policy.record_overload("government")
            observed.append(state.pause_seconds)
            clock.advance(state.pause_seconds + 1.0)

        assert observed == [60.0, 120.0, 240.0, 300.0, 300.0, 300.0]

    def test_the_pause_expires_on_the_monotonic_clock(self) -> None:
        clock = _FakeClock()
        policy = _policy(clock, base_seconds=60.0)
        policy.record_overload("government")

        clock.advance(59.9)
        assert policy.is_paused("government") is True

        clock.advance(0.2)
        assert policy.is_paused("government") is False
        assert policy.remaining_seconds("government") == 0.0

    def test_a_single_good_scan_does_not_forgive_the_escalation(self) -> None:
        """A channel that flaps must keep escalating.

        Resetting on the first within-capacity scan is exactly how a station
        that is only intermittently able to keep up would end up back on the
        base delay forever -- i.e. back to the every-30-seconds overload churn
        this policy exists to end.
        """

        clock = _FakeClock()
        policy = _policy(clock, base_seconds=60.0, recovery_scans=3)
        policy.record_overload("government")
        clock.advance(61.0)

        policy.record_within_capacity("government")
        assert policy.state("government").consecutive_overloads == 1

        # The next overload escalates from 1, not from zero.
        assert policy.record_overload("government").pause_seconds == 120.0

    def test_enough_healthy_scans_forgive_the_channel(self) -> None:
        clock = _FakeClock()
        policy = _policy(clock, base_seconds=60.0, recovery_scans=3)
        policy.record_overload("government")
        clock.advance(61.0)

        for _ in range(3):
            policy.record_within_capacity("government")

        assert policy.state("government").consecutive_overloads == 0
        assert policy.record_overload("government").pause_seconds == 60.0

    def test_draining_inside_a_pause_window_does_not_count_as_recovery(self) -> None:
        clock = _FakeClock()
        policy = _policy(clock, base_seconds=60.0, recovery_scans=2)
        policy.record_overload("government")

        for _ in range(10):
            clock.advance(2.0)
            policy.record_within_capacity("government")

        assert policy.is_paused("government") is True
        assert policy.state("government").healthy_scans == 0

    def test_forget_clears_a_channel_that_went_off_air(self) -> None:
        clock = _FakeClock()
        policy = _policy(clock, base_seconds=60.0)
        policy.record_overload("government")

        policy.forget("government")

        assert policy.is_paused("government") is False
        assert policy.record_overload("government").pause_seconds == 60.0

    def test_channels_back_off_independently(self) -> None:
        clock = _FakeClock()
        policy = _policy(clock, base_seconds=60.0)

        policy.record_overload("government")

        assert policy.is_paused("government") is True
        assert policy.is_paused("education") is False

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"base_seconds": 0.0}, "base_seconds"),
            ({"base_seconds": 60.0, "max_seconds": 30.0}, "max_seconds"),
            ({"recovery_scans": 0}, "recovery_scans"),
        ],
    )
    def test_nonsense_configuration_fails_fast(
        self,
        kwargs: dict[str, float | int],
        message: str,
    ) -> None:
        with pytest.raises(ValueError, match=message):
            CaptionBackoffPolicy(**kwargs)  # type: ignore[arg-type]

    def test_shipped_defaults_are_the_documented_ones(self) -> None:
        policy = CaptionBackoffPolicy()

        assert policy.base_seconds == DEFAULT_BASE_BACKOFF_SECONDS == 60.0
        assert policy.max_seconds == DEFAULT_MAX_BACKOFF_SECONDS == 900.0
