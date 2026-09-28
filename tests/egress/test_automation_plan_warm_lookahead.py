# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U60: a plan SHORTER than the rollover lead strands its successor's preparation.

Live C10, 2026-09-27 21:17:42. The station rolls one scheduled item per plan
(``civiccast/egress/source_plan.py``: ``max_segments=1`` on the GStreamer path),
so the plan on air is one item long. The rollover trigger is

    ``max(last_segment_start_at, plan_end_at - lead)``

and for an item shorter than ``lead`` (690s at the station's 300s preparation
timeout -- see ``_rollover_lead_seconds``) the first term wins: the dispatch for
the NEXT boundary fires the instant the CURRENT plan settles, which is also the
instant that dispatch's own synchronous cold conform starts. The preparation's
whole runway is therefore the length of the plan on air -- measured live at 290s
for a government item whose first-time conform took 383.6s. The plan ran to EOS
with no reload in flight, the worker held the slate for ~100s, and the next
dispatch inherited the delay: a latched lateness cascade.

The fix is an off-air LOOK-AHEAD warm. On the recovery dispatch (the only
regime where a leg is shorter than the lead), the automation walks the
boundaries ahead and asks the daemon to warm the first one whose own dispatch
is still a full lead away -- so the cache entry the air path will need is
already resident when the reload's synchronous prepare runs. A boundary whose
dispatch is nearer than ``now + lead`` is deliberately NOT warmed: it cannot
finish in time, and warming it would run a second whole-asset conform
concurrently with the reload's own cold conform.

This test drives ``ChannelAutomationService`` directly, mirroring
``tests/egress/test_automation_rollover_retry_log_cadence.py``'s harness. No
station is touched and the engine's changeover code is not exercised.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from civiccast.egress.automation import ChannelAutomationService, ChannelAutomationSettings
from civiccast.egress.errors import SourcePrepareError
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
    EgressStateRow,
)
from civiccast.egress.store import InMemoryEgressStore

# The station's computed lead is 690s (2 passes over its 300s preparation
# timeout + the settle budget + the margin, floored at
# ``_ROLLOVER_MIN_LEAD_SECONDS``) -- the numbers below are all relative to it.
_NOW = datetime(2026, 9, 27, 21, 17, 42, tzinfo=UTC)


def _at(seconds: float) -> datetime:
    return _NOW + timedelta(seconds=seconds)


class _FakeDaemon:
    """The cadence test's double, WITHOUT ``warm_source_plan``.

    The capability probe is the point: a daemon that cannot warm must still
    dispatch exactly as it does today.
    """

    def __init__(self, *, live_channels: set[str]) -> None:
        self.live_channels = live_channels
        self.processed: list[str] = []

    def has_live_process(self, channel_id: str) -> bool:
        return channel_id in self.live_channels

    def has_manual_override(self, channel_id: str) -> bool:
        return False

    def process_once(self, channel_id: str) -> int:
        self.processed.append(channel_id)
        return 0


class _WarmFakeDaemon(_FakeDaemon):
    """Adds the warm capability the automation looks for."""

    def __init__(self, *, live_channels: set[str], warmer=None) -> None:
        super().__init__(live_channels=live_channels)
        self.warmed: list[tuple[str, EgressSourcePlan]] = []
        self.warm_raised: list[str] = []
        self._warmer = warmer

    def warm_source_plan(self, channel_id: str, plan: EgressSourcePlan) -> None:
        self.warmed.append((channel_id, plan))
        if self._warmer is not None:
            # Recorded BEFORE the call so the list still names the channel
            # when the warmer raises out of here -- the fault has to travel
            # back through the automation's own guard, which is the thing
            # under test in ``test_a_raising_warmer_never_breaks_the_dispatch``.
            self.warm_raised.append(channel_id)
            self._warmer(channel_id, plan)


def _config(channel_id: str) -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        auto_start=False,
        slate_message="Stand by.",
        canonical_profile=CanonicalProfile(),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri=f"build/{channel_id}.ts")],
    )


def _item(channel_id: str, index: int, seconds: float) -> EgressSourcePlan:
    """The schedule item airing in ``[index*seconds, (index+1)*seconds)``."""

    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label=f"Item {index + 1}",
                path=f"C:/media/item-{index + 1}.ts",
                duration_seconds=seconds,
                kind="program",
                source_ref=f"item-{index + 1}",
            )
        ],
    )


