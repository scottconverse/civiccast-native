# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S24 slice 2 — trafficking compiler unit tests.

Covers, against an in-memory-SQLite-backed ``UnderwritingStore``:

* empty-candidates fast path;
* channel filter;
* flight start/end window;
* DC-5 FCC-ack gate;
* DC-4 per-day cap, including in-run accumulation (the compiler counts the
  placements it chose earlier in the same call, not just persisted rows);
* DC-1 daypart filter — both in-window and out-of-window matched on local
  wall-clock minute-of-day + weekday, plus the dangling-ref-drops-flight
  defensive default;
* picker fairness (least-aired wins) + tiebreaker (earliest created_at);
* idempotent re-run (same candidates → same placements, no duplicates);
* parametrized SkipReason hierarchy.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.autoschedule_models import ScheduleBlock
from civiccast.underwriting.models import (
    SpotFlight,
    UnderwritingSpot,
)
from civiccast.underwriting.service import (
    CandidateBreakSlot,
    TraffickingCompiler,
)
from civiccast.underwriting.store import UnderwritingStore

# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[UnderwritingStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'svc.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield UnderwritingStore(factory)
    finally:
        eng.dispose()


# --- helpers ----------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _make_spot(
    store: UnderwritingStore,
    spot_id: str,
    *,
    underwriter: str = "Acme Co.",
    fcc_ack: bool = True,
) -> UnderwritingSpot:
    return store.upsert_spot(
        UnderwritingSpot(
            spot_id=spot_id,
            station_id="civiccast-station",
            underwriter=underwriter,
            asset_id=f"asset-{spot_id}",
            fcc_compliant_ack=fcc_ack,
        )
    )


def _make_flight(
    store: UnderwritingStore,
    flight_id: str,
    *,
    spot_id: str,
    start_date: date = date(2026, 6, 1),
    end_date: date = date(2026, 6, 30),
    cap: int | None = None,
    daypart_block_id: str | None = None,
    channels: list[str] | None = None,
    created_at: datetime | None = None,
) -> SpotFlight:
    return store.upsert_flight(
        SpotFlight(
            flight_id=flight_id,
            spot_id=spot_id,
            start_date=start_date,
            end_date=end_date,
            frequency_cap_per_day=cap,
            daypart_block_id=daypart_block_id,
            channels=channels or ["channel-a"],
            created_at=created_at or _now(),
        )
    )


def _slot(
    channel: str,
    when: datetime,
    schedule_item_id: str,
) -> CandidateBreakSlot:
    return CandidateBreakSlot(
        channel_id=channel,
        scheduled_at=when,
        schedule_item_id=schedule_item_id,
    )


def _block(
    block_id: str,
    *,
    start_minute: int,
    end_minute: int,
    days_of_week: list[int],
) -> ScheduleBlock:
    now = _now()
    return ScheduleBlock(
        block_id=block_id,
        channel_id="channel-a",
        name=block_id,
        start_minute=start_minute,
        end_minute=end_minute,
        days_of_week=days_of_week,
        created_at=now,
        updated_at=now,
    )


# --- tests ------------------------------------------------------------------


