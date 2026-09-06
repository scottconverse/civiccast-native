# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the gi-free reload-switch decision logic (B3 fix).

``civiccast.egress.gst.engine`` cannot be imported at all without ``gi`` + a
real GStreamer install (module-level ``gi.require_version``/``Gst.init``), so
the decision logic that determines WHETHER a content-reload defers its
selector switch, and WHEN a rollover should trigger, lives in
``civiccast.egress.gst.reload_policy`` instead -- gi-free, importable and
testable on a bare checkout. This mirrors the existing pattern for
``decode_policy.py`` (see its module docstring / this suite's sibling
``test_gst_decode_policy.py`` if present).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from civiccast.egress.gst.reload_policy import (
    DEFERRED_SWITCH_SUFFIX,
    IMMEDIATE_SWITCH_SUFFIX,
    reload_id_from_sidecar_path,
    reload_sidecar_suffix,
    reload_switch_is_deferred,
    rollover_trigger_at,
    should_defer_switch,
)

_NOW = datetime(2026, 6, 12, 6, 0, tzinfo=UTC)


class TestShouldDeferSwitch:
    """Only an automation-driven extension of an already-ON_AIR plan, with no
    operator override active, may defer the selector switch to the outgoing
    leg's own EOS -- everything else must cut in immediately."""

    def test_on_air_with_no_override_defers(self) -> None:
        assert should_defer_switch(previous_state="ON_AIR", manual_override_active=False) is True

    def test_fallback_slate_gap_replan_never_defers(self) -> None:
        # Issue #157: filler must be interrupted the moment a due program is
        # ready -- it must never wait out the rest of its own duration.
        assert (
            should_defer_switch(previous_state="FALLBACK_SLATE", manual_override_active=False)
            is False
        )

    def test_live_takeover_never_defers_even_if_previously_on_air(self) -> None:
        # request_live_takeover sets the override BEFORE calling _request_reload,
        # so this is the exact shape _try_content_reload observes for a takeover.
        assert should_defer_switch(previous_state="ON_AIR", manual_override_active=True) is False

    def test_forced_slate_never_defers_even_if_previously_on_air(self) -> None:
        assert should_defer_switch(previous_state="ON_AIR", manual_override_active=True) is False

    def test_no_prior_state_never_defers(self) -> None:
        assert should_defer_switch(previous_state=None, manual_override_active=False) is False

    def test_transitioning_or_starting_never_defers(self) -> None:
        for state in ("TRANSITIONING", "STARTING", "STOPPED", "ERROR", "DRAINING"):
            assert should_defer_switch(previous_state=state, manual_override_active=False) is False


class TestReloadSidecarSuffix:
    """The switch-mode flag rides the one-shot reload sidecar's FILENAME (not a
    new control-line token): ``control.parse_control_line``'s ``reload <path>``
    grammar takes the entire line remainder as the path, so a wire-format
    version bump would be needed for a new token, while the path itself is a
    free-form string already unique per reload (ENG-005, a uuid4 hex)."""

    def test_deferred_suffix_round_trips(self) -> None:
        suffix = reload_sidecar_suffix(switch_at_end_of_current=True)
        assert suffix == DEFERRED_SWITCH_SUFFIX
        path = f"C:/work/ch1/playout-graph.reload.abc123{suffix}"
        assert reload_switch_is_deferred(path) is True

    def test_immediate_suffix_round_trips(self) -> None:
        suffix = reload_sidecar_suffix(switch_at_end_of_current=False)
        assert suffix == IMMEDIATE_SWITCH_SUFFIX
        path = f"C:/work/ch1/playout-graph.reload.abc123{suffix}"
        assert reload_switch_is_deferred(path) is False

    def test_unrecognized_filename_defaults_to_immediate(self) -> None:
        # A legacy sidecar (pre-B3) or any unrecognized shape must degrade to
        # the pre-existing, always-safe immediate-switch behavior -- never
        # silently hang waiting for an EOS nobody promised to defer to.
        assert reload_switch_is_deferred("/work/ch1/playout-graph.reload.deadbeef.json") is False
        assert reload_switch_is_deferred("/work/ch1/g.json") is False

    def test_suffixes_are_mutually_exclusive_and_both_end_in_json(self) -> None:
        assert DEFERRED_SWITCH_SUFFIX != IMMEDIATE_SWITCH_SUFFIX
        assert DEFERRED_SWITCH_SUFFIX.endswith(".json")
        assert IMMEDIATE_SWITCH_SUFFIX.endswith(".json")


