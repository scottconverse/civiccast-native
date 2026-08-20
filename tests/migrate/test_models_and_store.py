# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""0.4.0 migration data layer — normalized models + MigrationStore ledger."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.db import Base
from civiccast.migrate.models import ImportedShow, ImportPlan, NormalizedInventory
from civiccast.migrate.store import (
    BatchAlreadyRolledBackError,
    BatchNotFoundError,
    MigrationStore,
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[MigrationStore]:
    eng = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as sess:
            yield sess

    try:
        yield MigrationStore(factory)
    finally:
        eng.dispose()


class TestNormalizedModels:
    def test_imported_show_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            ImportedShow(source_ref="1", title="x", not_a_real_field="oops")  # type: ignore[call-arg]

    def test_imported_show_requires_a_title(self) -> None:
        with pytest.raises(ValidationError):
            ImportedShow(source_ref="1", title="")

    def test_normalized_inventory_defaults_to_empty_lists(self) -> None:
        inv = NormalizedInventory(source_system="cablecast")
        assert inv.shows == []
        assert inv.schedule_items == []
        assert inv.playlists == []

    def test_import_plan_generates_a_fresh_plan_id_each_time(self) -> None:
        a = ImportPlan(source_system="cablecast")
        b = ImportPlan(source_system="cablecast")
        assert a.plan_id != b.plan_id


class TestMigrationStore:
    def test_create_batch_then_get_batch_round_trips(self, store: MigrationStore) -> None:
        created = store.create_batch("batch-1", "cablecast")
        assert created.status == "applied"
        assert created.shows_created == 0

        fetched = store.get_batch("batch-1")
        assert fetched is not None
        assert fetched.import_batch_id == "batch-1"
        assert fetched.source_system == "cablecast"

    def test_get_batch_returns_none_for_unknown_id(self, store: MigrationStore) -> None:
        assert store.get_batch("nope") is None

    def test_add_item_is_reflected_in_batch_counts(self, store: MigrationStore) -> None:
        store.create_batch("batch-2", "cablecast")
        store.add_item(
            import_batch_id="batch-2", entity_type="asset", entity_id="a1", source_ref="1"
        )
        store.add_item(
            import_batch_id="batch-2",
            entity_type="schedule_item",
            entity_id="s1",
            source_ref="2",
        )
        batch = store.get_batch("batch-2")
        assert batch is not None
        assert batch.shows_created == 1
        assert batch.schedule_items_created == 1

        items = store.list_items("batch-2")
        assert {i.entity_id for i in items} == {"a1", "s1"}

    def test_list_batches_orders_newest_first(self, store: MigrationStore) -> None:
        store.create_batch("older", "cablecast")
        store.create_batch("newer", "cablecast")
        batches = store.list_batches()
        ids = [b.import_batch_id for b in batches]
        assert ids.index("newer") < ids.index("older")

    def test_mark_rolled_back_flips_status(self, store: MigrationStore) -> None:
        store.create_batch("batch-3", "cablecast")
        rolled_back = store.mark_rolled_back("batch-3")
        assert rolled_back.status == "rolled_back"
        assert rolled_back.rolled_back_at is not None

    def test_mark_rolled_back_twice_raises(self, store: MigrationStore) -> None:
        store.create_batch("batch-4", "cablecast")
        store.mark_rolled_back("batch-4")
        with pytest.raises(BatchAlreadyRolledBackError):
            store.mark_rolled_back("batch-4")

    def test_mark_rolled_back_unknown_batch_raises(self, store: MigrationStore) -> None:
        with pytest.raises(BatchNotFoundError):
            store.mark_rolled_back("does-not-exist")