class TestEmptyAndChannelFilter:
    def test_empty_candidates_returns_empty_result(self, store: UnderwritingStore) -> None:
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[])
        assert result.placements == []
        assert result.skipped == []
        assert result.for_date == date(2026, 6, 9)

    def test_channel_filter_drops_non_matching_flight(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-a")
        _make_flight(store, "flight-a", spot_id="spot-a", channels=["channel-a"])
        slot = _slot(
            "channel-b",
            datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
            "si-001",
        )
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert result.placements == []
        assert len(result.skipped) == 1
        assert result.skipped[0].reason == "no_active_flight_for_channel"


class TestFlightWindow:
    def test_flight_outside_date_window_dropped(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-a")
        # Flight runs in May, candidate is in June.
        _make_flight(
            store,
            "flight-a",
            spot_id="spot-a",
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 31),
            channels=["channel-a"],
        )
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-001")
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert result.placements == []
        assert result.skipped[0].reason == "no_active_flight_for_channel"


class TestFccAckGate:
    def test_require_fcc_ack_drops_unattested_spot(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-bad", fcc_ack=False)
        _make_flight(store, "flight-bad", spot_id="spot-bad", channels=["channel-a"])
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-001")
        compiler = TraffickingCompiler(store, require_fcc_ack=True)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert result.placements == []
        assert result.skipped[0].reason == "no_eligible_after_filters"

    def test_require_fcc_ack_keeps_attested_spot(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-good", fcc_ack=True)
        _make_flight(store, "flight-good", spot_id="spot-good", channels=["channel-a"])
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-001")
        compiler = TraffickingCompiler(store, require_fcc_ack=True)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert len(result.placements) == 1
        assert result.placements[0].flight_id == "flight-good"

    def test_fcc_ack_off_means_unattested_still_runs(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-bad", fcc_ack=False)
        _make_flight(store, "flight-bad", spot_id="spot-bad", channels=["channel-a"])
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-001")
        compiler = TraffickingCompiler(store, require_fcc_ack=False)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert len(result.placements) == 1


class TestFrequencyCap:
    def test_cap_of_two_allows_at_most_two_placements_per_day(
        self, store: UnderwritingStore
    ) -> None:
        _make_spot(store, "spot-a")
        _make_flight(
            store,
            "flight-a",
            spot_id="spot-a",
            channels=["channel-a"],
            cap=2,
        )
        slots = [
            _slot(
                "channel-a",
                datetime(2026, 6, 9, hour, 0, tzinfo=UTC),
                f"si-{hour:02d}",
            )
            for hour in (8, 12, 14, 18, 22)
        ]
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=slots)
        assert len(result.placements) == 2
        # The first two slots win; the remaining three skip "at cap".
        assert [p.schedule_item_id for p in result.placements] == ["si-08", "si-12"]
        assert [s.candidate.schedule_item_id for s in result.skipped] == [
            "si-14",
            "si-18",
            "si-22",
        ]
        for s in result.skipped:
            assert s.reason == "all_eligible_flights_at_cap"

    def test_cap_counts_persisted_plus_in_run(self, store: UnderwritingStore) -> None:
        """Two candidates resolving the same flight in ONE call cannot exceed the cap.

        Regression: counting only persisted placements would let a single-call
        burst exceed the cap because none of the just-chosen placements are
        committed until the call iterates further.
        """
        _make_spot(store, "spot-a")
        _make_flight(store, "flight-a", spot_id="spot-a", channels=["channel-a"], cap=1)
        slots = [
            _slot("channel-a", datetime(2026, 6, 9, 9, 0, tzinfo=UTC), "si-a"),
            _slot("channel-a", datetime(2026, 6, 9, 10, 0, tzinfo=UTC), "si-b"),
        ]
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=slots)
        assert len(result.placements) == 1
        assert len(result.skipped) == 1
        assert result.skipped[0].reason == "all_eligible_flights_at_cap"


class TestDaypart:
    """DC-1 daypart filter. Prime block is M-F 18:00-20:00 LOCAL.

    A flight tied to that block:
    * placed at 2026-06-09T17:00Z (Tue) with EST offset -300 → local 12:00
      Tue → outside the 18-20 window → filtered out;
    * placed at 2026-06-09T23:00Z (Tue) with EST offset -300 → local 18:00
      Tue → in-window → kept.
    """

    def _setup(self, store: UnderwritingStore) -> TraffickingCompiler:
        _make_spot(store, "spot-a")
        _make_flight(
            store,
            "flight-prime",
            spot_id="spot-a",
            channels=["channel-a"],
            daypart_block_id="db-prime",
        )

        def resolver(block_id: str) -> ScheduleBlock | None:
            if block_id == "db-prime":
                return _block(
                    "db-prime",
                    start_minute=18 * 60,
                    end_minute=20 * 60,
                    days_of_week=[0, 1, 2, 3, 4],
                )
            return None

        return TraffickingCompiler(store, daypart_resolver=resolver)

    def test_outside_local_window_dropped(self, store: UnderwritingStore) -> None:
        compiler = self._setup(store)
        # 2026-06-09 is a Tuesday. 17:00Z - 5h = 12:00 local Tue → outside 18-20.
        slot = _slot("channel-a", datetime(2026, 6, 9, 17, 0, tzinfo=UTC), "si-noon")
        result = compiler.compile_for_date(
            for_date=date(2026, 6, 9),
            candidates=[slot],
            local_tz_offset_minutes=-300,
        )
        assert result.placements == []
        assert result.skipped[0].reason == "all_eligible_flights_outside_daypart"

    def test_inside_local_window_kept(self, store: UnderwritingStore) -> None:
        compiler = self._setup(store)
        # 23:00Z - 5h = 18:00 local Tue → in 18-20 prime window.
        slot = _slot("channel-a", datetime(2026, 6, 9, 23, 0, tzinfo=UTC), "si-prime")
        result = compiler.compile_for_date(
            for_date=date(2026, 6, 9),
            candidates=[slot],
            local_tz_offset_minutes=-300,
        )
        assert len(result.placements) == 1
        assert result.placements[0].flight_id == "flight-prime"

    def test_resolver_returns_none_drops_flight(self, store: UnderwritingStore) -> None:
        """Dangling daypart_block_id → flight DROPPED (defensive default)."""
        _make_spot(store, "spot-a")
        _make_flight(
            store,
            "flight-dangling",
            spot_id="spot-a",
            channels=["channel-a"],
            daypart_block_id="db-missing",
        )

        def resolver(_block_id: str) -> ScheduleBlock | None:
            return None

        compiler = TraffickingCompiler(store, daypart_resolver=resolver)
        slot = _slot("channel-a", datetime(2026, 6, 9, 18, 0, tzinfo=UTC), "si-x")
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert result.placements == []
        assert result.skipped[0].reason == "all_eligible_flights_outside_daypart"

    def test_no_resolver_means_daypart_not_enforced(self, store: UnderwritingStore) -> None:
        """Caller didn't supply a resolver → daypart isn't enforceable → keep flight."""
        _make_spot(store, "spot-a")
        _make_flight(
            store,
            "flight-with-dp",
            spot_id="spot-a",
            channels=["channel-a"],
            daypart_block_id="db-prime",
        )
        slot = _slot("channel-a", datetime(2026, 6, 9, 3, 0, tzinfo=UTC), "si-x")
        compiler = TraffickingCompiler(store)  # no resolver
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert len(result.placements) == 1


class TestPickerFairness:
    def test_least_aired_flight_wins(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-a")
        _make_spot(store, "spot-b")
        t0 = datetime(2026, 5, 1, tzinfo=UTC)
        _make_flight(
            store,
            "flight-busy",
            spot_id="spot-a",
            channels=["channel-a"],
            created_at=t0,
        )
        _make_flight(
            store,
            "flight-quiet",
            spot_id="spot-b",
            channels=["channel-a"],
            created_at=t0,
        )
        # Pre-seed the busy flight with one historical placement so quiet wins.
        from civiccast.underwriting.models import SpotPlacement

        store.record_placement(
            SpotPlacement(
                placement_id="pl-seed",
                flight_id="flight-busy",
                channel_id="channel-a",
                scheduled_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
                schedule_item_id="si-seed",
            )
        )
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-pick")
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert len(result.placements) == 1
        assert result.placements[0].flight_id == "flight-quiet"

    def test_tiebreak_earliest_created_at_wins(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-a")
        _make_spot(store, "spot-b")
        _make_flight(
            store,
            "flight-late",
            spot_id="spot-a",
            channels=["channel-a"],
            created_at=datetime(2026, 5, 10, tzinfo=UTC),
        )
        _make_flight(
            store,
            "flight-early",
            spot_id="spot-b",
            channels=["channel-a"],
            created_at=datetime(2026, 5, 1, tzinfo=UTC),
        )
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-tie")
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert result.placements[0].flight_id == "flight-early"

    def test_in_run_lifetime_balances_picker_across_one_call(
        self, store: UnderwritingStore
    ) -> None:
        """Two equally-fresh flights, one call with two slots → each gets exactly one."""
        _make_spot(store, "spot-a")
        _make_spot(store, "spot-b")
        t0 = datetime(2026, 5, 1, tzinfo=UTC)
        _make_flight(store, "flight-aa", spot_id="spot-a", channels=["channel-a"], created_at=t0)
        _make_flight(store, "flight-bb", spot_id="spot-b", channels=["channel-a"], created_at=t0)
        slots = [
            _slot("channel-a", datetime(2026, 6, 9, 8, 0, tzinfo=UTC), "si-1"),
            _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-2"),
        ]
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=slots)
        flight_ids = sorted(p.flight_id for p in result.placements)
        assert flight_ids == ["flight-aa", "flight-bb"]


class TestIdempotence:
    def test_rerun_with_same_candidates_produces_same_placements(
        self, store: UnderwritingStore
    ) -> None:
        _make_spot(store, "spot-a")
        _make_flight(store, "flight-a", spot_id="spot-a", channels=["channel-a"])
        slots = [
            _slot("channel-a", datetime(2026, 6, 9, 8, 0, tzinfo=UTC), "si-1"),
            _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-2"),
        ]
        compiler = TraffickingCompiler(store)
        first = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=slots)
        second = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=slots)
        first_ids = sorted(p.placement_id for p in first.placements)
        second_ids = sorted(p.placement_id for p in second.placements)
        assert first_ids == second_ids
        # Persisted rows: exactly the same set, no duplicates.
        all_placements = store.list_placements()
        assert sorted(p.placement_id for p in all_placements) == first_ids
        assert len(all_placements) == len(first.placements)
        # Placement ids are deterministic on schedule_item_id.
        assert first_ids == ["pl-si-1", "pl-si-2"]


class TestSkipReasonHierarchy:
    """Parametrized end-to-end of each SkipReason."""

    @pytest.mark.parametrize(
        ("scenario", "expected_reason"),
        [
            ("no_channel_match", "no_active_flight_for_channel"),
            ("no_active_flight_for_date", "no_active_flight_for_channel"),
            ("fcc_ack_drops_all", "no_eligible_after_filters"),
            ("daypart_drops_all", "all_eligible_flights_outside_daypart"),
            ("cap_hit", "all_eligible_flights_at_cap"),
        ],
    )
    def test_skip_reason(
        self,
        store: UnderwritingStore,
        scenario: str,
        expected_reason: str,
    ) -> None:
        compiler_require_ack = False
        compiler_resolver = None
        if scenario == "no_channel_match":
            _make_spot(store, "spot-a")
            _make_flight(store, "flight-a", spot_id="spot-a", channels=["channel-a"])
            slots = [
                _slot(
                    "channel-other",
                    datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
                    "si-x",
                )
            ]
        elif scenario == "no_active_flight_for_date":
            _make_spot(store, "spot-a")
            _make_flight(
                store,
                "flight-a",
                spot_id="spot-a",
                channels=["channel-a"],
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 31),
            )
            slots = [
                _slot(
                    "channel-a",
                    datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
                    "si-x",
                )
            ]
        elif scenario == "fcc_ack_drops_all":
            _make_spot(store, "spot-a", fcc_ack=False)
            _make_flight(store, "flight-a", spot_id="spot-a", channels=["channel-a"])
            slots = [
                _slot(
                    "channel-a",
                    datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
                    "si-x",
                )
            ]
            compiler_require_ack = True
        elif scenario == "daypart_drops_all":
            _make_spot(store, "spot-a")
            _make_flight(
                store,
                "flight-a",
                spot_id="spot-a",
                channels=["channel-a"],
                daypart_block_id="db-prime",
            )

            def compiler_resolver(_bid: str) -> ScheduleBlock | None:
                return _block(
                    "db-prime",
                    start_minute=18 * 60,
                    end_minute=20 * 60,
                    days_of_week=[0, 1, 2, 3, 4],
                )

            slots = [
                _slot(
                    "channel-a",
                    datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
                    "si-x",
                )
            ]
        elif scenario == "cap_hit":
            _make_spot(store, "spot-a")
            _make_flight(
                store,
                "flight-a",
                spot_id="spot-a",
                channels=["channel-a"],
                cap=1,
            )
            slots = [
                _slot(
                    "channel-a",
                    datetime(2026, 6, 9, 8, 0, tzinfo=UTC),
                    "si-1",
                ),
                _slot(
                    "channel-a",
                    datetime(2026, 6, 9, 12, 0, tzinfo=UTC),
                    "si-2",
                ),
            ]
        else:
            raise AssertionError(scenario)

        compiler = TraffickingCompiler(
            store,
            daypart_resolver=compiler_resolver,
            require_fcc_ack=compiler_require_ack,
        )
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=slots)
        # The LAST candidate's skip reason is the one we assert on for cap_hit
        # (the first one will have been placed); for every other scenario, all
        # slots skip with the same reason.
        assert result.skipped, "expected at least one skipped slot in this scenario"
        assert result.skipped[-1].reason == expected_reason


