# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S22 slice 5 — S19 saved-search filtering on custom fields (spec DC-3).

Exercises the custom-field predicate seam on
:class:`civiccast.schedule.autoschedule_models.AssetQuery` +
:func:`civiccast.schedule.autoschedule_query._apply_filters`: a saved search that
carries one or more ``CustomFieldPredicate``s resolves the correct assets via a
correlated ``EXISTS`` over ``custom_field_values`` joined to ``custom_field_defs``
(keyed by the immutable ``key``, gated on ``searchable``). Behaviour is preserved
when no predicate is set (an empty ``custom_fields`` list adds zero clauses).

SQLite-backed; the assets + custom-field tables share one metadata so
``Base.metadata.create_all`` provisions all three.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

import pydantic
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.metadata.models import CustomFieldDefDb, CustomFieldValueDb
from civiccast.metadata.store import mint_value_id
from civiccast.schedule.autoschedule_models import AssetQuery, CustomFieldPredicate
from civiccast.schedule.autoschedule_query import (
    build_asset_query,
    pick_asset,
    resolve_assets,
)
from civiccast.schedule.models import ASSET_STATE_VALIDATED, Asset


def _asset(asset_id: str, title: str, *, published: datetime) -> Asset:
    return Asset(
        asset_id=asset_id,
        title=title,
        meeting_body="City Council",
        state=ASSET_STATE_VALIDATED,
        retention_policy="default",
        duration_seconds=3600,
        published_at=published,
    )


# Five assets; meeting_type / air_count / aired_on custom fields tag a subset.
_ASSETS = [
    ("a1", "Regular Meeting Jan", datetime(2026, 1, 10, tzinfo=UTC)),
    ("a2", "Workshop Feb", datetime(2026, 2, 15, tzinfo=UTC)),
    ("a3", "Budget Review Mar", datetime(2026, 3, 1, tzinfo=UTC)),
    ("a4", "Special Session Apr", datetime(2026, 4, 1, tzinfo=UTC)),
    ("a5", "Archive Clip", datetime(2026, 1, 1, tzinfo=UTC)),
]

# Field defs. meeting_type=list (searchable), priority=number (searchable),
# aired_on=date (searchable), secret_tag=text (NOT searchable -> cannot be filtered).
_DEFS = [
    ("fd_type", "meeting_type", "Meeting Type", "list", True),
    ("fd_pri", "priority", "Priority", "number", True),
    ("fd_aired", "aired_on", "Aired On", "date", True),
    ("fd_secret", "secret_tag", "Secret Tag", "text", False),
]

