# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CastusAdapter: header-driven generic CSV parsing.

Castus (castus.tv) does not publish its schedule/playlist export schema
anywhere reachable without an active customer support contract -- see the
citations in ``civiccast/migrate/adapters.py``'s Castus section. No column
name from Castus's real export could be sourced this session, so this
adapter (and its test fixture) intentionally do NOT assume a
Castus-specific header -- ``tests/migrate/fixtures/castus_schedule.csv``
uses a plausible generic label set (Channel/Date/Time/Program/Length/File)
to prove the alias-matching reader works, not to claim it matches a real
Castus export. Validate against a real customer export before production
use (see ``honest_reds`` in the 0.4.0 task report).
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
from civiccast.migrate.adapters import CastusAdapter, CastusConnection, SourceFormatError
from civiccast.migrate.service import MigrationService

FIXTURES = Path(__file__).parent / "fixtures"


def _adapter(csv_text: str) -> CastusAdapter:
    return CastusAdapter(CastusConnection(schedule_csv=csv_text))


def _golden_adapter() -> CastusAdapter:
    return _adapter((FIXTURES / "castus_schedule.csv").read_text(encoding="utf-8"))


class TestCastusParsing:
    def test_recognizes_generic_program_date_time_length_file_columns(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        assert inventory.source_system == "castus"
        assert {s.source_ref for s in inventory.shows} == {
            "citycouncil_072026.mp4",
            "parksrec_promo.mp4",
            "eve_lineup.mp4",
        }
        show = next(s for s in inventory.shows if s.source_ref == "citycouncil_072026.mp4")
        assert show.title == "City Council Meeting"
        assert show.duration_seconds == 3600  # "01:00:00" -> seconds
        assert show.media_ref == "citycouncil_072026.mp4"

    def test_schedule_items_get_channel_and_scheduled_at(self) -> None:
        inventory = _golden_adapter().fetch_inventory()
        item = next(i for i in inventory.schedule_items if i.show_source_ref == "eve_lineup.mp4")
        assert item.channel_ref == "2"
        assert item.scheduled_at == datetime(2026, 7, 10, 18, 0, tzinfo=UTC)
        assert item.duration_seconds == 7200


class TestCastusFalsification:
    def test_unrecognizable_header_raises_named_error(self) -> None:
        text = "Foo,Bar,Baz\n1,2,3\n"
        with pytest.raises(SourceFormatError, match="no recognizable title/program or file"):
            _adapter(text).fetch_inventory()

    def test_wrong_delimiter_raises_named_error(self) -> None:
        # Semicolon-delimited content fed to the comma reader collapses the
        # whole header into one unrecognized column.
        text = "Channel;Date;Time;Program;Length;File\n1;07/10/2026;20:00:00;Show;01:00:00;x.mp4\n"
        with pytest.raises(SourceFormatError, match="no recognizable"):
            _adapter(text).fetch_inventory()

    def test_truncated_row_raises_named_error(self) -> None:
        text = "Channel,Date,Time,Program,Length,File\n1,07/10/2026,20:00:00,Show\n"
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

    with Session(bind=engine) as session:
        assets = session.execute(Base.metadata.tables["civiccast.assets"].select()).mappings().all()
    assert any(a["asset_id"] == "castus-show-citycouncil072026mp4" for a in assets)

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
