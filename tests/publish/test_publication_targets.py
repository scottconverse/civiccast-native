# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The canonical publication-target resolver (WP-05 plan items 1-2).

``StaffAssetRow`` has no ``channel_id``, so both subscriber delivery and the
public RSS feed have to DERIVE it. One resolver answers for both; these tests
pin each derivation rule and the deduplication that keeps a resident subscribed
to two matching targets from being treated as two recipients.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.live.models  # noqa: F401 -- register live_sessions on Base.metadata
from civiccast.db import Base
from civiccast.live.models import LiveSession
from civiccast.publish.targets import (
    DEFAULT_CHANNEL_ID_FALLBACK,
    PublicationTarget,
    SqlChannelAssociationLookup,
    StaticChannelAssociationLookup,
    publication_id_for_asset,
    resolve_publication_targets,
)
from civiccast.schedule.models import ScheduleItem, StaffAssetRow


def _asset(
    asset_id: str = "meeting-42",
    *,
    meeting_body: str | None = None,
    source_live_session_id: str | None = None,
) -> StaffAssetRow:
    return StaffAssetRow(
        asset_id=asset_id,
        title="Council Meeting",
        meeting_body=meeting_body,
        state="validated",
        manifest_url=f"https://cdn.example/{asset_id}/playlist.m3u8",
        published_at=datetime(2026, 6, 10, tzinfo=UTC),
        retention_policy="meeting",
        source_live_session_id=source_live_session_id,
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sql_lookup(engine: Engine) -> SqlChannelAssociationLookup:
    @contextmanager
    def session_factory() -> Iterator[Session]:
        session = Session(bind=engine)
        try:
            yield session
        finally:
            session.close()

    return SqlChannelAssociationLookup(session_factory)


def _add_schedule_item(
    engine: Engine,
    *,
    asset_id: str,
    channel_id: str,
    scheduled_at: datetime,
    state: str = "scheduled",
) -> None:
    with Session(bind=engine) as session:
        session.add(
            ScheduleItem(
                id=uuid.uuid4(),
                asset_id=asset_id,
                channel_id=channel_id,
                mode="premiere",
                state=state,
                scheduled_at=scheduled_at,
                duration_seconds=3600,
                created_at=datetime.now(UTC),
            )
        )
        session.commit()


def _add_live_session(engine: Engine, *, live_session_id: str, channel_id: str) -> None:
    with Session(bind=engine) as session:
        session.add(
            LiveSession(
                live_session_id=live_session_id,
                channel_id=channel_id,
                title="Live council",
                state="recorded",
                created_at=datetime.now(UTC),
            )
        )
        session.commit()


class TestDerivationRules:
    def test_legacy_uploaded_asset_falls_back_to_the_station_default_channel(self) -> None:
        targets = resolve_publication_targets(_asset(), default_channel_id="government")

        assert targets == (
            PublicationTarget(
                target_type="channel", target_id="government", source="station_default"
            ),
        )

    def test_scheduled_asset_uses_the_schedule_association(
        self, engine: Engine, sql_lookup: SqlChannelAssociationLookup
    ) -> None:
        _add_schedule_item(
            engine,
            asset_id="meeting-42",
            channel_id="education",
            scheduled_at=datetime(2026, 6, 10, 19, tzinfo=UTC),
        )

        targets = resolve_publication_targets(
            _asset(), lookup=sql_lookup, default_channel_id="government"
        )

        assert [target.target_id for target in targets] == ["education"]
        assert targets[0].source == "schedule"

    def test_cancelled_schedule_rows_never_decide_the_channel(
        self, engine: Engine, sql_lookup: SqlChannelAssociationLookup
    ) -> None:
        _add_schedule_item(
            engine,
            asset_id="meeting-42",
            channel_id="education",
            scheduled_at=datetime(2026, 6, 1, 19, tzinfo=UTC),
            state="cancelled",
        )

        targets = resolve_publication_targets(
            _asset(), lookup=sql_lookup, default_channel_id="government"
        )

        assert [target.target_id for target in targets] == ["government"]

    def test_earliest_non_cancelled_airing_wins_when_scheduled_twice(
        self, engine: Engine, sql_lookup: SqlChannelAssociationLookup
    ) -> None:
        """Determinism matters: the delivery key is derived from the target."""

        _add_schedule_item(
            engine,
            asset_id="meeting-42",
            channel_id="community",
            scheduled_at=datetime(2026, 6, 20, 19, tzinfo=UTC),
        )
        _add_schedule_item(
            engine,
            asset_id="meeting-42",
            channel_id="education",
            scheduled_at=datetime(2026, 6, 10, 19, tzinfo=UTC),
        )

        first = resolve_publication_targets(_asset(), lookup=sql_lookup)
        second = resolve_publication_targets(_asset(), lookup=sql_lookup)

        assert [target.target_id for target in first] == ["education"]
        assert first == second

    def test_live_finalized_asset_uses_its_live_session_channel(
        self, engine: Engine, sql_lookup: SqlChannelAssociationLookup
    ) -> None:
        _add_live_session(engine, live_session_id="ls-7", channel_id="community")
        # A stale schedule row on a different channel must not win over the
        # session the recording was actually finalized from.
        _add_schedule_item(
            engine,
            asset_id="meeting-42",
            channel_id="education",
            scheduled_at=datetime(2026, 6, 10, 19, tzinfo=UTC),
        )

        targets = resolve_publication_targets(
            _asset(source_live_session_id="ls-7"), lookup=sql_lookup
        )

        assert [target.target_id for target in targets] == ["community"]
        assert targets[0].source == "live_session"

    def test_meeting_body_adds_a_second_target(self) -> None:
        targets = resolve_publication_targets(
            _asset(meeting_body="planning-commission"), default_channel_id="government"
        )

        assert targets == (
            PublicationTarget(
                target_type="channel", target_id="government", source="station_default"
            ),
            PublicationTarget(
                target_type="meeting_body",
                target_id="planning-commission",
                source="asset_meeting_body",
            ),
        )

    def test_blank_meeting_body_adds_nothing(self) -> None:
        targets = resolve_publication_targets(_asset(meeting_body="   "))

        assert [target.target_type for target in targets] == ["channel"]

    def test_a_station_without_a_profile_still_resolves_a_channel(self) -> None:
        """Never return zero targets: that would silently reach nobody."""

        targets = resolve_publication_targets(_asset())

        assert len(targets) == 1
        assert targets[0].target_id == DEFAULT_CHANNEL_ID_FALLBACK

    def test_duplicate_targets_are_collapsed(self) -> None:
        """A channel and meeting body may not both claim the same pair twice."""

        targets = resolve_publication_targets(
            _asset(meeting_body="government"), default_channel_id="government"
        )

        pairs = [(target.target_type, target.target_id) for target in targets]
        assert len(pairs) == len(set(pairs))


class TestLookups:
    def test_batched_lookup_resolves_a_page_of_assets(
        self, engine: Engine, sql_lookup: SqlChannelAssociationLookup
    ) -> None:
        _add_schedule_item(
            engine,
            asset_id="a1",
            channel_id="education",
            scheduled_at=datetime(2026, 6, 10, tzinfo=UTC),
        )
        _add_live_session(engine, live_session_id="ls-9", channel_id="community")

        resolved = sql_lookup.channel_ids_for_assets(
            [_asset("a1"), _asset("a2", source_live_session_id="ls-9"), _asset("a3")]
        )

        # a3 has no association at all; it is absent, not guessed.
        assert resolved == {"a1": "education", "a2": "community"}

    def test_static_lookup_is_the_no_durable_storage_shape(self) -> None:
        lookup = StaticChannelAssociationLookup()

        assert lookup.channel_ids_for_assets([_asset()]) == {}
        assert lookup.channel_id_for_asset(_asset()) is None


def test_publication_id_is_stable_across_reapproval() -> None:
    """The publication identity is what makes re-approval idempotent."""

    assert publication_id_for_asset("meeting-42") == publication_id_for_asset("meeting-42")
    assert publication_id_for_asset("meeting-42") != publication_id_for_asset("meeting-43")
