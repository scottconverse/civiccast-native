# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 84: ``ChannelAutomationService._check_plan_rollover``'s "rollover reload for
<ch> did not land within 45s; retrying" WARNING used to fire on EVERY ~2s poll tick
for as long as the actual retry stayed gated behind either floor
(``_ROLLOVER_RETRY_MIN_INTERVAL_SECONDS`` or ``_ROLLOVER_RETRY_MIN_WORKER_AGE_SECONDS``)
-- measured 1:1 with "deferred: worker pid has only been alive Ns" (a worker that keeps
crashing/relaunching right after every reload never gets a chance to settle). The
WARNING is emitted before either gate, and ``_rollover_issued_at`` is never cleared by
a gated tick, so the same log line repeated forever.

Fixed: the WARNING logs once when the 45s threshold is first crossed, then at most
once per 60s while the retry stays gated (DEBUG for every other gated tick), and a
separate WARNING fires when the retry actually dispatches. The gating logic itself
(the two floor checks) is unchanged -- only the log cadence changes.

Coordinator review round 2 (item 3): the "worker pid has only been alive Ns" WARNING
(a DIFFERENT log line than "did not land", gated on the worker-pid-age floor
specifically) had the exact same defect and was still firing on every gated tick
after round 1's fix landed -- measured 150 WARNINGs per 300s. It now has its own,
separately-bookkept cadence limit (``_rollover_pid_age_warned_at``), same rule.
``test_pid_age_deferred_warning_cadence_is_rate_limited`` below covers it in
isolation.

This test drives ``ChannelAutomationService`` directly (mirrors
``tests/egress/test_automation.py``'s own fixtures/helpers) and asserts on log record
levels via ``caplog``, decoupling the MONOTONIC clock (which gates retries/pid-age)
from the WALL-CLOCK ``now`` datetime (which gates the boundary trigger) so the retry
can be held gated across many simulated ticks without a real sleep.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from civiccast.egress.automation import ChannelAutomationService, ChannelAutomationSettings
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
    EgressStateRow,
)
from civiccast.egress.store import InMemoryEgressStore

_NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


class _FakeDaemon:
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


def _config(channel_id: str) -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=True,
        auto_start=False,
        slate_message="Stand by.",
        canonical_profile=CanonicalProfile(),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri=f"build/{channel_id}.ts")],
    )


def _plan_with_duration(
    channel_id: str, duration_seconds: float, *, source_ref: str = "seg"
) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label="Program",
                path="C:/media/program.ts",
                duration_seconds=duration_seconds,
                kind="program",
                source_ref=source_ref,
            )
        ],
    )


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


def test_rollover_retry_warning_cadence_while_gated_by_worker_pid_age(caplog) -> None:
    caplog.set_level(logging.DEBUG, logger="civiccast.egress.automation")
    clock = {"t": 0.0}  # monotonic -- gates retries/pid-age, independent of wall clock
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    _write_on_air_state(store, "public", proof_event_id="ev-1", pid=100)
    daemon = _FakeDaemon(live_channels={"public"})
    calls = {"n": 0}

    def provider(_cid: str) -> EgressSourcePlan:
        calls["n"] += 1
        return _plan_with_duration("public", 40.0 if calls["n"] == 1 else 400.0)

    service = ChannelAutomationService(
        store,
        daemon,
        provider,
        settings=ChannelAutomationSettings(),
        monotonic=lambda: clock["t"],
    )

    # t=0 (monotonic): establish the 40s horizon, then dispatch the initial
    # rollover reload once the wall clock crosses the boundary. Both calls
    # also latch pid 100 as first-seen at monotonic t=0 (_track_worker_pid
    # runs on every ON_AIR pass).
    service.run_once(now=_NOW)
    later = _NOW + timedelta(seconds=35)
    service.run_once(now=later)
    assert _pending_actions(store, "public") == ["reload"]
    assert calls["n"] == 2  # the initial provider call + the (unused) retry-shape plan

    # The dispatched reload never lands (current_proof_event_id stays ev-1).
    # Advance monotonic past the 45s ROLLOVER_ISSUED_TIMEOUT_SECONDS while
    # pid 100's age (46s) is still under the 60s worker-age retry floor --
    # gated, but this is the FIRST tick to cross the threshold: exactly one
    # WARNING.
    clock["t"] = 46.0
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []  # still gated -- no dispatch
    # Two independent WARNINGs are expected here: the pre-existing, unchanged
    # "deferred: worker pid ... waiting" one (fires every gated tick, not
    # touched by this fix) AND, since this is the FIRST tick to cross the
    # 45s threshold, one "did not land" WARNING.
    did_not_land_warnings = [
        r for r in caplog.records if r.levelname == "WARNING" and "did not land within" in r.message
    ]
    assert len(did_not_land_warnings) == 1

    # A later tick, still well under the 60s repeat-warning interval and
    # still gated by pid age (50s < 60s floor): the "did not land" line logs
    # at DEBUG this time, not WARNING (the pre-existing pid-age WARNING still
    # fires -- unrelated to this fix's cadence).
    clock["t"] = 50.0
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []
    assert [
        r for r in caplog.records if r.levelname == "WARNING" and "did not land within" in r.message
    ] == []
    debugs = [r for r in caplog.records if r.levelname == "DEBUG"]
    assert any("still has not landed" in r.message for r in debugs)

    # The worker relaunches (a fresh, still-too-young pid) -- exactly the
    # measured production scenario ("a worker that keeps crashing/
    # relaunching right after every reload"). pid age resets to 0 as of this
    # observation (monotonic t=55).
    clock["t"] = 55.0
    _write_on_air_state(store, "public", proof_event_id="ev-1", pid=200)
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []  # gated again by the fresh pid's age

    # 60s after the FIRST warning (t=46+60=106): the repeat-warning cadence
    # fires again even though the retry itself is STILL gated (pid 200's age
    # is now 106-55=51s, still under the 60s floor) -- a second WARNING, not
    # a dispatch.
    clock["t"] = 106.0
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []  # confirms still gated, not dispatched
    did_not_land_warnings = [
        r for r in caplog.records if r.levelname == "WARNING" and "did not land within" in r.message
    ]
    assert len(did_not_land_warnings) == 1

    # Finally past pid 200's own 60s age floor (monotonic t=120, age=65s):
    # the retry actually dispatches, and that gets its OWN WARNING,
    # independent of the repeat-cadence timer above.
    clock["t"] = 120.0
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == ["reload"]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("dispatched" in r.message for r in warnings)