class TestDateBoundaryInclusive:
    """Flight start_date/end_date are INCLUSIVE day bounds — confirm both edges."""

    def test_start_date_is_inclusive(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-a")
        _make_flight(
            store,
            "flight-a",
            spot_id="spot-a",
            channels=["channel-a"],
            start_date=date(2026, 6, 9),
            end_date=date(2026, 6, 30),
        )
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-edge")
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert len(result.placements) == 1

    def test_end_date_is_inclusive(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-a")
        _make_flight(
            store,
            "flight-a",
            spot_id="spot-a",
            channels=["channel-a"],
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 9),
        )
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-edge")
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert len(result.placements) == 1

    def test_day_after_end_date_excluded(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-a")
        _make_flight(
            store,
            "flight-a",
            spot_id="spot-a",
            channels=["channel-a"],
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 8),
        )
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-edge")
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert result.placements == []


class TestPlacementMaterialization:
    def test_placement_id_is_deterministic_on_schedule_item(self, store: UnderwritingStore) -> None:
        _make_spot(store, "spot-a")
        _make_flight(store, "flight-a", spot_id="spot-a", channels=["channel-a"])
        slot = _slot("channel-a", datetime(2026, 6, 9, 12, 0, tzinfo=UTC), "si-unique-001")
        compiler = TraffickingCompiler(store)
        result = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot])
        assert len(result.placements) == 1
        placement = result.placements[0]
        assert placement.placement_id == "pl-si-unique-001"
        assert placement.schedule_item_id == "si-unique-001"
        assert placement.channel_id == "channel-a"
        assert placement.flight_id == "flight-a"
        assert placement.scheduled_at == datetime(2026, 6, 9, 12, 0, tzinfo=UTC)


