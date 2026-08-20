# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S6 V1 (build step 7) slice 1 — CG board-designer data layer.

Covers civiccast.cg.board_models (CgBoard / CgZoneConfig / CgFeedSource /
CgBoardAuditEvent / CgFeedItemApproval validators + ORM peers) and
civiccast.cg.board_store.CgBoardStore (board upsert + one-active-per-channel
invariant, zone CRUD, feed CRUD + fetch-state, append-only audit, idempotent
feed-item approvals). SQLite-backed; the live-Postgres head + namespace checks
live in tests/live/test_real_postgres.py. The 0044 migration's up/down
reversibility is asserted by TestCgBoardDesignerMigration via the real Alembic
chain on an ephemeral SQLite DB.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from civiccast.cg.board_models import (
    CgBoard,
    CgBoardAuditEvent,
    CgFeedItemApproval,
    CgFeedSource,
    CgZoneConfig,
)
from civiccast.cg.board_store import CgBoardStore
from civiccast.db import Base

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[CgBoardStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'cgboard.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield CgBoardStore(factory)
    finally:
        eng.dispose()


def _board(board_id: str = "cgb_main", channel_id: str = "public", **kwargs: object) -> CgBoard:
    base: dict[str, object] = {
        "board_id": board_id,
        "channel_id": channel_id,
        "template_id": "tmpl_default",
        "active": True,
        "created_by": "op_a",
        "created_at": _T0,
        "updated_at": _T0,
    }
    base.update(kwargs)
    return CgBoard(**base)  # type: ignore[arg-type]


def _zone(zone_id: str = "z_ticker", board_id: str = "cgb_main", **kwargs: object) -> CgZoneConfig:
    base: dict[str, object] = {
        "zone_id": zone_id,
        "board_id": board_id,
        "region": "lower",
        "zone_kind": "ticker",
        "content_source": "manual",
        "created_at": _T0,
    }
    base.update(kwargs)
    return CgZoneConfig(**base)  # type: ignore[arg-type]


def _feed(
    feed_source_id: str = "feed_rss", channel_id: str = "public", **kwargs: object
) -> CgFeedSource:
    base: dict[str, object] = {
        "feed_source_id": feed_source_id,
        "channel_id": channel_id,
        "kind": "rss",
        "label": "City news",
        "source_url": "https://example.gov/news.rss",
        "trust_tier": "operator_curated",
        "refresh_seconds": 900,
        "enabled": True,
        "created_by": "op_a",
        "created_at": _T0,
    }
    base.update(kwargs)
    return CgFeedSource(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Board CRUD + one-active-per-channel invariant
# ---------------------------------------------------------------------------


def test_board_upsert_insert_then_get(store: CgBoardStore) -> None:
    stored = store.upsert_board(_board())
    assert stored.board_id == "cgb_main"
    fetched = store.get_board("cgb_main")
    assert fetched is not None
    assert fetched.template_id == "tmpl_default"
    assert fetched.active is True
    assert fetched.created_at.tzinfo is not None  # UTC re-attached on the SQLite round-trip


def test_board_get_missing_returns_none(store: CgBoardStore) -> None:
    assert store.get_board("nope") is None
    assert store.get_active_board("public") is None


def test_board_update_in_place_preserves_created_at(store: CgBoardStore) -> None:
    store.upsert_board(_board())  # created_at = _T0
    # The update payload carries a different (later) created_at/updated_at; the
    # store must keep the original created_at and stamp updated_at to "now".
    changed = _board(
        template_id="tmpl_lbar",
        created_at=datetime(2030, 1, 1, tzinfo=UTC),
        updated_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    result = store.upsert_board(changed)
    assert result.template_id == "tmpl_lbar"
    assert result.created_at == _T0  # preserved from the original insert, not the 2030 payload
    assert result.updated_at.year != 2030  # store stamps "now", not the caller's sentinel


def test_active_board_invariant_one_per_channel(store: CgBoardStore) -> None:
    store.upsert_board(_board(board_id="cgb_a"))
    store.upsert_board(_board(board_id="cgb_b"))  # second active board, same channel
    active = store.get_active_board("public")
    assert active is not None
    assert active.board_id == "cgb_b"
    # The first board was deactivated so the active board is unambiguous.
    first = store.get_board("cgb_a")
    assert first is not None and first.active is False


def test_inactive_board_does_not_deactivate_siblings(store: CgBoardStore) -> None:
    store.upsert_board(_board(board_id="cgb_a"))
    store.upsert_board(_board(board_id="cgb_b", channel_id="gov"))  # different channel
    store.upsert_board(_board(board_id="cgb_c", active=False))  # inactive, same channel as a
    assert store.get_active_board("public").board_id == "cgb_a"  # type: ignore[union-attr]
    assert store.get_active_board("gov").board_id == "cgb_b"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Zone CRUD + validators
# ---------------------------------------------------------------------------


def test_zone_upsert_get_list_delete(store: CgBoardStore) -> None:
    store.upsert_zone(_zone(zone_id="z1", manual_text="Welcome"))
    store.upsert_zone(_zone(zone_id="z2", region="main", zone_kind="primary"))
    zones = store.list_zones("cgb_main")
    assert {z.zone_id for z in zones} == {"z1", "z2"}
    fetched = store.get_zone("z1")
    assert fetched is not None and fetched.manual_text == "Welcome"
    assert store.delete_zone("z1") is True
    assert store.delete_zone("z1") is False
    assert {z.zone_id for z in store.list_zones("cgb_main")} == {"z2"}


def test_zone_update_in_place_preserves_created_at(store: CgBoardStore) -> None:
    store.upsert_zone(_zone(zone_id="z1", manual_text="Old"))  # created_at = _T0
    result = store.upsert_zone(
        _zone(zone_id="z1", manual_text="New", created_at=datetime(2030, 1, 1, tzinfo=UTC))
    )
    assert result.manual_text == "New"
    assert result.created_at == _T0  # preserved, not the 2030 payload


def test_feed_zone_requires_a_feed_source() -> None:
    with pytest.raises(ValueError, match="feed_source_id"):
        _zone(content_source="feed_adapter")  # no feed_source_id


def test_feed_source_id_only_valid_for_feed_zone() -> None:
    with pytest.raises(ValueError, match="only valid for feed_adapter"):
        _zone(content_source="manual", feed_source_id="feed_rss")


def test_feed_adapter_zone_with_feed_is_valid(store: CgBoardStore) -> None:
    zone = _zone(zone_id="zf", content_source="feed_adapter", feed_source_id="feed_rss")
    result = store.upsert_zone(zone)
    assert result.feed_source_id == "feed_rss"


# ---------------------------------------------------------------------------
# Feed-source CRUD + validators + fetch state
# ---------------------------------------------------------------------------


def test_feed_upsert_get_list_filters(store: CgBoardStore) -> None:
    store.upsert_feed(_feed(feed_source_id="f_on"))
    store.upsert_feed(_feed(feed_source_id="f_off", enabled=False))
    store.upsert_feed(_feed(feed_source_id="f_gov", channel_id="gov"))
    assert {f.feed_source_id for f in store.list_feeds("public")} == {"f_on", "f_off"}
    assert [f.feed_source_id for f in store.list_feeds("public", enabled_only=True)] == ["f_on"]
    assert store.delete_feed("f_on") is True
    assert store.delete_feed("f_on") is False


def test_feed_tags_round_trip(store: CgBoardStore) -> None:
    store.upsert_feed(_feed(feed_source_id="f_tagged", tags=["events", "community"]))
    got = store.get_feed("f_tagged")
    assert got is not None and got.tags == ["events", "community"]
    # A feed without tags round-trips as an empty list (default).
    store.upsert_feed(_feed(feed_source_id="f_plain"))
    assert store.get_feed("f_plain").tags == []  # type: ignore[union-attr]


def test_feed_weather_must_be_curated() -> None:
    with pytest.raises(ValueError, match="operator or partner curated"):
        _feed(kind="weather", trust_tier="public_permitted")


def test_mark_feed_fetch_records_success_then_error(store: CgBoardStore) -> None:
    store.upsert_feed(_feed(feed_source_id="f1"))
    t1 = datetime(2026, 6, 1, tzinfo=UTC)
    store.mark_feed_fetch("f1", fetched_at=t1, error=None)
    got = store.get_feed("f1")
    assert got is not None and got.last_fetched_at == t1 and got.last_fetch_error is None
    t2 = datetime(2026, 6, 2, tzinfo=UTC)
    store.mark_feed_fetch("f1", fetched_at=t2, error="timeout")
    got2 = store.get_feed("f1")
    assert got2 is not None and got2.last_fetch_error == "timeout"


def test_mark_feed_fetch_missing_feed_is_noop(store: CgBoardStore) -> None:
    store.mark_feed_fetch("ghost", fetched_at=_T0, error=None)  # no exception


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def test_audit_append_and_list_newest_first(store: CgBoardStore) -> None:
    store.append_audit(
        CgBoardAuditEvent(
            audit_id="a1",
            board_id="cgb_main",
            channel_id="public",
            event_kind="board_created",
            operator_id="op_a",
            occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
            details={"template_id": "tmpl_default"},
        )
    )
    store.append_audit(
        CgBoardAuditEvent(
            audit_id="a2",
            board_id="cgb_main",
            channel_id="public",
            event_kind="zone_added",
            occurred_at=datetime(2026, 6, 2, tzinfo=UTC),
        )
    )
    events = store.list_audit(board_id="cgb_main")
    assert [e.audit_id for e in events] == ["a2", "a1"]  # newest first
    assert events[1].details == {"template_id": "tmpl_default"}  # JSON round-trip
    # limit + offset paginate.
    assert [e.audit_id for e in store.list_audit(board_id="cgb_main", limit=1)] == ["a2"]
    assert [e.audit_id for e in store.list_audit(board_id="cgb_main", limit=1, offset=1)] == ["a1"]


# ---------------------------------------------------------------------------
# Feed-item approvals
# ---------------------------------------------------------------------------


def _approval(item_id: str = "item_1", **kwargs: object) -> CgFeedItemApproval:
    base: dict[str, object] = {
        "approval_id": f"appr_{item_id}",
        "channel_id": "public",
        "feed_source_id": "feed_rss",
        "item_id": item_id,
        "approved_by_operator": "op_a",
        "approved_at": _T0,
    }
    base.update(kwargs)
    return CgFeedItemApproval(**base)  # type: ignore[arg-type]


def test_approval_approve_list_revoke(store: CgBoardStore) -> None:
    store.approve_item(_approval(item_id="item_1"))
    store.approve_item(_approval(item_id="item_2"))
    approved = store.list_approved_item_ids(channel_id="public", feed_source_id="feed_rss")
    assert approved == {"item_1", "item_2"}
    assert store.revoke_item("appr_item_1") is True
    assert store.list_approved_item_ids(channel_id="public", feed_source_id="feed_rss") == {
        "item_2"
    }


def test_approval_is_idempotent(store: CgBoardStore) -> None:
    store.approve_item(_approval(item_id="item_1", approval_id="appr_a"))
    # Re-approving the same (channel, feed, item) with a different approval_id is a
    # no-op: the stored row wins, no duplicate, no integrity error.
    again = store.approve_item(_approval(item_id="item_1", approval_id="appr_b"))
    assert again.approval_id == "appr_a"
    assert store.list_approved_item_ids(channel_id="public", feed_source_id="feed_rss") == {
        "item_1"
    }


def test_approve_item_recovers_when_pre_check_misses_a_concurrent_winner(
    store: CgBoardStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A concurrent writer commits the winning row first.
    store.approve_item(_approval(item_id="race", approval_id="appr_win"))
    # Force this caller's idempotent pre-check to miss exactly once (the true
    # race: both writers saw "no row yet"). The INSERT then trips the
    # (channel, feed, item) UNIQUE constraint, so the handler must roll back and
    # return the committed winner instead of surfacing an IntegrityError.
    # (This also proves the ORM-declared UNIQUE is enforced: without it the
    # loser's insert would succeed and this would return "appr_loser".)
    original = CgBoardStore._existing_approval
    state = {"miss": True}

    def _flaky(self, session, approval):  # type: ignore[no-untyped-def]
        if state["miss"]:
            state["miss"] = False
            return None
        return original(self, session, approval)

    monkeypatch.setattr(CgBoardStore, "_existing_approval", _flaky)
    result = store.approve_item(_approval(item_id="race", approval_id="appr_loser"))
    assert result.approval_id == "appr_win"


# ---------------------------------------------------------------------------
# Migration 0044 reversibility (real Alembic chain on ephemeral SQLite)
# ---------------------------------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestCgBoardDesignerMigration:
    """0044_cg_board_designer creates the five S6 board-designer tables on
    upgrade and drops exactly those on a single-step downgrade to 0043 — the
    rest of the schema (cg_bulletins, auto-schedule tables) survives."""

    _TABLES = (
        "cg_boards",
        "cg_zone_configs",
        "cg_feed_sources",
        "cg_board_audit",
        "cg_feed_item_approvals",
    )

    def test_upgrade_head_creates_the_five_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table)
            approval_idx = {ix["name"] for ix in insp.get_indexes("cg_feed_item_approvals")}
            assert "ix_cg_feed_item_approvals_feed" in approval_idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_five_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0043_scheduling_automation")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table)
            assert insp.has_table("cg_bulletins")  # CA-3 table survives
            assert insp.has_table("auto_schedule_rules")  # S18 table survives
        finally:
            eng.dispose()