def test_rollover_retry_dispatch_clears_the_warn_cadence_for_a_future_window(caplog) -> None:
    """A retry that actually dispatches must not leave stale rate-limit
    bookkeeping behind -- a FUTURE undelivered window for the same channel
    should log its own fresh first-crossing WARNING, not inherit this one's
    timestamp (which could otherwise suppress it for up to 60s)."""
    caplog.set_level(logging.DEBUG, logger="civiccast.egress.automation")
    clock = {"t": 0.0}
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    _write_on_air_state(store, "public", proof_event_id="ev-1", pid=100)
    daemon = _FakeDaemon(live_channels={"public"})
    calls = {"n": 0}

    def provider(_cid: str) -> EgressSourcePlan:
        calls["n"] += 1
        return _plan_with_duration("public", 40.0 if calls["n"] == 1 else 400.0)

    service = ChannelAutomationService(
        store,
        daemon,
        provider,
        settings=ChannelAutomationSettings(),
        monotonic=lambda: clock["t"],
    )

    service.run_once(now=_NOW)
    later = _NOW + timedelta(seconds=35)
    service.run_once(now=later)
    assert _pending_actions(store, "public") == ["reload"]

    # pid stays young enough to gate the retry once, past the issued-timeout,
    # then ages past the worker-age floor on the NEXT tick so the retry
    # dispatches without a repeat-cadence WARNING muddying this assertion.
    clock["t"] = 46.0
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []

    clock["t"] = 65.0  # pid age 65s -- past the 60s worker-age floor
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == ["reload"]
    assert "public" not in service._rollover_retry_warned_at


def test_pid_age_deferred_warning_cadence_is_rate_limited(caplog) -> None:
    """Coordinator review round 2, item 3: the "worker pid has only been
    alive Ns" WARNING is a SEPARATE log line from "did not land" (gated on
    the worker-pid-age floor specifically, not the issued-timeout crossing)
    and had the identical defect -- still fired on every single gated tick
    even after round 1's "did not land" cadence fix landed, measured at 150
    WARNINGs per 300s. Proves it independently: first gated tick -> WARNING,
    a later tick still under the 60s repeat interval -> DEBUG only, and a
    tick 60s past the first WARNING (while STILL gated by pid age) ->
    WARNING again."""
    caplog.set_level(logging.DEBUG, logger="civiccast.egress.automation")
    clock = {"t": 0.0}
    store = InMemoryEgressStore()
    store.upsert_config(_config("public"))
    _write_on_air_state(store, "public", proof_event_id="ev-1", pid=100)
    daemon = _FakeDaemon(live_channels={"public"})
    calls = {"n": 0}

    def provider(_cid: str) -> EgressSourcePlan:
        calls["n"] += 1
        return _plan_with_duration("public", 40.0 if calls["n"] == 1 else 400.0)

    service = ChannelAutomationService(
        store,
        daemon,
        provider,
        settings=ChannelAutomationSettings(),
        monotonic=lambda: clock["t"],
    )

    service.run_once(now=_NOW)
    later = _NOW + timedelta(seconds=35)
    service.run_once(now=later)
    assert _pending_actions(store, "public") == ["reload"]

    def _pid_age_warnings() -> list[str]:
        return [
            r.message
            for r in caplog.records
            if r.levelname == "WARNING" and "worker pid has only been alive" in r.message
        ]

    def _pid_age_debugs() -> list[str]:
        return [
            r.message
            for r in caplog.records
            if r.levelname == "DEBUG" and "still deferred" in r.message
        ]

    # t=46: past the 45s issued-timeout, pid age 46s < the 60s worker-age
    # floor -- gated, and the FIRST tick to hit this specific gate: exactly
    # one pid-age WARNING.
    clock["t"] = 46.0
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []
    assert len(_pid_age_warnings()) == 1

    # t=50: still gated (pid age 50s), still well under the 60s repeat
    # interval since the pid-age WARNING's own last log (t=46) -- DEBUG only.
    clock["t"] = 50.0
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []
    assert _pid_age_warnings() == []
    assert len(_pid_age_debugs()) >= 1

    # t=106: 60s past the pid-age WARNING's own last log (t=46), and STILL
    # gated (pid age 106s -- wait, that would be past the 60s floor and
    # dispatch; use a relaunched, still-young pid instead, exactly like the
    # "did not land" cadence test's own approach, to hold this gate open).
    clock["t"] = 55.0
    _write_on_air_state(store, "public", proof_event_id="ev-1", pid=200)
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []  # gated again by the fresh pid's age

    clock["t"] = 106.0  # 60s after the pid-age WARNING's own last log at t=46
    caplog.clear()
    service.run_once(now=later)
    assert _pending_actions(store, "public") == []  # pid 200's age is 51s -- still gated
    assert len(_pid_age_warnings()) == 1
