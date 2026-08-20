# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S23 reporting data layer — models + ReportingStore + migration 0055.

SQLite-backed unit coverage; the live-Postgres full-chain head check lives in
tests/live/test_real_postgres.py. The 0055 migration's up/down reversibility is
asserted by TestAsRunAndEpgMigration via the real Alembic chain on SQLite.

Covers (spec §3/§6):
* the typed AsRunLogEntry + EpgExportConfig pydantic models (incl. the
  ``source_kind`` enum that reserves ``spot`` for S24, and the EPG ``format`` enum);
* store append/query of as-run entries by from/to/channel filters;
* EpgExportConfig CRUD;
* migration 0055 creates ``as_run_log`` + ``epg_export_configs`` with the report
  indexes and the DB-level CHECK constraints, and a single-step downgrade drops
  exactly those tables (0054's survive).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.reporting.models import AsRunLogEntry, EpgExportConfig
from civiccast.reporting.store import (
    EpgConfigNotFoundError,
    ReportingStore,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ReportingStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'reporting.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield ReportingStore(factory)
    finally:
        eng.dispose()


def _ts(hour: int, minute: int = 0, day: int = 1) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def _entry(entry_id: str = "ar_1", **kw: object) -> AsRunLogEntry:
    base: dict[str, object] = {
        "entry_id": entry_id,
        "station_id": "sta_main",
        "channel_id": "gov-ch12",
        "actual_start": _ts(9),
        "actual_end": _ts(10),
        "duration_s": 3600,
        "source_kind": "program",
    }
    base.update(kw)
    return AsRunLogEntry(**base)  # type: ignore[arg-type]


def _config(config_id: str = "epg_1", **kw: object) -> EpgExportConfig:
    base: dict[str, object] = {
        "config_id": config_id,
        "station_id": "sta_main",
        "channel_id": "gov-ch12",
        "format": "xmltv",
    }
    base.update(kw)
    return EpgExportConfig(**base)  # type: ignore[arg-type]


# --- pydantic models ---------------------------------------------------------


class TestAsRunModel:
    def test_defaults(self) -> None:
        e = _entry()
        # verified defaults True (backed by engine proof, not just intent).
        assert e.verified is True
        # optional planned-slot links default None (live/manual/filler).
        assert e.schedule_item_id is None
        assert e.asset_id is None
        assert e.scheduled_start is None

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            _entry(bogus="nope")  # type: ignore[call-arg]

    @pytest.mark.parametrize("kind", ["program", "filler", "live", "slate", "spot"])
    def test_accepts_every_source_kind_including_spot(self, kind: str) -> None:
        # 'spot' is a valid enum so S24 underwriting can populate it later, even
        # though no spot producer exists yet.
        e = _entry(source_kind=kind)
        assert e.source_kind == kind

    def test_rejects_bad_source_kind(self) -> None:
        with pytest.raises(ValidationError):
            _entry(source_kind="advert")


class TestEpgConfigModel:
    def test_defaults(self) -> None:
        c = _config()
        assert c.horizon_days == 14
        assert c.endpoint is None
        assert c.field_map == {}

    def test_field_map_default_is_independent(self) -> None:
        # No shared mutable default across instances.
        a = _config("epg_a")
        b = _config("epg_b")
        a.field_map["title"] = "Programme"
        assert b.field_map == {}

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            _config(bogus="nope")  # type: ignore[call-arg]

    @pytest.mark.parametrize("fmt", ["xlist", "xmltv", "csv"])
    def test_accepts_every_format(self, fmt: str) -> None:
        assert _config(format=fmt).format == fmt

    def test_rejects_bad_format(self) -> None:
        with pytest.raises(ValidationError):
            _config(format="json")


# --- as-run append + query ---------------------------------------------------


class TestAsRunStore:
    def test_append_and_round_trip(self, store: ReportingStore) -> None:
        store.append_as_run(_entry())
        rows = store.list_as_run("sta_main")
        assert len(rows) == 1
        got = rows[0]
        assert got.entry_id == "ar_1"
        assert got.duration_s == 3600
        assert got.source_kind == "program"
        assert got.verified is True

    def test_timestamps_are_utc_aware(self, store: ReportingStore) -> None:
        store.append_as_run(_entry())
        got = store.list_as_run("sta_main")[0]
        assert got.actual_start.tzinfo is not None
        assert got.actual_end.tzinfo is not None

    def test_naive_datetime_round_trips_as_utc_aware(self, store: ReportingStore) -> None:
        """T-5: the store's ``_as_utc`` read-side guard must NORMALIZE a
        tz-naive write back into a UTC-aware read.

        SQLite strips ``tzinfo`` on the column type, so the only place tz can
        be re-attached is the converter. The existing tests asserted the
        post-condition; this test sets up the exact pre-condition (write a
        naive ``actual_start``) so a future change that breaks ``_as_utc``
        cannot pass by accident.
        """
        naive_start = datetime(2026, 6, 1, 9, 0)  # naive
        naive_end = datetime(2026, 6, 1, 10, 0)  # naive
        store.append_as_run(
            _entry(
                "ar_naive",
                actual_start=naive_start,
                actual_end=naive_end,
            )
        )
        got = store.list_as_run("sta_main")[0]
        assert got.actual_start.tzinfo is UTC
        assert got.actual_end.tzinfo is UTC
        # And the absolute time portion is preserved (no shift).
        assert got.actual_start.replace(tzinfo=None) == naive_start
        assert got.actual_end.replace(tzinfo=None) == naive_end

    def test_list_scoped_by_station(self, store: ReportingStore) -> None:
        store.append_as_run(_entry("ar_main", station_id="sta_main"))
        store.append_as_run(_entry("ar_other", station_id="sta_other"))
        ids = [r.entry_id for r in store.list_as_run("sta_main")]
        assert ids == ["ar_main"]

    def test_list_ordered_by_actual_start(self, store: ReportingStore) -> None:
        store.append_as_run(_entry("ar_late", actual_start=_ts(12), actual_end=_ts(13)))
        store.append_as_run(_entry("ar_early", actual_start=_ts(8), actual_end=_ts(9)))
        ids = [r.entry_id for r in store.list_as_run("sta_main")]
        assert ids == ["ar_early", "ar_late"]

    def test_filter_by_channel(self, store: ReportingStore) -> None:
        store.append_as_run(_entry("ar_gov", channel_id="gov-ch12"))
        store.append_as_run(_entry("ar_edu", channel_id="edu-ch20"))
        ids = [r.entry_id for r in store.list_as_run("sta_main", channel_id="edu-ch20")]
        assert ids == ["ar_edu"]

    def test_filter_by_from_to_half_open(self, store: ReportingStore) -> None:
        # Half-open [from, to): the entry exactly at ``to`` is excluded.
        store.append_as_run(_entry("ar_8", actual_start=_ts(8), actual_end=_ts(9)))
        store.append_as_run(_entry("ar_10", actual_start=_ts(10), actual_end=_ts(11)))
        store.append_as_run(_entry("ar_12", actual_start=_ts(12), actual_end=_ts(13)))
        ids = [r.entry_id for r in store.list_as_run("sta_main", from_ts=_ts(9), to_ts=_ts(12))]
        assert ids == ["ar_10"]

    def test_filter_from_only(self, store: ReportingStore) -> None:
        store.append_as_run(_entry("ar_8", actual_start=_ts(8), actual_end=_ts(9)))
        store.append_as_run(_entry("ar_12", actual_start=_ts(12), actual_end=_ts(13)))
        ids = [r.entry_id for r in store.list_as_run("sta_main", from_ts=_ts(10))]
        assert ids == ["ar_12"]

    def test_append_is_idempotent_on_entry_id(self, store: ReportingStore) -> None:
        # Re-appending the same entry_id updates the row in place (no duplicate).
        store.append_as_run(_entry("ar_1", duration_s=3600))
        store.append_as_run(_entry("ar_1", duration_s=1800))
        rows = store.list_as_run("sta_main")
        assert len(rows) == 1
        assert rows[0].duration_s == 1800

    def test_optional_links_round_trip(self, store: ReportingStore) -> None:
        store.append_as_run(
            _entry(
                "ar_linked",
                schedule_item_id="si_99",
                asset_id="ast_42",
                scheduled_start=_ts(9),
            )
        )
        got = store.list_as_run("sta_main")[0]
        assert got.schedule_item_id == "si_99"
        assert got.asset_id == "ast_42"
        assert got.scheduled_start == _ts(9)

    def test_unverified_filler_round_trip(self, store: ReportingStore) -> None:
        store.append_as_run(_entry("ar_filler", source_kind="filler", verified=False))
        got = store.list_as_run("sta_main")[0]
        assert got.source_kind == "filler"
        assert got.verified is False


# --- EPG config CRUD ---------------------------------------------------------


class TestEpgConfigStore:
    def test_upsert_and_get(self, store: ReportingStore) -> None:
        store.upsert_config(_config(field_map={"title": "Programme"}))
        got = store.get_config("epg_1")
        assert got is not None
        assert got.format == "xmltv"
        assert got.field_map == {"title": "Programme"}

    def test_get_missing_returns_none(self, store: ReportingStore) -> None:
        assert store.get_config("epg_nope") is None

    def test_list_scoped_by_station(self, store: ReportingStore) -> None:
        store.upsert_config(_config("epg_main", station_id="sta_main"))
        store.upsert_config(_config("epg_other", station_id="sta_other"))
        ids = [c.config_id for c in store.list_configs("sta_main")]
        assert ids == ["epg_main"]

    def test_upsert_updates_in_place(self, store: ReportingStore) -> None:
        store.upsert_config(_config(horizon_days=14))
        store.upsert_config(_config(horizon_days=7, format="csv"))
        got = store.get_config("epg_1")
        assert got is not None
        assert got.horizon_days == 7
        assert got.format == "csv"
        # Only one row.
        assert len(store.list_configs("sta_main")) == 1

    def test_delete(self, store: ReportingStore) -> None:
        store.upsert_config(_config())
        store.delete_config("epg_1")
        assert store.get_config("epg_1") is None

    def test_delete_missing_raises(self, store: ReportingStore) -> None:
        with pytest.raises(EpgConfigNotFoundError):
            store.delete_config("epg_nope")

    def test_timestamps_are_utc_aware(self, store: ReportingStore) -> None:
        store.upsert_config(_config())
        got = store.get_config("epg_1")
        assert got is not None
        assert got.created_at.tzinfo is not None
        assert got.updated_at.tzinfo is not None


# --- migration 0055 ----------------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestAsRunAndEpgMigration:
    """0055_asrun_and_epg creates its two tables on upgrade and drops exactly
    those on a single-step downgrade to 0054 — the rest survives. Tests upgrade
    to the EXPLICIT 0055 revision (not global head) so they stay correct as the
    chain advances past 0055 (S24 = 0057_underwriting_spots is the current
    head; pinning to head would jump past the slice these tests cover)."""

    _TABLES = ("as_run_log", "epg_export_configs")

    def test_upgrade_to_0055_lands_at_that_revision(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0055_asrun_and_epg")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            from sqlalchemy import text

            with eng.connect() as conn:
                head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert head == "0055_asrun_and_epg"
        finally:
            eng.dispose()

    def test_upgrade_to_0055_creates_the_two_tables_and_indexes(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0055_asrun_and_epg")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table), table
            idx = {ix["name"] for ix in insp.get_indexes("as_run_log")}
            assert "ix_as_run_log_channel_actual_start" in idx
            assert "ix_as_run_log_station_actual_start" in idx
            assert "ix_as_run_log_asset" in idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_two_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0055_asrun_and_epg")
        command.downgrade(cfg, "0054_custom_metadata_fields")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table), table
            # 0054's table survives the single-step downgrade.
            assert insp.has_table("custom_field_defs")
        finally:
            eng.dispose()
