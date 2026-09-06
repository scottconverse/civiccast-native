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
from itertools import pairwise

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


class _PendingReloadAwareDaemon(_FakeDaemon):
    """A daemon double that, like the real ``EgressDaemon`` (F1 redesign),
    can report an armed-but-not-yet-settled reload via
    ``has_pending_reload_settlement``."""

    def __init__(self, *, live_channels: set[str] | None = None) -> None:
        super().__init__(live_channels=live_channels)
        self.pending_channels: set[str] = set()

    def has_pending_reload_settlement(self, channel_id: str) -> bool:
        return channel_id in self.pending_channels


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

    def test_check_plan_rollover_records_the_plan_end_scoped_to_the_enqueued_commands_own_id(
        self,
    ) -> None:
        """Coordinator review, round 8, item 4: ``_check_plan_rollover``
        generates the reload command's id up front and must pass the EXACT
        same id to both ``record_rollover_plan_end`` and the ``_enqueue``
        call that dispatches it (round 7's whole point) -- nothing in the
        prior test suite pinned that the two ids actually agree, only that
        ``_enqueue`` was CALLED with *a* ``command_id`` keyword. If the two
        ever drifted apart, ``EgressDaemon._request_reload``'s command-id
        scoping would never match the command that actually drains, and the
        recorded ``plan_end_at`` would silently never be used at all --
        reintroducing dead air on an already-past horizon that should have
        cut immediately (see ``_rollover_plan_end_at``'s docstring)."""
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")

        class _RecordingDaemon(_FakeDaemon):
            def __init__(self) -> None:
                super().__init__(live_channels={"public"})
                self.recorded: list[tuple[str, datetime, str | None]] = []

            def record_rollover_plan_end(
                self, channel_id: str, plan_end_at: datetime, *, command_id: str | None
            ) -> None:
                self.recorded.append((channel_id, plan_end_at, command_id))

        daemon = _RecordingDaemon()
        calls = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return _plan_with_duration("public", 40.0 if calls["n"] == 1 else 400.0)

        service = ChannelAutomationService(
            store, daemon, provider, settings=ChannelAutomationSettings()
        )

        service.run_once(now=_NOW)  # establish the horizon: plan ends 40s from now
        later = _NOW + timedelta(seconds=15)
        service.run_once(now=later)  # inside the lookahead -> rollover dispatch

        assert len(daemon.recorded) == 1
        pending = store.pop_pending_commands("public")
        assert [command.action for command in pending] == ["reload"]
        recorded_channel_id, _recorded_plan_end_at, recorded_command_id = daemon.recorded[0]
        assert recorded_channel_id == "public"
        # The load-bearing assertion: the id EgressDaemon will see draining
        # this command must be the exact id the plan_end was scoped to.
        assert recorded_command_id is not None
        assert recorded_command_id == pending[0].command_id

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

    def test_rollover_never_retries_while_the_daemon_reports_a_pending_settlement(
        self,
    ) -> None:
        """Hostile-review follow-up, item 2 (F1 redesign): a DEFERRED switch's
        ``current_proof_event_id`` does not change until it actually SETTLES,
        which for an automation-driven ON_AIR extension can be ~120s+ after
        this dispatches it -- far longer than ``_ROLLOVER_ISSUED_TIMEOUT_
        SECONDS`` (45s). Without checking the daemon's own "armed, still
        settling" signal first, the retry-if-undelivered branch would fire
        every ~45s while a perfectly healthy deferred reload is still
        legitimately settling (re-preparing synchronously, superseding the
        still-armed leg, creating another prepared-plan directory each time).
        Proves: zero re-dispatches across a 120s-plus wait while the daemon
        reports pending, then a normal landing once it reports settled."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air_state(store, "public", proof_event_id="ev-1")
        daemon = _PendingReloadAwareDaemon(live_channels={"public"})
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

        service.run_once(now=_NOW)  # establish horizon: 40s plan
        later = _NOW + timedelta(seconds=35)
        service.run_once(now=later)  # trigger fires -> one reload dispatched
        assert calls["n"] == 2
        assert _pending_actions(store, "public") == ["reload"]

        # The daemon now reports this reload as armed and still settling.
        daemon.pending_channels.add("public")

        # 120 seconds pass (well past the 45s retry timeout) with the daemon
        # still reporting pending throughout -- NOT ONE re-dispatch.
        for _ in range(12):
            clock["now"] += 10.0
            service.run_once(now=later)
            assert _pending_actions(store, "public") == []
        assert calls["n"] == 2  # still just the one prepare call from the dispatch above

        # The reload finally settles: the daemon no longer reports it pending,
        # and (as the real EgressDaemon._commit_reload_settlement does)
        # current_proof_event_id changes to reflect the landed plan.
        daemon.pending_channels.discard("public")
        self._on_air_state(store, "public", proof_event_id="ev-2")
        clock["now"] += 10.0
        service.run_once(now=later)

        # Recognized as "a fresh plan just took air" (existing branch) -- the
        # horizon re-establishes from the NEW plan, no retry dispatched for
        # the now-landed one.
        assert _pending_actions(store, "public") == []

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
        dispatches with the boundary-aligned lead shrinking cycle over
        cycle until it goes negative -- the trigger arrives at or after the
        plan's real end and the engine would have reached EOS and
        restarted. The shipped, scaled floor (used by every other test in
        this class) keeps that lead at a steady ~120s indefinitely instead.

        Item 78 fix 2 (the stale-horizon guard in ``_check_plan_rollover``)
        changes the EXACT dispatch cadence the flat-floor bug produces here
        versus its original measurement: once a negative lead actually lands
        the tracked horizon on a ``plan_end_at`` at or before "now", this
        pass now discards it and re-establishes from the current dispatch
        rather than blindly dispatching another rollover against a target
        already behind wall clock -- see the two "was stale ... re-
        establishing" log lines this simulation now emits. That backstop
        bounds the damage (no runaway "one dispatch every single tick,
        forever") but it does NOT make the flat floor safe: the boundary-
        aligned lead still goes negative here, repeatedly and by a growing
        margin, because the floor itself is still wrong for this plan
        shape. The scaled floor below remains the real fix; this guard is
        defense-in-depth for whatever gets past it (a stalled automation
        pass, not merely a mistuned constant)."""

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

        assert buggy_dispatches == [120.0, 420.0, 840.0, 1140.0, 1560.0]
        assert buggy_leads == [120.0, 60.0, -120.0, -180.0, -360.0]
        assert min(buggy_leads) < 0  # the flat floor is still not safe

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

        def provider(_cid: str) -> EgressSourcePlan:
            plans["n"] += 1
            return _plan_with_duration("public", 100.0, source_ref=f"seg-{plans['n']}")

        service = ChannelAutomationService(
            store,
            daemon,
            provider,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )
        assert service._rollover_min_interval_seconds(100.0) == 50.0

        # Establish a 100s horizon, then trigger (a 100s plan is already
        # inside its own 120s lead floor).
        service.run_once(now=_NOW)
        service.run_once(now=_NOW + timedelta(seconds=1))
        assert _pending_actions(store, "public") == ["reload"]

        # The reload lands -> a fresh proof event -> a fresh 100s horizon that
        # is immediately inside its own lead floor again. Without the scaled
        # interval floor this would dispatch again straight away, once per
        # plan.
        self._on_air_state(store, "public", proof_event_id="ev-2")
        clock["now"] += 40.0  # 40s since the dispatch, < the 50s scaled floor
        service.run_once(now=_NOW + timedelta(seconds=41))
        service.run_once(now=_NOW + timedelta(seconds=42))
        assert _pending_actions(store, "public") == []

        # Past the scaled floor, the next one is allowed through -- well
        # before this 100-second plan would otherwise reach EOS.
        clock["now"] += 20.0  # 60s since the dispatch, > the 50s scaled floor
        service.run_once(now=_NOW + timedelta(seconds=61))
        service.run_once(now=_NOW + timedelta(seconds=62))
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


