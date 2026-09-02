# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Resolving which CDN package a captioned asset belongs to.

``live_finalization_jobs.asset_id`` is a plain nullable column with no unique
constraint -- the primary key is ``live_session_id`` -- so more than one
completed row can name the same asset. An earlier ``scalar_one_or_none()``
here raised ``MultipleResultsFound`` on that shape, turning a survivable
ambiguity into a failed caption job on a recording that was otherwise ready
to publish.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from civiccast.db import Base
from civiccast.live.cdn_targets import (
    build_asset_cdn_package_target_lookup,
    live_package_cdn_prefix,
)
from civiccast.live.models import (
    FINALIZATION_STATE_COMPLETED,
    FINALIZATION_STATE_PENDING,
    LiveFinalizationJob,
)

_ASSET_ID = "council-2026-08-16"


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        session = maker()
        try:
            yield session
        finally:
            session.close()

    return factory


def _job(
    session_factory,
    *,
    live_session_id: str,
    state: str = FINALIZATION_STATE_COMPLETED,
    asset_id: str | None = _ASSET_ID,
    manifest_url: str | None = None,
    completed_at: datetime | None = None,
) -> None:
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            LiveFinalizationJob(
                live_session_id=live_session_id,
                state=state,
                asset_id=asset_id,
                package_manifest_url=manifest_url,
                completed_at=completed_at,
                updated_at=now,
            )
        )
        session.commit()


class TestAssetCdnPackageTargetLookup:
    def test_no_finalization_row_means_no_cdn_package(self, session_factory) -> None:
        lookup = build_asset_cdn_package_target_lookup(session_factory)

        assert lookup(_ASSET_ID) is None

    def test_a_single_completed_row_resolves_to_its_session_prefix(self, session_factory) -> None:
        _job(
            session_factory,
            live_session_id="ls_one",
            manifest_url="https://cdn.example.org/live/ls_one/playlist.m3u8",
            completed_at=datetime.now(UTC),
        )
        lookup = build_asset_cdn_package_target_lookup(session_factory)

        target = lookup(_ASSET_ID)

        assert target is not None
        assert target.prefix == live_package_cdn_prefix("ls_one")
        assert target.recorded_manifest_url == "https://cdn.example.org/live/ls_one/playlist.m3u8"

    def test_two_completed_rows_for_one_asset_take_the_most_recent(self, session_factory) -> None:
        """The reviewer's case: a re-finalize leaves two completed rows.

        The newest completed package is the one whose files are on the CDN
        now, so its manifest is the one a caption republish must rewrite.
        """

        earlier = datetime.now(UTC) - timedelta(hours=3)
        _job(
            session_factory,
            live_session_id="ls_old",
            manifest_url="https://cdn.example.org/live/ls_old/playlist.m3u8",
            completed_at=earlier,
        )
        _job(
            session_factory,
            live_session_id="ls_new",
            manifest_url="https://cdn.example.org/live/ls_new/playlist.m3u8",
            completed_at=datetime.now(UTC),
        )
        lookup = build_asset_cdn_package_target_lookup(session_factory)

        target = lookup(_ASSET_ID)

        assert target is not None
        assert target.prefix == live_package_cdn_prefix("ls_new")

    def test_a_null_completed_at_never_beats_a_real_one(self, session_factory) -> None:
        """An older row with no completion timestamp must not win."""

        _job(session_factory, live_session_id="ls_nulltime", completed_at=None)
        _job(
            session_factory,
            live_session_id="ls_timed",
            manifest_url="https://cdn.example.org/live/ls_timed/playlist.m3u8",
            completed_at=datetime.now(UTC),
        )
        lookup = build_asset_cdn_package_target_lookup(session_factory)

        target = lookup(_ASSET_ID)

        assert target is not None
        assert target.prefix == live_package_cdn_prefix("ls_timed")

    def test_an_unfinished_finalization_is_not_a_cdn_package(self, session_factory) -> None:
        _job(
            session_factory,
            live_session_id="ls_pending",
            state=FINALIZATION_STATE_PENDING,
            manifest_url="https://cdn.example.org/live/ls_pending/playlist.m3u8",
        )
        lookup = build_asset_cdn_package_target_lookup(session_factory)

        assert lookup(_ASSET_ID) is None

    def test_another_assets_row_is_not_returned(self, session_factory) -> None:
        _job(
            session_factory,
            live_session_id="ls_other",
            asset_id="some-other-asset",
            manifest_url="https://cdn.example.org/live/ls_other/playlist.m3u8",
            completed_at=datetime.now(UTC),
        )
        lookup = build_asset_cdn_package_target_lookup(session_factory)

        assert lookup(_ASSET_ID) is None
