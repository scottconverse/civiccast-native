# SPDX-License-Identifier: Apache-2.0
"""Podcast generation and RSS tests for v0.8."""

from __future__ import annotations

from civiccast.podcast.models import PodcastChapter, PodcastEpisodeCreate
from civiccast.podcast.rss import render_podcast_rss, validate_podcast_rss
from civiccast.podcast.service import create_podcast_episode
from civiccast.podcast.store import InMemoryPodcastStore


def test_create_podcast_episode_uses_stable_guid_and_lufs_target() -> None:
    episode = create_podcast_episode(
        PodcastEpisodeCreate(
            asset_id="council-2026-05-14",
            channel_id="gov-ch12",
            title="Council Meeting",
            portal_url="https://portal.example/watch/council",
            source_media_url="https://cdn.example/council.m3u8",
            signed_transcript_url="https://portal.example/records/council.pdf",
            summary="Budget hearing and public comment.",
            chapters=[PodcastChapter(t=15, title="Call to order")],
        )
    )

    assert episode.audio_url.endswith("/council-2026-05-14.mp3")
    assert episode.rss_guid.startswith("civiccast:podcast:council-2026-05-14")
    assert episode.loudness_lufs == -16.0
    assert episode.transcript_url == "https://portal.example/records/council.pdf"


def test_podcast_rss_contains_enclosure_chapters_and_transcript_link() -> None:
    episode = create_podcast_episode(
        PodcastEpisodeCreate(
            asset_id="council-2026-05-14",
            channel_id="gov-ch12",
            title="Council Meeting",
            portal_url="https://portal.example/watch/council",
            source_media_url="https://cdn.example/council.m3u8",
            signed_transcript_url="https://portal.example/records/council.pdf",
            summary="Budget hearing and public comment.",
            chapters=[PodcastChapter(t=15, title="Call to order")],
        )
    )

    xml = render_podcast_rss(channel_id="gov-ch12", episodes=[episode])

    assert validate_podcast_rss(xml) == []
    assert "audio/mpeg" in xml
    assert "Call to order" in xml
    assert "records/council.pdf" in xml


def test_podcast_store_lists_by_channel() -> None:
    store = InMemoryPodcastStore()
    episode = create_podcast_episode(
        PodcastEpisodeCreate(
            asset_id="council-2026-05-14",
            channel_id="gov-ch12",
            title="Council Meeting",
            portal_url="https://portal.example/watch/council",
            source_media_url="https://cdn.example/council.m3u8",
        )
    )

    store.upsert_episode(episode)

    assert store.get_episode("council-2026-05-14") == episode
    assert store.list_for_channel("gov-ch12") == [episode]
    assert store.list_for_channel("other") == []
