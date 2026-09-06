# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Channel automation driver tests (cable automation CA-2).

The driver makes playout self-driving: auto_start channels come back on air
after restarts, slate gaps re-plan when a program becomes due, and command
latches prevent storms. The daemon double records process_once calls; the
real InMemoryEgressStore carries configs, the durable command queue, and
state rows.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from civiccast.egress.automation import ChannelAutomationService, ChannelAutomationSettings
from civiccast.egress.models import (
    CanonicalProfile,
    EgressConfig,
    EgressSinkSpec,
    EgressSourcePlan,
    EgressSourceSegment,
    EgressStateRow,
)
from civiccast.egress.source_plan import SourcePrepareError
from civiccast.egress.store import InMemoryEgressStore

_NOW = datetime(2026, 6, 12, 6, 0, tzinfo=UTC)


class _FakeDaemon:
    def __init__(
        self,
        *,
        live_channels: set[str] | None = None,
        manual_override_channels: set[str] | None = None,
    ) -> None:
        self.live_channels = live_channels or set()
        self.processed: list[str] = []
        # B1 fix: mirrors PlayoutSupervisor.has_manual_override -- a channel in
        # this set stands in for an active operator live takeover or forced
        # fallback slate.
        self.manual_override_channels = manual_override_channels or set()

    def has_live_process(self, channel_id: str) -> bool:
        return channel_id in self.live_channels

    def has_manual_override(self, channel_id: str) -> bool:
        return channel_id in self.manual_override_channels

    def process_once(self, channel_id: str) -> int:
        self.processed.append(channel_id)
        return 0


def _config(channel_id: str, *, enabled: bool = True, auto_start: bool = False) -> EgressConfig:
    return EgressConfig(
        channel_id=channel_id,
        enabled=enabled,
        auto_start=auto_start,
        slate_message="Stand by.",
        canonical_profile=CanonicalProfile(),
        sinks=[EgressSinkSpec(kind="file", label="Proof", uri=f"build/{channel_id}.ts")],
    )


def _plan(channel_id: str) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label="Council Meeting",
                path="C:/media/council.ts",
                duration_seconds=1800,
                kind="program",
                source_ref="council",
            )
        ],
    )


def _pending_actions(store: InMemoryEgressStore, channel_id: str) -> list[str]:
    return [command.action for command in store.pop_pending_commands(channel_id)]


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


class _HorizonAwareDaemon(_FakeDaemon):
    """A daemon double that, like the real ``EgressDaemon``, can say which source
    plan it actually DISPATCHED (``dispatched_plan_horizon``)."""

    def __init__(self, *, live_channels: set[str] | None = None) -> None:
        super().__init__(live_channels=live_channels)
        self.dispatched: dict[str, tuple[str | None, tuple[float, ...], bool]] = {}

    def dispatched_plan_horizon(
        self, channel_id: str
    ) -> tuple[str | None, tuple[float, ...], bool] | None:
        return self.dispatched.get(channel_id)


def _plan_with_segments(
    channel_id: str, durations: tuple[float, ...], *, source_ref_prefix: str = "seg"
) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label=f"Program {n}",
                path=f"C:/media/program-{n}.ts",
                duration_seconds=duration,
                kind="program",
                source_ref=f"{source_ref_prefix}-{n}",
            )
            for n, duration in enumerate(durations)
        ],
    )


class TestRelayIdentifierValidation:
    """Audit Critical (TEST-001/QA-001): the API layer must reject relay
    identifiers the relay runtime categorically rejects - otherwise a saved
    config poisons the automation pass at air time."""

    def test_whitespace_only_values_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="sdi_relay_device"):
            EgressConfig.model_validate(
                _config("public").model_dump() | {"sdi_relay_device": "   "}
            )
        with pytest.raises(ValueError, match="ndi_relay_name"):
            EgressConfig.model_validate(_config("public").model_dump() | {"ndi_relay_name": "  "})

    def test_control_characters_are_rejected(self) -> None:
        for bad in ("Deck\nLink", "Deck\rLink", "Deck\x00Link", "Deck\x01Link", "Deck\tLink"):
            with pytest.raises(ValueError, match="control"):
                EgressConfig.model_validate(
                    _config("public").model_dump() | {"sdi_relay_device": bad}
                )
            with pytest.raises(ValueError, match="control"):
                EgressConfig.model_validate(
                    _config("public").model_dump() | {"ndi_relay_name": bad}
                )

    def test_padding_is_stripped_and_clean_values_pass(self) -> None:
        config = EgressConfig.model_validate(
            _config("public").model_dump()
            | {"sdi_relay_device": "  DeckLink Mini  ", "ndi_relay_name": " CivicCast Public "}
        )
        assert config.sdi_relay_device == "DeckLink Mini"
        assert config.ndi_relay_name == "CivicCast Public"