# (asset_id, field_id, value, value_num, value_date)
_VALUES = [
    ("a1", "fd_type", "Regular", None, None),
    ("a2", "fd_type", "Workshop", None, None),
    ("a3", "fd_type", "Regular", None, None),
    ("a4", "fd_type", "Special", None, None),
    # a5 has no meeting_type value (the valid zero-state).
    ("a1", "fd_pri", "10", 10.0, None),
    ("a2", "fd_pri", "50", 50.0, None),
    ("a3", "fd_pri", "90", 90.0, None),
    ("a1", "fd_aired", "2026-05-01", None, "2026-05-01"),
    ("a2", "fd_aired", "2026-06-15", None, "2026-06-15"),
    ("a3", "fd_aired", "2026-07-20", None, "2026-07-20"),
    # secret_tag (not searchable): a1 + a3 tagged "vip" — must NOT be filterable.
    ("a1", "fd_secret", "vip", None, None),
    ("a3", "fd_secret", "vip", None, None),
]


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    eng = create_engine(f"sqlite:///{tmp_path / 'cf.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as s:
            yield s

    with factory() as setup:
        for aid, title, pub in _ASSETS:
            setup.add(_asset(aid, title, published=pub))
        for fid, key, label, ftype, searchable in _DEFS:
            setup.add(
                CustomFieldDefDb(
                    field_id=fid,
                    station_id="st_main",
                    key=key,
                    label=label,
                    type=ftype,
                    options=["Regular", "Workshop", "Special"] if ftype == "list" else [],
                    required=False,
                    searchable=searchable,
                    api_exposed=True,
                    order=0,
                )
            )
        for aid, fid, value, vnum, vdate in _VALUES:
            setup.add(
                CustomFieldValueDb(
                    value_id=mint_value_id(aid, fid),
                    asset_id=aid,
                    field_id=fid,
                    value=value,
                    value_num=vnum,
                    value_date=date.fromisoformat(vdate) if vdate else None,
                )
            )
        setup.commit()

    with factory() as s:
        yield s
    eng.dispose()


def _ids(rows: list) -> set[str]:  # type: ignore[type-arg]
    return {r.asset_id for r in rows}


# ---------------------------------------------------------------------------
# Behaviour-preservation: no predicate == old behaviour
# ---------------------------------------------------------------------------


def test_empty_custom_fields_matches_all(session: Session) -> None:
    # Empty predicate list adds zero clauses -> every asset still matches.
    assert _ids(resolve_assets(session, AssetQuery())) == {"a1", "a2", "a3", "a4", "a5"}


def test_empty_custom_fields_compose_with_core_filters(session: Session) -> None:
    # A core filter still narrows when custom_fields is empty (no regression).
    rows = resolve_assets(session, AssetQuery(title_contains="Workshop"))
    assert _ids(rows) == {"a2"}


# ---------------------------------------------------------------------------
# DC-3: a saved search filters on a custom field and resolves the right assets
# ---------------------------------------------------------------------------


def test_eq_predicate_resolves_matching_assets(session: Session) -> None:
    q = AssetQuery(
        custom_fields=[CustomFieldPredicate(key="meeting_type", op="eq", value="Regular")]
    )
    assert _ids(resolve_assets(session, q)) == {"a1", "a3"}


def test_eq_predicate_no_match_returns_empty(session: Session) -> None:
    q = AssetQuery(
        custom_fields=[CustomFieldPredicate(key="meeting_type", op="eq", value="Nonexistent")]
    )
    assert resolve_assets(session, q) == []


def test_eq_predicate_excludes_assets_without_a_value(session: Session) -> None:
    # a5 has no meeting_type value -> never matches an eq predicate (EXISTS is false).
    q = AssetQuery(
        custom_fields=[CustomFieldPredicate(key="meeting_type", op="eq", value="Special")]
    )
    assert _ids(resolve_assets(session, q)) == {"a4"}


def test_num_range_predicate_uses_value_num(session: Session) -> None:
    q = AssetQuery(
        custom_fields=[CustomFieldPredicate(key="priority", op="num_range", num_min=20, num_max=95)]
    )
    # a1=10 below band; a2=50, a3=90 in band.
    assert _ids(resolve_assets(session, q)) == {"a2", "a3"}


def test_num_range_single_bound(session: Session) -> None:
    q = AssetQuery(custom_fields=[CustomFieldPredicate(key="priority", op="num_range", num_min=50)])
    assert _ids(resolve_assets(session, q)) == {"a2", "a3"}


def test_date_range_predicate_uses_value_date(session: Session) -> None:
    q = AssetQuery(
        custom_fields=[
            CustomFieldPredicate(
                key="aired_on",
                op="date_range",
                date_min=date(2026, 5, 15),
                date_max=date(2026, 7, 1),
            )
        ]
    )
    # a1=05-01 below; a2=06-15 in band; a3=07-20 above.
    assert _ids(resolve_assets(session, q)) == {"a2"}


def test_multiple_predicates_compose_as_and(session: Session) -> None:
    # meeting_type=Regular -> {a1,a3}; priority>=80 -> {a3}. AND -> {a3}.
    q = AssetQuery(
        custom_fields=[
            CustomFieldPredicate(key="meeting_type", op="eq", value="Regular"),
            CustomFieldPredicate(key="priority", op="num_range", num_min=80),
        ]
    )
    assert _ids(resolve_assets(session, q)) == {"a3"}


def test_custom_field_composes_with_core_filter(session: Session) -> None:
    # core title_contains="Review" -> {a3}; cf meeting_type=Regular -> {a1,a3}. AND -> {a3}.
    q = AssetQuery(
        title_contains="Review",
        custom_fields=[CustomFieldPredicate(key="meeting_type", op="eq", value="Regular")],
    )
    assert _ids(resolve_assets(session, q)) == {"a3"}


# ---------------------------------------------------------------------------
# Searchable gate (spec §3): a non-searchable field cannot be filtered on
# ---------------------------------------------------------------------------


def test_non_searchable_field_never_matches(session: Session) -> None:
    # secret_tag is searchable=False; a1/a3 carry "vip" but the gate drops the EXISTS
    # join (def must be searchable), so the predicate matches NOTHING.
    q = AssetQuery(custom_fields=[CustomFieldPredicate(key="secret_tag", op="eq", value="vip")])
    assert resolve_assets(session, q) == []


def test_unknown_key_never_matches(session: Session) -> None:
    # A key with no def resolves to no field_id -> EXISTS over an empty join -> no rows.
    q = AssetQuery(custom_fields=[CustomFieldPredicate(key="does_not_exist", op="eq", value="x")])
    assert resolve_assets(session, q) == []


# ---------------------------------------------------------------------------
# pick strategies route through the same funnel
# ---------------------------------------------------------------------------


def test_pick_top_result_honours_custom_field(session: Session) -> None:
    # meeting_type=Regular -> {a1,a3}; default order published DESC -> a3 first.
    q = AssetQuery(
        custom_fields=[CustomFieldPredicate(key="meeting_type", op="eq", value="Regular")]
    )
    picked = pick_asset(session, q, "top_result")
    assert picked is not None
    assert picked.asset_id == "a3"


def test_pick_returns_none_when_custom_field_excludes_all(session: Session) -> None:
    q = AssetQuery(custom_fields=[CustomFieldPredicate(key="meeting_type", op="eq", value="Nope")])
    assert pick_asset(session, q, "newest") is None


# ---------------------------------------------------------------------------
# build_asset_query stays pure (bound params, no interpolation) + round-trips
# ---------------------------------------------------------------------------


def test_build_asset_query_with_cf_is_parameterized(session: Session) -> None:
    stmt = build_asset_query(
        AssetQuery(
            custom_fields=[CustomFieldPredicate(key="meeting_type", op="eq", value="Regular")]
        )
    )
    compiled = str(stmt)
    assert "custom_field_values" in compiled
    assert "custom_field_defs" in compiled
    # Values are bound parameters, never inlined literals.
    assert "Regular" not in compiled
    assert "meeting_type" not in compiled


# ---------------------------------------------------------------------------
# CustomFieldPredicate validation (extra=forbid + inverted-range guards)
# ---------------------------------------------------------------------------


def test_predicate_forbids_extra_keys() -> None:
    with pytest.raises(pydantic.ValidationError):
        CustomFieldPredicate(key="x", op="eq", value="y", bogus=1)  # type: ignore[call-arg]


def test_predicate_rejects_inverted_num_range() -> None:
    with pytest.raises(pydantic.ValidationError):
        CustomFieldPredicate(key="priority", op="num_range", num_min=90, num_max=10)


def test_predicate_rejects_inverted_date_range() -> None:
    with pytest.raises(pydantic.ValidationError):
        CustomFieldPredicate(
            key="aired_on",
            op="date_range",
            date_min=date(2026, 7, 1),
            date_max=date(2026, 1, 1),
        )


def test_assetquery_round_trips_custom_fields_through_json() -> None:
    # A saved search persists AssetQuery as JSON (query_json); cf predicates must survive.
    q = AssetQuery(
        custom_fields=[
            CustomFieldPredicate(key="meeting_type", op="eq", value="Regular"),
            CustomFieldPredicate(key="priority", op="num_range", num_min=10, num_max=90),
        ]
    )
    restored = AssetQuery.model_validate_json(q.model_dump_json())
    assert restored == q
    assert restored.custom_fields[0].key == "meeting_type"
    assert restored.custom_fields[1].op == "num_range"
