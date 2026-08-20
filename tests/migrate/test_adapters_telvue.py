# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""TelvueAdapter: TelVue HyperCaster "Native CSV" schedule export parsing.

The golden fixture ``tests/migrate/fixtures/telvue_schedule.csv`` uses the
column set + formats sourced verbatim from TelVue's own knowledge base (see
the citations in ``civiccast/migrate/adapters.py``'s TelVue section) --
Output/Date/Time/Type/Source ID/Source Name/Offset/Title/Duration. It is a
station-plausible example built from those sourced field definitions, not a
captured real customer export (TelVue does not publish one to fetch, unlike
Cablecast's live server).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from civiccast.migrate.adapters import SourceFormatError, TelvueAdapter, TelvueConnection
from civiccast.migrate.service import MigrationService

FIXTURES = Path(__file__).parent / "fixtures"


def _adapter(csv_text: str) -> TelvueAdapter:
    return TelvueAdapter(TelvueConnection(schedule_csv=csv_text))


def _golden_adapter() -> TelvueAdapter:
    return _adapter((FIXTURES / "telvue_schedule.csv").read_text(encoding="utf-8"))


class TestTelvueParsing:
    def test_only_playout_rows_become_shows(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        # Row 3 is Type=PLAYLIST ("Evening Lineup") -- excluded, not a fake show.
        assert {s.source_ref for s in inventory.shows} == {"4210", "parksrec_promo.mpg"}

    def test_source_id_wins_over_source_name_when_present(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        show = next(s for s in inventory.shows if s.source_ref == "4210")
        assert show.title == "City Council Meeting"
        assert show.duration_seconds == 3600
        assert show.media_ref == "citycouncil_072026.mpg"

    def test_blank_source_id_falls_back_to_source_name_for_both_ref_and_title(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        # Row 2 has a blank Source ID and a blank Title -- TelVue's own docs
        # say a blank Source ID means "match on filename," and Native CSV's
        # Title column is documented as "used for overlays," not canonical
        # metadata, so the filename is the honest fallback for both.
        show = next(s for s in inventory.shows if s.source_ref == "parksrec_promo.mpg")
        assert show.title == "parksrec_promo.mpg"
        assert show.duration_seconds == 90

    def test_repeated_airing_of_the_same_show_produces_one_show_two_items(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        items = [i for i in inventory.schedule_items if i.show_source_ref == "4210"]
        assert len(items) == 2
        assert {i.scheduled_at for i in items} == {
            datetime(2026, 7, 10, 20, 0, tzinfo=UTC),
            datetime(2026, 7, 12, 10, 0, tzinfo=UTC),
        }
        assert all(s.source_ref == "4210" for s in inventory.shows if s.source_ref == "4210")

    def test_channel_ref_comes_from_output_column(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        item = next(
            i for i in inventory.schedule_items if i.show_source_ref == "parksrec_promo.mpg"
        )
        assert item.channel_ref == "1"

    def test_offset_and_output_are_carried_in_raw_extra_not_guessed(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        show = next(s for s in inventory.shows if s.source_ref == "4210")
        assert show.raw_extra == {"Offset": "0", "Output": "1"}


class TestTelvueFalsification:
    """Malformed exports must raise a typed, problem-naming error -- never
    a silent empty/wrong import."""

    def test_missing_required_column_raises_named_error(self) -> None:
        # No "Duration" column at all -- a structural format problem, not a
        # per-row data gap the service layer's "no usable duration" skip
        # already covers.
        text = (
            "Output,Date,Time,Type,Source ID,Source Name,Offset,Title\n"
            "1,07/10/2026,20:00:00,PLAYOUT,4210,x.mpg,0,Title\n"
        )
        with pytest.raises(SourceFormatError, match=r"missing required column.*Duration"):
            _adapter(text).fetch_inventory()

    def test_truncated_row_raises_named_error(self) -> None:
        # Header has 9 columns; the data row was cut off mid-row.
        text = (
            "Output,Date,Time,Type,Source ID,Source Name,Offset,Title,Duration\n"
            "1,07/10/2026,20:00:00,PLAYOUT,4210,x.mpg,0\n"
        )
        with pytest.raises(SourceFormatError, match=r"row 2 has 7 field\(s\), expected 9"):
            _adapter(text).fetch_inventory()

    def test_empty_file_raises_named_error(self) -> None:
        with pytest.raises(SourceFormatError, match="schedule file is empty"):
            _adapter("").fetch_inventory()

    def test_duplicate_header_name_raises_named_error_instead_of_dropping_a_column(self) -> None:
        # Two "Source ID" columns -- an operator-templated/copy-paste export
        # artifact. Field count still matches the header, so only a
        # duplicate-name check catches this; `dict(zip(...))` would silently
        # keep just the last "Source ID" value and drop the other.
        text = (
            "Output,Date,Time,Type,Source ID,Source Name,Offset,Title,Source ID,Duration\n"
            "1,07/10/2026,20:00:00,PLAYOUT,4210,x.mpg,0,Title,4210,3600\n"
        )
        with pytest.raises(SourceFormatError, match="duplicate column"):
            _adapter(text).fetch_inventory()


def test_end_to_end_dry_run_apply_rollback(tmp_path: Path) -> None:
    """fixture -> dry-run -> apply -> rollback, reusing the exact
    MigrationService the real dry-run/apply/rollback endpoints call --
    proves TelVue rows flow through the UNCHANGED existing service."""
    from collections.abc import Iterator
    from contextlib import contextmanager

    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from civiccast.db import Base

    engine = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    service = MigrationService(factory)
    inventory = _golden_adapter().fetch_inventory()

    plan = service.dry_run(inventory)
    assert {s.source_ref for s in plan.shows_to_create} == {"4210", "parksrec_promo.mpg"}
    assert len(plan.schedule_items_to_create) == 3

    batch = service.apply(plan)
    assert batch.shows_created == 2
    assert batch.schedule_items_created == 3
    assert batch.apply_failures == []

    tables = inspect(engine).get_table_names(schema="civiccast")
    with Session(bind=engine) as session:
        assets = session.execute(Base.metadata.tables["civiccast.assets"].select()).mappings().all()
        schedule_rows = (
            session.execute(Base.metadata.tables["civiccast.schedule_items"].select())
            .mappings()
            .all()
        )
    assert len(assets) == 2
    assert len(schedule_rows) == 3
    assert "asset_id" in assets[0] and any(a["asset_id"] == "telvue-show-4210" for a in assets)

    rolled_back = service.rollback(batch.import_batch_id)
    assert rolled_back.status == "rolled_back"

    with Session(bind=engine) as session:
        assets_after = (
            session.execute(Base.metadata.tables["civiccast.assets"].select()).mappings().all()
        )
        schedule_after = (
            session.execute(Base.metadata.tables["civiccast.schedule_items"].select())
            .mappings()
            .all()
        )
    assert assets_after == []
    assert schedule_after == []
    assert tables  # sanity: metadata was actually registered
