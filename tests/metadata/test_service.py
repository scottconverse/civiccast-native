# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S22 CustomFieldService — the validation + orchestration seam (slice 2).

The service wraps :class:`CustomFieldStore` and adds the two contracts the store
cannot enforce on its own (spec §6):

* **Reference resolution** — ``asset_ref`` / ``producer_ref`` values must resolve to an
  existing asset / producer. The store validates only the type-shape; resolution needs
  the asset / producer lookups, injected here as ``Callable[[str], bool]`` resolvers so
  the service stays unit-testable offline (the ai_models injected-probe convention).
* **Orchestration** — def CRUD (create/update with key-immutability surfaced),
  delete-safety (confirm cascade), and per-asset value read/set that resolves the
  station's definitions and runs the store's typed validation, with ref resolution
  layered in BEFORE the write so a bad reference never persists.

All typed-validation paths the store already covers (list/number/date/boolean/required/
unknown-field/full-replace/denormalization) are re-asserted end-to-end through the
service so the seam is proven, plus the service-only ref-resolution cases.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.metadata.models import CustomFieldDef, CustomFieldValue
from civiccast.metadata.service import (
    CustomFieldService,
    FieldReferenceError,
)
from civiccast.metadata.store import (
    CustomFieldStore,
    FieldImmutableKeyError,
    FieldNotFoundError,
    FieldValidationError,
    FieldValuesExistError,
)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[CustomFieldStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'svc.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield CustomFieldStore(factory)
    finally:
        eng.dispose()


# Resolvers: by default, a small known universe of assets/producers exists.
_KNOWN_ASSETS = {"ast_real", "ast_1", "ast_2", "ast_3"}
_KNOWN_PRODUCERS = {"prod_real", "city_tv"}


def _service(
    store: CustomFieldStore,
    *,
    assets: set[str] | None = None,
    producers: set[str] | None = None,
) -> CustomFieldService:
    known_assets = _KNOWN_ASSETS if assets is None else assets
    known_producers = _KNOWN_PRODUCERS if producers is None else producers
    return CustomFieldService(
        store,
        asset_exists=lambda aid: aid in known_assets,
        producer_exists=lambda pid: pid in known_producers,
    )


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


def _val(field_id: str, value: str, asset_id: str = "ast_real") -> CustomFieldValue:
    return CustomFieldValue(asset_id=asset_id, field_id=field_id, value=value)


# --- field-definition orchestration ------------------------------------------


class TestDefCrud:
    def test_create_and_get(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        saved = svc.create_field(_def())
        assert saved.key == "meeting_type"
        got = svc.get_field("fld_meeting_type")
        assert got is not None
        assert got.label == "Meeting Type"

    def test_get_missing_returns_none(self, store: CustomFieldStore) -> None:
        assert _service(store).get_field("fld_nope") is None

    def test_list_fields_scoped_and_ordered(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def("fld_b", key="b", label="Bravo", order=2))
        svc.create_field(_def("fld_a", key="a", label="Alpha", order=1))
        assert [d.field_id for d in svc.list_fields("sta_main")] == ["fld_a", "fld_b"]

    def test_list_fields_exposed_only(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def("fld_pub", key="pub", api_exposed=True, searchable=True))
        svc.create_field(_def("fld_hidden", key="hidden", api_exposed=False))
        ids = [d.field_id for d in svc.list_fields("sta_main", exposed_only=True)]
        assert ids == ["fld_pub"]

    def test_update_label_is_editable(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def())
        updated = svc.update_field(_def(label="Type of Meeting"))
        assert updated.label == "Type of Meeting"

    def test_update_key_is_immutable(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def())
        with pytest.raises(FieldImmutableKeyError):
            svc.update_field(_def(key="meeting_kind"))


# --- deletion safety ----------------------------------------------------------


class TestDeleteSafety:
    def test_delete_unknown_raises(self, store: CustomFieldStore) -> None:
        with pytest.raises(FieldNotFoundError):
            _service(store).delete_field("fld_nope")

    def test_delete_without_values_succeeds(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def())
        svc.delete_field("fld_meeting_type")
        assert svc.get_field("fld_meeting_type") is None

    def test_delete_with_values_blocked_without_confirm(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def())
        svc.set_asset_values(
            "ast_real", [_val("fld_meeting_type", "Regular")], station_id="sta_main"
        )
        with pytest.raises(FieldValuesExistError):
            svc.delete_field("fld_meeting_type")
        assert svc.get_field("fld_meeting_type") is not None

    def test_delete_with_values_cascades_with_confirm(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def())
        svc.set_asset_values(
            "ast_real", [_val("fld_meeting_type", "Regular")], station_id="sta_main"
        )
        svc.delete_field("fld_meeting_type", confirm=True)
        assert svc.get_field("fld_meeting_type") is None
        assert svc.get_asset_values("ast_real") == []


# --- value read/set through the service (typed validation end-to-end) ---------


def _seed_typed_defs(svc: CustomFieldService) -> None:
    svc.create_field(_def("fld_text", key="note", label="Note", type="text"))
    svc.create_field(
        _def("fld_list", key="cat", label="Category", type="list", options=["Gov", "PEG"])
    )
    svc.create_field(_def("fld_num", key="ep", label="Episode", type="number"))
    svc.create_field(_def("fld_date", key="aired", label="Aired", type="date"))
    svc.create_field(_def("fld_bool", key="flag", label="Flagged", type="boolean"))
    svc.create_field(_def("fld_asset", key="related", label="Related", type="asset_ref"))
    svc.create_field(_def("fld_prod", key="producer", label="Producer", type="producer_ref"))


class TestValues:
    def test_empty_is_valid_zero_state(self, store: CustomFieldStore) -> None:
        assert _service(store).get_asset_values("ast_real") == []

    def test_set_and_get_round_trip(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def("fld_text", key="note", type="text"))
        svc.set_asset_values("ast_real", [_val("fld_text", "hello")], station_id="sta_main")
        got = {v.field_id: v.value for v in svc.get_asset_values("ast_real")}
        assert got == {"fld_text": "hello"}

    def test_set_is_full_replace(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def("fld_a", key="a", type="text"))
        svc.create_field(_def("fld_b", key="b", type="text"))
        svc.set_asset_values(
            "ast_real",
            [_val("fld_a", "1"), _val("fld_b", "2")],
            station_id="sta_main",
        )
        svc.set_asset_values("ast_real", [_val("fld_a", "X")], station_id="sta_main")
        got = {v.field_id: v.value for v in svc.get_asset_values("ast_real")}
        assert got == {"fld_a": "X"}

    def test_number_denormalizes(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        svc.set_asset_values("ast_real", [_val("fld_num", "42")], station_id="sta_main")
        num = next(v for v in svc.get_asset_values("ast_real") if v.field_id == "fld_num")
        assert num.value_num == 42.0

    def test_date_denormalizes(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        svc.set_asset_values("ast_real", [_val("fld_date", "2026-03-14")], station_id="sta_main")
        d = next(v for v in svc.get_asset_values("ast_real") if v.field_id == "fld_date")
        assert d.value_date == date(2026, 3, 14)

    def test_list_rejects_non_option(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldValidationError):
            svc.set_asset_values("ast_real", [_val("fld_list", "Nope")], station_id="sta_main")

    def test_list_accepts_option(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        svc.set_asset_values("ast_real", [_val("fld_list", "PEG")], station_id="sta_main")
        cat = next(v for v in svc.get_asset_values("ast_real") if v.field_id == "fld_list")
        assert cat.value == "PEG"

    def test_number_rejects_non_numeric(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldValidationError):
            svc.set_asset_values("ast_real", [_val("fld_num", "nope")], station_id="sta_main")

    @pytest.mark.parametrize("bad", ["inf", "-inf", "nan", "infinity"])
    def test_number_rejects_non_finite(self, store: CustomFieldStore, bad: str) -> None:
        # T1 at the service seam: a non-finite number is a typed-validation failure
        # (FieldValidationError -> 422 at the router), same as any other bad number.
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldValidationError):
            svc.set_asset_values("ast_real", [_val("fld_num", bad)], station_id="sta_main")

    def test_date_rejects_non_date(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldValidationError):
            svc.set_asset_values(
                "ast_real", [_val("fld_date", "14/03/2026")], station_id="sta_main"
            )

    def test_boolean_rejects_non_boolean(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldValidationError):
            svc.set_asset_values("ast_real", [_val("fld_bool", "maybe")], station_id="sta_main")

    def test_required_must_be_present(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def("fld_text", key="note", type="text"))
        svc.create_field(_def("fld_req", key="req", label="Req", type="text", required=True))
        with pytest.raises(FieldValidationError):
            svc.set_asset_values("ast_real", [_val("fld_text", "hi")], station_id="sta_main")

    def test_unknown_field_rejected(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldValidationError):
            svc.set_asset_values("ast_real", [_val("fld_ghost", "x")], station_id="sta_main")


# --- reference resolution (service-only, spec §6) ----------------------------


class TestReferenceResolution:
    def test_asset_ref_resolves(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        svc.set_asset_values("ast_real", [_val("fld_asset", "ast_1")], station_id="sta_main")
        ref = next(v for v in svc.get_asset_values("ast_real") if v.field_id == "fld_asset")
        assert ref.value == "ast_1"

    def test_asset_ref_unresolved_rejected(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldReferenceError):
            svc.set_asset_values(
                "ast_real", [_val("fld_asset", "ast_missing")], station_id="sta_main"
            )

    def test_producer_ref_resolves(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        svc.set_asset_values("ast_real", [_val("fld_prod", "city_tv")], station_id="sta_main")
        ref = next(v for v in svc.get_asset_values("ast_real") if v.field_id == "fld_prod")
        assert ref.value == "city_tv"

    def test_producer_ref_unresolved_rejected(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldReferenceError):
            svc.set_asset_values("ast_real", [_val("fld_prod", "ghost")], station_id="sta_main")

    def test_bad_ref_is_not_persisted(self, store: CustomFieldStore) -> None:
        # A failed ref resolution must roll the whole set back (nothing persists).
        svc = _service(store)
        _seed_typed_defs(svc)
        with pytest.raises(FieldReferenceError):
            svc.set_asset_values(
                "ast_real",
                [_val("fld_text", "ok"), _val("fld_asset", "ast_missing")],
                station_id="sta_main",
            )
        assert svc.get_asset_values("ast_real") == []

    def test_reference_error_is_a_validation_error(self, store: CustomFieldStore) -> None:
        # FieldReferenceError subclasses FieldValidationError so the router's 422 path
        # catches both (the unresolved ref is a typed-validation failure).
        assert issubclass(FieldReferenceError, FieldValidationError)

    def test_ref_value_is_stored_in_the_canonical_resolved_form(
        self, store: CustomFieldStore
    ) -> None:
        # The resolver validates the stripped id; the STORED value must match what resolved
        # (no value/resolution drift), so a later exact cf.<key>=<id> / S19 eq filter agrees.
        svc = _service(store)
        _seed_typed_defs(svc)
        svc.set_asset_values("ast_real", [_val("fld_asset", "  ast_1  ")], station_id="sta_main")
        ref = next(v for v in svc.get_asset_values("ast_real") if v.field_id == "fld_asset")
        assert ref.value == "ast_1"  # stored stripped, not "  ast_1  "

        svc.set_asset_values(
            "ast_real",
            [_val("fld_asset", "ast_1"), _val("fld_prod", " city_tv ")],
            station_id="sta_main",
        )
        prod = next(v for v in svc.get_asset_values("ast_real") if v.field_id == "fld_prod")
        assert prod.value == "city_tv"


# --- public exposure projection (DC-5 helper) --------------------------------


class TestPublicExposure:
    def test_public_values_only_for_exposed_fields(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(_def("fld_pub", key="pub", type="text", api_exposed=True, searchable=True))
        svc.create_field(
            _def("fld_secret", key="secret", type="text", api_exposed=False, searchable=True)
        )
        svc.set_asset_values(
            "ast_real",
            [_val("fld_pub", "shown"), _val("fld_secret", "hidden")],
            station_id="sta_main",
        )
        public = svc.get_public_asset_values("ast_real", station_id="sta_main")
        keys = {v.field_id for v in public}
        assert keys == {"fld_pub"}

    def test_non_searchable_excluded_from_public(self, store: CustomFieldStore) -> None:
        svc = _service(store)
        svc.create_field(
            _def("fld_internal", key="internal", type="text", api_exposed=True, searchable=False)
        )
        svc.set_asset_values("ast_real", [_val("fld_internal", "x")], station_id="sta_main")
        assert svc.get_public_asset_values("ast_real", station_id="sta_main") == []
