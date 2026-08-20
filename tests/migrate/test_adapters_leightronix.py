# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""LeightronixAdapter: header-driven generic CSV parsing.

Leightronix NEXUS/UltraNEXUS exports a schedule as CSV through an
operator-built "Export/Print template" that lets the station choose which
Days/Channels/**Columns** appear in the report (see the citation in
``civiccast/migrate/adapters.py``'s Castus/Leightronix section) -- there is
no one fixed column set to hardcode, so this adapter uses the same
alias-matching reader as Castus. ``tests/migrate/fixtures/
leightronix_schedule.csv`` deliberately uses DIFFERENT column labels than
the Castus fixture (Air Date/Air Time/Program/Video File vs.
Date/Time/Program/File) to prove the alias matching genuinely generalizes
across an operator-templated header, not just one fixed label set.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.db import Base
from civiccast.migrate.adapters import (
    LeightronixAdapter,
    LeightronixConnection,
    SourceFormatError,
)
from civiccast.migrate.service import MigrationService

FIXTURES = Path(__file__).parent / "fixtures"


def _adapter(csv_text: str) -> LeightronixAdapter:
    return LeightronixAdapter(LeightronixConnection(schedule_csv=csv_text))


def _golden_adapter() -> LeightronixAdapter:
    return _adapter((FIXTURES / "leightronix_schedule.csv").read_text(encoding="utf-8"))


class TestLeightronixParsing:
    def test_recognizes_air_date_air_time_program_video_file_columns(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        assert inventory.source_system == "leightronix"
        assert {s.source_ref for s in inventory.shows} == {
            "CITYCOUNCIL072026.mpg",
            "PARKSRECPROMO.mpg",
            "EVELINEUP.mpg",
        }
        show = next(s for s in inventory.shows if s.source_ref == "CITYCOUNCIL072026.mpg")
        assert show.title == "City Council Meeting"
        assert show.duration_seconds == 3600

    def test_schedule_items_get_channel_and_scheduled_at(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        item = next(i for i in inventory.schedule_items if i.show_source_ref == "PARKSRECPROMO.mpg")
        assert item.channel_ref == "1"
        assert item.scheduled_at == datetime(2026, 7, 11, 9, 0, tzinfo=UTC)
        assert item.duration_seconds == 90


class TestLeightronixFalsification:
    def test_missing_duration_column_raises_named_error(self) -> None:
        text = "Channel,Air Date,Air Time,Program,Video File\n1,07/10/2026,20:00:00,Show,x.mpg\n"
        with pytest.raises(SourceFormatError, match="no recognizable duration/length"):
            _adapter(text).fetch_inventory()

    def test_truncated_row_raises_named_error(self) -> None:
        text = "Channel,Air Date,Air Time,Program,Length,Video File\n1,07/10/2026,20:00:00,Show\n"
        with pytest.raises(SourceFormatError, match=r"row 2 has 4 field\(s\), expected 6"):
            _adapter(text).fetch_inventory()

    def test_empty_file_raises_named_error(self) -> None:
        with pytest.raises(SourceFormatError, match="schedule file is empty"):
            _adapter("").fetch_inventory()


def test_end_to_end_dry_run_apply_rollback(tmp_path: Path) -> None:
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
    assert len(plan.shows_to_create) == 3
    assert len(plan.schedule_items_to_create) == 3

    batch = service.apply(plan)
    assert batch.shows_created == 3
    assert batch.schedule_items_created == 3
    assert batch.apply_failures == []

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
