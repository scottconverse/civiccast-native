# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S6 V1 (build step 7) slice 3a — CG board-designer service.

Covers civiccast.cg.board_service.CgBoardService: board create/update/view,
zone add/update/delete (active-board requirement + validator pass-through),
feed CRUD (+ weather-curated guard), feed-item approval, live preview, and the
append-only board-scoped audit trail with verified operator ids. SQLite store;
a monotonic clock makes audit ordering deterministic.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.cg.board_service import (
    BoardNotFoundError,
    CgBoardService,
    FeedInput,
    FeedNotFoundError,
    FeedUpdateInput,
    ServiceValidationError,
    ZoneInput,
    ZoneNotFoundError,
    ZoneUpdateInput,
)
from civiccast.cg.board_store import CgBoardStore
from civiccast.db import Base

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


class _MonotonicClock:
    def __init__(self) -> None:
        self._t = _NOW

    def __call__(self) -> datetime:
        self._t = self._t + timedelta(seconds=1)
        return self._t


@pytest.fixture
def svc(tmp_path: Path) -> Iterator[tuple[CgBoardService, CgBoardStore]]:
    eng = create_engine(f"sqlite:///{tmp_path / 'svc.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    store = CgBoardStore(factory)
    try:
        yield CgBoardService(store, clock=_MonotonicClock()), store
    finally:
        eng.dispose()


def _ticker(**kwargs: object) -> ZoneInput:
    base: dict[str, object] = {"region": "lower", "zone_kind": "ticker", "content_source": "manual"}
    base.update(kwargs)
    return ZoneInput(**base)  # type: ignore[arg-type]


def _rss_feed(**kwargs: object) -> FeedInput:
    base: dict[str, object] = {
        "kind": "rss",
        "label": "City news",
        "source_url": "https://x.gov/news.rss",
        "trust_tier": "operator_curated",
    }
    base.update(kwargs)
    return FeedInput(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Board
# ---------------------------------------------------------------------------


def test_create_board_and_view(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    board = service.create_board(
        "public", template_id="standard-community-board", operator_id="op_a"
    )
    assert board.active is True
    assert board.created_by == "op_a"
    view = service.get_board_view("public")
    assert view is not None
    assert view.board.board_id == board.board_id
    assert view.zones == [] and view.feeds == []
    audit = service.list_audit("public")
    assert [e.event_kind for e in audit] == ["board_created"]
    assert audit[0].operator_id == "op_a"
    assert audit[0].details["template_id"] == "standard-community-board"


def test_get_board_view_none_without_board(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    assert service.get_board_view("public") is None
    assert service.list_audit("public") == []
    assert service.preview("public") is None


def test_update_board_404_without_board(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    with pytest.raises(BoardNotFoundError):
        service.update_board("public", template_id="x", operator_id="op_a")


def test_update_board_changes_template(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    updated = service.update_board("public", template_id="live-lower-banner", operator_id="op_b")
    assert updated.template_id == "live-lower-banner"
    kinds = [e.event_kind for e in service.list_audit("public")]
    assert "board_updated" in kinds


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------


def test_add_zone_requires_active_board(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    with pytest.raises(BoardNotFoundError):
        service.add_zone("public", payload=_ticker(), operator_id="op_a")


def test_add_zone_and_audit(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    board = service.create_board(
        "public", template_id="standard-community-board", operator_id="op_a"
    )
    zone = service.add_zone("public", payload=_ticker(manual_text="Hi"), operator_id="op_a")
    assert zone.board_id == board.board_id
    view = service.get_board_view("public")
    assert view is not None and [z.zone_id for z in view.zones] == [zone.zone_id]
    assert "zone_added" in [e.event_kind for e in service.list_audit("public")]


def test_add_zone_persists_allowed_tags(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, store = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    zone = service.add_zone(
        "public", payload=_ticker(allowed_tags=["events", "alerts"]), operator_id="op_a"
    )
    assert zone.allowed_tags == ["events", "alerts"]
    assert store.get_zone(zone.zone_id).allowed_tags == ["events", "alerts"]  # type: ignore[union-attr]


def test_add_feed_zone_without_feed_is_422(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    with pytest.raises(ServiceValidationError):
        service.add_zone(
            "public",
            payload=ZoneInput(region="lower", zone_kind="ticker", content_source="feed_adapter"),
            operator_id="op_a",
        )


def test_update_zone_404_and_revalidate(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    zone = service.add_zone("public", payload=_ticker(manual_text="Old"), operator_id="op_a")
    with pytest.raises(ZoneNotFoundError):
        service.update_zone(
            "public", "ghost", payload=ZoneUpdateInput(manual_text="x"), operator_id="op_a"
        )
    updated = service.update_zone(
        "public", zone.zone_id, payload=ZoneUpdateInput(manual_text="New"), operator_id="op_a"
    )
    assert updated.manual_text == "New"
    # Switching to feed_adapter without a feed must fail the validator.
    with pytest.raises(ServiceValidationError):
        service.update_zone(
            "public",
            zone.zone_id,
            payload=ZoneUpdateInput(content_source="feed_adapter"),
            operator_id="op_a",
        )


def test_delete_zone(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    zone = service.add_zone("public", payload=_ticker(), operator_id="op_a")
    assert service.delete_zone("public", zone.zone_id, operator_id="op_a") is True
    with pytest.raises(ZoneNotFoundError):
        service.delete_zone("public", zone.zone_id, operator_id="op_a")
    assert "zone_removed" in [e.event_kind for e in service.list_audit("public")]


# ---------------------------------------------------------------------------
# Feeds + approvals
# ---------------------------------------------------------------------------


def test_feed_crud(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    feed = service.add_feed("public", payload=_rss_feed(), operator_id="op_a")
    assert [f.feed_source_id for f in service.list_feeds("public")] == [feed.feed_source_id]
    updated = service.update_feed(
        "public", feed.feed_source_id, payload=FeedUpdateInput(label="Renamed"), operator_id="op_a"
    )
    assert updated.label == "Renamed"
    assert service.delete_feed("public", feed.feed_source_id, operator_id="op_a") is True
    assert service.list_feeds("public") == []


def test_add_weather_feed_public_is_422(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    with pytest.raises(ServiceValidationError):
        service.add_feed(
            "public",
            payload=FeedInput(
                kind="weather",
                label="WX",
                source_url="https://x.gov/wx.json",
                trust_tier="public_permitted",
            ),
            operator_id="op_a",
        )


def test_update_feed_404(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    with pytest.raises(FeedNotFoundError):
        service.update_feed(
            "public", "ghost", payload=FeedUpdateInput(label="x"), operator_id="op_a"
        )


def test_approve_feed_item(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, store = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    feed = service.add_feed("public", payload=_rss_feed(), operator_id="op_a")
    service.approve_feed_item(
        "public", feed_source_id=feed.feed_source_id, item_id="i1", operator_id="op_a"
    )
    assert store.list_approved_item_ids(
        channel_id="public", feed_source_id=feed.feed_source_id
    ) == {"i1"}
    with pytest.raises(FeedNotFoundError):
        service.approve_feed_item(
            "public", feed_source_id="ghost", item_id="i1", operator_id="op_a"
        )


_REVIEW_RSS = (
    '<?xml version="1.0"?><rss><channel>'
    "<item><title>Story A</title><guid>g-a</guid></item>"
    "<item><title>Story B</title><guid>g-b</guid></item>"
    "</channel></rss>"
)


def test_list_feed_items_for_review_stamps_real_approval(
    svc: tuple[CgBoardService, CgBoardStore],
) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    feed = service.add_feed("public", payload=_rss_feed(), operator_id="op_a")

    items = service.list_feed_items_for_review(
        "public", feed_source_id=feed.feed_source_id, fetch=lambda _url: _REVIEW_RSS
    )
    assert len(items) == 2
    assert all(not it.approved for it in items)  # nothing approved yet -> all pending

    # Approve one item; the review list must then show it approved, the other pending.
    service.approve_feed_item(
        "public", feed_source_id=feed.feed_source_id, item_id=items[0].item_id, operator_id="op_a"
    )
    again = service.list_feed_items_for_review(
        "public", feed_source_id=feed.feed_source_id, fetch=lambda _url: _REVIEW_RSS
    )
    by_id = {it.item_id: it.approved for it in again}
    assert by_id[items[0].item_id] is True
    assert by_id[items[1].item_id] is False


def test_list_feed_items_for_review_404_on_unknown_feed(
    svc: tuple[CgBoardService, CgBoardStore],
) -> None:
    service, _ = svc
    with pytest.raises(FeedNotFoundError):
        service.list_feed_items_for_review("public", feed_source_id="ghost", fetch=lambda _url: "")


# ---------------------------------------------------------------------------
# Preview + audit ordering
# ---------------------------------------------------------------------------


def test_preview_resolves_board(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    resolved = service.preview("public")
    assert resolved is not None
    # Empty board back-fills all four required kinds for a valid snapshot.
    assert {"primary", "ticker", "schedule", "logo"} <= {z.kind for z in resolved.snapshot.zones}


def test_preview_renders_coming_up_interstitial(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    _, store = svc

    def reader(_channel_id: str, now: datetime) -> list[tuple[datetime, str]]:
        return [(now + timedelta(hours=1), "City Council")]

    service = CgBoardService(store, clock=lambda: _NOW, upcoming_reader=reader)
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    zone = service.add_zone(
        "public",
        payload=ZoneInput(region="side", zone_kind="schedule", content_source="schedule"),
        operator_id="op_a",
    )
    resolved = service.preview("public")
    assert resolved is not None
    sched = next(z for z in resolved.snapshot.zones if z.zone_id == zone.zone_id)
    assert [i["title"] for i in sched.content["items"]] == ["City Council"]


def test_audit_lists_newest_first(svc: tuple[CgBoardService, CgBoardStore]) -> None:
    service, _ = svc
    service.create_board("public", template_id="standard-community-board", operator_id="op_a")
    service.add_zone("public", payload=_ticker(), operator_id="op_a")
    kinds = [e.event_kind for e in service.list_audit("public")]
    assert kinds == ["zone_added", "board_created"]  # monotonic clock -> newest first
