# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S23 reporting service — aggregation reports + CSV/XML exporters.

Covers (spec §6 / DC-2 / DC-3 / DC-5):
* Shows report — group by ``asset_id``, sum airtime, count plays, first/last
  aired; ``asset_id=None`` rows excluded; channel filter narrows; ordered by
  total airtime desc.
* Hours-by-Category — resolve a S22 custom field by ``(station_id, key)``,
  LEFT JOIN ``as_run_log`` → ``custom_field_values`` ON
  ``(asset_id, field_id)``; sum ``duration_s`` per ``value``; rows without a
  value land in ``(uncategorized)`` (emitted last); ``field_not_found=True``
  short-circuit when the key has no def. All bound params (the ``DROP TABLE``
  payload is just a string value, not a SQL fragment).
* As-Run report — projection over ``list_as_run`` with an optional
  per-asset ``category`` resolved via the same field.
* Exporters — ``export_as_run_csv``, ``export_as_run_xml``,
  ``export_shows_csv``, ``export_shows_xml`` round-trip headers/columns;
  XML parses; CSV survives embedded commas/quotes.

SQLite-backed unit coverage. The PG-specific GROUP BY behavior is asserted in
``tests/live/test_real_postgres.py::TestRealPostgresReportingHoursByCategory``.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.metadata.models import CustomFieldDef, CustomFieldValue
from civiccast.metadata.store import CustomFieldStore
from civiccast.reporting.models import AsRunLogEntry
from civiccast.reporting.service import (
    ReportingService,
    export_as_run_csv,
    export_as_run_xml,
    export_shows_csv,
    export_shows_xml,
)
from civiccast.reporting.store import ReportingStore


@pytest.fixture
def env(tmp_path: Path) -> Iterator[tuple[ReportingService, ReportingStore, CustomFieldStore]]:
    """Wire a ReportingService over a fresh SQLite engine.

    A single session factory backs the reporting store, the custom-field
    store, and the service's own queries — so the service's joins see the
    same rows the stores wrote.
    """
    eng = create_engine(f"sqlite:///{tmp_path / 'reporting.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield (
            ReportingService(factory),
            ReportingStore(factory),
            CustomFieldStore(factory),
        )
    finally:
        eng.dispose()


def _ts(hour: int, minute: int = 0, day: int = 1) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def _entry(entry_id: str, **kw: object) -> AsRunLogEntry:
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


def _def(field_id: str, key: str, **kw: object) -> CustomFieldDef:
    base: dict[str, object] = {
        "field_id": field_id,
        "station_id": "sta_main",
        "key": key,
        "label": key.title(),
        "type": "text",
    }
    base.update(kw)
    return CustomFieldDef(**base)  # type: ignore[arg-type]


def _value(asset_id: str, field_id: str, value: str) -> CustomFieldValue:
    return CustomFieldValue(asset_id=asset_id, field_id=field_id, value=value)


# --- Shows report (DC-2) ----------------------------------------------------


