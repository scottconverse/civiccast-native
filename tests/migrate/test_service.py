# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""MigrationService: dry-run diffing, apply, and rollback.

THE GATE (``test_apply_then_rollback_restores_prior_state_byte_exact``):
seeds pre-existing data in the REAL ``assets`` / ``schedule_items`` tables,
applies a real import into those same tables, verifies the new rows landed,
then rolls back and verifies the tables are back to EXACTLY the pre-existing
snapshot — not "close enough," a literal row-for-row dict comparison.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.db import Base
from civiccast.migrate.models import ImportedScheduleItem, ImportedShow, NormalizedInventory
from civiccast.migrate.service import MigrationService
from civiccast.migrate.store import BatchAlreadyRolledBackError
from civiccast.schedule.models import Asset, ScheduleItem


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Any]:
    eng = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def service(engine: Any) -> MigrationService:
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as sess:
            yield sess

    return MigrationService(factory)


def _dump_table(engine: Any, table_name: str) -> list[dict[str, Any]]:
    """Every row of ``table_name`` as a plain dict, for byte-exact comparison."""
    with Session(bind=engine) as session:
        table = Base.metadata.tables[f"civiccast.{table_name}"]
        rows = session.execute(table.select()).mappings().all()
        return sorted((dict(r) for r in rows), key=lambda r: str(sorted(r.items())))


def _seed_preexisting(engine: Any) -> None:
    with Session(bind=engine) as session:
        session.add(
            Asset(
                asset_id="existing-show",
                title="Existing Show",
                manifest_url="https://example.org/existing/index.m3u8",
                state="validated",
            )
        )
        session.add(
            ScheduleItem(
                id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                asset_id="existing-show",
                channel_id="cablecast-ch-9",
                mode="premiere",
                scheduled_at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                scheduled_at_end=datetime(2026, 1, 1, 13, 0, tzinfo=UTC),
                duration_seconds=3600,
            )
        )
        session.commit()


def _inventory(*, channel_ref: str = "2") -> NormalizedInventory:
    return NormalizedInventory(
        source_system="cablecast",
        shows=[
            ImportedShow(
                source_ref="73411",
                title="John Militaru Ministries Internat'l",
                description="Faith programming.",
                category="Religion",
                duration_seconds=3515,
                media_ref="https://station.example.org/cablecastapi/v1/reels/75355",
            ),
            ImportedShow(
                source_ref="73410",
                title="DW-TV Journal News",
                duration_seconds=1695,
            ),
        ],
        schedule_items=[
            ImportedScheduleItem(
                source_ref="1087848",
                show_source_ref="73411",
                channel_ref=channel_ref,
                scheduled_at=datetime(2026, 7, 11, 20, 0, tzinfo=UTC),
                duration_seconds=3515,
            ),
            ImportedScheduleItem(
                source_ref="1087849",
                show_source_ref="73410",
                channel_ref=channel_ref,
                scheduled_at=datetime(2026, 7, 12, 9, 0, tzinfo=UTC),
                duration_seconds=1695,
            ),
        ],
    )


