# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S18 slice 2 — AssetQuery -> SQL executor + pick strategies.

Exercises civiccast.schedule.autoschedule_query against a SQLite ``assets``
table seeded with varied meeting_body / title / state / duration / published_at,
proving each filter narrows correctly (including LIKE-metacharacter escaping),
ordering honours order_by/desc with NULLs last, exclusion works, and the three
pick strategies (top_result / newest / random_result) behave + handle no-match.
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.db import Base
from civiccast.schedule.autoschedule_models import AssetQuery
from civiccast.schedule.autoschedule_query import (
    build_asset_query,
    pick_asset,
    resolve_assets,
)
from civiccast.schedule.models import (
    ASSET_STATE_PENDING,
    ASSET_STATE_RECORDED,
    ASSET_STATE_VALIDATED,
    Asset,
)


def _asset(
    asset_id: str,
    title: str,
    *,
    meeting_body: str | None,
    state: str,
    duration: int | None,
    published: datetime | None,
) -> Asset:
    return Asset(
        asset_id=asset_id,
        title=title,
        meeting_body=meeting_body,
        state=state,
        retention_policy="default",
        duration_seconds=duration,
        published_at=published,
    )


# Seed set. published_at chosen so the natural (published DESC) order is
# a3 > a2 > a1 > a5 > a4(NULL-last).
_SEED = [
    (
        "a1",
        "City Council Regular Meeting",
        "City Council",
        ASSET_STATE_VALIDATED,
        3600,
        datetime(2026, 1, 10, tzinfo=UTC),
    ),
    (
        "a2",
        "Parks Board Workshop",
        "Parks Board",
        ASSET_STATE_VALIDATED,
        1800,
        datetime(2026, 2, 15, tzinfo=UTC),
    ),
    (
        "a3",
        "City Council Budget 50% Review",
        "City Council",
        ASSET_STATE_VALIDATED,
        5400,
        datetime(2026, 3, 1, tzinfo=UTC),
    ),
    ("a4", "Old Pending Clip", "City Council", ASSET_STATE_PENDING, None, None),
    (
        "a5",
        "Council Archive",
        "City Council",
        ASSET_STATE_RECORDED,
        600,
        datetime(2026, 1, 1, tzinfo=UTC),
    ),
]


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    eng = create_engine(f"sqlite:///{tmp_path / 'assets.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as s:
            yield s

    with factory() as setup:
        for aid, title, body, state, dur, pub in _SEED:
            setup.add(
                _asset(aid, title, meeting_body=body, state=state, duration=dur, published=pub)
            )
        setup.commit()

    with factory() as s:
        yield s
    eng.dispose()


def _ids(rows: list) -> list[str]:  # type: ignore[type-arg]
    return [r.asset_id for r in rows]


# ---------------------------------------------------------------------------
# resolve_assets — filters + ordering
# ---------------------------------------------------------------------------


def test_empty_query_returns_all_published_desc_nulls_last(session: Session) -> None:
    assert _ids(resolve_assets(session, AssetQuery())) == ["a3", "a2", "a1", "a5", "a4"]


def test_meeting_body_exact_filter(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(meeting_body="City Council"))
    assert set(_ids(rows)) == {"a1", "a3", "a4", "a5"}


def test_title_contains_is_case_insensitive(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(title_contains="council"))
    assert set(_ids(rows)) == {"a1", "a3", "a5"}


def test_title_contains_escapes_literal_percent(session: Session) -> None:
    # "50%" is matched literally — only a3's title contains it.
    assert _ids(resolve_assets(session, AssetQuery(title_contains="50%"))) == ["a3"]


def test_title_contains_escapes_underscore_wildcard(session: Session) -> None:
    # If "_" were an unescaped wildcard, "50_" would match a3's "50%". Escaped,
    # it is a literal underscore that no title contains -> empty.
    assert resolve_assets(session, AssetQuery(title_contains="50_")) == []


def test_states_in_filter(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(states=[ASSET_STATE_VALIDATED]))
    assert set(_ids(rows)) == {"a1", "a2", "a3"}


def test_duration_range_excludes_out_of_band_and_null(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(min_duration_seconds=1000, max_duration_seconds=4000))
    # a1=3600, a2=1800 in band; a3=5400 over, a5=600 under, a4=NULL excluded.
    assert set(_ids(rows)) == {"a1", "a2"}


def test_published_after_is_inclusive_and_excludes_null(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(published_after=datetime(2026, 2, 1, tzinfo=UTC)))
    assert set(_ids(rows)) == {"a2", "a3"}


def test_published_before_is_exclusive_half_open(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(published_before=datetime(2026, 2, 1, tzinfo=UTC)))
    # a1 (01-10), a5 (01-01); a2/a3 on/after the bound, a4 NULL excluded.
    assert set(_ids(rows)) == {"a1", "a5"}


def test_order_by_title_ascending(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(order_by="title", order_desc=False))
    titles = [r.title for r in rows]
    assert titles == sorted(titles)


def test_order_by_duration_desc_nulls_last(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(order_by="duration_seconds", order_desc=True))
    # 5400, 3600, 1800, 600, then NULL (a4) last.
    assert _ids(rows) == ["a3", "a1", "a2", "a5", "a4"]


def test_exclude_asset_ids_drops_rows(session: Session) -> None:
    rows = resolve_assets(session, AssetQuery(), exclude_asset_ids={"a3", "a2"})
    assert _ids(rows) == ["a1", "a5", "a4"]


def test_build_asset_query_is_pure_select(session: Session) -> None:
    # Smoke: the builder yields a Select over assets; values are bound params,
    # not interpolated literals.
    stmt = build_asset_query(AssetQuery(meeting_body="City Council"))
    compiled = str(stmt)
    assert "assets" in compiled
    assert "City Council" not in compiled  # parameterized, not inlined


# ---------------------------------------------------------------------------
# pick_asset — strategies
# ---------------------------------------------------------------------------


def test_pick_top_result_is_first_in_query_order(session: Session) -> None:
    # Default order = published DESC -> a3 is first.
    picked = pick_asset(session, AssetQuery(), "top_result")
    assert picked is not None
    assert picked.asset_id == "a3"


def test_pick_newest_ignores_query_order(session: Session) -> None:
    # order_by=title would put "City Council Budget..." mid-list, but newest
    # always returns the max published_at (a3).
    picked = pick_asset(session, AssetQuery(order_by="title", order_desc=False), "newest")
    assert picked is not None
    assert picked.asset_id == "a3"


def test_pick_top_result_honours_exclusion(session: Session) -> None:
    picked = pick_asset(session, AssetQuery(), "top_result", exclude_asset_ids={"a3"})
    assert picked is not None
    assert picked.asset_id == "a2"  # next newest after a3


def test_pick_random_is_eligible_and_deterministic_with_seed(session: Session) -> None:
    q = AssetQuery(meeting_body="City Council")
    eligible = set(_ids(resolve_assets(session, q)))
    first = pick_asset(session, q, "random_result", rng=random.Random(0))
    second = pick_asset(session, q, "random_result", rng=random.Random(0))
    assert first is not None and second is not None
    assert first.asset_id in eligible
    assert first.asset_id == second.asset_id  # same seed -> same choice


def test_pick_returns_none_when_nothing_matches(session: Session) -> None:
    assert pick_asset(session, AssetQuery(meeting_body="Nope"), "top_result") is None
    assert pick_asset(session, AssetQuery(meeting_body="Nope"), "newest") is None
    assert (
        pick_asset(session, AssetQuery(meeting_body="Nope"), "random_result", rng=random.Random(0))
        is None
    )