class TestShowsReport:
    def test_empty_window_returns_empty_rows(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, _store, _cf = env
        report = service.shows_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        assert report.rows == []
        assert report.station_id == "sta_main"

    def test_groups_by_asset_and_sums_airtime(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        _service, store, _cf = env
        # Asset A plays twice (3600 + 1800), asset B plays once (600).
        store.append_as_run(
            _entry("e1", asset_id="ast_a", actual_start=_ts(8), actual_end=_ts(9), duration_s=3600)
        )
        store.append_as_run(
            _entry(
                "e2",
                asset_id="ast_a",
                actual_start=_ts(12),
                actual_end=_ts(12, 30),
                duration_s=1800,
            )
        )
        store.append_as_run(
            _entry(
                "e3", asset_id="ast_b", actual_start=_ts(14), actual_end=_ts(14, 10), duration_s=600
            )
        )
        service = _service
        report = service.shows_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        # Order by total_airtime_s desc → ast_a (5400) first, then ast_b (600).
        assert [r.asset_id for r in report.rows] == ["ast_a", "ast_b"]
        row_a = report.rows[0]
        assert row_a.play_count == 2
        assert row_a.total_airtime_s == 5400
        assert row_a.first_aired == _ts(8)
        assert row_a.last_aired == _ts(12)
        row_b = report.rows[1]
        assert row_b.play_count == 1
        assert row_b.total_airtime_s == 600

    def test_channel_filter_narrows(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        _service, store, _cf = env
        store.append_as_run(_entry("g1", asset_id="ast_a", channel_id="gov-ch12"))
        store.append_as_run(_entry("e1", asset_id="ast_b", channel_id="edu-ch20"))
        report = _service.shows_report(
            station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23), channel_id="edu-ch20"
        )
        assert [r.asset_id for r in report.rows] == ["ast_b"]

    def test_excludes_rows_without_asset_id(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        _service, store, _cf = env
        # Filler / live / slate with no library asset have asset_id=None.
        store.append_as_run(_entry("filler", source_kind="filler", asset_id=None))
        store.append_as_run(_entry("live", source_kind="live", asset_id=None))
        store.append_as_run(_entry("show", source_kind="program", asset_id="ast_a"))
        report = _service.shows_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        assert [r.asset_id for r in report.rows] == ["ast_a"]

    def test_spot_with_asset_id_is_included(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        # ``spot`` (S24 underwriting) with a library asset_id IS a show row.
        _service, store, _cf = env
        store.append_as_run(_entry("u1", source_kind="spot", asset_id="ast_under"))
        report = _service.shows_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        assert [r.asset_id for r in report.rows] == ["ast_under"]

    def test_ties_break_by_asset_id(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        _service, store, _cf = env
        store.append_as_run(_entry("b", asset_id="ast_b", duration_s=600))
        store.append_as_run(_entry("a", asset_id="ast_a", duration_s=600))
        report = _service.shows_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        # Equal airtime → asset_id asc as secondary order.
        assert [r.asset_id for r in report.rows] == ["ast_a", "ast_b"]


# --- Hours-by-Category report (DC-3) ----------------------------------------


class TestHoursByCategoryReport:
    def test_field_not_found_short_circuits(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, _cf = env
        store.append_as_run(_entry("e1", asset_id="ast_a", duration_s=3600))
        report = service.hours_by_category(
            station_id="sta_main",
            field_key="category",
            from_ts=_ts(0),
            to_ts=_ts(23),
        )
        assert report.field_not_found is True
        assert report.rows == []
        assert report.field_key == "category"

    def test_groups_and_sums_by_value(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        # Asset A is "Government" (3600+1800=5400), B is "Public-access" (600).
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", "Government")],
            definitions=cf.list_defs("sta_main"),
        )
        cf.set_values(
            "ast_b",
            [_value("ast_b", "cf_cat", "Public-access")],
            definitions=cf.list_defs("sta_main"),
        )
        store.append_as_run(_entry("e1", asset_id="ast_a", duration_s=3600))
        store.append_as_run(_entry("e2", asset_id="ast_a", duration_s=1800))
        store.append_as_run(_entry("e3", asset_id="ast_b", duration_s=600))
        report = service.hours_by_category(
            station_id="sta_main",
            field_key="category",
            from_ts=_ts(0),
            to_ts=_ts(23),
        )
        assert report.field_not_found is False
        # desc by total_seconds → Government (5400) first.
        cats = [(r.category, r.total_seconds, r.entry_count) for r in report.rows]
        assert cats == [("Government", 5400, 2), ("Public-access", 600, 1)]
        # total_hours = seconds / 3600 (rounded to 3 decimal places — the spec's
        # "3 decimal places acceptable" precision for franchise reports).
        assert report.rows[0].total_hours == pytest.approx(1.5)
        assert report.rows[1].total_hours == pytest.approx(600 / 3600.0, abs=1e-3)

    def test_uncategorized_bucket_last(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", "Government")],
            definitions=cf.list_defs("sta_main"),
        )
        # ast_b has no value for ``category`` → uncategorized bucket.
        store.append_as_run(_entry("e1", asset_id="ast_a", duration_s=7200))
        store.append_as_run(_entry("e2", asset_id="ast_b", duration_s=3600))
        # Filler with asset_id=None also lands in uncategorized.
        store.append_as_run(_entry("filler", asset_id=None, duration_s=1800, source_kind="filler"))
        report = service.hours_by_category(
            station_id="sta_main",
            field_key="category",
            from_ts=_ts(0),
            to_ts=_ts(23),
        )
        # Even though uncategorized has 3600+1800=5400 (bigger than Government's 7200? no,
        # 7200 > 5400), uncategorized is ALWAYS last regardless of size.
        names = [r.category for r in report.rows]
        assert names == ["Government", "(uncategorized)"]
        uncat = report.rows[-1]
        assert uncat.total_seconds == 5400
        assert uncat.entry_count == 2

    def test_uncategorized_last_even_when_largest(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", "Government")],
            definitions=cf.list_defs("sta_main"),
        )
        store.append_as_run(_entry("e1", asset_id="ast_a", duration_s=600))
        # Bigger uncategorized bucket but still last.
        store.append_as_run(_entry("filler", asset_id=None, duration_s=9000, source_kind="filler"))
        report = service.hours_by_category(
            station_id="sta_main",
            field_key="category",
            from_ts=_ts(0),
            to_ts=_ts(23),
        )
        names = [r.category for r in report.rows]
        assert names == ["Government", "(uncategorized)"]

    def test_channel_filter_narrows(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", "Government")],
            definitions=cf.list_defs("sta_main"),
        )
        store.append_as_run(_entry("g1", asset_id="ast_a", channel_id="gov-ch12", duration_s=3600))
        store.append_as_run(_entry("e1", asset_id="ast_a", channel_id="edu-ch20", duration_s=1800))
        report = service.hours_by_category(
            station_id="sta_main",
            field_key="category",
            from_ts=_ts(0),
            to_ts=_ts(23),
            channel_id="edu-ch20",
        )
        assert [(r.category, r.total_seconds) for r in report.rows] == [("Government", 1800)]

    def test_sql_injection_payload_is_just_a_value(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        """An attacker-supplied value with SQL fragments is bound, not interpolated."""
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        nasty = "'; DROP TABLE as_run_log; --"
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", nasty)],
            definitions=cf.list_defs("sta_main"),
        )
        store.append_as_run(_entry("e1", asset_id="ast_a", duration_s=3600))
        # No SQL error: the value is a bound parameter, not an injected fragment.
        report = service.hours_by_category(
            station_id="sta_main",
            field_key="category",
            from_ts=_ts(0),
            to_ts=_ts(23),
        )
        assert [r.category for r in report.rows] == [nasty]
        # And the table still exists (we can still query it).
        assert len(store.list_as_run("sta_main")) == 1

    def test_field_key_injection_payload_is_just_a_value(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        """T-7: the ``field_key`` URL parameter must be bound on
        ``_resolve_field_id``'s ``WHERE CustomFieldDefDb.key == :key`` and
        never spliced into SQL. The value-side probe (above) covers the join's
        value column; this mirrors it on the key side.

        The route reads ``field_key`` straight off the URL alias and passes it
        to the resolver; SQLAlchemy binds the parameter. Locking it with a
        test prevents a future refactor that builds a raw SQL string from
        re-introducing the seam.
        """
        service, store, _cf = env
        # Seed a valid as-run row so the table is non-empty (we'll assert
        # survival after the probe).
        store.append_as_run(_entry("e1", asset_id="ast_a", duration_s=3600))
        nasty_key = "category'; DROP TABLE custom_field_defs; --"
        # No SQL error: the key is bound. No matching def → field_not_found.
        report = service.hours_by_category(
            station_id="sta_main",
            field_key=nasty_key,
            from_ts=_ts(0),
            to_ts=_ts(23),
        )
        assert report.field_not_found is True
        assert report.field_key == nasty_key
        assert report.rows == []
        # And the tables still exist — the SUM/COUNT still runs cleanly.
        assert len(store.list_as_run("sta_main")) == 1

    def test_window_excludes_entries_outside_range(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", "Government")],
            definitions=cf.list_defs("sta_main"),
        )
        store.append_as_run(
            _entry("inside", asset_id="ast_a", actual_start=_ts(10), duration_s=600)
        )
        store.append_as_run(_entry("after", asset_id="ast_a", actual_start=_ts(20), duration_s=600))
        report = service.hours_by_category(
            station_id="sta_main",
            field_key="category",
            from_ts=_ts(9),
            to_ts=_ts(11),
        )
        assert [(r.category, r.entry_count) for r in report.rows] == [("Government", 1)]


# --- As-Run report ----------------------------------------------------------


class TestAsRunReport:
    def test_structure_without_field_key(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, _cf = env
        store.append_as_run(_entry("e1", asset_id="ast_a"))
        report = service.as_run_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        assert len(report.rows) == 1
        row = report.rows[0]
        assert row.entry.entry_id == "e1"
        assert row.category is None
        assert report.field_key is None

    def test_category_resolution_when_field_key_supplied(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", "Government")],
            definitions=cf.list_defs("sta_main"),
        )
        store.append_as_run(_entry("with_cat", asset_id="ast_a"))
        store.append_as_run(_entry("no_cat", asset_id="ast_b"))  # asset has no value
        store.append_as_run(_entry("no_asset", asset_id=None, source_kind="filler"))
        report = service.as_run_report(
            station_id="sta_main",
            from_ts=_ts(0),
            to_ts=_ts(23),
            field_key="category",
        )
        by_id = {r.entry.entry_id: r.category for r in report.rows}
        assert by_id["with_cat"] == "Government"
        assert by_id["no_cat"] is None
        assert by_id["no_asset"] is None
        assert report.field_key == "category"

    def test_field_key_unknown_returns_all_null_categories(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        # field_key that doesn't resolve — every category is None, no error.
        service, store, _cf = env
        store.append_as_run(_entry("e1", asset_id="ast_a"))
        report = service.as_run_report(
            station_id="sta_main",
            from_ts=_ts(0),
            to_ts=_ts(23),
            field_key="nope",
        )
        assert [r.category for r in report.rows] == [None]


# --- exporters --------------------------------------------------------------


class TestExporters:
    def test_as_run_csv_round_trip(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, _cf = env
        store.append_as_run(_entry("e1", asset_id="ast_a"))
        report = service.as_run_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        text = export_as_run_csv(report.rows)
        rows = list(csv.reader(io.StringIO(text)))
        # First row is the header.
        assert rows[0] == [
            "entry_id",
            "station_id",
            "channel_id",
            "asset_id",
            "schedule_item_id",
            "scheduled_start",
            "actual_start",
            "actual_end",
            "duration_s",
            "source_kind",
            "verified",
            "category",
        ]
        assert rows[1][0] == "e1"
        assert rows[1][3] == "ast_a"

    def test_as_run_csv_quotes_embedded_commas_and_quotes(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", 'has,comma and "quote"')],
            definitions=cf.list_defs("sta_main"),
        )
        store.append_as_run(_entry("e1", asset_id="ast_a"))
        report = service.as_run_report(
            station_id="sta_main",
            from_ts=_ts(0),
            to_ts=_ts(23),
            field_key="category",
        )
        text = export_as_run_csv(report.rows)
        # csv.reader correctly parses the escaped value back.
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[1][-1] == 'has,comma and "quote"'

    def test_as_run_xml_is_well_formed(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, cf = env
        cf.upsert_def(_def("cf_cat", "category"))
        # Adversarial value with XML-special chars — must serialize safely.
        cf.set_values(
            "ast_a",
            [_value("ast_a", "cf_cat", "<bad>&\"'</bad>")],
            definitions=cf.list_defs("sta_main"),
        )
        store.append_as_run(_entry("e1", asset_id="ast_a"))
        report = service.as_run_report(
            station_id="sta_main",
            from_ts=_ts(0),
            to_ts=_ts(23),
            field_key="category",
        )
        text = export_as_run_xml(report.rows)
        # Parses without error → well-formed.
        root = ET.fromstring(text)
        rows = list(root)
        assert len(rows) == 1
        # The element's text decoded back to the original (no injection).
        cat = rows[0].find("category")
        assert cat is not None
        assert cat.text == "<bad>&\"'</bad>"

    def test_shows_csv_round_trip(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, _cf = env
        store.append_as_run(_entry("e1", asset_id="ast_a", duration_s=600))
        store.append_as_run(_entry("e2", asset_id="ast_a", duration_s=300))
        report = service.shows_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        text = export_shows_csv(report.rows)
        rows = list(csv.reader(io.StringIO(text)))
        assert rows[0] == [
            "asset_id",
            "play_count",
            "total_airtime_s",
            "first_aired",
            "last_aired",
        ]
        assert rows[1][0] == "ast_a"
        assert rows[1][1] == "2"
        assert rows[1][2] == "900"

    def test_shows_xml_parses(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, store, _cf = env
        store.append_as_run(_entry("e1", asset_id="ast_a"))
        report = service.shows_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        text = export_shows_xml(report.rows)
        root = ET.fromstring(text)
        rows = list(root)
        assert len(rows) == 1
        assert rows[0].find("asset_id").text == "ast_a"  # type: ignore[union-attr]

    def test_empty_exports_produce_header_only_csv_and_empty_root_xml(
        self, env: tuple[ReportingService, ReportingStore, CustomFieldStore]
    ) -> None:
        service, _store, _cf = env
        empty_asrun = service.as_run_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        empty_shows = service.shows_report(station_id="sta_main", from_ts=_ts(0), to_ts=_ts(23))
        # CSV: header row only.
        assert len(list(csv.reader(io.StringIO(export_as_run_csv(empty_asrun.rows))))) == 1
        assert len(list(csv.reader(io.StringIO(export_shows_csv(empty_shows.rows))))) == 1
        # XML: parses, zero child rows.
        assert len(list(ET.fromstring(export_as_run_xml(empty_asrun.rows)))) == 0
        assert len(list(ET.fromstring(export_shows_xml(empty_shows.rows)))) == 0