class TestDryRun:
    def test_proposes_every_new_show_and_schedule_item(self, service: MigrationService) -> None:
        plan = service.dry_run(_inventory())
        assert {s.source_ref for s in plan.shows_to_create} == {"73411", "73410"}
        assert {i.source_ref for i in plan.schedule_items_to_create} == {"1087848", "1087849"}
        assert plan.conflicts == []
        assert plan.skipped == []

    def test_deterministic_asset_id_is_stable_across_dry_runs(
        self, service: MigrationService
    ) -> None:
        plan_a = service.dry_run(_inventory())
        plan_b = service.dry_run(_inventory())
        ids_a = {s.source_ref: s.asset_id for s in plan_a.shows_to_create}
        ids_b = {s.source_ref: s.asset_id for s in plan_b.shows_to_create}
        assert ids_a == ids_b

    def test_flags_title_collision_with_existing_asset_as_conflict(
        self, engine: Any, service: MigrationService
    ) -> None:
        with Session(bind=engine) as session:
            session.add(Asset(asset_id="pre-existing", title="DW-TV Journal News"))
            session.commit()

        plan = service.dry_run(_inventory())
        conflicted_refs = {c.source_ref for c in plan.conflicts}
        assert "73410" in conflicted_refs
        assert "73410" not in {s.source_ref for s in plan.shows_to_create}

    def test_flags_already_imported_show_as_conflict_on_rerun(
        self, service: MigrationService
    ) -> None:
        plan = service.dry_run(_inventory())
        service.apply(plan)

        rerun_plan = service.dry_run(_inventory())
        assert rerun_plan.shows_to_create == []
        show_conflicts = {c.source_ref for c in rerun_plan.conflicts if c.kind == "show"}
        assert show_conflicts == {"73411", "73410"}
        # The schedule items also collide with the ones just applied — same
        # honest signal, one level down.
        schedule_conflicts = {
            c.source_ref for c in rerun_plan.conflicts if c.kind == "schedule_item"
        }
        assert schedule_conflicts == {"1087848", "1087849"}

    def test_flags_distinct_source_refs_colliding_on_the_same_derived_asset_id(
        self, service: MigrationService
    ) -> None:
        # "Show 1" and "show_1" both strip down to the same safe_ref
        # ("show1"), so they'd otherwise both land in shows_to_create with
        # the identical target asset_id -- apply() would insert the first
        # fine and the second would trip a PK IntegrityError with no warning
        # from dry_run.
        inv = _inventory()
        inv.shows[0].source_ref = "Show 1"
        inv.shows[1].source_ref = "show_1"
        inv.schedule_items[0].show_source_ref = "Show 1"
        inv.schedule_items[1].show_source_ref = "show_1"
        plan = service.dry_run(inv)
        created_ids = [s.asset_id for s in plan.shows_to_create]
        assert len(created_ids) == len(set(created_ids)), (
            "two distinct source_refs collided on one derived asset_id"
        )

    def test_skips_duplicate_source_ref_within_one_export(self, service: MigrationService) -> None:
        inv = _inventory()
        inv.shows.append(inv.shows[0].model_copy())
        plan = service.dry_run(inv)
        assert any(s.kind == "show" and "Duplicate" in s.reason for s in plan.skipped)

    def test_skips_schedule_item_referencing_unknown_show(self, service: MigrationService) -> None:
        inv = _inventory()
        inv.schedule_items.append(
            ImportedScheduleItem(
                source_ref="9999",
                show_source_ref="not-in-this-export",
                scheduled_at=datetime(2026, 8, 1, tzinfo=UTC),
                duration_seconds=60,
            )
        )
        plan = service.dry_run(inv)
        skipped = {s.source_ref for s in plan.skipped if s.kind == "schedule_item"}
        assert "9999" in skipped

    def test_skips_schedule_item_with_no_usable_duration(self, service: MigrationService) -> None:
        inv = _inventory()
        inv.schedule_items[0].duration_seconds = None
        plan = service.dry_run(inv)
        skipped = {s.source_ref for s in plan.skipped if s.kind == "schedule_item"}
        assert "1087848" in skipped

    def test_flags_time_collision_with_existing_schedule_item(
        self, engine: Any, service: MigrationService
    ) -> None:
        _seed_preexisting(engine)
        # Same channel the pre-existing item occupies, overlapping window.
        inv = _inventory(channel_ref="9")
        inv.schedule_items[0].scheduled_at = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
        plan = service.dry_run(inv)
        conflicted = {c.source_ref for c in plan.conflicts if c.kind == "schedule_item"}
        assert "1087848" in conflicted

    def test_title_with_underscore_does_not_wildcard_match_a_different_title(
        self, engine: Any, service: MigrationService
    ) -> None:
        # File-based adapters (TelVue/Castus/Leightronix) fall back to the
        # on-server filename as the title, and filenames routinely contain
        # underscores. SQL LIKE/ILIKE treats "_" as a single-char wildcard,
        # so an unescaped ilike() would falsely collide "council_mtg_2026"
        # with an unrelated pre-existing title like "councilXmtg2026".
        with Session(bind=engine) as session:
            session.add(Asset(asset_id="pre-existing", title="councilXmtgY2026"))
            session.commit()

        inv = _inventory()
        inv.shows[0].title = "council_mtg_2026"
        plan = service.dry_run(inv)
        conflicted_refs = {c.source_ref for c in plan.conflicts if c.kind == "show"}
        assert conflicted_refs == set()
        assert {s.source_ref for s in plan.shows_to_create} == {"73411", "73410"}

    def test_flags_time_collision_within_the_same_import(self, service: MigrationService) -> None:
        inv = _inventory(channel_ref="same")
        # Force both items onto the identical overlapping window.
        inv.schedule_items[1].scheduled_at = inv.schedule_items[0].scheduled_at
        inv.schedule_items[1].duration_seconds = inv.schedule_items[0].duration_seconds
        plan = service.dry_run(inv)
        assert len(plan.schedule_items_to_create) == 1
        assert any(c.kind == "schedule_item" for c in plan.conflicts)


