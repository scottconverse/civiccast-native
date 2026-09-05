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


class TestRolloverCadence:
    """D43 hardening (2026-09-05).

    With 30-second schedule slots the source plan was 8 segments / 240
    seconds (``source_plan.max_segments``), so ``rollover_trigger_at`` landed
    120 seconds in and this check would dispatch a reload roughly every two
    minutes PER CHANNEL -- and each dispatch runs ``SourcePreparer.prepare``
    synchronously on the automation thread (``daemon._try_content_reload``).

    Measured evidence, stated plainly: a 2-hour control-plane log from the
    real-hardware tester shows ZERO rollover dispatches and zero horizon
    establishments, so this fast cycle is NOT the cause of the CPU burn
    observed there. These are the two conservative bounds against it anyway:
    a plan window measured in seconds (``source_plan.PLAN_MIN_SECONDS``) and
    a hard per-channel minimum interval between dispatches.
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

    def _thirty_second_plan(self, channel_id: str) -> EgressSourcePlan:
        """What ``ScheduleSourcePlanProvider`` now builds from a schedule of
        30-second slots: 60 segments, 1800 seconds (``PLAN_MIN_SECONDS``)."""

        return EgressSourcePlan(
            channel_id=channel_id,
            segments=[
                EgressSourceSegment(
                    label=f"Item {index}",
                    path="C:/media/program.ts",
                    duration_seconds=30.0,
                    kind="program",
                    source_ref=f"item-{index}",
                )
                for index in range(60)
            ],
        )

    def test_thirty_second_items_no_longer_roll_over_every_two_minutes(self) -> None:
        """The regression this whole pass exists for: tick a channel through
        30 simulated minutes of 2-second poll intervals and count dispatches.

        The old behavior (a 240-second plan for this schedule) produced a
        rollover every ~120 seconds: ~14 in this window. With a 1800-second
        plan the trigger does not arrive until 1680 seconds in (the 120s lead
        floor is earlier than the last segment's start at 1770s), so exactly
        ONE rollover fires, at ~28 minutes.
        """
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        calls = {"n": 0}

        def provider(cid: str) -> EgressSourcePlan:
            # Like the real join-in-progress provider, a later call reaches
            # further into the schedule than an earlier one, so a rollover is
            # always available to dispatch if the trigger fires.
            calls["n"] += 1
            return self._thirty_second_plan(cid)

        service = ChannelAutomationService(
            store,
            daemon,
            provider,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

        dispatch_times: list[float] = []
        for tick in range(0, 1800, 2):  # 30 minutes at the real 2s poll cadence
            clock["now"] = 1000.0 + tick
            service.run_once(now=_NOW + timedelta(seconds=tick))
            if _pending_actions(store, "public") == ["reload"]:
                dispatch_times.append(float(tick))
                # The daemon applies the reload: a fresh proof event, which is
                # how the service learns the rollover landed.
                self._on_air_state(store, "public", proof_event_id=f"ev-{len(dispatch_times) + 1}")

        assert len(dispatch_times) == 1, dispatch_times
        # ~28 minutes in, not 2. The old code's first dispatch was at 120s.
        assert dispatch_times[0] >= 1600.0
        # And the schedule provider is not re-queried on every poll tick
        # either: establish the horizon, re-query at the trigger, re-establish
        # once the reload lands. Three calls in 900 ticks.
        assert calls["n"] == 3

    def test_a_short_plan_cannot_dispatch_faster_than_the_minimum_interval(self) -> None:
        """Belt-and-braces floor under the CADENCE, independent of the plan
        window: even if a plan comes back short (a nearly-exhausted schedule,
        a provider quirk), one channel may not dispatch rollovers closer
        together than ``_ROLLOVER_MIN_INTERVAL_SECONDS``."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _FakeDaemon(live_channels={"public"})
        plans = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            plans["n"] += 1
            return _plan_with_duration("public", 150.0, source_ref=f"seg-{plans['n']}")

        service = ChannelAutomationService(
            store,
            daemon,
            provider,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

        # Establish a 150s horizon, then trigger (a 150s plan is already
        # inside its own 120s lead floor).
        service.run_once(now=_NOW)
        service.run_once(now=_NOW + timedelta(seconds=1))
        assert _pending_actions(store, "public") == ["reload"]

        # The reload lands -> a fresh proof event -> a fresh 150s horizon that
        # is immediately inside its own lead floor again. Without the interval
        # floor this would dispatch again straight away, once per plan.
        for round_index in range(2, 6):
            self._on_air_state(store, "public", proof_event_id=f"ev-{round_index}")
            clock["now"] += 60.0
            service.run_once(now=_NOW + timedelta(seconds=60 * round_index))
            service.run_once(now=_NOW + timedelta(seconds=60 * round_index + 1))
            assert _pending_actions(store, "public") == []

        # Past the interval floor, the next one is allowed through.
        self._on_air_state(store, "public", proof_event_id="ev-9")
        clock["now"] += 120.0  # 360s since the dispatch, > the 300s floor
        service.run_once(now=_NOW + timedelta(seconds=400))
        service.run_once(now=_NOW + timedelta(seconds=401))
        assert _pending_actions(store, "public") == ["reload"]
        assert ChannelAutomationService._ROLLOVER_MIN_INTERVAL_SECONDS == 300.0

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

        service.run_once(now=_NOW)
        service.run_once(now=_NOW + timedelta(seconds=1))
        assert _pending_actions(store, "public") == ["reload"]

        # Off air and back on again, well inside the 300s interval.
        store.write_state(EgressStateRow(channel_id="public", state="STOPPED", updated_at=_NOW))
        clock["now"] += 10.0
        service.run_once(now=_NOW + timedelta(seconds=11))
        self._on_air_state(store, "public", proof_event_id="ev-2")
        clock["now"] += 10.0
        service.run_once(now=_NOW + timedelta(seconds=21))
        service.run_once(now=_NOW + timedelta(seconds=22))
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


def _plan_with_segments(channel_id: str, durations: tuple[float, ...]) -> EgressSourcePlan:
    return EgressSourcePlan(
        channel_id=channel_id,
        segments=[
            EgressSourceSegment(
                label=f"Program {n}",
                path=f"C:/media/program-{n}.ts",
                duration_seconds=duration,
                kind="program",
                source_ref=f"seg-{n}",
            )
            for n, duration in enumerate(durations)
        ],
    )


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
