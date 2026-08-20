# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S6 V1 (build step 7) slice 2a — board resolution + bulletin time-window.

Covers civiccast.cg.board_resolver.resolve_board (active board -> snapshot;
graceful degrade of a deleted/disabled feed; approval-gated feed filtering;
back-fill of missing required zone kinds; template fallback) and the
bulletin_is_airable / airable_bulletins helpers. SQLite-backed store; no network
(feed items are passed in).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.cg.board_models import CgBoard, CgFeedItemApproval, CgFeedSource, CgZoneConfig
from civiccast.cg.board_resolver import (
    airable_bulletins,
    bulletin_is_airable,
    coming_up_next,
    resolve_board,
)
from civiccast.cg.board_store import CgBoardStore
from civiccast.cg.models import CgBulletinSubmission, CgFeedItem
from civiccast.db import Base

_NOW = datetime(2026, 6, 1, 18, 0, tzinfo=UTC)
_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path) -> Iterator[CgBoardStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'res.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield CgBoardStore(factory)
    finally:
        eng.dispose()


def _seed_board(store: CgBoardStore, *, template_id: str = "standard-community-board") -> str:
    store.upsert_board(
        CgBoard(
            board_id="cgb_main",
            channel_id="public",
            template_id=template_id,
            active=True,
            created_by="op_a",
            created_at=_T0,
            updated_at=_T0,
        )
    )
    return "cgb_main"


def _zone(
    zone_id: str, zone_kind: str, region: str, content_source: str, **kwargs: object
) -> CgZoneConfig:
    base: dict[str, object] = {
        "zone_id": zone_id,
        "board_id": "cgb_main",
        "region": region,
        "zone_kind": zone_kind,
        "content_source": content_source,
        "created_at": _T0,
    }
    base.update(kwargs)
    return CgZoneConfig(**base)  # type: ignore[arg-type]


def _feed(store: CgBoardStore, feed_source_id: str = "feed_rss", **kwargs: object) -> str:
    base: dict[str, object] = {
        "feed_source_id": feed_source_id,
        "channel_id": "public",
        "kind": "rss",
        "label": "City news",
        "source_url": "https://example.gov/news.rss",
        "trust_tier": "operator_curated",
        "created_by": "op_a",
        "created_at": _T0,
    }
    base.update(kwargs)
    store.upsert_feed(CgFeedSource(**base))  # type: ignore[arg-type]
    return feed_source_id


# ---------------------------------------------------------------------------
# resolve_board
# ---------------------------------------------------------------------------


def test_resolve_returns_none_without_an_active_board(store: CgBoardStore) -> None:
    assert resolve_board(store, "public", now=_NOW) is None


def test_resolve_builds_snapshot_from_configured_zones(store: CgBoardStore) -> None:
    _seed_board(store)
    store.upsert_zone(_zone("z_p", "primary", "main", "schedule"))
    store.upsert_zone(_zone("z_t", "ticker", "lower", "manual", manual_text="Welcome"))
    store.upsert_zone(_zone("z_s", "schedule", "side", "schedule"))
    store.upsert_zone(_zone("z_l", "logo", "bug", "image", image_asset_ref="logo_png"))

    resolved = resolve_board(store, "public", now=_NOW)
    assert resolved is not None
    assert resolved.backfilled_kinds == []  # all required kinds configured
    assert resolved.degraded_zone_ids == []
    kinds = {z.kind for z in resolved.snapshot.zones}
    assert {"primary", "ticker", "schedule", "logo"} <= kinds
    ticker = next(z for z in resolved.snapshot.zones if z.zone_id == "z_t")
    assert ticker.content == {"text": "Welcome"}


def test_resolve_backfills_missing_required_kinds(store: CgBoardStore) -> None:
    _seed_board(store)
    store.upsert_zone(_zone("z_t", "ticker", "lower", "manual", manual_text="Hi"))
    resolved = resolve_board(store, "public", now=_NOW)
    assert resolved is not None
    # ticker was configured; primary/schedule/logo are back-filled (in that order).
    assert resolved.backfilled_kinds == ["primary", "schedule", "logo"]
    # The snapshot is still valid (its validator requires all four kinds).
    assert {"primary", "ticker", "schedule", "logo"} <= {z.kind for z in resolved.snapshot.zones}
    assert any(z.zone_id == "_default_primary" for z in resolved.snapshot.zones)


def test_resolve_feed_zone_renders_items(store: CgBoardStore) -> None:
    _seed_board(store)
    _feed(store, "feed_rss")
    store.upsert_zone(_zone("z_t", "ticker", "lower", "feed_adapter", feed_source_id="feed_rss"))
    items = {"feed_rss": [CgFeedItem(item_id="i1", title="Library board meets tonight")]}
    resolved = resolve_board(store, "public", now=_NOW, feed_items_by_source=items)
    assert resolved is not None
    ticker = next(z for z in resolved.snapshot.zones if z.zone_id == "z_t")
    assert ticker.content["items"] == [{"item_id": "i1", "title": "Library board meets tonight"}]
    assert "z_t" not in resolved.degraded_zone_ids


def test_resolve_degrades_zone_when_feed_missing_or_disabled(store: CgBoardStore) -> None:
    _seed_board(store)
    # Zone names a feed that does not exist -> degraded, not an error.
    store.upsert_zone(_zone("z_t", "ticker", "lower", "feed_adapter", feed_source_id="ghost"))
    resolved = resolve_board(store, "public", now=_NOW)
    assert resolved is not None
    assert "z_t" in resolved.degraded_zone_ids
    ticker = next(z for z in resolved.snapshot.zones if z.zone_id == "z_t")
    assert ticker.content == {"items": [], "degraded": True}

    # A disabled feed degrades the same way.
    _feed(store, "feed_off", enabled=False)
    store.upsert_zone(_zone("z_t2", "ticker", "lower", "feed_adapter", feed_source_id="feed_off"))
    resolved2 = resolve_board(store, "public", now=_NOW)
    assert resolved2 is not None and "z_t2" in resolved2.degraded_zone_ids


def test_resolve_approval_gate_filters_to_approved_items(store: CgBoardStore) -> None:
    _seed_board(store)
    _feed(store, "feed_rss")
    store.upsert_zone(
        _zone(
            "z_t",
            "ticker",
            "lower",
            "feed_adapter",
            feed_source_id="feed_rss",
            approval_required=True,
        )
    )
    store.approve_item(
        CgFeedItemApproval(
            approval_id="appr_1",
            channel_id="public",
            feed_source_id="feed_rss",
            item_id="i_ok",
            approved_by_operator="op_a",
            approved_at=_T0,
        )
    )
    items = {
        "feed_rss": [
            CgFeedItem(item_id="i_ok", title="Approved item"),
            CgFeedItem(item_id="i_no", title="Unapproved item"),
        ]
    }
    resolved = resolve_board(store, "public", now=_NOW, feed_items_by_source=items)
    assert resolved is not None
    ticker = next(z for z in resolved.snapshot.zones if z.zone_id == "z_t")
    rendered_ids = [i["item_id"] for i in ticker.content["items"]]
    assert rendered_ids == ["i_ok"]  # the unapproved item is hidden


def test_resolve_falls_back_to_active_template_for_unknown_id(store: CgBoardStore) -> None:
    _seed_board(store, template_id="does-not-exist")
    resolved = resolve_board(store, "public", now=_NOW)
    assert resolved is not None
    assert resolved.snapshot.template.template_id == "standard-community-board"


# ---------------------------------------------------------------------------
# CG depth (slice 6b): allowed_tags filter (DC-CG3) + interstitial (DC-CG4)
# ---------------------------------------------------------------------------


def test_resolve_feed_zone_filters_by_allowed_tags(store: CgBoardStore) -> None:
    _seed_board(store)
    _feed(store, "feed_rss")
    store.upsert_zone(
        _zone(
            "z_t",
            "ticker",
            "lower",
            "feed_adapter",
            feed_source_id="feed_rss",
            allowed_tags=["events"],
        )
    )
    items = {
        "feed_rss": [
            CgFeedItem(item_id="i_ev", title="Arts fair", tags=["events"]),
            CgFeedItem(item_id="i_other", title="Budget notice", tags=["finance"]),
            CgFeedItem(item_id="i_untagged", title="Untagged"),
        ]
    }
    resolved = resolve_board(store, "public", now=_NOW, feed_items_by_source=items)
    assert resolved is not None
    ticker = next(z for z in resolved.snapshot.zones if z.zone_id == "z_t")
    assert [i["item_id"] for i in ticker.content["items"]] == ["i_ev"]


def test_resolve_schedule_zone_renders_coming_up_interstitial(store: CgBoardStore) -> None:
    _seed_board(store)
    store.upsert_zone(_zone("z_s", "schedule", "side", "schedule"))
    upcoming = [
        (_NOW + timedelta(hours=2), "Planning Board"),
        (_NOW + timedelta(hours=1), "City Council"),
        (_NOW - timedelta(hours=1), "Already aired"),
    ]
    resolved = resolve_board(store, "public", now=_NOW, upcoming=upcoming)
    assert resolved is not None
    sched = next(z for z in resolved.snapshot.zones if z.zone_id == "z_s")
    titles = [i["title"] for i in sched.content["items"]]
    assert titles == ["City Council", "Planning Board"]  # future only, earliest first


def test_coming_up_next_filters_sorts_and_caps() -> None:
    entries = [
        (_NOW + timedelta(hours=3), "C"),
        (_NOW + timedelta(hours=1), "A"),
        (_NOW - timedelta(hours=1), "Past"),
        (_NOW + timedelta(hours=2), "B"),
    ]
    result = coming_up_next(entries, now=_NOW, count=2)
    assert [r["title"] for r in result] == ["A", "B"]
    assert all("time" in r for r in result)


def test_coming_up_next_includes_exact_now_boundary() -> None:
    # The schedule zone keeps events with starts_at >= now, so an event starting
    # at exactly `now` must be shown — pins the >= vs > boundary from drifting.
    result = coming_up_next([(_NOW, "Starts now")], now=_NOW, count=2)
    assert [r["title"] for r in result] == ["Starts now"]


# ---------------------------------------------------------------------------
# Bulletin time-window helpers
# ---------------------------------------------------------------------------


def _bulletin(state: str, **kwargs: object) -> CgBulletinSubmission:
    base: dict[str, object] = {
        "submission_id": "b1",
        "organization": "Org",
        "submitter_label": "Volunteer",
        "title": "Notice",
        "message": "Body",
        "target_zone_kind": "ticker",
        "state": state,
    }
    if state in {"accepted", "scheduled"}:
        base["approved_by_operator"] = "op_a"
    if state in {"needs_changes", "declined"}:
        base["moderation_notes"] = "fix it"
    base.update(kwargs)
    return CgBulletinSubmission(**base)  # type: ignore[arg-type]


def test_bulletin_airable_accepted_without_window() -> None:
    assert bulletin_is_airable(_bulletin("accepted"), now=_NOW) is True


def test_bulletin_not_airable_when_declined_or_needs_changes() -> None:
    assert bulletin_is_airable(_bulletin("declined"), now=_NOW) is False
    assert bulletin_is_airable(_bulletin("needs_changes"), now=_NOW) is False
    assert bulletin_is_airable(_bulletin("submitted"), now=_NOW) is False


def test_bulletin_window_future_and_expired() -> None:
    future = _bulletin("scheduled", requested_start=_NOW + timedelta(hours=1))
    assert bulletin_is_airable(future, now=_NOW) is False  # not yet
    expired = _bulletin(
        "scheduled",
        requested_start=_NOW - timedelta(hours=2),
        requested_end=_NOW - timedelta(hours=1),
    )
    assert bulletin_is_airable(expired, now=_NOW) is False  # past end
    live = _bulletin(
        "scheduled",
        requested_start=_NOW - timedelta(hours=1),
        requested_end=_NOW + timedelta(hours=1),
    )
    assert bulletin_is_airable(live, now=_NOW) is True


def test_bulletin_window_is_half_open_at_end() -> None:
    # now == requested_end -> expired (half-open [start, end)).
    at_end = _bulletin("accepted", requested_end=_NOW)
    assert bulletin_is_airable(at_end, now=_NOW) is False


def test_airable_bulletins_filters_and_preserves_order() -> None:
    bulletins = [
        _bulletin("accepted", submission_id="a"),
        _bulletin("declined", submission_id="b"),
        _bulletin("scheduled", submission_id="c", requested_start=_NOW + timedelta(days=1)),
        _bulletin("scheduled", submission_id="d"),
    ]
    result = [b.submission_id for b in airable_bulletins(bulletins, now=_NOW)]
    assert result == ["a", "d"]