class TestApplyAndRollback:
    def test_apply_creates_real_asset_and_schedule_rows(
        self, engine: Any, service: MigrationService
    ) -> None:
        plan = service.dry_run(_inventory())
        batch = service.apply(plan)

        assert batch.status == "applied"
        assert batch.shows_created == 2
        assert batch.schedule_items_created == 2
        assert batch.apply_failures == []

        with Session(bind=engine) as session:
            assert session.get(Asset, "cablecast-show-73410") is not None
            militaru = session.get(Asset, "cablecast-show-73411")
            assert militaru is not None
            assert militaru.state == "pending_ingest"
            assert militaru.manifest_url is None

    def test_apply_records_a_failure_instead_of_raising_on_a_race(
        self, engine: Any, service: MigrationService
    ) -> None:
        plan = service.dry_run(_inventory())
        # Simulate a second import batch landing the same asset id between
        # dry-run and apply.
        with Session(bind=engine) as session:
            session.add(Asset(asset_id=plan.shows_to_create[0].asset_id, title="Raced in"))
            session.commit()

        batch = service.apply(plan)
        failed_refs = {f.source_ref for f in batch.apply_failures if f.kind == "show"}
        assert plan.shows_to_create[0].source_ref in failed_refs
        # The other show still applies fine.
        assert batch.shows_created == 1

    def test_apply_does_not_orphan_an_asset_row_when_the_ledger_write_fails(
        self,
        engine: Any,
        service: MigrationService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A DB hiccup/disk-full/dropped-connection during the ledger write
        # (anything other than the two exception types apply() already
        # catches) must not leave a committed, un-ledgered, unrollbackable
        # Asset row behind -- apply() should surface it as a recorded
        # failure, not an uncaught exception with an orphan row.
        plan = service.dry_run(_inventory())
        real_add_item = service._ledger.add_item

        def _boom(**kwargs: Any) -> None:
            if kwargs["entity_type"] == "asset":
                raise RuntimeError("disk full")
            real_add_item(**kwargs)

        monkeypatch.setattr(service._ledger, "add_item", _boom)

        batch = service.apply(plan)  # must not raise

        with Session(bind=engine) as session:
            assert session.get(Asset, plan.shows_to_create[0].asset_id) is None
            assert session.get(Asset, plan.shows_to_create[1].asset_id) is None
        failed_refs = {f.source_ref for f in batch.apply_failures if f.kind == "show"}
        assert failed_refs == {s.source_ref for s in plan.shows_to_create}

    def test_apply_does_not_orphan_a_schedule_item_when_the_ledger_write_fails(
        self,
        engine: Any,
        service: MigrationService,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        plan = service.dry_run(_inventory())
        real_add_item = service._ledger.add_item

        def _boom(**kwargs: Any) -> None:
            if kwargs["entity_type"] == "schedule_item":
                raise RuntimeError("connection dropped")
            real_add_item(**kwargs)

        monkeypatch.setattr(service._ledger, "add_item", _boom)

        batch = service.apply(plan)  # must not raise

        with Session(bind=engine) as session:
            remaining = session.execute(select(ScheduleItem)).scalars().all()
            assert remaining == []
        failed_refs = {f.source_ref for f in batch.apply_failures if f.kind == "schedule_item"}
        assert failed_refs == {i.source_ref for i in plan.schedule_items_to_create}

    def test_rollback_does_not_delete_an_asset_a_later_schedule_item_now_references(
        self, engine: Any, service: MigrationService
    ) -> None:
        # schedule_items.asset_id has no FK (see service.py/store.py module
        # docstrings), so staff can schedule a rerun against a freshly
        # imported pending_ingest asset through the normal schedule API
        # before an operator rolls back the (mistaken) import batch. That
        # staff-created row is not in this batch's ledger and must survive.
        plan = service.dry_run(_inventory())
        batch = service.apply(plan)
        imported_asset_id = plan.shows_to_create[0].asset_id

        with Session(bind=engine) as session:
            session.add(
                ScheduleItem(
                    id=uuid.uuid4(),
                    asset_id=imported_asset_id,
                    channel_id="staff-ch-1",
                    mode="premiere",
                    scheduled_at=datetime(2026, 9, 1, tzinfo=UTC),
                    scheduled_at_end=datetime(2026, 9, 1, 1, 0, tzinfo=UTC),
                    duration_seconds=3600,
                )
            )
            session.commit()

        service.rollback(batch.import_batch_id)

        with Session(bind=engine) as session:
            assert session.get(Asset, imported_asset_id) is not None, (
                "asset was deleted out from under a schedule_item that still references it"
            )

    def test_apply_then_rollback_restores_prior_state_byte_exact(
        self, engine: Any, service: MigrationService
    ) -> None:
        _seed_preexisting(engine)
        before_assets = _dump_table(engine, "assets")
        before_schedule = _dump_table(engine, "schedule_items")
        assert len(before_assets) == 1
        assert len(before_schedule) == 1

        plan = service.dry_run(_inventory())
        batch = service.apply(plan)
        assert batch.shows_created == 2
        assert batch.schedule_items_created == 2

        mid_assets = _dump_table(engine, "assets")
        mid_schedule = _dump_table(engine, "schedule_items")
        assert len(mid_assets) == 3
        assert len(mid_schedule) == 3

        rolled_back = service.rollback(batch.import_batch_id)
        assert rolled_back.status == "rolled_back"
        assert rolled_back.rolled_back_at is not None

        after_assets = _dump_table(engine, "assets")
        after_schedule = _dump_table(engine, "schedule_items")
        assert after_assets == before_assets
        assert after_schedule == before_schedule

        # A fresh dry-run against the same source now proposes the imported
        # rows again — proof the deletion was real, not a soft/cancelled
        # state left behind.
        rerun_plan = service.dry_run(_inventory())
        assert {s.source_ref for s in rerun_plan.shows_to_create} == {"73411", "73410"}

    def test_rollback_twice_raises(self, service: MigrationService) -> None:
        plan = service.dry_run(_inventory())
        batch = service.apply(plan)
        service.rollback(batch.import_batch_id)
        with pytest.raises(BatchAlreadyRolledBackError):
            service.rollback(batch.import_batch_id)

    def test_list_batches_surfaces_the_applied_batch(self, service: MigrationService) -> None:
        plan = service.dry_run(_inventory())
        batch = service.apply(plan)
        ids = {b.import_batch_id for b in service.list_batches()}
        assert batch.import_batch_id in ids


def test_table_metadata_is_registered_on_base(engine: Any) -> None:
    tables = inspect(engine).get_table_names(schema="civiccast")
    assert "import_batches" in tables
    assert "import_batch_items" in tables
