# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Readiness derivation + TTL setting (WP-07 / audit ENG-003).

Pure-function coverage of the rule that replaced "a configured live source is
ready because it exists". Every state the plan and the takeover gate branch on
is derived here, so this is where the boundaries get pinned:

* the TTL setting's default, its accepted 5-300s range, and what it does with
  garbage rather than taking the Live Room down;
* ready vs stale exactly at the TTL boundary;
* fail-closed derivation for a partially written or unrecognized row;
* a next action for every state, including the ones that are not failures.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from civiccast.live.readiness import (
    DEFAULT_READINESS_TTL_SECONDS,
    MAX_READINESS_TTL_SECONDS,
    MIN_READINESS_TTL_SECONDS,
    PROBE_STATE_FAILED,
    PROBE_STATE_NEVER_PROBED,
    PROBE_STATE_READY,
    PROBE_STATES,
    READINESS_TTL_ENV_VAR,
    next_action_for,
    observation_age_seconds,
    readiness_state,
    readiness_ttl_seconds,
)

_NOW = datetime(2026, 9, 2, 18, 0, 0, tzinfo=UTC)


class TestTtlSetting:
    def test_default_is_thirty_seconds(self) -> None:
        assert readiness_ttl_seconds({}) == 30
        assert DEFAULT_READINESS_TTL_SECONDS == 30

    def test_accepted_range_is_five_to_three_hundred(self) -> None:
        assert MIN_READINESS_TTL_SECONDS == 5
        assert MAX_READINESS_TTL_SECONDS == 300

    @pytest.mark.parametrize(("raw", "expected"), [("5", 5), ("30", 30), ("300", 300)])
    def test_in_range_values_are_honoured(self, raw: str, expected: int) -> None:
        assert readiness_ttl_seconds({READINESS_TTL_ENV_VAR: raw}) == expected

    @pytest.mark.parametrize(("raw", "expected"), [("1", 5), ("0", 5), ("-9", 5), ("9999", 300)])
    def test_out_of_range_values_clamp_to_the_bound(self, raw: str, expected: int) -> None:
        assert readiness_ttl_seconds({READINESS_TTL_ENV_VAR: raw}) == expected

    @pytest.mark.parametrize("raw", ["", "   ", "soon", "30s", "None"])
    def test_unparseable_values_fall_back_rather_than_raise(self, raw: str) -> None:
        # This is read on the request path that renders the Live Room. A
        # mistyped env var must not take the operator's source list down.
        assert readiness_ttl_seconds({READINESS_TTL_ENV_VAR: raw}) == 30


class TestObservationAge:
    def test_none_when_never_observed(self) -> None:
        assert observation_age_seconds(None, now=_NOW) is None

    def test_age_is_seconds_since_the_observation(self) -> None:
        assert observation_age_seconds(_NOW - timedelta(seconds=12), now=_NOW) == 12.0

    def test_naive_timestamps_are_read_as_utc(self) -> None:
        # SQLite round-trips DateTime(timezone=True) as naive UTC.
        naive = (_NOW - timedelta(seconds=7)).replace(tzinfo=None)
        assert observation_age_seconds(naive, now=_NOW) == 7.0

    def test_a_future_observation_reads_as_just_now_not_as_negative(self) -> None:
        assert observation_age_seconds(_NOW + timedelta(seconds=5), now=_NOW) == 0.0


class TestReadinessState:
    def test_persisted_states_do_not_include_stale(self) -> None:
        # Staleness is a function of the clock. Persisting it would leave a row
        # reading "stale" forever after a successful probe that never rewrote
        # the column.
        assert PROBE_STATES == (PROBE_STATE_NEVER_PROBED, PROBE_STATE_READY, PROBE_STATE_FAILED)

    def test_never_probed(self) -> None:
        assert readiness_state(PROBE_STATE_NEVER_PROBED, None, ttl_seconds=30, now=_NOW) == (
            "never_probed"
        )

    def test_failed_stays_failed_regardless_of_age(self) -> None:
        assert (
            readiness_state(
                PROBE_STATE_FAILED, _NOW - timedelta(seconds=1), ttl_seconds=30, now=_NOW
            )
            == "failed"
        )

    def test_ready_inside_the_ttl(self) -> None:
        assert (
            readiness_state(
                PROBE_STATE_READY, _NOW - timedelta(seconds=29), ttl_seconds=30, now=_NOW
            )
            == "ready"
        )

    def test_ready_exactly_at_the_ttl_boundary_is_still_ready(self) -> None:
        assert (
            readiness_state(
                PROBE_STATE_READY, _NOW - timedelta(seconds=30), ttl_seconds=30, now=_NOW
            )
            == "ready"
        )

    def test_one_second_past_the_ttl_is_stale(self) -> None:
        assert (
            readiness_state(
                PROBE_STATE_READY, _NOW - timedelta(seconds=31), ttl_seconds=30, now=_NOW
            )
            == "stale"
        )

    def test_ready_without_a_timestamp_fails_closed(self) -> None:
        # A partially written row must not read as ready.
        assert readiness_state(PROBE_STATE_READY, None, ttl_seconds=30, now=_NOW) == "never_probed"

    @pytest.mark.parametrize("value", [None, "", "unknown", "READY", "stale"])
    def test_unrecognized_probe_state_fails_closed(self, value: str | None) -> None:
        assert (
            readiness_state(value, _NOW - timedelta(seconds=1), ttl_seconds=30, now=_NOW)
            == "never_probed"
        )


class TestNextAction:
    def test_every_state_gets_a_concrete_next_action(self) -> None:
        for state in ("ready", "stale", "failed", "never_probed"):
            action = next_action_for(state, source_name="Council Cam")  # type: ignore[arg-type]
            assert "Council Cam" in action
            assert action.endswith(".")

    def test_failed_carries_the_safe_reason_forward(self) -> None:
        action = next_action_for(
            "failed", source_name="Council Cam", detail="Connection refused by the encoder"
        )
        assert "Connection refused by the encoder" in action
        assert "Check source" in action

    def test_failed_without_a_reason_still_says_what_to_do(self) -> None:
        action = next_action_for("failed", source_name="Council Cam", detail="   ")
        assert "Check source" in action

    def test_ready_does_not_ask_the_operator_to_do_anything_first(self) -> None:
        assert "take air" in next_action_for("ready", source_name="Council Cam")
