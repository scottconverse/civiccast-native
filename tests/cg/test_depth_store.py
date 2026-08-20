# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S18 gap 6 (build step 7) slice 6 — CG depth data layer.

Covers civiccast.cg.depth_models (BulletinMedia / BulletinAudio / ZoneTag
validators) and civiccast.cg.depth_store.CgDepthStore (media/audio/tag CRUD),
the CgZoneConfig.allowed_tags round-trip through CgBoardStore, and the 0045
migration's up/down reversibility on the real Alembic chain.
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

from civiccast.cg.board_models import CgZoneConfig
from civiccast.cg.board_store import CgBoardStore
from civiccast.cg.depth_models import BulletinAudio, BulletinMedia, ZoneTag
from civiccast.cg.depth_store import CgDepthStore
from civiccast.db import Base

_T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def engine(tmp_path: Path):  # type: ignore[no-untyped-def]
    eng = create_engine(f"sqlite:///{tmp_path / 'depth.sqlite'}", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def depth(engine) -> CgDepthStore:  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return CgDepthStore(factory)


# ---------------------------------------------------------------------------
# BulletinMedia
# ---------------------------------------------------------------------------


def test_media_add_list_delete(depth: CgDepthStore) -> None:
    depth.add_media(
        BulletinMedia(
            media_id="m1",
            bulletin_id="b1",
            kind="uploaded_image",
            asset_ref="img_1",
            created_at=_T0,
        )
    )
    depth.add_media(
        BulletinMedia(
            media_id="m2",
            bulletin_id="b1",
            kind="live_video",
            live_source="ndi://cam1",
            created_at=_T0,
        )
    )
    media = depth.list_media("b1")
    assert {m.media_id for m in media} == {"m1", "m2"}
    assert depth.delete_media("m1") is True
    assert depth.delete_media("m1") is False
    assert [m.media_id for m in depth.list_media("b1")] == ["m2"]


def test_live_video_media_requires_live_source() -> None:
    with pytest.raises(ValueError, match="live_video media requires a live_source"):
        BulletinMedia(media_id="m", bulletin_id="b", kind="live_video", created_at=_T0)


def test_live_video_media_rejects_asset_ref() -> None:
    with pytest.raises(ValueError, match="must not carry an asset_ref"):
        BulletinMedia(
            media_id="m",
            bulletin_id="b",
            kind="live_video",
            live_source="ndi://x",
            asset_ref="a",
            created_at=_T0,
        )


def test_image_media_requires_asset_ref() -> None:
    with pytest.raises(ValueError, match="requires an asset_ref"):
        BulletinMedia(media_id="m", bulletin_id="b", kind="uploaded_image", created_at=_T0)


def test_slide_media_rejects_live_source() -> None:
    with pytest.raises(ValueError, match="must not carry a live_source"):
        BulletinMedia(
            media_id="m",
            bulletin_id="b",
            kind="fullscreen_slide",
            asset_ref="a",
            live_source="x",
            created_at=_T0,
        )


# ---------------------------------------------------------------------------
# BulletinAudio
# ---------------------------------------------------------------------------


def test_audio_set_list_delete_and_upsert(depth: CgDepthStore) -> None:
    depth.set_audio(
        BulletinAudio(
            audio_id="a1", scope="bulletin", target_id="b1", asset_ref="bed_1", created_at=_T0
        )
    )
    depth.set_audio(
        BulletinAudio(
            audio_id="a2",
            scope="channel",
            target_id="public",
            asset_ref="bed_2",
            loudness_regime="duck",
            created_at=_T0,
        )
    )
    assert [a.audio_id for a in depth.list_audio(scope="bulletin", target_id="b1")] == ["a1"]
    channel_audio = depth.list_audio(scope="channel", target_id="public")
    assert channel_audio[0].loudness_regime == "duck"
    # set is an upsert — re-setting the same id updates in place (no duplicate).
    depth.set_audio(
        BulletinAudio(
            audio_id="a1", scope="bulletin", target_id="b1", asset_ref="bed_1b", created_at=_T0
        )
    )
    refreshed = depth.list_audio(scope="bulletin", target_id="b1")
    assert len(refreshed) == 1 and refreshed[0].asset_ref == "bed_1b"
    assert depth.delete_audio("a1") is True


def test_audio_defaults_to_inherit_loudness() -> None:
    audio = BulletinAudio(
        audio_id="a", scope="channel", target_id="public", asset_ref="bed", created_at=_T0
    )
    assert audio.loudness_regime == "inherit"


# ---------------------------------------------------------------------------
# ZoneTag
# ---------------------------------------------------------------------------


def test_zone_tag_add_list_delete(depth: CgDepthStore) -> None:
    depth.add_tag(ZoneTag(tag_id="t_events", channel_id="public", label="Events", created_at=_T0))
    depth.add_tag(ZoneTag(tag_id="t_alerts", channel_id="public", label="Alerts", created_at=_T0))
    depth.add_tag(ZoneTag(tag_id="t_gov", channel_id="gov", label="Gov", created_at=_T0))
    assert {t.tag_id for t in depth.list_tags("public")} == {"t_events", "t_alerts"}
    assert depth.delete_tag("t_events") is True
    assert [t.tag_id for t in depth.list_tags("public")] == ["t_alerts"]


# ---------------------------------------------------------------------------
# allowed_tags round-trip through the board store
# ---------------------------------------------------------------------------


def test_zone_allowed_tags_round_trip(engine) -> None:  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    store = CgBoardStore(factory)
    store.upsert_zone(
        CgZoneConfig(
            zone_id="z1",
            board_id="b1",
            region="lower",
            zone_kind="ticker",
            content_source="manual",
            allowed_tags=["t_events", "t_alerts"],
            created_at=_T0,
        )
    )
    fetched = store.get_zone("z1")
    assert fetched is not None
    assert fetched.allowed_tags == ["t_events", "t_alerts"]
    # A zone created without tags round-trips as an empty list (default).
    store.upsert_zone(
        CgZoneConfig(
            zone_id="z2",
            board_id="b1",
            region="main",
            zone_kind="primary",
            content_source="schedule",
            created_at=_T0,
        )
    )
    assert store.get_zone("z2").allowed_tags == []  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Migration 0045 reversibility
# ---------------------------------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestCgDepthMigration:
    _TABLES = ("bulletin_media", "bulletin_audio", "zone_tags")

    def test_upgrade_creates_tables_and_allowed_tags_column(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table)
            cols = {c["name"] for c in insp.get_columns("cg_zone_configs")}
            assert "allowed_tags" in cols
            # 0046 (the chain head) added cg_feed_sources.tags for DC-CG3.
            assert "tags" in {c["name"] for c in insp.get_columns("cg_feed_sources")}
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_depth_only(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0044_cg_board_designer")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table)
            cols = {c["name"] for c in insp.get_columns("cg_zone_configs")}
            assert "allowed_tags" not in cols
            assert insp.has_table("cg_boards")  # the board-designer tables survive
        finally:
            eng.dispose()
