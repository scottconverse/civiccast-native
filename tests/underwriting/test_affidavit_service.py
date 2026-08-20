# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S24 slice 3 — UnderwriterAffidavit service + CSV/XML/PDF exports.

Covers the affidavit join over S23's as-run ledger (spec §6 algorithm + DC-3),
half-open UTC window semantics, source_kind / asset-set / channel-set filters,
the placement_id back-link, two-underwriter isolation, and round-trips through
the CSV/XML/PDF export helpers.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.reporting.models import AsRunLogEntry
from civiccast.reporting.store import ReportingStore
from civiccast.underwriting.models import (
    SpotFlight,
    SpotPlacement,
    UnderwritingSpot,
)
from civiccast.underwriting.service import (
    AffidavitService,
    UnderwriterAffidavit,
    export_affidavit_csv,
    export_affidavit_pdf,
    export_affidavit_xml,
)
from civiccast.underwriting.store import UnderwritingStore

STATION = "civiccast-station"


@pytest.fixture
def stores(tmp_path: Path) -> Iterator[tuple[UnderwritingStore, ReportingStore]]:
    """Wire ONE SQLite engine that hosts BOTH the reporting + underwriting tables.

    ``Base.metadata.create_all`` brings up every table registered against the
    shared declarative base, so the affidavit join's two stores can share a
    single engine in tests without fixturing two separate databases.
    """
    eng = create_engine(f"sqlite:///{tmp_path / 's24_affidavit.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield UnderwritingStore(factory), ReportingStore(factory)
    finally:
        eng.dispose()


def _ts(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


def _spot(spot_id: str, underwriter: str, asset_id: str) -> UnderwritingSpot:
    return UnderwritingSpot(
        spot_id=spot_id,
        station_id=STATION,
        underwriter=underwriter,
        asset_id=asset_id,
    )


def _flight(
    flight_id: str,
    spot_id: str,
    channels: list[str],
    start: date = date(2026, 6, 1),
    end: date = date(2026, 6, 30),
) -> SpotFlight:
    return SpotFlight(
        flight_id=flight_id,
        spot_id=spot_id,
        start_date=start,
        end_date=end,
        channels=channels,
    )


def _placement(
    placement_id: str,
    flight_id: str,
    channel_id: str,
    scheduled_at: datetime,
    schedule_item_id: str,
) -> SpotPlacement:
    return SpotPlacement(
        placement_id=placement_id,
        flight_id=flight_id,
        channel_id=channel_id,
        scheduled_at=scheduled_at,
        schedule_item_id=schedule_item_id,
    )


def _asrun(
    entry_id: str,
    *,
    channel_id: str = "gov-ch12",
    asset_id: str | None = "asset-acme-15",
    actual_start: datetime,
    duration_s: int = 15,
    source_kind: str = "spot",
    schedule_item_id: str | None = None,
) -> AsRunLogEntry:
    return AsRunLogEntry(
        entry_id=entry_id,
        station_id=STATION,
        channel_id=channel_id,
        schedule_item_id=schedule_item_id,
        asset_id=asset_id,
        actual_start=actual_start,
        actual_end=actual_start + timedelta(seconds=duration_s),
        duration_s=duration_s,
        source_kind=source_kind,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# AffidavitService.for_underwriter — join correctness
# ---------------------------------------------------------------------------


class TestAffidavitJoin:
    def test_empty_no_spots_no_asrun(
        self, stores: tuple[UnderwritingStore, ReportingStore]
    ) -> None:
        u_store, r_store = stores
        svc = AffidavitService(u_store, r_store)
        result = svc.for_underwriter(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        assert result.aired == []
        assert result.total_airings == 0
        assert result.total_seconds == 0

    def test_three_airings_one_spot_one_flight(
        self, stores: tuple[UnderwritingStore, ReportingStore]
    ) -> None:
        u_store, r_store = stores
        u_store.upsert_spot(_spot("spot-acme-001", "Acme Co.", "asset-acme-15"))
        u_store.upsert_flight(_flight("fl-acme", "spot-acme-001", ["gov-ch12"]))
        # 3 placements with deterministic ids
        for i in range(3):
            u_store.record_placement(
                _placement(
                    f"pl-si-{i}",
                    "fl-acme",
                    "gov-ch12",
                    _ts(2026, 6, 10, 9 + i),
                    f"si-{i}",
                )
            )
        # 3 as-run rows that match (schedule_item_id matches the placement)
        for i in range(3):
            r_store.append_as_run(
                _asrun(
                    f"ar-{i}",
                    actual_start=_ts(2026, 6, 10, 9 + i),
                    schedule_item_id=f"si-{i}",
                )
            )
        result = AffidavitService(u_store, r_store).for_underwriter(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        assert result.total_airings == 3
        assert result.total_seconds == 45
        # Each airing carries a placement_id (the schedule_item_id matched)
        assert all(a.placement_id is not None for a in result.aired)
        # Sorted by aired_at ASC
        assert [a.aired_at for a in result.aired] == sorted(a.aired_at for a in result.aired)

    def test_source_kind_program_excluded(
        self, stores: tuple[UnderwritingStore, ReportingStore]
    ) -> None:
        u_store, r_store = stores
        u_store.upsert_spot(_spot("spot-acme-001", "Acme Co.", "asset-acme-15"))
        u_store.upsert_flight(_flight("fl-acme", "spot-acme-001", ["gov-ch12"]))
        r_store.append_as_run(
            _asrun("ar-prog", actual_start=_ts(2026, 6, 10, 9), source_kind="program")
        )
        result = AffidavitService(u_store, r_store).for_underwriter(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        assert result.total_airings == 0

    def test_asset_not_in_underwriter_set_excluded(
        self, stores: tuple[UnderwritingStore, ReportingStore]
    ) -> None:
        u_store, r_store = stores
        u_store.upsert_spot(_spot("spot-acme-001", "Acme Co.", "asset-acme-15"))
        u_store.upsert_flight(_flight("fl-acme", "spot-acme-001", ["gov-ch12"]))
        # Foreign asset_id — not one of the underwriter's assets
        r_store.append_as_run(
            _asrun(
                "ar-foreign",
                actual_start=_ts(2026, 6, 10, 9),
                asset_id="asset-zzz-other",
            )
        )
        result = AffidavitService(u_store, r_store).for_underwriter(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        assert result.total_airings == 0

    def test_channel_not_in_underwriter_set_included(
        self, stores: tuple[UnderwritingStore, ReportingStore]
    ) -> None:
        """Historical as-run rows on a channel the underwriter no longer
        targets are still billable (Q-6 fix).

        The as-run ledger is the append-only source of truth for what aired;
        the flight set is prospective policy. A spot that aired on a channel
        the underwriter later removed from its flight still counts toward
        the billing period — the asset → spot map is the strong attribution
        proof. Replaces the prior "defense-in-depth exclude on channel
        mismatch" rule that silently dropped a real airing from billing.
        """
        u_store, r_store = stores
        u_store.upsert_spot(_spot("spot-acme-001", "Acme Co.", "asset-acme-15"))
        u_store.upsert_flight(_flight("fl-acme", "spot-acme-001", ["gov-ch12"]))
        r_store.append_as_run(
            _asrun(
                "ar-other-chan",
                actual_start=_ts(2026, 6, 10, 9),
                channel_id="edu-ch15",
            )
        )
        result = AffidavitService(u_store, r_store).for_underwriter(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        assert result.total_airings == 1
        # The off-flight channel is reported faithfully for billing transparency.
        assert result.aired[0].channel_id == "edu-ch15"

    def test_placement_join_populates_placement_id(
        self, stores: tuple[UnderwritingStore, ReportingStore]
    ) -> None:
        u_store, r_store = stores
        u_store.upsert_spot(_spot("spot-acme-001", "Acme Co.", "asset-acme-15"))
        u_store.upsert_flight(_flight("fl-acme", "spot-acme-001", ["gov-ch12"]))
        u_store.record_placement(
            _placement("pl-si-1", "fl-acme", "gov-ch12", _ts(2026, 6, 10, 9), "si-1")
        )
        # Matched
        r_store.append_as_run(
            _asrun("ar-matched", actual_start=_ts(2026, 6, 10, 9), schedule_item_id="si-1")
        )
        # No matching placement (legacy / manual airing) — still included
        r_store.append_as_run(
            _asrun(
                "ar-unmatched",
                actual_start=_ts(2026, 6, 10, 10),
                schedule_item_id="si-unknown",
            )
        )
        # No schedule_item_id at all — still included
        r_store.append_as_run(
            _asrun("ar-no-si", actual_start=_ts(2026, 6, 10, 11), schedule_item_id=None)
        )
        result = AffidavitService(u_store, r_store).for_underwriter(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        assert result.total_airings == 3
        by_id = {a.aired_at.hour: a for a in result.aired}
        assert by_id[9].placement_id == "pl-si-1"
        assert by_id[10].placement_id is None
        assert by_id[11].placement_id is None

    def test_half_open_window_boundary(
        self, stores: tuple[UnderwritingStore, ReportingStore]
    ) -> None:
        u_store, r_store = stores
        u_store.upsert_spot(_spot("spot-acme-001", "Acme Co.", "asset-acme-15"))
        u_store.upsert_flight(_flight("fl-acme", "spot-acme-001", ["gov-ch12"]))
        # Inclusive end: 2026-06-30 23:59:59 UTC should be IN
        r_store.append_as_run(_asrun("ar-in", actual_start=_ts(2026, 6, 30, 23, 59, 59)))
        # 2026-07-01 00:00:00 UTC should be OUT (half-open)
        r_store.append_as_run(_asrun("ar-out", actual_start=_ts(2026, 7, 1, 0, 0, 0)))
        result = AffidavitService(u_store, r_store).for_underwriter(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        assert result.total_airings == 1
        assert result.aired[0].aired_at == _ts(2026, 6, 30, 23, 59, 59)

    def test_two_underwriters_isolated(
        self, stores: tuple[UnderwritingStore, ReportingStore]
    ) -> None:
        u_store, r_store = stores
        u_store.upsert_spot(_spot("spot-acme-001", "Acme Co.", "asset-acme-15"))
        u_store.upsert_flight(_flight("fl-acme", "spot-acme-001", ["gov-ch12"]))
        u_store.upsert_spot(_spot("spot-zeta-001", "Zeta LLC", "asset-zeta-15"))
        u_store.upsert_flight(_flight("fl-zeta", "spot-zeta-001", ["gov-ch12"]))
        r_store.append_as_run(
            _asrun(
                "ar-acme",
                actual_start=_ts(2026, 6, 10, 9),
                asset_id="asset-acme-15",
            )
        )
        r_store.append_as_run(
            _asrun(
                "ar-zeta",
                actual_start=_ts(2026, 6, 10, 10),
                asset_id="asset-zeta-15",
            )
        )
        svc = AffidavitService(u_store, r_store)
        acme = svc.for_underwriter(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        zeta = svc.for_underwriter(
            station_id=STATION,
            underwriter="Zeta LLC",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
        )
        assert acme.total_airings == 1
        assert acme.aired[0].asset_id == "asset-acme-15"
        assert zeta.total_airings == 1
        assert zeta.aired[0].asset_id == "asset-zeta-15"


# ---------------------------------------------------------------------------
# Export helpers — CSV / XML / PDF
# ---------------------------------------------------------------------------


def _sample_affidavit(special_underwriter: str = "Acme Co.") -> UnderwriterAffidavit:
    """Build an affidavit directly (without the store) for export-only tests."""
    from civiccast.underwriting.service import AffidavitAiring

    return UnderwriterAffidavit(
        station_id=STATION,
        underwriter=special_underwriter,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        aired=[
            AffidavitAiring(
                spot_id="spot-acme-001",
                asset_id="asset-acme-15",
                channel_id="gov-ch12",
                aired_at=_ts(2026, 6, 10, 9),
                duration_s=15,
                placement_id="pl-si-1",
            ),
            AffidavitAiring(
                spot_id="spot-acme-001",
                asset_id="asset-acme-15",
                channel_id="gov-ch12",
                aired_at=_ts(2026, 6, 10, 10),
                duration_s=30,
                placement_id=None,
            ),
        ],
        total_airings=2,
        total_seconds=45,
    )


class TestExportCsv:
    def test_round_trip(self) -> None:
        affidavit = _sample_affidavit()
        csv_text = export_affidavit_csv(affidavit)
        rows = list(csv.reader(io.StringIO(csv_text)))
        # header + N airings + 1 summary
        assert len(rows) == 2 + 2
        assert rows[0] == [
            "aired_at_iso",
            "channel_id",
            "spot_id",
            "asset_id",
            "duration_s",
            "placement_id",
        ]
        # Summary row carries the SUMMARY token in column 0.
        assert rows[-1][0] == "SUMMARY"
        # placement_id None renders as an empty string for the second airing
        assert rows[2][5] == ""

    def test_special_chars_rfc4180_quoting(self) -> None:
        affidavit = _sample_affidavit('Smith "Bill" & Sons, LLC')
        csv_text = export_affidavit_csv(affidavit)
        rows = list(csv.reader(io.StringIO(csv_text)))
        # The underwriter lands in the summary row, column 1 — verify the
        # special chars round-tripped exactly through csv quoting.
        assert rows[-1][1] == 'Smith "Bill" & Sons, LLC'

    def test_formula_injection_is_neutralized(self) -> None:
        # SEC-3: the underwriter value is echoed from a caller-supplied query
        # param and this CSV is opened in Excel/LibreOffice by finance staff.
        # A leading formula trigger must be apostrophe-prefixed so it renders as
        # literal text instead of executing.
        payload = '=HYPERLINK("http://evil/",A1)'
        affidavit = _sample_affidavit(payload)
        csv_text = export_affidavit_csv(affidavit)
        rows = list(csv.reader(io.StringIO(csv_text)))
        assert rows[-1][1] == "'" + payload
        assert not rows[-1][1].startswith("=")


class TestExportXml:
    def test_round_trip(self) -> None:
        affidavit = _sample_affidavit()
        xml_text = export_affidavit_xml(affidavit)
        root = ET.fromstring(xml_text)
        assert root.tag == "underwriter_affidavit"
        assert root.attrib["underwriter"] == "Acme Co."
        airings = root.find("airings")
        assert airings is not None
        assert len(list(airings)) == 2
        totals = root.find("totals")
        assert totals is not None
        assert totals.attrib["airings"] == "2"
        assert totals.attrib["seconds"] == "45"

    def test_special_chars_entity_escaped(self) -> None:
        affidavit = _sample_affidavit('Smith "Bill" & Sons, LLC')
        xml_text = export_affidavit_xml(affidavit)
        # Round-trips through ET parsing without exception, attribute preserved.
        root = ET.fromstring(xml_text)
        assert root.attrib["underwriter"] == 'Smith "Bill" & Sons, LLC'


class TestExportPdf:
    def test_returns_pdf_bytes(self) -> None:
        affidavit = _sample_affidavit()
        pdf_bytes = export_affidavit_pdf(affidavit)
        assert pdf_bytes.startswith(b"%PDF")

    def test_empty_affidavit_still_renders(self) -> None:
        # Render an affidavit with zero airings — exercise the no-rows path.
        empty = UnderwriterAffidavit(
            station_id=STATION,
            underwriter="Acme Co.",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            aired=[],
            total_airings=0,
            total_seconds=0,
        )
        pdf_bytes = export_affidavit_pdf(empty)
        assert pdf_bytes.startswith(b"%PDF")
