# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Item 23 producer ops data layer — models + ProducerOpsStore + migration
0063_producer_ops.

Real-SQLite unit tests (the migration is run end-to-end against a temp
SQLite DB), mirroring ``tests/paywall/test_models_and_store.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.producer_ops.models import (
    CallSheet,
    CallSheetAssignment,
    EquipmentAccessRule,
    EquipmentCheckout,
    EquipmentItem,
    SeriesApplication,
    TrainingBadge,
    VolunteerRole,
)
from civiccast.producer_ops.store import (
    CallSheetNotFoundError,
    CheckoutNotFoundError,
    EquipmentAlreadyCheckedOutError,
    EquipmentNotFoundError,
    MissingRequiredBadgeError,
    ProducerOpsStore,
    SeriesApplicationNotFoundError,
    VolunteerNotFoundError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[ProducerOpsStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'p.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as sess:
            yield sess

    try:
        yield ProducerOpsStore(factory)
    finally:
        eng.dispose()


def _volunteer(volunteer_id: str = "vol-1", **overrides: object) -> VolunteerRole:
    defaults: dict[str, object] = {
        "volunteer_id": volunteer_id,
        "display_name": "Alex Volunteer",
        "role_name": "camera",
    }
    defaults.update(overrides)
    return VolunteerRole(**defaults)  # type: ignore[arg-type]


def _equipment(equipment_id: str = "cam-1", **overrides: object) -> EquipmentItem:
    defaults: dict[str, object] = {
        "equipment_id": equipment_id,
        "name": "Camera 1",
        "category": "camera",
    }
    defaults.update(overrides)
    return EquipmentItem(**defaults)  # type: ignore[arg-type]


# --- models -------------------------------------------------------------


class TestSeriesApplicationModel:
    def test_default_state_is_submitted(self) -> None:
        app = SeriesApplication(
            application_id="app-1",
            contributor_id="contrib-1",
            series_title="Weekly Roundtable",
            proposed_cadence="every Tuesday",
            description="A weekly civic roundtable.",
        )
        assert app.state == "submitted"
        assert app.series_id is None

    def test_uppercase_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            SeriesApplication(
                application_id="APP-Bad",
                contributor_id="contrib-1",
                series_title="x",
                proposed_cadence="x",
                description="x",
            )

    def test_unknown_state_rejected(self) -> None:
        with pytest.raises(ValueError):
            SeriesApplication(
                application_id="app-1",
                contributor_id="contrib-1",
                series_title="x",
                proposed_cadence="x",
                description="x",
                state="maybe",  # type: ignore[arg-type]
            )


class TestEquipmentCheckoutModel:
    def test_checked_out_with_returned_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            EquipmentCheckout(
                checkout_id="co-1",
                equipment_id="cam-1",
                volunteer_id="vol-1",
                state="checked_out",
                returned_at=datetime.now(UTC),
            )

    def test_returned_without_returned_at_rejected(self) -> None:
        with pytest.raises(ValueError):
            EquipmentCheckout(
                checkout_id="co-1",
                equipment_id="cam-1",
                volunteer_id="vol-1",
                state="returned",
            )

    def test_valid_returned_checkout(self) -> None:
        checkout = EquipmentCheckout(
            checkout_id="co-1",
            equipment_id="cam-1",
            volunteer_id="vol-1",
            state="returned",
            returned_at=datetime.now(UTC),
        )
        assert checkout.state == "returned"


# --- series applications --------------------------------------------------


class TestSeriesApplicationStore:
    def test_create_and_get_round_trip(self, store: ProducerOpsStore) -> None:
        app = SeriesApplication(
            application_id="app-1",
            contributor_id="contrib-1",
            series_title="Weekly Roundtable",
            proposed_cadence="every Tuesday",
            description="A weekly civic roundtable.",
        )
        created = store.create_series_application(app)
        assert created.state == "submitted"
        fetched = store.get_series_application("app-1")
        assert fetched.series_title == "Weekly Roundtable"

    def test_get_missing_raises(self, store: ProducerOpsStore) -> None:
        with pytest.raises(SeriesApplicationNotFoundError):
            store.get_series_application("missing")

    def test_review_transitions_state(self, store: ProducerOpsStore) -> None:
        store.create_series_application(
            SeriesApplication(
                application_id="app-1",
                contributor_id="contrib-1",
                series_title="x",
                proposed_cadence="x",
                description="x",
            )
        )
        reviewed = store.review_series_application("app-1", state="approved", series_id="series-42")
        assert reviewed.state == "approved"
        assert reviewed.series_id == "series-42"

    def test_review_missing_raises(self, store: ProducerOpsStore) -> None:
        with pytest.raises(SeriesApplicationNotFoundError):
            store.review_series_application("missing", state="approved")

    def test_list_orders_by_created_at(self, store: ProducerOpsStore) -> None:
        store.create_series_application(
            SeriesApplication(
                application_id="app-1",
                contributor_id="contrib-1",
                series_title="First",
                proposed_cadence="x",
                description="x",
            )
        )
        store.create_series_application(
            SeriesApplication(
                application_id="app-2",
                contributor_id="contrib-1",
                series_title="Second",
                proposed_cadence="x",
                description="x",
            )
        )
        rows = store.list_series_applications()
        assert [r.application_id for r in rows] == ["app-1", "app-2"]


# --- volunteer roster ------------------------------------------------------


class TestVolunteerStore:
    def test_upsert_creates_then_updates(self, store: ProducerOpsStore) -> None:
        created = store.upsert_volunteer(_volunteer())
        assert created.active is True
        updated = store.upsert_volunteer(_volunteer(display_name="Alex U. Volunteer"))
        assert updated.display_name == "Alex U. Volunteer"
        assert len(store.list_volunteers()) == 1

    def test_get_missing_raises(self, store: ProducerOpsStore) -> None:
        with pytest.raises(VolunteerNotFoundError):
            store.get_volunteer("missing")

    def test_active_only_filter(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer("vol-1", active=True))
        store.upsert_volunteer(_volunteer("vol-2", active=False))
        assert {v.volunteer_id for v in store.list_volunteers(active_only=True)} == {"vol-1"}
        assert {v.volunteer_id for v in store.list_volunteers()} == {"vol-1", "vol-2"}


# --- call sheets ------------------------------------------------------------


class TestCallSheetStore:
    def test_create_and_assign(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.create_call_sheet(
            CallSheet(
                call_sheet_id="cs-1",
                title="City Council Live Shoot",
                shoot_date=datetime.now(UTC),
            )
        )
        assignment = store.add_call_sheet_assignment(
            CallSheetAssignment(
                assignment_id="asn-1",
                call_sheet_id="cs-1",
                volunteer_id="vol-1",
                role_name="camera",
            )
        )
        assert assignment.call_sheet_id == "cs-1"
        assert [a.assignment_id for a in store.list_call_sheet_assignments("cs-1")] == ["asn-1"]

    def test_assign_unknown_call_sheet_raises(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        with pytest.raises(CallSheetNotFoundError):
            store.add_call_sheet_assignment(
                CallSheetAssignment(
                    assignment_id="asn-1",
                    call_sheet_id="missing",
                    volunteer_id="vol-1",
                    role_name="camera",
                )
            )

    def test_assign_unknown_volunteer_raises(self, store: ProducerOpsStore) -> None:
        store.create_call_sheet(
            CallSheet(call_sheet_id="cs-1", title="x", shoot_date=datetime.now(UTC))
        )
        with pytest.raises(VolunteerNotFoundError):
            store.add_call_sheet_assignment(
                CallSheetAssignment(
                    assignment_id="asn-1",
                    call_sheet_id="cs-1",
                    volunteer_id="missing",
                    role_name="camera",
                )
            )

    def test_get_missing_call_sheet_raises(self, store: ProducerOpsStore) -> None:
        with pytest.raises(CallSheetNotFoundError):
            store.get_call_sheet("missing")


# --- equipment + checkouts --------------------------------------------------


class TestEquipmentCheckoutStore:
    def test_checkout_and_return_round_trip(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.upsert_equipment(_equipment())
        checkout = store.check_out(
            EquipmentCheckout(checkout_id="co-1", equipment_id="cam-1", volunteer_id="vol-1")
        )
        assert checkout.state == "checked_out"
        assert store.get_open_checkout("cam-1") is not None

        returned = store.return_checkout("co-1")
        assert returned.state == "returned"
        assert returned.returned_at is not None
        assert store.get_open_checkout("cam-1") is None

    def test_double_checkout_rejected(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.upsert_equipment(_equipment())
        store.check_out(
            EquipmentCheckout(checkout_id="co-1", equipment_id="cam-1", volunteer_id="vol-1")
        )
        with pytest.raises(EquipmentAlreadyCheckedOutError):
            store.check_out(
                EquipmentCheckout(checkout_id="co-2", equipment_id="cam-1", volunteer_id="vol-1")
            )

    def test_checkout_after_return_allowed(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.upsert_equipment(_equipment())
        store.check_out(
            EquipmentCheckout(checkout_id="co-1", equipment_id="cam-1", volunteer_id="vol-1")
        )
        store.return_checkout("co-1")
        second = store.check_out(
            EquipmentCheckout(checkout_id="co-2", equipment_id="cam-1", volunteer_id="vol-1")
        )
        assert second.state == "checked_out"

    def test_checkout_unknown_equipment_raises(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        with pytest.raises(EquipmentNotFoundError):
            store.check_out(
                EquipmentCheckout(checkout_id="co-1", equipment_id="missing", volunteer_id="vol-1")
            )

    def test_checkout_unknown_volunteer_raises(self, store: ProducerOpsStore) -> None:
        store.upsert_equipment(_equipment())
        with pytest.raises(VolunteerNotFoundError):
            store.check_out(
                EquipmentCheckout(checkout_id="co-1", equipment_id="cam-1", volunteer_id="missing")
            )

    def test_return_missing_checkout_raises(self, store: ProducerOpsStore) -> None:
        with pytest.raises(CheckoutNotFoundError):
            store.return_checkout("missing")

    def test_checkout_requires_badge_when_rule_set(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.upsert_equipment(_equipment())
        store.set_access_rule(
            EquipmentAccessRule(
                rule_id="rule-1", equipment_id="cam-1", required_badge_name="camera-1"
            )
        )
        with pytest.raises(MissingRequiredBadgeError):
            store.check_out(
                EquipmentCheckout(checkout_id="co-1", equipment_id="cam-1", volunteer_id="vol-1")
            )

    def test_checkout_succeeds_with_badge(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.upsert_equipment(_equipment())
        store.set_access_rule(
            EquipmentAccessRule(
                rule_id="rule-1", equipment_id="cam-1", required_badge_name="camera-1"
            )
        )
        store.grant_badge(
            TrainingBadge(badge_id="badge-1", volunteer_id="vol-1", badge_name="camera-1")
        )
        checkout = store.check_out(
            EquipmentCheckout(checkout_id="co-1", equipment_id="cam-1", volunteer_id="vol-1")
        )
        assert checkout.state == "checked_out"

    def test_expired_badge_blocks_checkout(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.upsert_equipment(_equipment())
        store.set_access_rule(
            EquipmentAccessRule(
                rule_id="rule-1", equipment_id="cam-1", required_badge_name="camera-1"
            )
        )
        store.grant_badge(
            TrainingBadge(
                badge_id="badge-1",
                volunteer_id="vol-1",
                badge_name="camera-1",
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        with pytest.raises(MissingRequiredBadgeError):
            store.check_out(
                EquipmentCheckout(checkout_id="co-1", equipment_id="cam-1", volunteer_id="vol-1")
            )

    def test_item_with_no_rule_is_uncontrolled(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.upsert_equipment(_equipment())
        checkout = store.check_out(
            EquipmentCheckout(checkout_id="co-1", equipment_id="cam-1", volunteer_id="vol-1")
        )
        assert checkout.state == "checked_out"


class TestTrainingBadgeStore:
    def test_grant_and_list(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.grant_badge(
            TrainingBadge(badge_id="badge-1", volunteer_id="vol-1", badge_name="camera-1")
        )
        badges = store.list_badges_for_volunteer("vol-1")
        assert [b.badge_name for b in badges] == ["camera-1"]

    def test_grant_unknown_volunteer_raises(self, store: ProducerOpsStore) -> None:
        with pytest.raises(VolunteerNotFoundError):
            store.grant_badge(
                TrainingBadge(badge_id="badge-1", volunteer_id="missing", badge_name="camera-1")
            )

    def test_has_active_badge_false_when_none(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        assert store.has_active_badge("vol-1", "camera-1") is False

    def test_has_active_badge_false_when_expired(self, store: ProducerOpsStore) -> None:
        store.upsert_volunteer(_volunteer())
        store.grant_badge(
            TrainingBadge(
                badge_id="badge-1",
                volunteer_id="vol-1",
                badge_name="camera-1",
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
        )
        assert store.has_active_badge("vol-1", "camera-1") is False


class TestEquipmentAccessRuleStore:
    def test_set_rule_requires_existing_equipment(self, store: ProducerOpsStore) -> None:
        with pytest.raises(EquipmentNotFoundError):
            store.set_access_rule(
                EquipmentAccessRule(
                    rule_id="rule-1", equipment_id="missing", required_badge_name="camera-1"
                )
            )

    def test_set_rule_replaces_existing(self, store: ProducerOpsStore) -> None:
        store.upsert_equipment(_equipment())
        store.set_access_rule(
            EquipmentAccessRule(
                rule_id="rule-1", equipment_id="cam-1", required_badge_name="camera-1"
            )
        )
        replaced = store.set_access_rule(
            EquipmentAccessRule(
                rule_id="rule-2", equipment_id="cam-1", required_badge_name="camera-2"
            )
        )
        assert replaced.required_badge_name == "camera-2"
        fetched = store.get_access_rule("cam-1")
        assert fetched is not None
        assert fetched.required_badge_name == "camera-2"

    def test_get_rule_none_when_unset(self, store: ProducerOpsStore) -> None:
        store.upsert_equipment(_equipment())
        assert store.get_access_rule("cam-1") is None


# --- migration ----------------------------------------------------------------


def _make_cfg(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


class TestMigration0062UpgradeDowngrade:
    """The migration must create all six tables + the CHECKs/INDEXes and
    cleanly downgrade back to ``0062_media_integrity_columns``. Real-SQLite
    here; the real-PG locks live in ``tests/live/test_real_postgres.py``."""

    _TABLES = (
        "series_applications",
        "volunteer_roles",
        "call_sheets",
        "call_sheet_assignments",
        "equipment_items",
        "equipment_checkouts",
        "training_badges",
        "equipment_access_rules",
    )

    def test_upgrade_creates_all_tables(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'mig.sqlite'}"
        cfg = _make_cfg(url)
        command.upgrade(cfg, "head")
        eng = create_engine(url, future=True)
        try:
            names = set(inspect(eng).get_table_names())
            for table in self._TABLES:
                assert table in names
        finally:
            eng.dispose()

    def test_upgrade_creates_partial_unique_index(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'mig2.sqlite'}"
        cfg = _make_cfg(url)
        command.upgrade(cfg, "head")
        eng = create_engine(url, future=True)
        try:
            with eng.connect() as conn:
                from sqlalchemy import text
                from sqlalchemy.exc import IntegrityError

                conn.execute(
                    text(
                        "INSERT INTO equipment_checkouts "
                        "(checkout_id, equipment_id, volunteer_id, state, checked_out_at) "
                        "VALUES ('co-1', 'cam-1', 'vol-1', 'checked_out', CURRENT_TIMESTAMP)"
                    )
                )
                conn.commit()
                with pytest.raises(IntegrityError):
                    conn.execute(
                        text(
                            "INSERT INTO equipment_checkouts "
                            "(checkout_id, equipment_id, volunteer_id, state, checked_out_at) "
                            "VALUES ('co-2', 'cam-1', 'vol-2', 'checked_out', CURRENT_TIMESTAMP)"
                        )
                    )
        finally:
            eng.dispose()

    def test_downgrade_drops_all_tables(self, tmp_path: Path) -> None:
        url = f"sqlite:///{tmp_path / 'mig3.sqlite'}"
        cfg = _make_cfg(url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0062_media_integrity_columns")
        eng = create_engine(url, future=True)
        try:
            names = set(inspect(eng).get_table_names())
            for table in self._TABLES:
                assert table not in names
        finally:
            eng.dispose()
