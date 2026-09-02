# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The public subscription RSS feed carries real records or none (WP-05).

The removed defect: every station's feed, for every target, emitted one
invented item titled "Example CivicCast recording" linking to
``https://portal.example/watch/{target_id}`` -- a production-looking link to a
host nobody owns, presented to residents as a published recording.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.publish.targets import StaticChannelAssociationLookup
from civiccast.schedule.models import StaffAssetRow
from civiccast.subscribe.router import get_publication_target_lookup, get_rss_asset_store

_PUBLIC_BASE = "https://records.example-city.gov"


class _FakeAssetStore:
    def __init__(self, rows: list[StaffAssetRow]) -> None:
        self._rows = rows

    def list_all(self) -> list[StaffAssetRow]:
        return list(self._rows)


class _StoreWithoutStaffProjection:
    """The ephemeral in-memory VOD store shape: no ``list_all`` at all."""


def _row(
    asset_id: str,
    *,
    title: str,
    published: bool = True,
    meeting_body: str | None = None,
    description: str | None = None,
) -> StaffAssetRow:
    return StaffAssetRow(
        asset_id=asset_id,
        title=title,
        description=description,
        meeting_body=meeting_body,
        state="validated",
        manifest_url=f"https://cdn.example/{asset_id}/playlist.m3u8",
        published_at=datetime(2026, 6, 10, 19, 0, tzinfo=UTC) if published else None,
        retention_policy="meeting",
    )


@pytest.fixture(autouse=True)
def _configured_public_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_PUBLIC_BASE_URL", _PUBLIC_BASE)


def _client(rows: list[StaffAssetRow] | None = None, *, store: object | None = None):
    app = create_app()
    resolved = store if store is not None else _FakeAssetStore(rows or [])
    app.dependency_overrides[get_rss_asset_store] = lambda: resolved
    app.dependency_overrides[get_publication_target_lookup] = StaticChannelAssociationLookup
    return app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(_client([])) as test_client:
        yield test_client


def _items(xml: str) -> list[dict[str, str]]:
    root = ElementTree.fromstring(xml)
    channel = root.find("channel")
    assert channel is not None
    return [{child.tag: (child.text or "") for child in item} for item in channel.findall("item")]


def test_nothing_published_returns_a_valid_empty_feed(client: TestClient) -> None:
    response = client.get("/api/public/subscribe/rss/channel/government.xml")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml")
    assert "portal.example" not in response.text
    assert "Example CivicCast recording" not in response.text
    assert _items(response.text) == []
    # Still a well-formed, configured feed -- a reader can subscribe today and
    # receive items the moment the station publishes one.
    root = ElementTree.fromstring(response.text)
    channel = root.find("channel")
    assert channel is not None
    assert (channel.findtext("link") or "").startswith(_PUBLIC_BASE)


def test_published_records_appear_with_the_real_watch_route() -> None:
    rows = [
        _row("meeting-42", title="Council Meeting", description="Regular session."),
        _row("meeting-41", title="Budget Workshop"),
    ]
    with TestClient(_client(rows)) as client:
        response = client.get("/api/public/subscribe/rss/channel/government.xml")

    items = _items(response.text)
    assert [item["title"] for item in items] == ["Council Meeting", "Budget Workshop"]
    assert items[0]["link"] == f"{_PUBLIC_BASE}/#/watch/meeting-42"
    assert items[0]["guid"] == "civiccast:asset:meeting-42"
    assert items[0]["description"] == "Regular session."
    assert "portal.example" not in response.text


def test_unpublished_recordings_never_reach_the_public_feed() -> None:
    rows = [
        _row("draft-1", title="Not Yet Public", published=False),
        _row("meeting-42", title="Council Meeting"),
    ]
    with TestClient(_client(rows)) as client:
        response = client.get("/api/public/subscribe/rss/channel/government.xml")

    assert [item["title"] for item in _items(response.text)] == ["Council Meeting"]


def test_a_meeting_body_feed_uses_the_same_resolver_as_delivery() -> None:
    rows = [
        _row("meeting-42", title="Planning Commission", meeting_body="planning-commission"),
        _row("meeting-41", title="Council Meeting"),
    ]
    with TestClient(_client(rows)) as client:
        body_feed = client.get("/api/public/subscribe/rss/meeting_body/planning-commission.xml")
        channel_feed = client.get("/api/public/subscribe/rss/channel/government.xml")

    assert [item["title"] for item in _items(body_feed.text)] == ["Planning Commission"]
    # The same recording is also on its channel: the resolver returns BOTH
    # targets, so both feeds carry it -- exactly as both would be notified.
    assert sorted(item["title"] for item in _items(channel_feed.text)) == [
        "Council Meeting",
        "Planning Commission",
    ]


def test_a_feed_for_another_channel_is_empty_not_seeded() -> None:
    rows = [_row("meeting-42", title="Council Meeting")]
    with TestClient(_client(rows)) as client:
        response = client.get("/api/public/subscribe/rss/channel/education.xml")

    assert _items(response.text) == []
    assert "Example CivicCast recording" not in response.text


def test_a_store_without_a_staff_projection_yields_an_empty_feed_not_an_error() -> None:
    with TestClient(_client(store=_StoreWithoutStaffProjection())) as client:
        response = client.get("/api/public/subscribe/rss/channel/government.xml")

    assert response.status_code == 200
    assert _items(response.text) == []


def test_unknown_target_type_is_still_a_404(client: TestClient) -> None:
    response = client.get("/api/public/subscribe/rss/producer/anything.xml")

    assert response.status_code == 404


def test_the_feed_carries_no_subscriber_pii() -> None:
    rows = [_row("meeting-42", title="Council Meeting")]
    with TestClient(_client(rows)) as client:
        response = client.get("/api/public/subscribe/rss/channel/government.xml")

    lowered = response.text.lower()
    assert "@" not in response.text
    assert "subscriber" not in lowered
    assert "unsubscribe" not in lowered