class TestRolloverTriggerAt:
    """Boundary-aligned trigger timing (B3 fix): the earlier of "the plan's
    last segment begins" and "``min_lead_seconds`` before the plan's projected
    end" -- never later than either candidate, so a cold conform
    (SourcePreparer, which can take minutes -- daemon.py's
    ``_try_content_reload`` calls it synchronously) always gets at least that
    much head start before the pipeline reaches its own EOS."""

    def test_last_segment_start_wins_when_it_is_earlier(self) -> None:
        plan_end_at = _NOW + timedelta(seconds=1800)
        last_segment_start_at = _NOW + timedelta(seconds=1200)  # 600s from the end
        trigger_at = rollover_trigger_at(
            plan_end_at=plan_end_at,
            last_segment_start_at=last_segment_start_at,
            min_lead_seconds=120.0,
        )
        assert trigger_at == last_segment_start_at

    def test_lead_floor_wins_when_the_last_segment_starts_too_late(self) -> None:
        plan_end_at = _NOW + timedelta(seconds=1800)
        # The plan's only/last segment starts at plan start -- far earlier
        # than 120s before the end would suggest waiting for.
        last_segment_start_at = _NOW
        trigger_at = rollover_trigger_at(
            plan_end_at=plan_end_at,
            last_segment_start_at=last_segment_start_at,
            min_lead_seconds=120.0,
        )
        assert trigger_at == last_segment_start_at  # still the earlier candidate

    def test_lead_floor_wins_when_it_is_the_earlier_candidate(self) -> None:
        plan_end_at = _NOW + timedelta(seconds=1800)
        # A last segment that starts only 30s before the end (short final
        # segment) is LATER than the 120s floor -- the floor must win.
        last_segment_start_at = plan_end_at - timedelta(seconds=30)
        trigger_at = rollover_trigger_at(
            plan_end_at=plan_end_at,
            last_segment_start_at=last_segment_start_at,
            min_lead_seconds=120.0,
        )
        assert trigger_at == plan_end_at - timedelta(seconds=120.0)

    def test_negative_min_lead_seconds_rejected(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="min_lead_seconds"):
            rollover_trigger_at(
                plan_end_at=_NOW,
                last_segment_start_at=_NOW,
                min_lead_seconds=-1.0,
            )


class TestReloadIdFromSidecarPath:
    """Hostile-review follow-up (third pass), item 5b: direct unit coverage
    of ``reload_id_from_sidecar_path`` -- the POSIX FIFO control channel has
    no separate envelope/ack id field, so the daemon's own reload_id rides
    the sidecar filename instead, and this function is what recovers it on
    the read side (see its own docstring for the full rationale)."""

    def test_valid_immediate_switch_path_extracts_the_id(self) -> None:
        path = "/work/gov/playout-graph.reload.abc-123.immediate.json"
        assert reload_id_from_sidecar_path(path) == "abc-123"

    def test_valid_deferred_switch_path_extracts_the_id(self) -> None:
        path = "/work/gov/playout-graph.reload.abc-123.defer-eos.json"
        assert reload_id_from_sidecar_path(path) == "abc-123"

    def test_windows_backslash_path_extracts_the_id(self) -> None:
        # The Windows D2 named-pipe seam doesn't need this function (it has
        # its own envelope id field), but the extraction itself must not
        # assume a POSIX separator -- a backslash-separated path still
        # isolates the filename correctly.
        path = r"C:\work\gov\playout-graph.reload.abc-123.immediate.json"
        assert reload_id_from_sidecar_path(path) == "abc-123"

    def test_malformed_path_missing_the_expected_prefix_falls_back_to_the_filename(
        self,
    ) -> None:
        # No "playout-graph.reload." prefix at all (e.g. a hand-constructed
        # path from an older test/tool) -- must never raise, just correlate
        # less precisely: the bare filename stem, suffix included.
        path = "/work/gov/some-other-file.immediate.json"
        assert reload_id_from_sidecar_path(path) == "some-other-file.immediate.json"

    def test_path_with_no_id_component_returns_the_empty_remainder(self) -> None:
        # The prefix is present but nothing follows it before the suffix --
        # degenerate, but still must not raise.
        path = "/work/gov/playout-graph.reload..immediate.json"
        assert reload_id_from_sidecar_path(path) == ""

    def test_path_with_an_unrecognized_suffix_keeps_the_suffix_as_part_of_the_id(
        self,
    ) -> None:
        # Neither known suffix matches, so nothing is stripped -- the
        # remainder (including whatever trailing extension it has) is
        # returned as-is, matching an old-format/unknown sidecar filename.
        path = "/work/gov/playout-graph.reload.abc-123.unknown-suffix"
        assert reload_id_from_sidecar_path(path) == "abc-123.unknown-suffix"
