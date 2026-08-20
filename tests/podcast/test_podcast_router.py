# SPDX-License-Identifier: Apache-2.0
"""Podcast router tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.playback_policy.router import get_playback_policy_store
from civiccast.playback_policy.store import PlaybackPolicyStore
from civiccast.podcast.router import get_podcast_store
from civiccast.podcast.store import InMemoryPodcastStore


@pytest.fixture
def store() -> InMemoryPodcastStore:
    return InMemoryPodcastStore()


@pytest.fixture
def playback_store() -> PlaybackPolicyStore:
    return PlaybackPolicyStore()


@pytest.fixture
def client(
    store: InMemoryPodcastStore, playback_store: PlaybackPolicyStore
) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_podcast_store] = lambda: store
    app.dependency_overrides[get_playback_policy_store] = lambda: playback_store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


def test_create_episode_and_public_feed(client: TestClient) -> None:
    response = client.post(
        "/api/staff/podcast/episodes",
        json={
            "asset_id": "council-2026-05-14",
            "channel_id": "gov-ch12",
            "title": "Council Meeting",
            "portal_url": "https://portal.example/watch/council",
            "source_media_url": "https://cdn.example/council.m3u8",
            "signed_transcript_url": "https://portal.example/records/council.pdf",
            "summary": "Budget hearing and public comment.",
            "chapters": [{"t": 15, "title": "Call to order"}],
        },
    )
    assert response.status_code == 200
    assert response.json()["loudness_lufs"] == -16.0

    feed = client.get("/api/public/podcast/gov-ch12.xml")
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("application/rss+xml")
    assert "<enclosure" in feed.text
    assert "Council Meeting" in feed.text


def test_authenticated_podcast_feed_requires_signed_viewer_token(client: TestClient) -> None:
    created = client.post(
        "/api/staff/podcast/episodes",
        json={
            "asset_id": "training-2026-05-14",
            "channel_id": "training",
            "title": "Board Training",
            "portal_url": "https://portal.example/watch/training",
            "source_media_url": "https://cdn.example/training.m3u8",
        },
    )
    policy = client.post(
        "/api/staff/playback-policy/channel/training",
        json={
            "access_tier": "invite_only",
            "invite_group_id": "board-training",
            "authenticated_rss_enabled": True,
        },
    )
    token = client.post(
        "/api/staff/playback-policy/viewer-tokens",
        json={
            "account_id": "viewer-one",
            "display_name": "Viewer One",
            "invite_groups": ["board-training"],
        },
    )
    blocked = client.get("/api/public/podcast/training.xml")
    feed = client.get("/api/public/podcast/training.xml", params={"token": token.json()["token"]})

    assert created.status_code == 200
    assert policy.status_code == 200
    assert token.status_code == 200
    assert blocked.status_code == 401
    assert feed.status_code == 200
    assert "Board Training" in feed.text