class TestRunOnceChannelIsolation:
    """Audit Critical: one channel's relay failure must never starve the
    other channels' supervision (run_once had no per-channel isolation)."""

    def test_poisoned_channel_does_not_starve_the_fleet(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(
            _config("aaa-poisoned").model_copy(
                update={
                    "sdi_relay_device": "DeckLink",
                    "sinks": [
                        EgressSinkSpec(kind="udp-ts", label="Headend", uri="udp://127.0.0.1:23101")
                    ],
                }
            )
        )
        store.upsert_config(_config("zzz-healthy", auto_start=True))
        daemon = _FakeDaemon(live_channels={"aaa-poisoned"})

        def exploding_factory(**_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("relay construction exploded")

        service = ChannelAutomationService(
            store,
            daemon,
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            sdi_supervisor_factory=exploding_factory,
        )

        seen = service.run_once(now=_NOW)

        # Both channels were processed despite the poisoned one raising.
        assert seen == ["aaa-poisoned", "zzz-healthy"]
        assert daemon.processed == ["aaa-poisoned", "zzz-healthy"]
        # The dark auto_start channel still got its start command.
        assert "start" in _pending_actions(store, "zzz-healthy")


class TestAutoStart:
    def test_dark_auto_start_channel_gets_exactly_one_start(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public", auto_start=True))
        daemon = _FakeDaemon()
        service = ChannelAutomationService(
            store, daemon, lambda _cid: None, settings=ChannelAutomationSettings()
        )

        service.run_once(now=_NOW)

        # The daemon consumed the start during run_once via process_once in
        # the REAL flow; with the fake daemon the command stays queued.
        assert _pending_actions(store, "public") == ["start"]
        assert daemon.processed == ["public"]

        # Latch: still dark on the next pass (fake daemon never starts it),
        # but no second start is issued.
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

    def test_live_channel_gets_no_start_and_latch_resets_after_drop(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public", auto_start=True))
        daemon = _FakeDaemon(live_channels={"public"})
        service = ChannelAutomationService(
            store, daemon, lambda _cid: None, settings=ChannelAutomationSettings()
        )

        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

        # Encoder dies (operatorless drop) -> next pass re-issues start.
        daemon.live_channels.clear()
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["start"]

    def test_non_auto_start_and_disabled_channels_are_left_alone(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("manual", auto_start=False))
        store.upsert_config(_config("dark", enabled=False, auto_start=True))
        daemon = _FakeDaemon()
        service = ChannelAutomationService(
            store, daemon, lambda _cid: None, settings=ChannelAutomationSettings()
        )

        seen = service.run_once(now=_NOW)

        assert seen == ["manual"]
        assert _pending_actions(store, "manual") == []
        assert _pending_actions(store, "dark") == []
        assert daemon.processed == ["manual"]


class TestSlateReplan:
    def _slate_state(self, store: InMemoryEgressStore, channel_id: str) -> None:
        store.write_state(
            EgressStateRow(channel_id=channel_id, state="FALLBACK_SLATE", updated_at=_NOW)
        )

    def test_due_program_triggers_exactly_one_reload(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._slate_state(store, "public")
        daemon = _FakeDaemon(live_channels={"public"})
        service = ChannelAutomationService(
            store, daemon, lambda cid: _plan(cid), settings=ChannelAutomationSettings()
        )

        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["reload"]

        # Latched while still on slate: no reload storm.
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

        # Once the channel leaves slate, the latch clears for the next gap.
        store.write_state(EgressStateRow(channel_id="public", state="ON_AIR", updated_at=_NOW))
        service.run_once(now=_NOW)
        self._slate_state(store, "public")
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["reload"]

    def test_no_plan_or_unplayable_plan_stays_on_slate(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._slate_state(store, "public")
        daemon = _FakeDaemon(live_channels={"public"})

        none_service = ChannelAutomationService(
            store, daemon, lambda _cid: None, settings=ChannelAutomationSettings()
        )
        none_service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

        def _raises(_cid: str) -> EgressSourcePlan:
            raise SourcePrepareError("media missing")

        raising_service = ChannelAutomationService(
            store, daemon, _raises, settings=ChannelAutomationSettings()
        )
        raising_service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

    def test_slate_replan_backs_off_exponentially_and_gives_up_after_max_failures(
        self,
    ) -> None:
        """Hostile-review "no flap" fix (2026-09-05): a persistently-failing
        reload used to retry forever at a flat 30s cooldown -- indefinite
        kill/restart churn against a due item that will never prepare
        successfully. The cooldown now doubles with every consecutive
        failure (30s, 60s, 120s, 240s, 300s-capped), and past
        ``_SLATE_REPLAN_MAX_CONSECUTIVE_FAILURES`` (5) attempts, it stops
        retrying entirely and raises an operator alert instead."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._slate_state(store, "public")
        daemon = _FakeDaemon(live_channels={"public"})
        alerted: list[str] = []

        class _FakeAlerts:
            def begin_tick(self, channel_id: str) -> None:
                pass

            def end_tick(self, channel_id: str) -> None:
                pass

            def on_slate_reload_exhausted(self, channel_id: str, *, detail: str) -> None:
                alerted.append(detail)

        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan(cid),
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
            automation_alerts=_FakeAlerts(),  # type: ignore[arg-type]
        )

        # Delta review fix: a failure is counted the moment it is OBSERVED
        # (back on FALLBACK_SLATE with the previous dispatch still marked
        # pending) rather than pre-emptively on every dispatch -- so the 5th
        # consecutive failure is detected (and give-up fires) at the
        # "flapped back to slate" checkpoint of the 5th iteration below,
        # not on a would-be 6th dispatch attempt.
        expected_cooldowns = [30.0, 60.0, 120.0, 240.0, 300.0]  # doubling, capped at 300s
        for attempt, cooldown in enumerate(expected_cooldowns, start=1):
            service.run_once(now=_NOW)
            assert _pending_actions(store, "public") == ["reload"], f"attempt {attempt}"
            # Simulate the flap: the reload is dispatched (TRANSITIONING),
            # then fails and lands back on slate -- still failing.
            store.write_state(
                EgressStateRow(channel_id="public", state="TRANSITIONING", updated_at=_NOW)
            )
            service.run_once(now=_NOW)  # clears the one-shot _reload_issued latch
            self._slate_state(store, "public")
            # Short of THIS attempt's cooldown: no retry yet, but the flap
            # back to slate IS observed here -- the failure is counted on
            # this very tick, giving up immediately once the 5th one lands.
            clock["now"] += cooldown - 1.0
            service.run_once(now=_NOW)
            assert _pending_actions(store, "public") == [], (
                f"cooldown not yet elapsed, attempt {attempt}"
            )
            clock["now"] += 1.0  # now past the cooldown

        # The 5th consecutive failure was already observed and counted
        # inside the loop above -- gave up without needing a distinct 6th
        # dispatch attempt.
        # Delta review fix: the give-up tick used to fall through into a
        # second, redundant "already given up" check and fire the alert
        # TWICE on that one tick -- exactly once now.
        assert len(alerted) == 1
        assert "public" in alerted[0] and "5 consecutive failures" in alerted[0]

        # It stays given up: no reload dispatches again, ever.
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []
        clock["now"] += 1000.0
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

        # A genuine success (ON_AIR) resets the streak for the next gap.
        store.write_state(EgressStateRow(channel_id="public", state="ON_AIR", updated_at=_NOW))
        service.run_once(now=_NOW)
        self._slate_state(store, "public")
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["reload"]

    def test_stale_pending_mark_is_discarded_on_a_stopped_or_error_terminal_state(
        self,
    ) -> None:
        """Delta review fix: a dispatched reload marked pending must not
        count a FALSE failure against a LATER, unrelated FALLBACK_SLATE
        period if the channel passed through a terminal STOPPED/ERROR
        state in between (an operator stop, or a crash) -- that terminal
        state has nothing to do with the reload's own outcome, so the
        stale pending mark is discarded rather than carried forward and
        misread as "the dispatched reload flapped back to slate"."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._slate_state(store, "public")
        daemon = _FakeDaemon(live_channels={"public"})
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan(cid),
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["reload"]
        assert "public" in service._slate_replan_pending  # type: ignore[attr-defined]

        # The channel is stopped (an operator action, or a crash) before
        # the dispatched reload ever resolves either way.
        store.write_state(EgressStateRow(channel_id="public", state="STOPPED", updated_at=_NOW))
        service.run_once(now=_NOW)
        assert "public" not in service._slate_replan_pending  # type: ignore[attr-defined]

        # A later, UNRELATED return to FALLBACK_SLATE (e.g. after a manual
        # restart) must start the attempt count fresh -- not count a false
        # failure for the stale mark. (Past the first dispatch's own
        # cooldown, an unrelated concern from the cadence-pacing fix, so it
        # alone doesn't block this second dispatch.)
        clock["now"] += 31.0
        self._slate_state(store, "public")
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["reload"]
        assert service._slate_replan_attempts.get("public", 0) == 0  # type: ignore[attr-defined]


class TestPlanRollover:
    """Soak evidence 2026-09-04 (kit 4b30c99, Desktop/CIVICCAST-EVIDENCE/
    soak-120-4b30c99-20260904): back-to-back scheduled premieres EOS'd the
    GStreamer worker at every source-plan boundary (6-8 restarts/channel in
    2h) because nothing ever extended a LIVE (ON_AIR) plan before it ran
    out -- only a FALLBACK_SLATE gap re-planned (TestSlateReplan above).
    ``_check_plan_rollover`` fixes this by reusing the SAME seamless
    ``reload`` dispatch _check_slate_replan already uses, before EOS."""

    def _on_air_state(
        self, store: InMemoryEgressStore, channel_id: str, *, proof_event_id: str
    ) -> None:
        store.write_state(
            EgressStateRow(
                channel_id=channel_id,
                state="ON_AIR",
                current_source_label="Council Meeting",
                current_proof_event_id=proof_event_id,
                updated_at=_NOW,
            )
        )

    def test_no_rollover_while_plan_has_plenty_of_runway(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_duration(cid, 1800.0),
            settings=ChannelAutomationSettings(),
        )

        # First tick establishes the horizon (30 min out) -- nothing due.
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []
        # A later tick, still nowhere near the end, still issues nothing.
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

    def test_rollover_dispatches_exactly_one_reload_before_eos(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        # The live plan has 40s left; the schedule underneath it extends
        # much further once the clock moves inside the lookahead window.
        calls = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return _plan_with_duration("public", 40.0 if calls["n"] == 1 else 400.0)

        service = ChannelAutomationService(
            store, daemon, provider, settings=ChannelAutomationSettings()
        )

        # Establish the horizon: plan ends 40s from now.
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

        # 15s later the plan is inside the 30s lookahead -> roll it over.
        later = _NOW + timedelta(seconds=15)
        service.run_once(now=later)
        assert _pending_actions(store, "public") == ["reload"]

        # Same plan boundary (proof event unchanged): no second reload while
        # the daemon has not yet applied the first one (no command storm).
        service.run_once(now=later + timedelta(seconds=1))
        assert _pending_actions(store, "public") == []

    def test_no_rollover_when_schedule_has_nothing_further(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        # The schedule genuinely has nothing published beyond the item
        # already airing: every call reflects the SAME fixed end time, just
        # re-anchored (join-in-progress) at whatever "now" it is asked from
        # -- exactly what build_source_plan_from_schedule does when no new
        # item follows the one currently on air.
        deadline = _NOW + timedelta(seconds=40)
        clock = {"now": _NOW}

        def provider(_cid: str) -> EgressSourcePlan:
            remaining = max(0.0, (deadline - clock["now"]).total_seconds())
            return _plan_with_duration("public", remaining)

        service = ChannelAutomationService(
            store, daemon, provider, settings=ChannelAutomationSettings()
        )

        service.run_once(now=clock["now"])
        clock["now"] = _NOW + timedelta(seconds=15)
        service.run_once(now=clock["now"])

        # No reload -- there is nothing to roll onto; the plan is left to
        # reach its own natural end (the existing, unchanged EOS path).
        assert _pending_actions(store, "public") == []

    def test_rollover_re_establishes_horizon_once_the_reload_lands(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        calls = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return _plan_with_duration("public", 40.0 if calls["n"] == 1 else 400.0)

        service = ChannelAutomationService(
            store, daemon, provider, settings=ChannelAutomationSettings()
        )
        service.run_once(now=_NOW)
        later = _NOW + timedelta(seconds=15)
        service.run_once(now=later)
        assert _pending_actions(store, "public") == ["reload"]

        # The daemon applies the seamless reload and writes a fresh
        # current_proof_event_id -- the tracked horizon must follow it, not
        # keep firing against the stale one.
        self._on_air_state(store, "public", proof_event_id="ev-2")
        service.run_once(now=later)
        assert _pending_actions(store, "public") == []

    def test_rollover_never_fires_off_of_the_slate_replan_state(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        store.write_state(
            EgressStateRow(channel_id="public", state="FALLBACK_SLATE", updated_at=_NOW)
        )
        daemon = _FakeDaemon(live_channels={"public"})
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_duration(cid, 40.0),
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)
        # _check_slate_replan issues its own reload for the gap; the
        # rollover check must not ALSO fire while the channel is off ON_AIR.
        assert _pending_actions(store, "public") == ["reload"]

    # -- Hostile-review B1: skip entirely under an operator override ----------

    def test_rollover_skipped_during_live_takeover(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"}, manual_override_channels={"public"})
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_duration(cid, 40.0),
            settings=ChannelAutomationSettings(),
        )

        # Establish, then push well past the (now much earlier) trigger point --
        # under any override the check must still never enqueue a reload.
        service.run_once(now=_NOW)
        service.run_once(now=_NOW + timedelta(seconds=35))
        assert _pending_actions(store, "public") == []

    def test_rollover_skipped_during_forced_slate(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        # The state row stays ON_AIR: a forced-slate pad toggle (swap_role)
        # writes NO state-row transition at all (B1's real defect).
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"}, manual_override_channels={"public"})
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_duration(cid, 40.0),
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)
        service.run_once(now=_NOW + timedelta(seconds=35))
        assert _pending_actions(store, "public") == []

    def test_rollover_resumes_once_the_override_clears(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"}, manual_override_channels={"public"})
        calls = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return _plan_with_duration("public", 40.0 if calls["n"] == 1 else 400.0)

        service = ChannelAutomationService(
            store, daemon, provider, settings=ChannelAutomationSettings()
        )

        service.run_once(now=_NOW)
        later = _NOW + timedelta(seconds=35)
        service.run_once(now=later)
        assert _pending_actions(store, "public") == []  # override still active

        # The override clears: the very next pass establishes a fresh horizon
        # (nothing was ever tracked while the override was active) --
        # nothing to dispatch on THIS tick yet.
        daemon.manual_override_channels.discard("public")
        service.run_once(now=later)
        assert _pending_actions(store, "public") == []

        # A subsequent pass past the boundary rolls over normally.
        service.run_once(now=later + timedelta(seconds=1))
        assert _pending_actions(store, "public") == ["reload"]

    # -- Hostile-review B2: retry pacing + a dropped reload's failure latch ----

    def test_rollover_backs_off_after_source_prepare_error(self) -> None:
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        calls = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            if calls["n"] == 1:
                return _plan_with_duration("public", 40.0)
            raise SourcePrepareError("media temporarily unreadable")

        service = ChannelAutomationService(
            store,
            daemon,
            provider,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

        service.run_once(now=_NOW)  # establish horizon: 40s plan
        later = _NOW + timedelta(seconds=35)  # well past the boundary trigger
        service.run_once(now=later)
        assert calls["n"] == 2  # one retry attempt, which raised

        # Within the cooldown: no re-query (no command storm against a
        # persistently failing source).
        clock["now"] += 5.0
        service.run_once(now=later)
        assert calls["n"] == 2
        assert _pending_actions(store, "public") == []

        # Past the cooldown: retries.
        clock["now"] += 30.0
        service.run_once(now=later)
        assert calls["n"] == 3

    def test_rollover_retries_once_if_the_dispatched_reload_never_lands(self) -> None:
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
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
            monotonic=lambda: clock["now"],
        )

        service.run_once(now=_NOW)
        later = _NOW + timedelta(seconds=35)
        service.run_once(now=later)
        assert _pending_actions(store, "public") == ["reload"]

        # The daemon never applies it (current_proof_event_id stays ev-1 --
        # e.g. the command was dropped, or the worker control channel wasn't
        # ready). Short of the timeout: still waiting, no second reload.
        clock["now"] += 10.0
        service.run_once(now=later)
        assert _pending_actions(store, "public") == []

        # Past _ROLLOVER_ISSUED_TIMEOUT_SECONDS: the latch clears and one
        # retry is dispatched.
        clock["now"] += 40.0
        service.run_once(now=later)
        assert _pending_actions(store, "public") == ["reload"]

    def test_rollover_bookkeeping_survives_a_pending_reload_drain_and_b2_retries_during_it(
        self,
    ) -> None:
        """BLOCKER A hostile-review redo (2026-09-05): ``daemon._request_
        reload``'s terminate+restart fallback, for an ON_AIR program, is
        DESIGNED to wait for that program's own natural EOS (a graceful
        drain, not a stuck latch) -- so the state row can legitimately stay
        TRANSITIONING for a long time with a reload genuinely still pending
        (``pending_reload_since`` set on the row, daemon.py's honest
        annotation). A first pass at this fix wiped this method's own
        tracking (``_plan_horizon``/``_rollover_issued``/
        ``_rollover_issued_at``) on ANY non-ON_AIR tick, including this one --
        making the B2 "reload never landed" retry permanently unreachable
        for the whole drain. The redo carves out exactly this case: a
        TRANSITIONING row WITH ``pending_reload_since`` set keeps its
        bookkeeping, so B2's own undelivered-reload timeout still fires
        DURING the drain, without needing the state to return to ON_AIR
        first."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
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
            monotonic=lambda: clock["now"],
        )

        service.run_once(now=_NOW)
        later = _NOW + timedelta(seconds=35)
        service.run_once(now=later)
        assert _pending_actions(store, "public") == ["reload"]

        # The dispatched reload falls back to the terminate+restart drain
        # (daemon.py's ``_request_reload``): the state row goes to
        # TRANSITIONING with the SAME proof event, honestly marked as a
        # pending reload (not just a bare, unexplained TRANSITIONING).
        store.write_state(
            EgressStateRow(
                channel_id="public",
                state="TRANSITIONING",
                current_source_label="Council Meeting",
                current_proof_event_id="ev-1",
                updated_at=_NOW,
                pending_reload_since=_NOW,
            )
        )
        clock["now"] += 50.0  # well past _ROLLOVER_ISSUED_TIMEOUT_SECONDS (45s)
        service.run_once(now=later)
        # Reachable DURING the drain -- no need to wait for ON_AIR to return.
        assert _pending_actions(store, "public") == ["reload"]
        calls_after_first_retry = calls["n"]

        # Delta review fix: this retry fires AT MOST ONCE per drain. The
        # daemon-side already-pending guard would have ignored the
        # duplicate "reload" this retry enqueued anyway (tested separately
        # in test_daemon.py), so the row stays exactly as it was --
        # TRANSITIONING, same proof event, same pending_reload_since --
        # simulating that. 10 more ticks, well past ANOTHER
        # _ROLLOVER_ISSUED_TIMEOUT_SECONDS window, must not retry again or
        # re-query the schedule again.
        for _ in range(10):
            clock["now"] += 50.0
            service.run_once(now=later)
            assert _pending_actions(store, "public") == []
        assert calls["n"] == calls_after_first_retry  # no further re-query, ever

    def test_rollover_bookkeeping_is_wiped_for_an_unrelated_transitioning_row(self) -> None:
        """Contrast case: a TRANSITIONING row with NO pending reload (an
        ordinary restart mid-flight, a manual takeover, ...) is NOT this
        method's own drain -- the carve-out above must not swallow every
        TRANSITIONING row, only the ones this method's own rollover reload
        produced. Tracking is wiped exactly as before."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
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
            monotonic=lambda: clock["now"],
        )

        service.run_once(now=_NOW)
        later = _NOW + timedelta(seconds=35)
        service.run_once(now=later)
        assert _pending_actions(store, "public") == ["reload"]

        # TRANSITIONING with NO pending_reload_since -- an unrelated
        # transition, not this method's own drain.
        store.write_state(
            EgressStateRow(
                channel_id="public",
                state="TRANSITIONING",
                current_source_label="Council Meeting",
                current_proof_event_id="ev-1",
                updated_at=_NOW,
            )
        )
        clock["now"] += 50.0
        service.run_once(now=later)
        assert _pending_actions(store, "public") == []

        # Tracking was wiped: back on ON_AIR with the same proof event, this
        # is a fresh horizon establishment (no immediate dispatch), not a
        # continuation of the earlier undelivered-reload timer.
        self._on_air_state(store, "public", proof_event_id="ev-1")
        service.run_once(now=later)
        assert _pending_actions(store, "public") == []
        service.run_once(now=later + timedelta(seconds=390))
        assert _pending_actions(store, "public") == ["reload"]

    # -- Hostile-review B3: earlier, boundary-aligned trigger ------------------

    def test_rollover_waits_for_the_last_segment_on_a_multi_segment_plan(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        # Three 10-minute segments (30 min total) already loaded -- the last
        # segment does not begin until 20 minutes in, comfortably past the
        # 120s-before-end floor (28 min in). The trigger must wait for that
        # last-segment boundary, not fire the moment the plan is established.
        plan = EgressSourcePlan(
            channel_id="public",
            segments=[
                EgressSourceSegment(
                    label=f"Program {i}",
                    path="C:/media/program.ts",
                    duration_seconds=600.0,
                    kind="program",
                    source_ref=f"seg-{i}",
                )
                for i in range(3)
            ],
        )
        calls = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return plan

        service = ChannelAutomationService(
            store, daemon, provider, settings=ChannelAutomationSettings()
        )

        service.run_once(now=_NOW)  # establish: end in 1800s, last segment at +1200s
        assert calls["n"] == 1

        # 10 minutes in -- nowhere near the last segment or the 120s floor.
        service.run_once(now=_NOW + timedelta(seconds=600))
        assert calls["n"] == 1
        assert _pending_actions(store, "public") == []

        # 19 minutes in -- still one minute short of the last-segment boundary.
        service.run_once(now=_NOW + timedelta(seconds=1140))
        assert calls["n"] == 1

        # 20 minutes in -- the last segment begins now; the trigger fires and
        # re-queries the schedule. The fake provider always returns the same
        # fixed-duration plan regardless of when it is asked (unlike the real
        # join-in-progress-aware ScheduleSourcePlanProvider), so a later query
        # necessarily projects further into the future than the original --
        # exactly the same "schedule continues further" shape the other
        # rollover tests use to trigger a dispatch. What this test actually
        # pins is the TIMING: no re-query at all before the boundary.
        service.run_once(now=_NOW + timedelta(seconds=1200))
        assert calls["n"] == 2
        assert _pending_actions(store, "public") == ["reload"]

    def test_service_wires_the_120s_lead_floor_into_rollover_trigger_at(self) -> None:
        """``_check_plan_rollover`` computes its trigger via
        ``reload_policy.rollover_trigger_at``, passing the service's
        ``_ROLLOVER_MIN_LEAD_SECONDS`` as the floor. Pinned directly against
        the (gi-free, independently unit-tested) pure function rather than
        end-to-end, since a plan with a long single segment has no earlier
        last-segment-start candidate to exercise the floor against -- the
        floor's own behavior is ``reload_policy``'s responsibility; this pins
        that the two stay wired together."""
        from civiccast.egress.gst.reload_policy import rollover_trigger_at

        plan_end_at = _NOW + timedelta(seconds=1800)  # a 30-minute single segment
        last_segment_start_at = _NOW  # the only segment starts at plan start
        trigger_at = rollover_trigger_at(
            plan_end_at=plan_end_at,
            last_segment_start_at=last_segment_start_at,
            min_lead_seconds=ChannelAutomationService._ROLLOVER_MIN_LEAD_SECONDS,
        )
        assert trigger_at == last_segment_start_at  # the earlier candidate wins
        assert ChannelAutomationService._ROLLOVER_MIN_LEAD_SECONDS == 120.0

    # -- Rollover horizon guards (tester finding, 2026-09-05) -----------------
    #
    # A live tester observed ``_check_plan_rollover`` dispatch a reload while
    # logging "the live plan ends in -1208s" (a stale, already-past horizon),
    # and separately dispatch on a "schedule continues 0s further" advance --
    # the epsilon-less ``fresh_end <= plan_end_at`` check let a near-zero
    # advance through, paying for a full synchronous prepare
    # (``daemon._try_content_reload``) for no real extension.

    def test_no_rollover_when_the_tracked_horizon_has_already_passed(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        calls = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return _plan_with_duration("public", 40.0)

        service = ChannelAutomationService(
            store, daemon, provider, settings=ChannelAutomationSettings()
        )

        service.run_once(now=_NOW)  # establish horizon: plan ends 40s from now
        assert calls["n"] == 1

        # A tick arrives long after the tracked plan's projected end (a missed
        # poll, a paused process, or a control-plane stall) -- remaining time
        # is negative. Dispatching a rollover here would extend an already-
        # wrong projection; the guard skips it and leaves the channel to the
        # slate-replan/EOS path instead of re-querying the schedule.
        much_later = _NOW + timedelta(seconds=1250)
        service.run_once(now=much_later)
        assert _pending_actions(store, "public") == []
        assert calls["n"] == 1  # never re-queried the schedule for a stale horizon

        # The stale horizon was discarded (not just skipped-in-place, per the
        # coordinator's redo): a later tick re-establishes a fresh, correct
        # projection from "now", and a rollover fires again once THAT
        # projection's own boundary is reached -- the mechanism recovers
        # rather than staying stuck on the first bad projection forever.
        reestablish_at = much_later + timedelta(seconds=1)
        service.run_once(now=reestablish_at)
        assert calls["n"] == 2  # re-established fresh
        assert _pending_actions(store, "public") == []

        dispatch_at = reestablish_at + timedelta(seconds=35)  # >= 20s min-lead advance
        service.run_once(now=dispatch_at)
        assert _pending_actions(store, "public") == ["reload"]

    @pytest.mark.parametrize(
        ("second_plan_seconds", "expect_dispatch"),
        [
            # 40s plan, min lead = min(120, 0.5*40) = 20s.
            pytest.param(15.4, False, id="0.4s_advance_below_the_lead"),
            pytest.param(35.0, True, id="one_full_lead_of_advance"),
        ],
    )
    def test_rollover_requires_a_full_lead_of_advance_before_dispatching(
        self, second_plan_seconds: float, expect_dispatch: bool
    ) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        calls = {"n": 0}
        later = _NOW + timedelta(seconds=25)  # inside the boundary-aligned trigger

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return _plan_with_duration("public", 40.0 if calls["n"] == 1 else second_plan_seconds)

        service = ChannelAutomationService(
            store, daemon, provider, settings=ChannelAutomationSettings()
        )

        service.run_once(now=_NOW)  # establish: 40s plan
        service.run_once(now=later)

        assert _pending_actions(store, "public") == (["reload"] if expect_dispatch else [])


class TestRolloverCadence:
    """Hostile-review fix (2026-09-05): D43 (#170) and this PR's first pass at
    D45 both encoded a premise that was never the shipped shape. D43's
    ``PLAN_MIN_SECONDS=1800`` (a 60-segment, 1800-second plan for 30-second
    schedule items) is reverted -- see ``source_plan.py``. What a
    30-second-item schedule actually builds now is an 8-segment, 240-second
    plan (``max_segments=8``), and these tests exercise the REAL
    ``ChannelAutomationService`` against that shape (and a longer one) using
    ``_HorizonAwareDaemon``/``_plan_with_segments`` -- the same dispatched-
    plan-horizon fixtures ``TestRolloverHorizonComesFromTheDispatchedPlan``
    uses, which is what the real ``EgressDaemon`` (not a re-query-only fake)
    gives the service to work with in production.
    """

    def _on_air_state(
        self, store: InMemoryEgressStore, channel_id: str, *, proof_event_id: str
    ) -> None:
        store.write_state(
            EgressStateRow(
                channel_id=channel_id,
                state="ON_AIR",
                current_source_label="Program",
                current_proof_event_id=proof_event_id,
                updated_at=_NOW,
            )
        )

    def _simulate(
        self,
        durations: tuple[float, ...],
        *,
        total_ticks: float,
        step: float = 2.0,
        min_interval_override: Callable[[float], float] | None = None,
    ) -> tuple[list[float], int]:
        """Tick a real ``ChannelAutomationService`` (backed by
        ``_HorizonAwareDaemon``, mirroring how the real ``EgressDaemon``
        reports what it actually dispatched) through ``total_ticks`` seconds
        of the real 2-second poll cadence, and return every tick a rollover
        reload was dispatched, plus how many times the source-plan provider
        was called. ``min_interval_override``, when given, replaces
        ``_rollover_min_interval_seconds`` entirely -- used to reproduce a
        prior (buggy) floor formula for comparison against the shipped one."""

        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _HorizonAwareDaemon(live_channels={"public"})
        # The plan actually on air from the channel's initial start.
        daemon.dispatched["public"] = ("ev-1", durations, False)
        calls = {"n": 0}

        def provider(cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return _plan_with_segments(cid, durations, source_ref_prefix=f"call{calls['n']}")

        service = ChannelAutomationService(
            store,
            daemon,
            provider,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )
        if min_interval_override is not None:
            service._rollover_min_interval_seconds = min_interval_override  # type: ignore[method-assign]

        dispatch_times: list[float] = []
        tick = 0.0
        ev_n = 1
        while tick < total_ticks:
            clock["now"] = 1000.0 + tick
            service.run_once(now=_NOW + timedelta(seconds=tick))
            if _pending_actions(store, "public") == ["reload"]:
                dispatch_times.append(tick)
                ev_n += 1
                new_ev = f"ev-{ev_n}"
                # The daemon executes the reload: it re-fetches the plan (the
                # same call a real _try_content_reload makes) and records it
                # as dispatched, DEFERRED (the channel is ON_AIR with no
                # manual override, so reload_policy.should_defer_switch is
                # True) -- this is what lets automation's next horizon be
                # dated from the OUTGOING leg's own end.
                daemon.dispatched["public"] = (new_ev, durations, True)
                self._on_air_state(store, "public", proof_event_id=new_ev)
            tick += step
        return dispatch_times, calls["n"]

    def test_thirty_second_items_roll_over_every_240_seconds_well_before_eos(
        self,
    ) -> None:
        """The regression this whole pass exists for, in its shipped shape:
        an 8-segment, 30-second-item plan is 240 seconds. The first rollover
        fires at the boundary-aligned trigger (120s -- ``_ROLLOVER_MIN_LEAD_
        SECONDS`` before the 240s end), and each later one fires 240s after
        the last -- always 120s (comfortably >= 100s) before that plan's own
        end, never at or after it. No FALLBACK_SLATE/EOS boundary is ever
        reached: every dispatch lands well inside the plan it is extending.
        """
        dispatch_times, calls = self._simulate((30.0,) * 8, total_ticks=1200)

        assert dispatch_times == [120.0, 360.0, 600.0, 840.0, 1080.0]
        # Each dispatch is 120s ahead of the plan boundary it is extending
        # (dispatch N's plan ends at 240*(N+1)) -- well over the 100s floor
        # this test exists to pin.
        for index, dispatch_at in enumerate(dispatch_times):
            plan_end_at = 240.0 * (index + 1)
            assert plan_end_at - dispatch_at >= 100.0
        # Not re-queried on every poll tick: once to establish (from the
        # dispatched plan, no provider call needed) is free; each trigger
        # re-queries once to confirm there's more schedule to roll onto.
        assert calls == len(dispatch_times)

    def test_sixty_seven_second_items_roll_over_at_416_of_536(self) -> None:
        """A different item length is not a special case: an 8-segment,
        67-second-item plan is 536 seconds, and the same boundary-aligned
        120s lead applies -- the first rollover fires at 416s (536 - 120),
        with 120s of runway before EOS."""
        dispatch_times, _calls = self._simulate((67.0,) * 8, total_ticks=1700)

        assert dispatch_times == [416.0, 952.0, 1488.0]
        for index, dispatch_at in enumerate(dispatch_times):
            plan_end_at = 536.0 * (index + 1)
            assert plan_end_at - dispatch_at >= 100.0

    def test_a_very_short_plan_still_rolls_over_before_its_own_end(self) -> None:
        """Item 3's regression case: an 8x3s (24-second) plan.

        Hostile-review fix (NEW-3, 2026-09-05): the shipped
        ``_rollover_min_interval_seconds`` floor alone was not enough --
        with a flat 120s ``_ROLLOVER_MIN_LEAD_SECONDS``,
        ``rollover_trigger_at`` still landed at or after a plan this short
        actually ends (``plan_end_at - 120`` is deep in the plan's own
        past), so dispatches happened but at/after EOS. Scaling the LEAD
        the same way (``_rollover_min_lead_seconds`` -- half the plan's
        duration, clamped at the historic 120s ceiling) fixes this too:
        every rollover now lands with real runway to spare, not just
        "eventually, somehow, still dispatching."

        MEASURED with both fixes shipped: a rollover every 24s (at 12s,
        36s, 60s, ...), each with a lead of exactly 12s -- half the plan's
        24-second life -- over the boundary it is extending."""
        dispatch_times, _calls = self._simulate((3.0,) * 8, total_ticks=300)

        assert len(dispatch_times) >= 5, dispatch_times

        def leads(dispatch_times: list[float]) -> list[float]:
            return [
                24.0 * (index + 1) - dispatch_at for index, dispatch_at in enumerate(dispatch_times)
            ]

        plan_leads = leads(dispatch_times)
        # The real invariant this test exists to pin: every dispatch lands
        # with meaningful runway before the plan it is extending actually
        # ends -- never "eventually dispatches, but after EOS."
        assert all(lead >= 0.25 * 24.0 for lead in plan_leads), plan_leads

    def test_the_flat_floor_bug_the_scaled_floor_fixes(self) -> None:
        """The CHANGELOG-cited measurement, reproduced directly: against an
        8x30s (240-second) plan, a flat 300s floor (D43's original value)
        dispatches every 300s while the boundary-aligned lead shrinks each
        cycle -- 120s, 60s, then 0s. The shipped, scaled floor (used by every
        other test in this class) keeps that lead at a steady ~120s
        indefinitely instead.

        Rollover horizon guard update (tester finding, 2026-09-05, redone
        after a hostile review of the first fix): the flat floor's shrinking
        lead is still demonstrated all the way through a NEGATIVE lead --
        the horizon guard (``automation.py``'s "remaining <= 0" check) does
        NOT stop the flat floor's cadence from ever going negative; it pops
        the stale tracked horizon so the NEXT tick re-establishes a fresh
        one (from "now", since ``switch_deferred`` has no earlier
        ``previous_end_at`` to anchor to once the horizon is gone) instead
        of dispatching against a projection already proven wrong. The flat
        floor's OWN cadence (every 300s) still re-arrives at a boundary the
        fresh projection cannot outrun for long, so the same shrinking-lead
        failure recurs -- rollovers keep firing, but at an increasingly
        negative lead, exactly like the un-guarded original bug. The guard's
        job is narrower than "fix the flat floor" (the scaled floor already
        does that): it only stops ONE bad dispatch from extending an
        already-known-wrong number, and proves a rollover fires again once a
        correct projection is back in place."""

        def flat_300s_floor(_planned_seconds: float) -> float:
            return 300.0

        buggy_dispatches, _ = self._simulate(
            (30.0,) * 8, total_ticks=1800, min_interval_override=flat_300s_floor
        )
        fixed_dispatches, _ = self._simulate((30.0,) * 8, total_ticks=1800)

        def leads(dispatch_times: list[float]) -> list[float]:
            return [
                240.0 * (index + 1) - dispatch_at
                for index, dispatch_at in enumerate(dispatch_times)
            ]

        buggy_leads = leads(buggy_dispatches)
        fixed_leads = leads(fixed_dispatches)

        assert buggy_dispatches == [120.0, 420.0, 842.0, 1142.0, 1564.0]
        assert min(buggy_leads) < 0  # the trigger arrives at/after EOS
        # But the mechanism keeps working: rollovers keep firing after the
        # horizon is discarded and re-established, rather than getting stuck
        # forever on the first stale projection.
        assert len(buggy_dispatches) > 2

        assert fixed_dispatches[:5] == [120.0, 360.0, 600.0, 840.0, 1080.0]
        assert all(lead >= 100.0 for lead in fixed_leads)

    def test_a_short_plan_cannot_dispatch_faster_than_its_scaled_minimum_interval(
        self,
    ) -> None:
        """D45: the CADENCE floor now scales with the plan actually on air
        (``_rollover_min_interval_seconds``) instead of a fixed 300s -- a flat
        300s floor is longer than the lifetime of a short plan (e.g. an
        8-segment, 30-second-item plan is only 240s), which would silently
        starve every rollover after the first until the engine hits EOS and
        restarts. For a 100-second plan the scaled floor is 50s (half the
        plan, clamped to the 30s-300s range): still a real floor under the
        cadence, but one a short plan can actually live inside."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        plans = {"n": 0}

        # n=1 establishes a 100s baseline; n=3 re-establishes another 100s
        # baseline after the first reload lands. n=2/4/5 return a much
        # LARGER duration so the min-lead-advance guard is cleared by a wide
        # margin regardless of how much real time elapsed -- this decouples
        # "is the guard satisfied" from "is the cadence floor satisfied" so
        # the floor-blocked tick below discriminates the FLOOR specifically
        # (coordinator redo note: the floor tests must not accidentally also
        # be testing the min-lead guard at its own boundary).
        def provider(_cid: str) -> EgressSourcePlan:
            plans["n"] += 1
            duration = 100.0 if plans["n"] in (1, 3) else 300.0
            return _plan_with_duration("public", duration, source_ref=f"seg-{plans['n']}")

        service = ChannelAutomationService(
            store,
            daemon,
            provider,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )
        assert service._rollover_min_interval_seconds(100.0) == 50.0

        # Establish a 100s horizon (a 100s plan is already inside its own
        # 120s lead floor -- the trigger fires from the first tick), then
        # check once the schedule has advanced well beyond it.
        service.run_once(now=_NOW)
        clock["now"] += 55.0
        service.run_once(now=_NOW + timedelta(seconds=55))
        assert _pending_actions(store, "public") == ["reload"]

        # The reload lands -> a fresh proof event -> a fresh 100s horizon,
        # re-established on this tick (establish-only: never dispatches).
        self._on_air_state(store, "public", proof_event_id="ev-2")
        clock["now"] += 1.0
        service.run_once(now=_NOW + timedelta(seconds=56))
        assert _pending_actions(store, "public") == []

        # Within the scaled cadence floor (< 50s since the dispatch, on the
        # MONOTONIC clock): no dispatch -- even though the schedule advance
        # here (n=4 returns 300s, comfortably clearing the 50s min-lead
        # guard on its own) proves this block is the cadence floor, not the
        # min-lead guard.
        clock["now"] += 40.0
        service.run_once(now=_NOW + timedelta(seconds=96))
        assert _pending_actions(store, "public") == []

        # Past the scaled floor (60s since the dispatch, monotonic) AND a
        # full rollover lead of schedule advance since the re-establish: the
        # next one is allowed through -- well before this 100-second plan
        # would otherwise reach EOS.
        clock["now"] += 20.0
        service.run_once(now=_NOW + timedelta(seconds=116))
        assert _pending_actions(store, "public") == ["reload"]

    def test_the_scaled_interval_never_exceeds_the_historic_ceiling(self) -> None:
        """A long plan (>= 600s) is unaffected by D45: the scaled floor
        clamps back down to the historic flat 300s, same as before. A short
        plan's floor is always HALF its own duration, never a flat 30s
        (paired with the real-dispatch behavioral tests above, which show
        what this number actually does to the automation's cadence)."""
        assert ChannelAutomationService._ROLLOVER_MIN_INTERVAL_SECONDS == 300.0
        service = ChannelAutomationService(
            InMemoryEgressStore(),
            _FakeDaemon(),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
        )
        assert service._rollover_min_interval_seconds(1800.0) == 300.0
        assert service._rollover_min_interval_seconds(10.0) == 5.0

    def test_the_scaled_interval_never_exceeds_half_a_24_second_plan(self) -> None:
        """Item 3's exact regression case: an intermediate version of this
        fix floored the interval at a flat 30s (``max(30.0, 0.5 *
        planned_seconds)``), which for a very short plan is LONGER than the
        plan's entire life.

        MEASURED (with the shipped, ALSO-scaled lead --
        ``_rollover_min_lead_seconds``, NEW-3 -- in place; a real dispatch
        simulation, not a one-off unit check): an 8x3s (24-second) plan with
        that flat 30s floor still dispatches ten times in this window (at
        12s, 42s, 72s, ... 282s), NOT "exactly one rollover, ever" -- but the
        boundary-aligned lead shrinks every cycle (12s, 6s, 0s, then
        negative from the fourth rollover on), so once it turns negative
        the trigger is arriving at or after the plan's real end: the same
        failure mode this whole mechanism exists to prevent, just at a
        smaller scale and slower to show up than "one dispatch and then
        nothing." The fixed floor (``_ROLLOVER_MIN_INTERVAL_FLOOR_SECONDS``
        = 1.0, a trivial epsilon) must never return more than half of
        ``planned_seconds`` -- see
        ``test_a_very_short_plan_still_rolls_over_before_its_own_end`` above
        for the shipped floor's actual (positive-lead, indefinite) cadence."""
        service = ChannelAutomationService(
            InMemoryEgressStore(),
            _FakeDaemon(),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
        )
        assert service._rollover_min_interval_seconds(24.0) == 12.0
        assert service._rollover_min_interval_seconds(24.0) <= 0.5 * 24.0

    def test_the_interval_floor_is_cleared_when_the_channel_leaves_the_air(self) -> None:
        """The floor governs EXTENSIONS of a live plan. A channel that goes
        dark and comes back must not be throttled by an earlier rollover --
        the slate replan and auto-start paths are unaffected."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_duration(cid, 150.0),
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

        # 150s plan -> scaled min-lead/floor = min(120 or 300, 0.5*150) = 75s.
        service.run_once(now=_NOW)
        clock["now"] += 10.0
        service.run_once(now=_NOW + timedelta(seconds=80))
        assert _pending_actions(store, "public") == ["reload"]

        # Off air and back on again, only 15s later on the monotonic clock --
        # comfortably INSIDE the 75s scaled floor were it not cleared.
        store.write_state(EgressStateRow(channel_id="public", state="STOPPED", updated_at=_NOW))
        clock["now"] += 5.0
        service.run_once(now=_NOW + timedelta(seconds=90))
        self._on_air_state(store, "public", proof_event_id="ev-2")
        clock["now"] += 5.0
        service.run_once(now=_NOW + timedelta(seconds=91))  # re-establishes the horizon
        assert _pending_actions(store, "public") == []

        # WELL past a full rollover lead of schedule advance since the
        # re-establish (100s, comfortably above the 75s min-lead so this
        # isn't right at that guard's own boundary) -- the interval floor
        # from before going off air must not still be throttling this (only
        # 15s elapsed on the MONOTONIC clock since the earlier dispatch).
        clock["now"] += 5.0
        service.run_once(now=_NOW + timedelta(seconds=191))
        assert _pending_actions(store, "public") == ["reload"]


class TestPerChannelLatchIndependence:
    """CA-4: N channels in one pass with fully independent state/latches.

    Renamed from TestThreeChannelConcurrency (audit TEST-010): no
    concurrency is exercised here - the pass is sequential by design and
    these tests pin per-channel latch independence within one pass."""

    def _three_channel_store(self) -> InMemoryEgressStore:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public", auto_start=True))
        store.upsert_config(_config("education", auto_start=True))
        store.upsert_config(_config("government", auto_start=False))
        return store

    def test_one_pass_drives_all_enabled_channels_independently(self) -> None:
        store = self._three_channel_store()
        daemon = _FakeDaemon(live_channels={"education"})
        service = ChannelAutomationService(
            store, daemon, lambda _cid: None, settings=ChannelAutomationSettings()
        )

        seen = service.run_once(now=_NOW)

        assert seen == ["education", "government", "public"]
        assert daemon.processed == ["education", "government", "public"]
        # Only the dark auto_start channel gets a start; the live one and
        # the manual one are untouched.
        assert _pending_actions(store, "public") == ["start"]
        assert _pending_actions(store, "education") == []
        assert _pending_actions(store, "government") == []

    def test_one_channel_crash_restarts_only_that_channel(self) -> None:
        store = self._three_channel_store()
        daemon = _FakeDaemon(live_channels={"public", "education"})
        service = ChannelAutomationService(
            store, daemon, lambda _cid: None, settings=ChannelAutomationSettings()
        )
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []
        assert _pending_actions(store, "education") == []

        # public's encoder dies; education stays live.
        daemon.live_channels.discard("public")
        service.run_once(now=_NOW)

        assert _pending_actions(store, "public") == ["start"]
        assert _pending_actions(store, "education") == []
        assert _pending_actions(store, "government") == []

    def test_slate_replan_latches_are_per_channel(self) -> None:
        store = self._three_channel_store()
        for channel_id in ("public", "education"):
            store.write_state(
                EgressStateRow(channel_id=channel_id, state="FALLBACK_SLATE", updated_at=_NOW)
            )
        daemon = _FakeDaemon(live_channels={"public", "education", "government"})
        # Only education has a playable plan.
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan(cid) if cid == "education" else None,
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)

        assert _pending_actions(store, "education") == ["reload"]
        assert _pending_actions(store, "public") == []
        assert _pending_actions(store, "government") == []


class TestAutomationRollup:
    """CA-4: the System Health rollup of auto_start channel states."""

    def test_states_map_to_on_air_slate_and_dark(self) -> None:
        from civiccast.egress.automation import summarize_automation

        store = InMemoryEgressStore()
        store.upsert_config(_config("public", auto_start=True))
        store.upsert_config(_config("education", auto_start=True))
        store.upsert_config(_config("government", auto_start=True))
        store.upsert_config(_config("manual", auto_start=False))
        store.upsert_config(_config("disabled", enabled=False, auto_start=True))
        store.write_state(EgressStateRow(channel_id="public", state="ON_AIR", updated_at=_NOW))
        store.write_state(
            EgressStateRow(channel_id="education", state="FALLBACK_SLATE", updated_at=_NOW)
        )
        # government has no state row at all -> dark.

        rollup = summarize_automation(store)

        assert rollup.automated == 3
        assert rollup.on_air == 1
        assert rollup.on_slate == 1
        assert rollup.dark == ["government"]

    def test_error_and_stopped_states_are_dark(self) -> None:
        from civiccast.egress.automation import summarize_automation

        store = InMemoryEgressStore()
        store.upsert_config(_config("public", auto_start=True))
        store.write_state(EgressStateRow(channel_id="public", state="ERROR", updated_at=_NOW))

        assert summarize_automation(store).dark == ["public"]


class TestSettings:
    def test_from_env_validates_mode_and_poll(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_CHANNEL_AUTOMATION", "sometimes")
        with pytest.raises(ValueError, match="CIVICCAST_CHANNEL_AUTOMATION"):
            ChannelAutomationSettings.from_env()

        monkeypatch.setenv("CIVICCAST_CHANNEL_AUTOMATION", "off")
        monkeypatch.setenv("CIVICCAST_CHANNEL_AUTOMATION_POLL_SECONDS", "0")
        with pytest.raises(ValueError, match="positive"):
            ChannelAutomationSettings.from_env()

        monkeypatch.setenv("CIVICCAST_CHANNEL_AUTOMATION_POLL_SECONDS", "5")
        settings = ChannelAutomationSettings.from_env()
        assert settings.mode == "off"
        assert settings.poll_seconds == 5.0

        monkeypatch.delenv("CIVICCAST_CHANNEL_AUTOMATION")
        monkeypatch.delenv("CIVICCAST_CHANNEL_AUTOMATION_POLL_SECONDS")
        assert ChannelAutomationSettings.from_env().mode == "inline"


class TestNdiRelay:
    """Issue #116: the automation pass supervises per-channel NDI relays."""

    @staticmethod
    def _ndi_config(channel_id: str = "public") -> EgressConfig:
        return _config(channel_id).model_copy(
            update={
                "ndi_relay_name": "CivicCast Public",
                "sinks": [
                    EgressSinkSpec(
                        kind="udp-ts",
                        label="Cable headend",
                        uri="udp://127.0.0.1:23101",
                        extra_output_args=["-muxrate", "8000k"],
                    )
                ],
            }
        )

    class _FakeRelay:
        def __init__(self, channel_id: str, ndi_name: str, source_uri: str) -> None:
            from civiccast.egress.ndi_relay import NdiRelayStatus

            self.channel_id = channel_id
            self.ndi_name = ndi_name
            self.source_uri = source_uri
            self.ensured = 0
            self.stopped = False
            self._status = NdiRelayStatus(
                channel_id=channel_id, ndi_name=ndi_name, state="running", pid=99
            )

        def ensure_running(self):  # type: ignore[no-untyped-def]
            self.ensured += 1
            return self._status

        def stop(self) -> None:
            self.stopped = True

        def status(self):  # type: ignore[no-untyped-def]
            return self._status

    def test_named_channel_gets_one_supervised_relay(self) -> None:
        from civiccast.egress.ndi_relay import clear_relay_statuses, get_relay_status

        clear_relay_statuses()
        store = InMemoryEgressStore()
        store.upsert_config(self._ndi_config())
        created: list[TestNdiRelay._FakeRelay] = []

        def factory(*, channel_id, ndi_name, source_uri):  # type: ignore[no-untyped-def]
            relay = self._FakeRelay(channel_id, ndi_name, source_uri)
            created.append(relay)
            return relay

        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            ndi_supervisor_factory=factory,
        )

        service.run_once(now=_NOW)
        service.run_once(now=_NOW)

        assert len(created) == 1
        assert created[0].source_uri == "udp://127.0.0.1:23101"
        assert created[0].ensured == 2
        status = get_relay_status("public")
        assert status is not None and status.state == "running"

    def test_clearing_the_name_stops_the_relay(self) -> None:
        from civiccast.egress.ndi_relay import clear_relay_statuses, get_relay_status

        clear_relay_statuses()
        store = InMemoryEgressStore()
        store.upsert_config(self._ndi_config())
        created: list[TestNdiRelay._FakeRelay] = []

        def factory(*, channel_id, ndi_name, source_uri):  # type: ignore[no-untyped-def]
            relay = self._FakeRelay(channel_id, ndi_name, source_uri)
            created.append(relay)
            return relay

        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            ndi_supervisor_factory=factory,
        )
        service.run_once(now=_NOW)
        assert created[0].ensured == 1

        store.upsert_config(self._ndi_config().model_copy(update={"ndi_relay_name": None}))
        service.run_once(now=_NOW)

        assert created[0].stopped is True
        assert get_relay_status("public") is None

    def test_channel_without_udp_sink_reports_blocked(self) -> None:
        from civiccast.egress.ndi_relay import clear_relay_statuses, get_relay_status

        clear_relay_statuses()
        store = InMemoryEgressStore()
        store.upsert_config(_config("public").model_copy(update={"ndi_relay_name": "X"}))

        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            ndi_supervisor_factory=lambda **kw: pytest.fail("must not spawn"),
        )
        service.run_once(now=_NOW)

        status = get_relay_status("public")
        assert status is not None
        assert status.state == "blocked"
        assert "udp" in status.next_step.lower()


class TestSdiRelay:
    """Issue #117: the automation pass supervises per-channel SDI relays."""

    @staticmethod
    def _sdi_config(channel_id: str = "public") -> EgressConfig:
        return _config(channel_id).model_copy(
            update={
                "sdi_relay_device": "DeckLink Mini Monitor 4K",
                "sinks": [
                    EgressSinkSpec(
                        kind="udp-ts",
                        label="Cable headend",
                        uri="udp://127.0.0.1:23101",
                        extra_output_args=["-muxrate", "8000k"],
                    )
                ],
            }
        )

    class _FakeRelay:
        def __init__(self, channel_id: str, device: str, source_uri: str) -> None:
            from civiccast.egress.sdi_relay import SdiRelayStatus

            self.channel_id = channel_id
            self.device = device
            self.source_uri = source_uri
            self.ensured = 0
            self.stopped = False
            self._status = SdiRelayStatus(
                channel_id=channel_id, device=device, state="running", pid=99
            )

        def ensure_running(self):  # type: ignore[no-untyped-def]
            self.ensured += 1
            return self._status

        def stop(self) -> None:
            self.stopped = True

        def status(self):  # type: ignore[no-untyped-def]
            return self._status

    def test_configured_channel_gets_one_supervised_relay(self) -> None:
        from civiccast.egress.sdi_relay import clear_relay_statuses, get_relay_status

        clear_relay_statuses()
        store = InMemoryEgressStore()
        store.upsert_config(self._sdi_config())
        created: list[TestSdiRelay._FakeRelay] = []

        def factory(*, channel_id, device, source_uri):  # type: ignore[no-untyped-def]
            relay = self._FakeRelay(channel_id, device, source_uri)
            created.append(relay)
            return relay

        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            sdi_supervisor_factory=factory,
        )

        service.run_once(now=_NOW)
        service.run_once(now=_NOW)

        assert len(created) == 1
        assert created[0].source_uri == "udp://127.0.0.1:23101"
        assert created[0].device == "DeckLink Mini Monitor 4K"
        assert created[0].ensured == 2
        status = get_relay_status("public")
        assert status is not None and status.state == "running"

    def test_clearing_the_device_stops_the_relay(self) -> None:
        from civiccast.egress.sdi_relay import clear_relay_statuses, get_relay_status

        clear_relay_statuses()
        store = InMemoryEgressStore()
        store.upsert_config(self._sdi_config())
        created: list[TestSdiRelay._FakeRelay] = []

        def factory(*, channel_id, device, source_uri):  # type: ignore[no-untyped-def]
            relay = self._FakeRelay(channel_id, device, source_uri)
            created.append(relay)
            return relay

        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            sdi_supervisor_factory=factory,
        )
        service.run_once(now=_NOW)
        assert created[0].ensured == 1

        store.upsert_config(self._sdi_config().model_copy(update={"sdi_relay_device": None}))
        service.run_once(now=_NOW)

        assert created[0].stopped is True
        assert get_relay_status("public") is None

    def test_channel_without_udp_sink_reports_blocked(self) -> None:
        from civiccast.egress.sdi_relay import clear_relay_statuses, get_relay_status

        clear_relay_statuses()
        store = InMemoryEgressStore()
        store.upsert_config(_config("public").model_copy(update={"sdi_relay_device": "DeckLink"}))

        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            sdi_supervisor_factory=lambda **kw: pytest.fail("must not spawn"),
        )
        service.run_once(now=_NOW)

        status = get_relay_status("public")
        assert status is not None
        assert status.state == "blocked"
        assert "udp" in status.next_step.lower()

    def test_device_change_replaces_the_relay(self) -> None:
        from civiccast.egress.sdi_relay import clear_relay_statuses

        clear_relay_statuses()
        store = InMemoryEgressStore()
        store.upsert_config(self._sdi_config())
        created: list[TestSdiRelay._FakeRelay] = []

        def factory(*, channel_id, device, source_uri):  # type: ignore[no-untyped-def]
            relay = self._FakeRelay(channel_id, device, source_uri)
            created.append(relay)
            return relay

        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            sdi_supervisor_factory=factory,
        )
        service.run_once(now=_NOW)
        store.upsert_config(
            self._sdi_config().model_copy(update={"sdi_relay_device": "DeckLink Duo 2"})
        )
        service.run_once(now=_NOW)

        assert len(created) == 2
        assert created[0].stopped is True
        assert created[1].device == "DeckLink Duo 2"


class TestPredecessorRelayReap:
    """Audit ENG-003: SDI/NDI relay processes were outside the orphan reap -
    after an unclean restart a dead server's relay holds the DeckLink card
    while the new relay backoff-loops forever. At automation boot, any
    pre-boot ffmpeg whose command line is a relay (-f decklink /
    -f libndi_newtek) is reaped."""

    def test_pre_boot_relay_processes_are_reaped(self) -> None:
        from civiccast.egress.automation import reap_predecessor_relays

        killed: list[tuple[int, float]] = []
        survivors = [
            # (pid, name, cmdline, created_at) - boot epoch is 1000.0
            (101, "ffmpeg.exe", "ffmpeg -i udp://127.0.0.1:23101 -f decklink DeckLink", 10.0),
            (102, "ffmpeg.exe", "ffmpeg -i udp://... -f libndi_newtek CivicCast", 20.0),
            (103, "ffmpeg.exe", "ffmpeg -i in.mp4 -f mpegts out.ts", 10.0),  # encoder, not relay
            (104, "ffmpeg.exe", "ffmpeg -i udp://... -f decklink X", 2000.0),  # post-boot
            (105, "notepad.exe", "notepad -f decklink", 10.0),  # not ffmpeg
        ]

        reap_predecessor_relays(
            boot_epoch=1000.0,
            scanner=lambda: list(survivors),
            terminator=lambda pid, created_at: killed.append((pid, created_at)),
        )

        assert killed == [(101, 10.0), (102, 20.0)]

    def test_reaped_relays_are_recorded_as_proof_events(self) -> None:
        # S9-4: when a store is given, each reap lands a durable coprocess-lifecycle
        # proof event — and a NON-relay process produces neither a reap nor an event.
        from civiccast.egress.automation import reap_predecessor_relays

        store = InMemoryEgressStore()
        survivors = [
            (102, "ffmpeg.exe", "ffmpeg -i udp://... -f libndi_newtek CivicCast", 20.0),
            (103, "ffmpeg.exe", "ffmpeg -i in.mp4 -f mpegts out.ts", 10.0),  # encoder, not a relay
        ]
        reaped = reap_predecessor_relays(
            boot_epoch=1000.0,
            scanner=lambda: list(survivors),
            terminator=lambda _pid, _ct: None,
            store=store,
        )
        assert reaped == [102]  # only the NDI relay, not the encoder
        events = store.recent_proof_events("egress-system", 10)
        assert len(events) == 1
        assert events[0].proof_boundary == "civiccast-egress-coprocess-lifecycle"
        assert "102" in events[0].source_path
        assert all("103" not in event.source_path for event in events)  # encoder never recorded

    def test_reap_without_store_still_reaps_but_emits_no_proof_events(self) -> None:
        # backward-compat: store omitted → prior behavior (reaps, no audit sink)
        from civiccast.egress.automation import reap_predecessor_relays

        reaped = reap_predecessor_relays(
            boot_epoch=1000.0,
            scanner=lambda: [(102, "ffmpeg.exe", "ffmpeg -f libndi_newtek X", 20.0)],
            terminator=lambda _pid, _ct: None,
        )
        assert reaped == [102]


class TestReloadChurnCooldown:
    """Audit ENG-002: a due program whose PREPARATION persistently fails
    (deleted/corrupt media) used to drive a reload->kill->slate cycle every
    ~2 ticks for the item's whole duration - a TS-reset storm worse than the
    one #154 fixed. Reloads get the same cooldown medicine as #152 starts."""

    def _service(self, store: InMemoryEgressStore, clock: dict) -> ChannelAutomationService:  # type: ignore[type-arg]
        return ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda _cid: _plan("public"),
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

    def _slate_state(self, store: InMemoryEgressStore, state: str) -> None:
        store.write_state(
            EgressStateRow(
                channel_id="public",
                state=state,  # type: ignore[arg-type]
                current_source_label="CivicCast slate",
                updated_at=_NOW,
            )
        )

    def test_prep_failure_flap_does_not_strobe_reloads(self) -> None:
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        service = self._service(store, clock)

        # Slate gap with a due plan: one reload.
        self._slate_state(store, "FALLBACK_SLATE")
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["reload"]

        # The daemon kills filler, the start fails preparation, the channel
        # flaps TRANSITIONING -> FALLBACK_SLATE (which used to clear the
        # one-shot latch). Within the cooldown: NO new reload.
        self._slate_state(store, "TRANSITIONING")
        clock["now"] += 2.0
        service.run_once(now=_NOW)
        self._slate_state(store, "FALLBACK_SLATE")
        clock["now"] += 2.0
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

        # Past the cooldown and still on slate with a due plan: retry.
        clock["now"] += 60.0
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["reload"]


class TestStartLatchRecovery:
    """Issue #152: a dark auto_start channel must be retried with bounded
    pacing, not exactly once - the one-shot latch deadlocked a channel for
    an hour during the CA-8 acceptance run."""

    def test_dark_channel_start_reissues_after_cooldown(self) -> None:
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public", auto_start=True))
        daemon = _FakeDaemon()  # never goes live: starts keep failing
        service = ChannelAutomationService(
            store,
            daemon,
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["start"]

        # Within the cooldown: no command storm.
        clock["now"] += 5.0
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

        # Past the cooldown and still dark: the driver tries again.
        clock["now"] += 60.0
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["start"]

    def test_live_channel_clears_the_retry_pacing(self) -> None:
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public", auto_start=True))
        daemon = _FakeDaemon(live_channels={"public"})
        service = ChannelAutomationService(
            store,
            daemon,
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == []

        # Channel drops: a start goes out immediately (no stale pacing).
        daemon.live_channels.clear()
        service.run_once(now=_NOW)
        assert _pending_actions(store, "public") == ["start"]


class TestRolloverHorizonComesFromTheDispatchedPlan:
    """Hostile-review (d): the rollover horizon must be derived from the plan the
    daemon ACTUALLY dispatched, not from a fresh call to the source plan provider.

    The provider re-windows from whatever schedule item is live at the moment of the
    call and caps the result at ``max_segments``, so calling it again returns a
    DIFFERENT segment list than the one on air. Summing that list and calling it "when
    the airing plan ends" can overshoot the real end -- and since
    ``rollover_trigger_at`` is computed from that number, the trigger then lands at or
    after the boundary it exists to get ahead of, which is the original EOS-restart
    defect wearing a different hat.

    Every case below uses MULTI-SEGMENT plans on purpose: with a single segment the
    plan's last-segment-start IS its start, so ``rollover_trigger_at`` returns the
    plan's own start time and every horizon -- right or wrong -- triggers on the next
    tick. A single-segment scenario cannot tell the two apart.
    """

    def _on_air(self, store: InMemoryEgressStore, channel_id: str, proof_event_id: str) -> None:
        store.write_state(
            EgressStateRow(
                channel_id=channel_id,
                state="ON_AIR",
                current_source_label="Council Meeting",
                current_proof_event_id=proof_event_id,
                updated_at=_NOW,
            )
        )

    #: The plan actually on air: 600s of first segment, then a 40s tail. Its real end
    #: is _NOW+640 and its boundary-aligned trigger is _NOW+520 (120s lead floor).
    _AIRING = (600.0, 40.0)
    #: What a re-query answers instead: the provider has re-windowed forward and is
    #: describing 1800s of schedule that is NOT the plan on air. Believing it puts the
    #: horizon at _NOW+1800 and the trigger at _NOW+900 -- 260s PAST the real end.
    _REQUERY = (900.0, 900.0)

    def test_an_over_reporting_re_query_no_longer_hides_an_imminent_boundary(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air(store, "public", "ev-1")
        daemon = _HorizonAwareDaemon(live_channels={"public"})
        daemon.dispatched["public"] = ("ev-1", self._AIRING, False)
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_segments(cid, self._REQUERY),
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)  # establishes the horizon from the DISPATCHED plan
        assert _pending_actions(store, "public") == []
        # _NOW+560 is past the airing plan's own trigger (_NOW+520) and still 80s
        # short of its end -- the whole point of a boundary-aligned rollover.
        service.run_once(now=_NOW + timedelta(seconds=560))
        assert _pending_actions(store, "public") == ["reload"]

    def test_the_legacy_re_query_would_have_slept_through_that_boundary(self) -> None:
        """The control for the test above: the SAME store, provider and clock, with a
        daemon that cannot report its dispatch. Nothing rolls over before the real end
        -- which is exactly the behaviour the fix replaces."""
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air(store, "public", "ev-1")
        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda cid: _plan_with_segments(cid, self._REQUERY),
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)
        service.run_once(now=_NOW + timedelta(seconds=560))
        assert _pending_actions(store, "public") == []

    def test_a_dispatch_record_for_a_different_proof_event_is_ignored(self) -> None:
        """A record the current proof event does not match is not evidence about what
        is on air now -- fall back to the legacy re-query rather than dating the
        horizon off a stale dispatch."""
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air(store, "public", "ev-2")
        daemon = _HorizonAwareDaemon(live_channels={"public"})
        daemon.dispatched["public"] = ("ev-1", self._AIRING, False)  # stale
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_segments(cid, self._REQUERY),
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)
        service.run_once(now=_NOW + timedelta(seconds=560))
        assert _pending_actions(store, "public") == []

    def test_a_deferred_rollover_plan_is_dated_from_the_OUTGOING_plan_s_end(self) -> None:
        """A boundary-aligned rollover plan does not start when it is dispatched: the
        engine holds it, prerolled, until the outgoing leg's own end
        (``switch_at_end_of_current``). Dating its horizon from the dispatch instant
        instead would put the projected end a whole rollover lead time early, and make
        the NEXT rollover fire before there was anything to roll onto."""
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air(store, "public", "ev-1")
        daemon = _HorizonAwareDaemon(live_channels={"public"})
        daemon.dispatched["public"] = ("ev-1", (500.0, 100.0), False)  # ends _NOW+600
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_segments(cid, (900.0, 900.0)),
            settings=ChannelAutomationSettings(),
        )
        service.run_once(now=_NOW)
        store.pop_pending_commands("public")

        # 500s in, a DEFERRED rollover lands: 300s of new content that will not begin
        # until the outgoing plan ends at _NOW+600, so it ends at _NOW+900 -- not at
        # (_NOW+500)+300 = _NOW+800.
        self._on_air(store, "public", "ev-2")
        daemon.dispatched["public"] = ("ev-2", (200.0, 100.0), True)
        service.run_once(now=_NOW + timedelta(seconds=500))
        assert _pending_actions(store, "public") == []

        # _NOW+700 is past the trigger a dispatch-instant horizon would have computed
        # (min(_NOW+700, _NOW+680) = _NOW+680) and short of the correct one
        # (min(_NOW+800, _NOW+780) = _NOW+780). Nothing may be dispatched here.
        service.run_once(now=_NOW + timedelta(seconds=700))
        assert _pending_actions(store, "public") == []

        # Past the correct trigger it rolls over as normal.
        service.run_once(now=_NOW + timedelta(seconds=800))
        assert _pending_actions(store, "public") == ["reload"]
