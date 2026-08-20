# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S24 underwriting data layer — models + UnderwritingStore + migration 0057.

Covers, against an in-memory SQLite + a tmp-file SQLite migration probe:

* pydantic validation on every entity (Slug pattern, channels uniqueness +
  non-empty, date order, frequency-cap range, FCC ack default-False);
* store CRUD round-trips with timezone-aware datetimes round-tripping
  through ``_as_utc``;
* ``delete_spot`` cascade — deleting a spot also drops its flights AND every
  placement that referenced those flights (loose-ref convention; no DB FK
  would catch the orphan otherwise);
* ``delete_flight`` cascade — deleting a flight drops its placements;
* ``list_flights(active_on=...)`` filter window;
* ``list_placements(channel + half-open [from_ts,to_ts))`` filter;
* migration ``0057_underwriting_spots`` up + down (drops only the three S24
  tables, leaves 0055's ``as_run_log`` intact).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.underwriting.models import (
    SpotFlight,
    SpotFlightInput,
    SpotPlacement,
    UnderwritingSpot,
)
from civiccast.underwriting.store import (
    FlightNotFoundError,
    SpotNotFoundError,
    UnderwritingStore,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[UnderwritingStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'u.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield UnderwritingStore(factory)
    finally:
        eng.dispose()


# --- models --------------------------------------------------------------


class TestUnderwritingSpotModel:
    def test_valid_spot(self) -> None:
        s = UnderwritingSpot(
            spot_id="spot-acme-001",
            station_id="civiccast-station",
            underwriter="Acme Co.",
            asset_id="asset-acme-15",
        )
        assert s.fcc_compliant_ack is False
        assert s.review_notes is None

    def test_underwriter_min_length(self) -> None:
        with pytest.raises(ValueError):
            UnderwritingSpot(
                spot_id="spot-a",
                station_id="sta",
                underwriter="",
                asset_id="asset-1",
            )

    def test_uppercase_spot_id_rejected_by_slug(self) -> None:
        with pytest.raises(ValueError):
            UnderwritingSpot(
                spot_id="Spot-Bad",
                station_id="sta",
                underwriter="X",
                asset_id="asset-1",
            )


class TestSpotFlightModel:
    def _today(self) -> date:
        return date(2026, 6, 1)

    def test_valid_flight(self) -> None:
        f = SpotFlight(
            flight_id="fl-a",
            spot_id="sp-a",
            start_date=self._today(),
            end_date=self._today() + timedelta(days=7),
            channels=["pub-1", "edu-1"],
        )
        # channels sorted-unique on validation
        assert f.channels == ["edu-1", "pub-1"]

    def test_empty_channels_rejected(self) -> None:
        with pytest.raises(ValueError):
            SpotFlight(
                flight_id="fl-a",
                spot_id="sp-a",
                start_date=self._today(),
                end_date=self._today(),
                channels=[],
            )

    def test_duplicate_channels_rejected(self) -> None:
        with pytest.raises(ValueError):
            SpotFlight(
                flight_id="fl-a",
                spot_id="sp-a",
                start_date=self._today(),
                end_date=self._today(),
                channels=["a", "a"],
            )

    def test_end_before_start_rejected(self) -> None:
        with pytest.raises(ValueError):
            SpotFlight(
                flight_id="fl-a",
                spot_id="sp-a",
                start_date=self._today() + timedelta(days=1),
                end_date=self._today(),
                channels=["pub-1"],
            )

    def test_frequency_cap_range(self) -> None:
        with pytest.raises(ValueError):
            SpotFlight(
                flight_id="fl-a",
                spot_id="sp-a",
                start_date=self._today(),
                end_date=self._today(),
                frequency_cap_per_day=0,
                channels=["pub-1"],
            )
        with pytest.raises(ValueError):
            SpotFlight(
                flight_id="fl-a",
                spot_id="sp-a",
                start_date=self._today(),
                end_date=self._today(),
                frequency_cap_per_day=1441,
                channels=["pub-1"],
            )


class TestSpotFlightInput:
    def test_input_sorts_channels(self) -> None:
        f = SpotFlightInput(
            flight_id="fl-a",
            spot_id="sp-a",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            channels=["pub-1", "edu-1", "gov-1"],
        )
        assert f.channels == ["edu-1", "gov-1", "pub-1"]

    def test_duplicate_channels_in_input_rejected(self) -> None:
        with pytest.raises(ValueError):
            SpotFlightInput(
                flight_id="fl-a",
                spot_id="sp-a",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 30),
                channels=["pub-1", "pub-1"],
            )


# --- store ---------------------------------------------------------------


def _spot(spot_id: str = "sp-a", **kw: object) -> UnderwritingSpot:
    return UnderwritingSpot(
        spot_id=spot_id,
        station_id="civiccast-station",
        underwriter=kw.get("underwriter", "Acme Co."),  # type: ignore[arg-type]
        asset_id=kw.get("asset_id", "asset-1"),  # type: ignore[arg-type]
        fcc_compliant_ack=kw.get("fcc_compliant_ack", False),  # type: ignore[arg-type]
    )


def _flight(flight_id: str = "fl-a", spot_id: str = "sp-a") -> SpotFlight:
    return SpotFlight(
        flight_id=flight_id,
        spot_id=spot_id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        frequency_cap_per_day=3,
        channels=["pub-1"],
    )


def _placement(placement_id: str = "pl-a", flight_id: str = "fl-a") -> SpotPlacement:
    return SpotPlacement(
        placement_id=placement_id,
        flight_id=flight_id,
        channel_id="pub-1",
        scheduled_at=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
        schedule_item_id="si-1",
    )


class TestStoreSpots:
    def test_upsert_then_get(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot())
        got = store.get_spot("sp-a")
        assert got is not None
        assert got.underwriter == "Acme Co."
        assert got.fcc_compliant_ack is False

    def test_upsert_is_idempotent(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot())
        store.upsert_spot(_spot(underwriter="Acme NEW"))
        got = store.get_spot("sp-a")
        assert got is not None
        assert got.underwriter == "Acme NEW"

    def test_list_spots_filters_to_station(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot("sp-a"))
        # different station
        other = UnderwritingSpot(
            spot_id="sp-b",
            station_id="other-station",
            underwriter="Other Co.",
            asset_id="asset-2",
        )
        store.upsert_spot(other)
        spots = store.list_spots("civiccast-station")
        assert [s.spot_id for s in spots] == ["sp-a"]

    def test_list_spots_filters_to_underwriter(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot("sp-a", underwriter="Acme Co."))
        store.upsert_spot(_spot("sp-b", underwriter="Other Co."))
        spots = store.list_spots("civiccast-station", underwriter="Acme Co.")
        assert [s.spot_id for s in spots] == ["sp-a"]

    def test_delete_spot_cascades_flights_and_placements(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot())
        store.upsert_flight(_flight())
        store.record_placement(_placement())
        store.delete_spot("sp-a")
        assert store.get_spot("sp-a") is None
        assert store.get_flight("fl-a") is None
        assert store.get_placement("pl-a") is None

    def test_delete_missing_spot_raises(self, store: UnderwritingStore) -> None:
        with pytest.raises(SpotNotFoundError):
            store.delete_spot("no-such-spot")


class TestStoreFlights:
    def test_round_trip(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot())
        store.upsert_flight(_flight())
        got = store.get_flight("fl-a")
        assert got is not None
        assert got.spot_id == "sp-a"
        assert got.channels == ["pub-1"]
        assert got.frequency_cap_per_day == 3

    def test_channels_round_trip_multi(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot())
        f = SpotFlight(
            flight_id="fl-b",
            spot_id="sp-a",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            channels=["pub-1", "edu-1", "gov-1"],
        )
        store.upsert_flight(f)
        got = store.get_flight("fl-b")
        assert got is not None
        assert got.channels == ["edu-1", "gov-1", "pub-1"]  # sorted-unique

    def test_list_flights_active_on_window(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot())
        store.upsert_flight(
            SpotFlight(
                flight_id="fl-early",
                spot_id="sp-a",
                start_date=date(2026, 6, 1),
                end_date=date(2026, 6, 7),
                channels=["pub-1"],
            )
        )
        store.upsert_flight(
            SpotFlight(
                flight_id="fl-late",
                spot_id="sp-a",
                start_date=date(2026, 6, 20),
                end_date=date(2026, 6, 30),
                channels=["pub-1"],
            )
        )
        fl_mid = store.list_flights(active_on=date(2026, 6, 15))
        assert fl_mid == []
        fl_early_day = store.list_flights(active_on=date(2026, 6, 1))
        assert [f.flight_id for f in fl_early_day] == ["fl-early"]
        fl_last_day = store.list_flights(active_on=date(2026, 6, 30))
        assert [f.flight_id for f in fl_last_day] == ["fl-late"]

    def test_delete_flight_cascades_placements(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot())
        store.upsert_flight(_flight())
        store.record_placement(_placement())
        store.delete_flight("fl-a")
        assert store.get_flight("fl-a") is None
        assert store.get_placement("pl-a") is None

    def test_delete_missing_flight_raises(self, store: UnderwritingStore) -> None:
        with pytest.raises(FlightNotFoundError):
            store.delete_flight("no-such-flight")


class TestStorePlacements:
    def _seed(self, store: UnderwritingStore) -> None:
        store.upsert_spot(_spot())
        store.upsert_flight(_flight())

    def test_record_then_get(self, store: UnderwritingStore) -> None:
        self._seed(store)
        store.record_placement(_placement())
        got = store.get_placement("pl-a")
        assert got is not None
        assert got.scheduled_at == datetime(2026, 6, 10, 18, 0, tzinfo=UTC)
        # tz must be UTC after round-trip (SQLite drops tz; _as_utc reattaches)
        assert got.scheduled_at.tzinfo is UTC

    def test_record_is_idempotent(self, store: UnderwritingStore) -> None:
        self._seed(store)
        store.record_placement(_placement())
        store.record_placement(
            SpotPlacement(
                placement_id="pl-a",
                flight_id="fl-a",
                channel_id="pub-1",
                scheduled_at=datetime(2026, 6, 11, 18, 0, tzinfo=UTC),
                schedule_item_id="si-1",
            )
        )
        got = store.get_placement("pl-a")
        assert got is not None
        assert got.scheduled_at == datetime(2026, 6, 11, 18, 0, tzinfo=UTC)

    def test_list_placements_window_and_channel(self, store: UnderwritingStore) -> None:
        self._seed(store)
        store.record_placement(
            SpotPlacement(
                placement_id="pl-1",
                flight_id="fl-a",
                channel_id="pub-1",
                scheduled_at=datetime(2026, 6, 10, 18, 0, tzinfo=UTC),
                schedule_item_id="si-1",
            )
        )
        store.record_placement(
            SpotPlacement(
                placement_id="pl-2",
                flight_id="fl-a",
                channel_id="edu-1",
                scheduled_at=datetime(2026, 6, 11, 18, 0, tzinfo=UTC),
                schedule_item_id="si-2",
            )
        )
        store.record_placement(
            SpotPlacement(
                placement_id="pl-3",
                flight_id="fl-a",
                channel_id="pub-1",
                scheduled_at=datetime(2026, 6, 12, 18, 0, tzinfo=UTC),
                schedule_item_id="si-3",
            )
        )
        # channel filter
        pub = store.list_placements(channel_id="pub-1")
        assert [p.placement_id for p in pub] == ["pl-1", "pl-3"]
        # half-open window
        window = store.list_placements(
            from_ts=datetime(2026, 6, 11, 0, 0, tzinfo=UTC),
            to_ts=datetime(2026, 6, 12, 0, 0, tzinfo=UTC),
        )
        assert [p.placement_id for p in window] == ["pl-2"]

    def test_delete_placements_for_flight(self, store: UnderwritingStore) -> None:
        self._seed(store)
        for i in range(3):
            store.record_placement(
                SpotPlacement(
                    placement_id=f"pl-{i}",
                    flight_id="fl-a",
                    channel_id="pub-1",
                    scheduled_at=datetime(2026, 6, 10 + i, 18, 0, tzinfo=UTC),
                    schedule_item_id=f"si-{i}",
                )
            )
        deleted = store.delete_placements_for_flight("fl-a")
        assert deleted == 3
        assert store.list_placements(flight_id="fl-a") == []


# --- migration 0057 ------------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestUnderwritingSpotsMigration:
    """0057_underwriting_spots creates its three tables on upgrade and drops
    exactly those on a single-step downgrade to 0055 (the parent), leaving
    0055's tables intact."""

    _TABLES = ("underwriting_spots", "spot_flights", "spot_placements")

    def test_upgrade_to_0057_lands_at_that_revision(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0057_underwriting_spots")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            with eng.connect() as conn:
                head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert head == "0057_underwriting_spots"
        finally:
            eng.dispose()

    def test_upgrade_creates_the_three_tables_and_indexes(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0057_underwriting_spots")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table), table
            spot_idx = {ix["name"] for ix in insp.get_indexes("underwriting_spots")}
            assert "ix_underwriting_spots_station" in spot_idx
            assert "ix_underwriting_spots_station_underwriter" in spot_idx
            assert "ix_underwriting_spots_asset" in spot_idx
            flight_idx = {ix["name"] for ix in insp.get_indexes("spot_flights")}
            assert "ix_spot_flights_spot" in flight_idx
            assert "ix_spot_flights_window" in flight_idx
            placement_idx = {ix["name"] for ix in insp.get_indexes("spot_placements")}
            assert "ix_spot_placements_channel_scheduled" in placement_idx
            assert "ix_spot_placements_flight" in placement_idx
            assert "ix_spot_placements_schedule_item" in placement_idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_three_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0057_underwriting_spots")
        command.downgrade(cfg, "0055_asrun_and_epg")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table), table
            # 0055's tables survive the single-step downgrade.
            assert insp.has_table("as_run_log")
            assert insp.has_table("epg_export_configs")
        finally:
            eng.dispose()