class TestPerChannelClockIsReadFreshEachIteration:
    """Item 78 fix 1: ``run_once()`` (no explicit ``now`` -- the shape
    ``run_forever`` actually uses in production) must read wall-clock time
    freshly for EACH channel's pass, not once for the whole scan. Reading it
    once meant a single channel's synchronous ``_start`` (``SourcePreparer``
    can block for minutes, per soak evidence) left every channel that poll
    tick -- including its own next tick -- computing rollover math against a
    timestamp that was already stale by however long the block lasted,
    freezing ``plan_end_at`` in the past and firing rollovers forever ("live
    plan ends in -698s")."""

    def test_now_is_read_once_per_channel_not_once_for_the_whole_pass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("a"))
        store.upsert_config(_config("b"))
        store.upsert_config(_config("c"))
        service = ChannelAutomationService(
            store,
            _FakeDaemon(),
            lambda _cid: None,
            settings=ChannelAutomationSettings(),
        )

        import civiccast.egress.automation as automation_module

        real_datetime = automation_module.datetime
        call_count = 0

        class _CountingDateTime(real_datetime):  # type: ignore[misc,valid-type]
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                nonlocal call_count
                call_count += 1
                return real_datetime.now(tz)

        monkeypatch.setattr(automation_module, "datetime", _CountingDateTime)

        service.run_once()  # no explicit `now` -- the real run_forever shape

        assert call_count == 3  # once per enabled channel, never once for the whole pass

    def test_the_blocking_channel_itself_sees_the_post_block_clock_not_a_stale_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Coordinator review, round 2: reading "now" once per channel is not
        enough if it is read at the TOP of that channel's own pass -- BEFORE
        ``daemon.process_once``, which is exactly where a channel's own
        synchronous ``_start`` (``SourcePreparer.prepare``) can block for
        minutes. The blocking channel must see the POST-block clock for its
        own ``_check_plan_rollover``, not the timestamp captured before the
        block. Channel "a" here blocks (advances a shared fake wall clock by
        2000s, longer than its own 1800s plan) inside ``process_once``;
        channel "b" never blocks. Both establish a horizon strictly in the
        future relative to the POST-block clock -- not the "-200s" a
        pre-block reading would have produced for "a"."""
        store = InMemoryEgressStore()
        store.upsert_config(_config("a"))
        store.upsert_config(_config("b"))

        def on_air(channel_id: str, proof_event_id: str) -> None:
            store.write_state(
                EgressStateRow(
                    channel_id=channel_id,
                    state="ON_AIR",
                    current_source_label="Program",
                    current_proof_event_id=proof_event_id,
                    updated_at=_NOW,
                )
            )

        on_air("a", "ev-a1")
        on_air("b", "ev-b1")

        import civiccast.egress.automation as automation_module

        wall_clock = {"now": _NOW}
        real_datetime = automation_module.datetime

        class _ControllableDateTime(real_datetime):  # type: ignore[misc,valid-type]
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return wall_clock["now"]

        monkeypatch.setattr(automation_module, "datetime", _ControllableDateTime)

        class _BlockingDaemon(_FakeDaemon):
            def process_once(self, channel_id: str) -> int:
                super().process_once(channel_id)
                if channel_id == "a":
                    # Simulate item 78's diagnosed ~915s SourcePreparer block
                    # (here 2000s -- longer than the 1800s plan below, so a
                    # stale pre-block "now" would establish an already-past
                    # horizon, not merely a short-lead one).
                    wall_clock["now"] = wall_clock["now"] + timedelta(seconds=2000)
                return 0

        daemon = _BlockingDaemon(live_channels={"a", "b"})
        service = ChannelAutomationService(
            store,
            daemon,
            lambda cid: _plan_with_duration(cid, 1800.0),
            settings=ChannelAutomationSettings(),
        )

        service.run_once()  # no explicit `now` -- the real run_forever shape

        post_block_now = wall_clock["now"]
        tracked_a = service._plan_horizon["a"]
        tracked_b = service._plan_horizon["b"]
        # A stale pre-block reading would have established plan_end_at at
        # _NOW+1800, which is 200s BEHIND post_block_now (_NOW+2000) -- the
        # exact "-200s" shape of the diagnosed bug. The fix must establish it
        # from the post-block clock instead, strictly in the future.
        assert tracked_a[1] > post_block_now
        assert tracked_a[1] == post_block_now + timedelta(seconds=1800)
        assert tracked_b[1] > post_block_now


class TestStaleRolloverHorizonIsReestablishedNotDispatchedAgainst:
    """Item 78 fix 2: once a tracked ``plan_end_at`` has slipped into the past
    (the channel's own automation pass blocked long enough that wall clock
    passed it by), the tracked horizon must be discarded and re-established
    from the CURRENT proof event/dispatch -- never dispatched against as if
    it were still a real future boundary. Dispatching against a stale,
    already-past ``plan_end_at`` is the exact frozen-horizon bug (soak
    evidence: "live plan ends in -698s", forever): the fresh plan the
    provider hands back always ends further in the future than a target
    stuck in the past, so every tick looks like a legitimate rollover and one
    fires every single poll, forever."""

    def test_a_stale_horizon_is_discarded_instead_of_driving_an_unthrottled_dispatch(
        self,
    ) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        store.write_state(
            EgressStateRow(
                channel_id="public",
                state="ON_AIR",
                current_source_label="Council Meeting",
                current_proof_event_id="ev-1",
                updated_at=_NOW,
            )
        )
        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda cid: _plan_with_duration(cid, 100.0),
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)  # establishes: ends at _NOW+100
        assert _pending_actions(store, "public") == []

        # A huge jump forward with NO proof-event change -- the shape a
        # long-blocked automation pass produces (item 78's diagnosed
        # scenario): the tracked plan_end_at (_NOW+100) is now far in the
        # past relative to "now". Without the fix, this dispatches a reload
        # (any fresh re-query trivially "ends later" than a target already
        # thousands of seconds in the past) -- every single tick, forever.
        far_future = _NOW + timedelta(seconds=5000)
        service.run_once(now=far_future)

        assert _pending_actions(store, "public") == []


class TestRolloverRetryDispatchTimestampIsClearedWithTheIssuedLatch:
    """Coordinator review, round 4, item 2(a): ``_rollover_retry_dispatched_at``
    must be cleared everywhere ``_rollover_issued`` itself is discarded (a
    landed rollover, or a discarded stale horizon) -- not only when the
    channel leaves the air. Without this, a stale retry timestamp left over
    from an earlier, already-resolved rollover sequence could incorrectly
    suppress the very FIRST retry of whatever rollover comes next, even
    though nothing about that next sequence has actually violated the 60s
    floor. These tests assert directly on the cleared state (white-box,
    deterministic) rather than threading a full establish/dispatch/retry/
    land timing chain through black-box behavior -- see
    ``TestRolloverRetryFloorMeasuredFromTheLastRetryNotTheOriginalDispatch``'s
    churn test for a black-box demonstration of the same clearing in a
    realistic relaunch scenario."""

    def _on_air(self, store: InMemoryEgressStore, channel_id: str, *, proof_event_id: str) -> None:
        store.write_state(
            EgressStateRow(
                channel_id=channel_id,
                state="ON_AIR",
                current_source_label="Council Meeting",
                current_proof_event_id=proof_event_id,
                updated_at=_NOW,
            )
        )

    def test_cleared_when_a_fresh_plan_takes_air(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air(store, "public", proof_event_id="ev-1")
        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda cid: _plan_with_duration(cid, 1800.0),
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)  # establish: ends far in the future
        assert _pending_actions(store, "public") == []

        # Simulate an earlier, already-resolved rollover retry sequence for
        # THIS channel having left a timestamp behind.
        service._rollover_retry_dispatched_at["public"] = service._monotonic()

        # A fresh proof event lands -- "a fresh plan just took air".
        self._on_air(store, "public", proof_event_id="ev-2")
        service.run_once(now=_NOW)

        assert service._rollover_retry_dispatched_at.get("public") is None

    def test_cleared_when_the_tracked_horizon_is_discarded_as_stale(self) -> None:
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air(store, "public", proof_event_id="ev-1")
        service = ChannelAutomationService(
            store,
            _FakeDaemon(live_channels={"public"}),
            lambda cid: _plan_with_duration(cid, 100.0),
            settings=ChannelAutomationSettings(),
        )

        service.run_once(now=_NOW)  # establish: ends at _NOW+100
        assert _pending_actions(store, "public") == []

        service._rollover_retry_dispatched_at["public"] = service._monotonic()

        # The wall clock jumps far past the tracked plan's own end -- the
        # horizon is stale and must be discarded/re-established (see
        # TestStaleRolloverHorizonIsReestablishedNotDispatchedAgainst above).
        far_future = _NOW + timedelta(seconds=5000)
        service.run_once(now=far_future)

        assert service._rollover_retry_dispatched_at.get("public") is None


class TestRolloverRetryRespectsAFloorAndAYoungWorkerGuard:
    """Item 78 fix 2 (second half): the B2 "reload never landed" retry path
    used to be fully exempt from any dispatch-cadence floor at all
    (deliberately -- "recovery, not cadence"), which meant a worker stuck
    crash-relaunching right after every reload got hit with an unthrottled
    re-arm about one second after every relaunch. Two independent guards now
    apply on the retry path only (the ordinary D45 per-plan cadence floor
    stays exempt on retry, as before): a flat minimum gap between retry
    dispatches, and a floor under how young the channel's current worker pid
    may be before another synchronous ``SourcePreparer.prepare`` is thrown at
    it."""

    def _on_air(
        self, store: InMemoryEgressStore, channel_id: str, *, proof_event_id: str, pid: int | None
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

    def test_the_floor_constants_match_the_spec(self) -> None:
        assert ChannelAutomationService._ROLLOVER_RETRY_MIN_INTERVAL_SECONDS == 60.0
        assert ChannelAutomationService._ROLLOVER_RETRY_MIN_WORKER_AGE_SECONDS == 60.0

    def test_retry_is_deferred_until_a_freshly_relaunched_worker_settles(self) -> None:
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air(store, "public", proof_event_id="ev-1", pid=111)
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

        service.run_once(now=_NOW)  # establishes the horizon; pid 111 first tracked
        later = _NOW + timedelta(seconds=35)
        service.run_once(now=later)  # dispatches the reload
        assert _pending_actions(store, "public") == ["reload"]

        # It never lands, AND (independently) the worker crashed and
        # relaunched with a NEW pid around the same time -- the process id
        # changed but the daemon has not confirmed a new source yet (the
        # proof event is unchanged).
        self._on_air(store, "public", proof_event_id="ev-1", pid=222)
        clock["now"] += 50.0  # past the 45s ISSUED_TIMEOUT
        service.run_once(now=later)
        # pid 222 has only been alive an instant by our tracking -- far
        # short of the 60s worker-age floor -- so the retry is deferred.
        assert _pending_actions(store, "public") == []
        assert calls["n"] == 2  # no extra prepare call while deferred

        # Once the pid has aged past the floor, the retry goes through.
        clock["now"] += 65.0
        service.run_once(now=later)
        assert _pending_actions(store, "public") == ["reload"]

    def test_an_unknown_pid_never_blocks_the_retry_indefinitely(self) -> None:
        """A bare test double / a state row with no pid information at all
        must never be treated as "just relaunched forever" -- see
        ``test_rollover_retries_once_if_the_dispatched_reload_never_lands``
        in ``TestPlanRollover``, which exercises this exact shape (pid always
        ``None``) and must keep passing unchanged."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        self._on_air(store, "public", proof_event_id="ev-1", pid=None)
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

        clock["now"] += 50.0  # past the 45s timeout (the retry-interval floor is a
        # no-op here: this is the FIRST retry, so _rollover_retry_dispatched_at
        # has nothing recorded yet to measure a gap from)
        service.run_once(now=later)
        assert _pending_actions(store, "public") == ["reload"]