class TestUtcDayWindowCap:
    """The per-day cap counts UTC-midnight days. Document the boundary behavior."""

    def test_cap_resets_at_utc_midnight(self, store: UnderwritingStore) -> None:
        """Two slots one second on either side of UTC midnight count as different days.

        This is the documented behavior of slice 2: the cap window is
        UTC-midnight-to-UTC-midnight, NOT local-day. A station operator with
        a hard local-day compliance contract is a follow-up.
        """
        _make_spot(store, "spot-a")
        _make_flight(
            store,
            "flight-a",
            spot_id="spot-a",
            channels=["channel-a"],
            cap=1,
            start_date=date(2026, 6, 8),
            end_date=date(2026, 6, 10),
        )
        # Day 1: one placement at 23:59:59Z fills the cap for 2026-06-08.
        slot1 = _slot(
            "channel-a",
            datetime(2026, 6, 8, 23, 59, 59, tzinfo=UTC),
            "si-day1",
        )
        # Day 2: 00:00:01Z next UTC day is a new cap window.
        slot2 = _slot("channel-a", datetime(2026, 6, 9, 0, 0, 1, tzinfo=UTC), "si-day2")
        compiler = TraffickingCompiler(store)
        r1 = compiler.compile_for_date(for_date=date(2026, 6, 8), candidates=[slot1])
        r2 = compiler.compile_for_date(for_date=date(2026, 6, 9), candidates=[slot2])
        assert len(r1.placements) == 1
        assert len(r2.placements) == 1


# A tiny anchor so editors can't accidentally chop the bottom of the file.
_END = timedelta(0)
