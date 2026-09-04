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
    def __init__(self, *, live_channels: set[str] | None = None) -> None:
        self.live_channels = live_channels or set()
        self.processed: list[str] = []

    def has_live_process(self, channel_id: str) -> bool:
        return channel_id in self.live_channels

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
