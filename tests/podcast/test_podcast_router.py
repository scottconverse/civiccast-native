# SPDX-License-Identifier: Apache-2.0
"""Podcast router tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.playback_policy.entitlements import issue_viewer_token
from civiccast.playback_policy.models import PlaybackPolicyUpdate, ViewerTokenRequest
from civiccast.playback_policy.router import get_playback_policy_store
from civiccast.playback_policy.store import PlaybackPolicyStore
from civiccast.podcast.models import PodcastEpisode
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
    store: InMemoryPodcastStore,
    playback_store: PlaybackPolicyStore,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    monkeypatch.delenv("CIVICCAST_STAFF_TOKENS", raising=False)
    monkeypatch.setenv("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", "1")
    monkeypatch.setenv("CIVICCAST_STAFF_TOKENS_FALLBACK_WITH_DB", "1")
    app = create_app()
    app.dependency_overrides[get_podcast_store] = lambda: store
    app.dependency_overrides[get_playback_policy_store] = lambda: playback_store
    with TestClient(app, headers={"Authorization": "Bearer operator-token-a"}) as c:
        yield c


def test_public_episode_audio_is_served_from_recorded_enclosure(
    client: TestClient, store: InMemoryPodcastStore, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CIVICCAST_PODCAST_MEDIA_DIR", str(tmp_path))
    (tmp_path / f"{sha256(b'asset-a').hexdigest()[:32]}.mp3").write_bytes(b"ID3sample-audio")
    store.upsert_episode(
        PodcastEpisode(
            episode_id="pod-a",
            asset_id="asset-a",
            channel_id="government",
            title="Council meeting",
            audio_url="https://station.example/api/public/podcast/audio/asset-a.mp3",
            rss_guid="civiccast:podcast:asset-a",
            loudness_lufs=-16,
            published_at=datetime.now(UTC),
        )
    )

    response = client.get("/api/public/podcast/audio/asset-a.mp3")

    assert response.status_code == 200
    assert response.content == b"ID3sample-audio"
    assert response.headers["content-type"].startswith("audio/mpeg")


def test_asset_restricted_podcast_audio_requires_a_viewer_token(
    client: TestClient,
    store: InMemoryPodcastStore,
    playback_store: PlaybackPolicyStore,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("CIVICCAST_PODCAST_MEDIA_DIR", str(tmp_path))
    (tmp_path / f"{sha256(b'asset-a').hexdigest()[:32]}.mp3").write_bytes(b"ID3private")
    store.upsert_episode(
        PodcastEpisode(
            episode_id="pod-a",
            asset_id="asset-a",
            channel_id="government",
            title="Private meeting",
            audio_url="https://station.example/api/public/podcast/audio/asset-a.mp3",
            rss_guid="civiccast:podcast:asset-a",
            loudness_lufs=-16,
            published_at=datetime.now(UTC),
        )
    )
    playback_store.upsert_policy(
        "asset",
        "asset-a",
        PlaybackPolicyUpdate(
            access_tier="invite_only",
            invite_group_id="private-meetings",
            authenticated_rss_enabled=True,
        ),
    )

    response = client.get("/api/public/podcast/audio/asset-a.mp3")
    feed = client.get("/api/public/podcast/government.xml")

    assert response.status_code == 401
    assert feed.status_code == 200
    assert "Private meeting" not in feed.text

    token = issue_viewer_token(
        ViewerTokenRequest(
            account_id="resident-a",
            display_name="Resident A",
            invite_groups=["private-meetings"],
        )
    ).token
    authorized_feed = client.get("/api/public/podcast/government.xml", params={"token": token})
    authorized_audio = client.get("/api/public/podcast/audio/asset-a.mp3", params={"token": token})

    assert authorized_feed.status_code == 200
    assert "Private meeting" in authorized_feed.text
    assert f"?token={token}" in authorized_feed.text
    assert authorized_feed.headers["cache-control"] == "private, no-store"
    assert authorized_audio.status_code == 200
    assert authorized_audio.content == b"ID3private"
    assert authorized_audio.headers["cache-control"] == "private, no-store"


def test_direct_episode_creation_rejects_caller_selected_media_path(client: TestClient) -> None:
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
    assert response.status_code == 409
    assert "Publish dashboard" in response.json()["detail"]

    feed = client.get("/api/public/podcast/gov-ch12.xml")
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("application/rss+xml")
    assert "Council Meeting" not in feed.text


def test_authenticated_podcast_feed_requires_signed_viewer_token(
    client: TestClient, store: InMemoryPodcastStore, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("CIVICCAST_PODCAST_MEDIA_DIR", str(tmp_path))
    (tmp_path / f"{sha256(b'training-2026-05-14').hexdigest()[:32]}.mp3").write_bytes(
        b"ID3training"
    )
    store.upsert_episode(
        PodcastEpisode(
            episode_id="pod-training",
            asset_id="training-2026-05-14",
            channel_id="training",
            title="Board Training",
            audio_url="https://station.example/api/public/podcast/audio/training-2026-05-14.mp3",
            rss_guid="civiccast:podcast:training-2026-05-14",
            loudness_lufs=-16,
            published_at=datetime.now(UTC),
        )
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

    assert policy.status_code == 200
    assert token.status_code == 200
    assert blocked.status_code == 401
    assert feed.status_code == 200
    assert "Board Training" in feed.text