class _Schedule:
    """A boundary provider over a finite list of equal-length items.

    ``plan_at(channel, at)`` answers the item airing at ``at`` -- the contract
    ``SourcePreparer.plan_at`` has -- and records every boundary it is asked
    about, so a test can pin which boundaries the look-ahead walked.
    """

    def __init__(self, channel_id: str, *, count: int, seconds: float) -> None:
        self.channel_id = channel_id
        self.count = count
        self.seconds = seconds
        self.calls: list[datetime] = []

    def _index(self, at: datetime) -> int:
        return int((at - _NOW).total_seconds() // self.seconds)

    def plan_at(self, channel_id: str, at: datetime) -> EgressSourcePlan | None:
        self.calls.append(at)
        index = self._index(at)
        if index < 0 or index >= self.count:
            return None
        return _item(channel_id, index, self.seconds)

    def horizon_plan(self, channel_id: str) -> EgressSourcePlan:
        """The plan the first tick establishes its horizon from."""

        return _item(channel_id, 0, self.seconds)


def _write_on_air_state(
    store: InMemoryEgressStore, channel_id: str, *, proof_event_id: str, pid: int
) -> None:
    store.write_state(
        EgressStateRow(
            channel_id=channel_id,
            state="ON_AIR",
            current_source_label="Council Meeting",
            current_proof_event_id=proof_event_id,
            updated_at=_NOW,
            pid=pid,
        )
    )


def _pending_actions(store: InMemoryEgressStore, channel_id: str) -> list[str]:
    return [command.action for command in store.pop_pending_commands(channel_id)]


def _service(
    store: InMemoryEgressStore, daemon: object, schedule: _Schedule, clock: dict[str, float]
) -> ChannelAutomationService:
    return ChannelAutomationService(
        store,
        daemon,  # type: ignore[arg-type]
        schedule.horizon_plan,
        settings=ChannelAutomationSettings(),
        boundary_source_plan_provider=schedule.plan_at,
        monotonic=lambda: clock["t"],
    )


def _armed_service(
    *, daemon: object, schedule: _Schedule, clock: dict[str, float]
) -> tuple[InMemoryEgressStore, ChannelAutomationService]:
    """Store + service with the horizon established and the first dispatch pending.

    Tick 1 (``_NOW``) establishes the tracked horizon and returns; tick 2 (two
    seconds later) is the recovery dispatch this item is about -- the plan on
    air is shorter than the lead, so the trigger collapsed to the plan's own
    start and there is nothing earlier to wait for.
    """

    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    _write_on_air_state(store, "public", proof_event_id="ev-1", pid=100)
    service = _service(store, daemon, schedule, clock)
    service.run_once(now=_NOW)
    return store, service


def test_short_leg_lookahead_warms_the_first_boundary_a_full_lead_away() -> None:
    """290s items, a 690s lead: the first savable boundary is the 5th item.

    Boundary ``fresh_end = _NOW+580`` dispatches at ``_NOW+290`` (the item-2
    start, the clamp), ``_NOW+870`` at ``_NOW+580``; both are nearer than one
    lead from the tick, so warming them would race the reload's own cold
    conform. ``_NOW+1160`` dispatches at ``_NOW+870``, which IS a full lead
    out -- that is the first plan worth warming, and only that one.
    """

    clock = {"t": 0.0}
    schedule = _Schedule("public", count=10, seconds=290.0)
    daemon = _WarmFakeDaemon(live_channels={"public"})
    store, service = _armed_service(daemon=daemon, schedule=schedule, clock=clock)

    service.run_once(now=_at(2))

    assert _pending_actions(store, "public") == ["reload"]
    assert len(daemon.warmed) == 1, daemon.warmed
    channel_id, warmed_plan = daemon.warmed[0]
    assert channel_id == "public"
    assert [seg.source_ref for seg in warmed_plan.segments] == ["item-5"]
    # The dispatch's own boundary first, then each boundary the walk stepped
    # over, ending on the one it warmed.
    assert schedule.calls == [_at(290), _at(580), _at(870), _at(1160)]


def test_lookahead_is_skipped_when_the_plan_on_air_covers_the_lead() -> None:
    """A 1800s item gives its successor's preparation a full lead of runway.

    ``inside_lead_recovery`` is False, so this is ordinary cadence -- the
    look-ahead must not spend a whole-asset conform on it.
    """

    clock = {"t": 0.0}
    schedule = _Schedule("public", count=4, seconds=1800.0)
    daemon = _WarmFakeDaemon(live_channels={"public"})
    store, service = _armed_service(daemon=daemon, schedule=schedule, clock=clock)

    # The boundary-aligned trigger for a 1800s plan under a 690s lead.
    service.run_once(now=_at(1120))

    assert _pending_actions(store, "public") == ["reload"]
    assert daemon.warmed == []
    assert schedule.calls == [_at(1800)]


def test_lookahead_gives_up_when_no_boundary_is_a_full_lead_away() -> None:
    """30s items: every boundary inside the walk's reach is unsavable.

    Nothing is warmed rather than something useless -- the bounded walk returns
    empty and the dispatch is unaffected.
    """

    clock = {"t": 0.0}
    schedule = _Schedule("public", count=100, seconds=30.0)
    daemon = _WarmFakeDaemon(live_channels={"public"})
    store, service = _armed_service(daemon=daemon, schedule=schedule, clock=clock)

    service.run_once(now=_at(2))

    assert _pending_actions(store, "public") == ["reload"]
    assert daemon.warmed == []
    # The dispatch's boundary, then the walk's bounded search.
    assert schedule.calls[0] == _at(30)
    assert len(schedule.calls) <= 1 + 8


def test_lookahead_stops_when_the_schedule_resolves_no_further_item() -> None:
    clock = {"t": 0.0}
    schedule = _Schedule("public", count=3, seconds=290.0)
    daemon = _WarmFakeDaemon(live_channels={"public"})
    store, service = _armed_service(daemon=daemon, schedule=schedule, clock=clock)

    service.run_once(now=_at(2))

    assert _pending_actions(store, "public") == ["reload"]
    assert daemon.warmed == []
    assert schedule.calls == [_at(290), _at(580), _at(870)]


def test_lookahead_survives_a_provider_that_raises_mid_walk() -> None:
    """``plan_at`` raises ``SourcePrepareError`` past the last published item.

    The dispatch has already been enqueued by then; a walk that cannot resolve
    a boundary must end quietly, not break the tick.
    """

    clock = {"t": 0.0}
    schedule = _Schedule("public", count=3, seconds=290.0)

    def raising(channel_id: str, at: datetime) -> EgressSourcePlan | None:
        if at >= _at(870):
            schedule.calls.append(at)
            raise SourcePrepareError("no schedule item at this boundary")
        return schedule.plan_at(channel_id, at)

    daemon = _WarmFakeDaemon(live_channels={"public"})
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    _write_on_air_state(store, "public", proof_event_id="ev-1", pid=100)
    service = ChannelAutomationService(
        store,
        daemon,  # type: ignore[arg-type]
        schedule.horizon_plan,
        settings=ChannelAutomationSettings(),
        boundary_source_plan_provider=raising,
        monotonic=lambda: clock["t"],
    )
    service.run_once(now=_NOW)

    service.run_once(now=_at(2))

    assert _pending_actions(store, "public") == ["reload"]
    assert daemon.warmed == []


def test_lookahead_is_skipped_when_the_daemon_cannot_warm() -> None:
    """The capability probe: an old daemon (no ``warm_source_plan``) is unchanged."""

    clock = {"t": 0.0}
    schedule = _Schedule("public", count=10, seconds=290.0)
    daemon = _FakeDaemon(live_channels={"public"})
    store, service = _armed_service(daemon=daemon, schedule=schedule, clock=clock)

    service.run_once(now=_at(2))

    assert _pending_actions(store, "public") == ["reload"]


def test_a_raising_warmer_never_breaks_the_dispatch() -> None:
    """Best-effort: the reload is already enqueued, so a warm failure is logged."""

    clock = {"t": 0.0}
    schedule = _Schedule("public", count=10, seconds=290.0)

    def boom(_channel_id: str, _plan: EgressSourcePlan) -> None:
        raise RuntimeError("warm backend unavailable")

    daemon = _WarmFakeDaemon(live_channels={"public"}, warmer=boom)
    store, service = _armed_service(daemon=daemon, schedule=schedule, clock=clock)

    service.run_once(now=_at(2))

    assert _pending_actions(store, "public") == ["reload"]
    assert [entry[1].segments[0].source_ref for entry in daemon.warmed] == ["item-5"]
    assert daemon.warm_raised == ["public"]