class TestRolloverRetryFloorMeasuredFromTheLastRetryNotTheOriginalDispatch:
    """Coordinator review, round 2, item 4: ``_ROLLOVER_RETRY_MIN_INTERVAL_SECONDS``
    was previously measured from ``_rollover_dispatched_at`` (the ORIGINAL
    dispatch) -- dead code, since the retry branch is only ever entered
    after ``_ROLLOVER_ISSUED_TIMEOUT_SECONDS`` (45s) has already elapsed
    since that same origin, so a floor <= 45s measured from it can never
    bind. It is now measured from ``_rollover_retry_dispatched_at`` (the
    last RETRY specifically), making it a real storm limiter: a channel
    stuck retrying repeatedly is capped to one retry per
    ``_ROLLOVER_RETRY_MIN_INTERVAL_SECONDS`` (60s), not one every time the
    45s timeout re-arms."""

    def test_a_worker_relaunching_faster_than_its_own_trigger_delay_gets_no_rollover_during_the_churn(
        self,
    ) -> None:
        """Coordinator review, round 3, item F (round-4 doc correction, item
        2(c)): models a REAL worker relaunch -- a non-ON_AIR tick
        (``STARTING``) followed by ON_AIR again with a FRESH proof event and
        a new pid -- not merely a changed pid on an otherwise-unbroken
        ON_AIR/proof-event stream (the round-2 shape, which really only
        exercised the worker-pid-age guard in isolation and never any of
        the horizon-reset cleanup branches at all).

        What this test actually demonstrates: the "not ON_AIR" branch's
        horizon reset (``_plan_horizon``/``_rollover_issued``/
        ``_rollover_dispatched_at``/``_rollover_retry_dispatched_at`` all
        cleared, present since round 2 -- the ``STARTING`` tick on every
        relaunch cycle) -- NOT round 3 item E's specific addition (clearing
        ``_rollover_retry_dispatched_at`` on the "fresh plan just took air"
        and "stale horizon" branches). Because the ``STARTING`` tick always
        runs immediately before the landing tick in this exact sequence,
        the "fresh plan took air" branch's own clearing is REDUNDANT here --
        the value is already ``None`` by the time it runs. Item E's two
        clearings are covered directly (and non-redundantly) by
        ``TestRolloverRetryDispatchTimestampIsClearedWithTheIssuedLatch``
        above instead.

        The plan here is two segments (40s, 200s): its boundary-aligned
        trigger is 40s after establishment (the last segment's own start),
        deliberately longer than the ~25s a horizon gets to live between one
        relaunch's landing and the next relaunch's ``STARTING`` tick (30s
        apart). Every relaunch therefore wipes the tracked horizon via the
        "not ON_AIR" branch before it ever gets far enough to reach its own
        trigger. This is the exact degrade mode named in the CHANGELOG: a
        worker that relaunches faster than a rollover's own trigger delay
        never keeps a horizon tracked long enough to fire one at all while
        it keeps doing that -- not a hang, just a reversion to the pre-
        item-78 shape (the channel reaches its own EOS/crash cycle and the
        daemon's own crash back-off, untouched by this fix, owns the
        restart). Once the worker stabilizes (stops relaunching), the
        rollover mechanism gets a real chance to run: one dispatch at the
        trigger and, since it never lands here either, retries capped to
        the 60s floor -- the same steady-state behavior the round-2 version
        of this test proved."""
        clock = {"now": 1000.0}
        store = InMemoryEgressStore()
        store.upsert_config(_config("public"))
        daemon = _FakeDaemon(live_channels={"public"})
        calls = {"n": 0}

        def provider(_cid: str) -> EgressSourcePlan:
            calls["n"] += 1
            return _plan_with_segments(
                "public", (40.0, 200.0), source_ref_prefix=f"call{calls['n']}"
            )

        service = ChannelAutomationService(
            store,
            daemon,
            provider,
            settings=ChannelAutomationSettings(),
            monotonic=lambda: clock["now"],
        )

        def starting(pid: int) -> None:
            store.write_state(
                EgressStateRow(
                    channel_id="public",
                    state="STARTING",
                    current_proof_event_id=None,
                    updated_at=_NOW,
                    pid=pid,
                )
            )

        def on_air(pid: int, proof_event_id: str) -> None:
            store.write_state(
                EgressStateRow(
                    channel_id="public",
                    state="ON_AIR",
                    current_source_label="Council Meeting",
                    current_proof_event_id=proof_event_id,
                    updated_at=_NOW,
                    pid=pid,
                )
            )

        # Wall clock advances in lockstep with the monotonic clock (unlike
        # every OTHER test in this module, which pins "now" to a single
        # fixed instant) -- required here so the plan's own 40s-out trigger
        # is ever actually reached by wall clock at all once the churn ends;
        # a pinned "now" would leave ``now < trigger_at`` true forever.
        wall_now = _NOW
        on_air(pid=1, proof_event_id="ev-1")
        service.run_once(now=wall_now)  # establish: 240s plan, trigger 40s out

        dispatch_times: list[float] = []
        pid_counter = 1
        proof_counter = 1
        tick = 0.0
        step = 5.0
        last_relaunch_tick = 0.0
        pending_landing = False
        # Bounded to stay within the ONE plan lifetime (240s) the LAST
        # relaunch (landing by tick 250) establishes -- long enough to
        # observe the churn producing nothing, then the original dispatch
        # and several retries, short enough that the item-2 stale-horizon
        # guard never re-establishes a SECOND lifetime and confuses the
        # gap-spacing assertions below with another original-dispatch reset.
        while tick < 460.0:
            clock["now"] += step
            wall_now = wall_now + timedelta(seconds=step)
            tick += step
            if pending_landing:
                # The relaunch "lands" the next tick after STARTING -- back
                # ON_AIR with a fresh proof event, same new pid.
                on_air(pid=pid_counter, proof_event_id=f"ev-{proof_counter}")
                pending_landing = False
            elif tick <= 250.0 and tick - last_relaunch_tick >= 30.0:
                pid_counter += 1
                proof_counter += 1
                last_relaunch_tick = tick
                starting(pid=pid_counter)
                pending_landing = True
            service.run_once(now=wall_now)
            if _pending_actions(store, "public") == ["reload"]:
                dispatch_times.append(clock["now"])

        # No rollover ever got far enough to dispatch during the churn (every
        # relaunch wipes the horizon well before its own 40s trigger delay).
        assert all(t > 1000.0 + 250.0 for t in dispatch_times), dispatch_times
        # The original dispatch plus several retries land once the worker
        # stabilizes -- not a vacuous "zero dispatches ever" result.
        assert len(dispatch_times) >= 3, dispatch_times
        gaps = [b - a for a, b in pairwise(dispatch_times)]
        # The FIRST gap is original-dispatch -> first-retry, legitimately
        # governed by the 45s ISSUED_TIMEOUT alone (the interval floor is a
        # no-op for a channel's very first retry -- nothing recorded yet to
        # measure a gap from). Every gap AFTER that is retry -> retry, and
        # must respect the 60s interval floor -- the storm limiter this fix
        # exists to make meaningful.
        assert gaps[0] >= 45.0, gaps
        assert all(gap >= 60.0 for gap in gaps[1:]), gaps
