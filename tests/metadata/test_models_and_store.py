# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S22 metadata data layer — models + CustomFieldStore + migration 0054.

SQLite-backed; the live-Postgres full-chain head check lives in
tests/live/test_real_postgres.py. The 0054 migration's up/down reversibility is
asserted by TestCustomMetadataFieldsMigration via the real Alembic chain on SQLite.

Covers (spec §3/§6): typed CustomFieldDef + CustomFieldValue models, store CRUD,
typed validation at write (list->option, number->value_num, date->value_date,
required->present), key-immutability after creation, and delete-with-values guard.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.metadata.models import CustomFieldDef, CustomFieldValue
from civiccast.metadata.store import (
    CustomFieldStore,
    FieldImmutableKeyError,
    FieldNotFoundError,
    FieldValidationError,
    FieldValuesExistError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[CustomFieldStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'metadata.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield CustomFieldStore(factory)
    finally:
        eng.dispose()


def _def(field_id: str = "fld_meeting_type", **kw: object) -> CustomFieldDef:
    base: dict[str, object] = {
        "field_id": field_id,
        "station_id": "sta_main",
        "key": "meeting_type",
        "label": "Meeting Type",
        "type": "text",
    }
    base.update(kw)
    return CustomFieldDef(**base)  # type: ignore[arg-type]


# --- pydantic models ---------------------------------------------------------


class TestModels:
    def test_def_defaults(self) -> None:
        d = _def()
        assert d.options == []
        assert d.required is False
        assert d.searchable is True
        assert d.api_exposed is True
        assert d.order == 0

    def test_value_defaults(self) -> None:
        v = CustomFieldValue(asset_id="ast_1", field_id="fld_meeting_type", value="Regular")
        assert v.value_num is None
        assert v.value_date is None

    def test_def_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            CustomFieldDef(
                field_id="fld_x",
                station_id="sta_main",
                key="k",
                label="L",
                type="text",
                bogus="nope",  # type: ignore[call-arg]
            )

    def test_def_rejects_bad_type(self) -> None:
        with pytest.raises(ValidationError):
            _def(type="rich_text")  # not in CustomFieldType


# --- field-definition CRUD ---------------------------------------------------


class TestFieldDefs:
    def test_get_missing_returns_none(self, store: CustomFieldStore) -> None:
        assert store.get_def("fld_nope") is None

    def test_upsert_and_round_trip(self, store: CustomFieldStore) -> None:
        saved = store.upsert_def(_def())
        assert saved.key == "meeting_type"
        got = store.get_def("fld_meeting_type")
        assert got is not None
        assert got.label == "Meeting Type"
        assert got.type == "text"

    def test_list_orders_by_order_then_label(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_b", key="b", label="Bravo", order=2))
        store.upsert_def(_def("fld_a", key="a", label="Alpha", order=1))
        store.upsert_def(_def("fld_c", key="c", label="Charlie", order=1))
        ordered = [d.field_id for d in store.list_defs("sta_main")]
        # order=1 rows first (alpha, charlie by label), then order=2 (bravo)
        assert ordered == ["fld_a", "fld_c", "fld_b"]

    def test_list_scoped_by_station(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_main", station_id="sta_main", key="m"))
        store.upsert_def(_def("fld_other", station_id="sta_other", key="o"))
        ids = [d.field_id for d in store.list_defs("sta_main")]
        assert ids == ["fld_main"]

    def test_list_exposed_only(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_pub", key="pub", searchable=True, api_exposed=True))
        store.upsert_def(_def("fld_hidden", key="hidden", searchable=True, api_exposed=False))
        store.upsert_def(_def("fld_internal", key="internal", searchable=False, api_exposed=True))
        ids = [d.field_id for d in store.list_defs("sta_main", exposed_only=True)]
        assert ids == ["fld_pub"]

    def test_label_is_editable(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def())
        updated = store.upsert_def(_def(label="Type of Meeting"))
        assert updated.label == "Type of Meeting"

    def test_key_is_immutable_after_creation(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def())
        with pytest.raises(FieldImmutableKeyError):
            store.upsert_def(_def(key="meeting_kind"))  # same field_id, changed key
        # The stored key is unchanged.
        assert store.get_def("fld_meeting_type").key == "meeting_type"  # type: ignore[union-attr]

    def test_timestamps_are_utc_aware(self, store: CustomFieldStore) -> None:
        d = store.upsert_def(_def())
        assert d.created_at.tzinfo is not None
        assert d.updated_at.tzinfo is not None


# --- deletion safety ---------------------------------------------------------


class TestDeleteDef:
    def test_delete_unknown_raises(self, store: CustomFieldStore) -> None:
        with pytest.raises(FieldNotFoundError):
            store.delete_def("fld_nope")

    def test_delete_without_values_succeeds(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def())
        store.delete_def("fld_meeting_type")
        assert store.get_def("fld_meeting_type") is None

    def test_delete_with_values_blocked_without_confirm(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def())
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_meeting_type", value="Regular")],
            definitions=store.list_defs("sta_main"),
        )
        with pytest.raises(FieldValuesExistError):
            store.delete_def("fld_meeting_type")
        # Still present; no silent loss.
        assert store.get_def("fld_meeting_type") is not None

    def test_delete_with_values_cascades_with_confirm(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def())
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_meeting_type", value="Regular")],
            definitions=store.list_defs("sta_main"),
        )
        store.delete_def("fld_meeting_type", confirm=True)
        assert store.get_def("fld_meeting_type") is None
        # The value rows are gone too (cascade).
        assert store.get_values("ast_1") == []


# --- asset values + typed validation (spec §6) -------------------------------


def _defs_for_value_tests(store: CustomFieldStore) -> list[CustomFieldDef]:
    store.upsert_def(_def("fld_text", key="note", label="Note", type="text"))
    store.upsert_def(
        _def("fld_list", key="cat", label="Category", type="list", options=["Gov", "PEG"])
    )
    store.upsert_def(_def("fld_num", key="ep", label="Episode", type="number"))
    store.upsert_def(_def("fld_date", key="aired", label="Aired", type="date"))
    store.upsert_def(_def("fld_bool", key="flag", label="Flagged", type="boolean"))
    store.upsert_def(_def("fld_req", key="prod", label="Producer Name", type="text", required=True))
    return store.list_defs("sta_main")


class TestValues:
    def test_empty_values_is_valid_zero_state(self, store: CustomFieldStore) -> None:
        # Absence of any custom field is always valid (S22 key claim).
        assert store.get_values("ast_unknown") == []

    def test_set_and_get_round_trip(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_text", key="note", type="text"))
        defs = store.list_defs("sta_main")
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_text", value="hello")],
            definitions=defs,
        )
        got = {v.field_id: v.value for v in store.get_values("ast_1")}
        assert got == {"fld_text": "hello"}

    def test_set_is_full_replace(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_a", key="a", type="text"))
        store.upsert_def(_def("fld_b", key="b", type="text"))
        defs = store.list_defs("sta_main")
        store.set_values(
            "ast_1",
            [
                CustomFieldValue(asset_id="ast_1", field_id="fld_a", value="1"),
                CustomFieldValue(asset_id="ast_1", field_id="fld_b", value="2"),
            ],
            definitions=defs,
        )
        # Replace with only fld_a -> fld_b's value row is removed.
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_a", value="X")],
            definitions=defs,
        )
        got = {v.field_id: v.value for v in store.get_values("ast_1")}
        assert got == {"fld_a": "X"}

    def test_number_denormalizes_value_num(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        store.set_values(
            "ast_1",
            [
                CustomFieldValue(asset_id="ast_1", field_id="fld_num", value="42"),
                CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
            ],
            definitions=defs,
        )
        num = next(v for v in store.get_values("ast_1") if v.field_id == "fld_num")
        assert num.value_num == 42.0
        assert num.value_date is None

    def test_date_denormalizes_value_date(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        store.set_values(
            "ast_1",
            [
                CustomFieldValue(asset_id="ast_1", field_id="fld_date", value="2026-03-14"),
                CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
            ],
            definitions=defs,
        )
        d = next(v for v in store.get_values("ast_1") if v.field_id == "fld_date")
        assert d.value_date == date(2026, 3, 14)
        assert d.value_num is None

    @pytest.mark.parametrize(
        ("field_id", "value"),
        [("fld_text", "a note"), ("fld_list", "PEG"), ("fld_bool", "true")],
    )
    def test_non_numeric_non_date_types_denormalize_to_none(
        self, store: CustomFieldStore, field_id: str, value: str
    ) -> None:
        # T4: text/list/boolean leave BOTH value_num and value_date None (matching the
        # number<->date cross-isolation already covered for the range types).
        defs = _defs_for_value_tests(store)
        store.set_values(
            "ast_1",
            [
                CustomFieldValue(asset_id="ast_1", field_id=field_id, value=value),
                CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
            ],
            definitions=defs,
        )
        stored = next(v for v in store.get_values("ast_1") if v.field_id == field_id)
        assert stored.value_num is None
        assert stored.value_date is None

    def test_list_must_be_an_option(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        with pytest.raises(FieldValidationError):
            store.set_values(
                "ast_1",
                [
                    CustomFieldValue(asset_id="ast_1", field_id="fld_list", value="NotAnOption"),
                    CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
                ],
                definitions=defs,
            )

    def test_list_accepts_a_valid_option(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        store.set_values(
            "ast_1",
            [
                CustomFieldValue(asset_id="ast_1", field_id="fld_list", value="PEG"),
                CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
            ],
            definitions=defs,
        )
        cat = next(v for v in store.get_values("ast_1") if v.field_id == "fld_list")
        assert cat.value == "PEG"

    def test_number_rejects_non_numeric(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        with pytest.raises(FieldValidationError):
            store.set_values(
                "ast_1",
                [
                    CustomFieldValue(asset_id="ast_1", field_id="fld_num", value="not-a-number"),
                    CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
                ],
                definitions=defs,
            )

    @pytest.mark.parametrize("bad", ["inf", "+inf", "-inf", "infinity", "nan", "NaN"])
    def test_number_rejects_non_finite(self, store: CustomFieldStore, bad: str) -> None:
        # T1: bare float() accepts inf/-inf/nan; a non-finite number is invisible to range
        # scans (and NaN breaks the value<->value_num invariant), so it is rejected exactly
        # like any other bad number (422 via FieldValidationError at the router).
        defs = _defs_for_value_tests(store)
        with pytest.raises(FieldValidationError):
            store.set_values(
                "ast_1",
                [
                    CustomFieldValue(asset_id="ast_1", field_id="fld_num", value=bad),
                    CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
                ],
                definitions=defs,
            )

    def test_number_accepts_finite_after_non_finite_guard(self, store: CustomFieldStore) -> None:
        # The finite path still works (the guard only rejects NaN/inf/-inf).
        defs = _defs_for_value_tests(store)
        store.set_values(
            "ast_1",
            [
                CustomFieldValue(asset_id="ast_1", field_id="fld_num", value="-273.15"),
                CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
            ],
            definitions=defs,
        )
        num = next(v for v in store.get_values("ast_1") if v.field_id == "fld_num")
        assert num.value_num == -273.15

    def test_date_rejects_non_date(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        with pytest.raises(FieldValidationError):
            store.set_values(
                "ast_1",
                [
                    CustomFieldValue(asset_id="ast_1", field_id="fld_date", value="14/03/2026"),
                    CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
                ],
                definitions=defs,
            )

    def test_boolean_rejects_non_boolean(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        with pytest.raises(FieldValidationError):
            store.set_values(
                "ast_1",
                [
                    CustomFieldValue(asset_id="ast_1", field_id="fld_bool", value="maybe"),
                    CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
                ],
                definitions=defs,
            )

    def test_boolean_accepts_true_false(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        store.set_values(
            "ast_1",
            [
                CustomFieldValue(asset_id="ast_1", field_id="fld_bool", value="true"),
                CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
            ],
            definitions=defs,
        )
        b = next(v for v in store.get_values("ast_1") if v.field_id == "fld_bool")
        assert b.value == "true"

    def test_required_must_be_present(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        # fld_req is required but omitted from the value set.
        with pytest.raises(FieldValidationError):
            store.set_values(
                "ast_1",
                [CustomFieldValue(asset_id="ast_1", field_id="fld_text", value="hi")],
                definitions=defs,
            )

    def test_required_blank_is_rejected(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        with pytest.raises(FieldValidationError):
            store.set_values(
                "ast_1",
                [CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="   ")],
                definitions=defs,
            )

    def test_value_for_unknown_field_is_rejected(self, store: CustomFieldStore) -> None:
        defs = _defs_for_value_tests(store)
        with pytest.raises(FieldValidationError):
            store.set_values(
                "ast_1",
                [
                    CustomFieldValue(asset_id="ast_1", field_id="fld_ghost", value="x"),
                    CustomFieldValue(asset_id="ast_1", field_id="fld_req", value="Jane"),
                ],
                definitions=defs,
            )

    def test_set_value_upserts_one_row_per_asset_field(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_text", key="note", type="text"))
        defs = store.list_defs("sta_main")
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_text", value="v1")],
            definitions=defs,
        )
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_text", value="v2")],
            definitions=defs,
        )
        vals = store.get_values("ast_1")
        assert len(vals) == 1
        assert vals[0].value == "v2"

    def test_values_are_isolated_per_asset(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_text", key="note", type="text"))
        defs = store.list_defs("sta_main")
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_text", value="a")],
            definitions=defs,
        )
        store.set_values(
            "ast_2",
            [CustomFieldValue(asset_id="ast_2", field_id="fld_text", value="b")],
            definitions=defs,
        )
        assert store.get_values("ast_1")[0].value == "a"
        assert store.get_values("ast_2")[0].value == "b"

    def test_value_timestamps_are_utc_aware(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_text", key="note", type="text"))
        defs = store.list_defs("sta_main")
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_text", value="x")],
            definitions=defs,
        )
        v = store.get_values("ast_1")[0]
        assert v.created_at.tzinfo is not None
        assert v.updated_at.tzinfo is not None


# --- range-query denormalization read-back ----------------------------------


class TestRangeDenormalization:
    def test_num_range_columns_persist(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_num", key="ep", type="number"))
        defs = store.list_defs("sta_main")
        for aid, n in (("ast_1", "10"), ("ast_2", "20"), ("ast_3", "30")):
            store.set_values(
                aid,
                [CustomFieldValue(asset_id=aid, field_id="fld_num", value=n)],
                definitions=defs,
            )
        # value_num is the denormalized numeric used by S19/S23 range scans.
        assert store.get_values("ast_2")[0].value_num == 20.0

    def test_date_range_columns_persist(self, store: CustomFieldStore) -> None:
        store.upsert_def(_def("fld_date", key="aired", type="date"))
        defs = store.list_defs("sta_main")
        store.set_values(
            "ast_1",
            [CustomFieldValue(asset_id="ast_1", field_id="fld_date", value="2026-06-01")],
            definitions=defs,
        )
        assert store.get_values("ast_1")[0].value_date == date(2026, 6, 1)


# --- migration 0054 ----------------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestCustomMetadataFieldsMigration:
    """0054_custom_metadata_fields creates its two tables on upgrade and drops
    exactly those on a single-step downgrade to 0053 — the rest survives."""

    _TABLES = ("custom_field_defs", "custom_field_values")

    def test_upgrade_to_0054_records_that_revision(self, tmp_path: Path) -> None:
        # The GLOBAL chain head advanced past 0054 (S23 = 0055_asrun_and_epg pins
        # the head in tests/reporting/). This test upgrades to the EXPLICIT 0054
        # revision so it still locks 0054's own tables without asserting it is the
        # global head.
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0054_custom_metadata_fields")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            from sqlalchemy import text

            with eng.connect() as conn:
                head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert head == "0054_custom_metadata_fields"
        finally:
            eng.dispose()

    def test_upgrade_creates_the_two_tables_and_indexes(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0054_custom_metadata_fields")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table), table
            idx = {ix["name"] for ix in insp.get_indexes("custom_field_values")}
            assert "ix_custom_field_values_field_value" in idx
            assert "ix_custom_field_values_field_num" in idx
            assert "ix_custom_field_values_field_date" in idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_two_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "0054_custom_metadata_fields")
        command.downgrade(cfg, "0053_ai_model_configuration")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table), table
            # 0053 table survives the single-step downgrade.
            assert insp.has_table("ai_model_configuration")
        finally:
            eng.dispose()


def _ts() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)
