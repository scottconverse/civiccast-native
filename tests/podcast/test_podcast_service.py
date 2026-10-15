# SPDX-License-Identifier: Apache-2.0
"""Podcast generation and RSS tests for v0.8."""

from __future__ import annotations

import hashlib
import math
import struct
import wave
from pathlib import Path

import pytest

from civiccast.podcast.models import PodcastChapter, PodcastEpisodeCreate
from civiccast.podcast.rss import render_podcast_rss, validate_podcast_rss
from civiccast.podcast.service import create_podcast_episode
from civiccast.podcast.store import InMemoryPodcastStore


@pytest.fixture
def audio_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "meeting.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        samples = (
            struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * t / 16000)))
            for t in range(16000)
        )
        audio.writeframes(b"".join(samples))
    output_dir = tmp_path / "podcasts"
    monkeypatch.setenv("CIVICCAST_PODCAST_MEDIA_DIR", str(output_dir))
    monkeypatch.setenv("CIVICCAST_PUBLIC_BASE_URL", "https://station.example")
    return source


def test_episode_creation_writes_playable_audio(tmp_path: Path, audio_source: Path) -> None:
    output_dir = tmp_path / "podcasts"

    episode = create_podcast_episode(
        PodcastEpisodeCreate(
            asset_id="meeting-1",
            channel_id="government",
            title="Council meeting",
            portal_url="https://station.example/#/watch/meeting-1",
            source_media_url=audio_source.as_uri(),
        )
    )

    audio_path = next(output_dir.glob("*.mp3"))
    assert audio_path.is_file()
    assert audio_path.stat().st_size > 1000
    assert episode.audio_url.startswith("https://station.example/api/public/podcast/audio/")
    assert episode.duration_seconds is not None and episode.duration_seconds >= 1


def test_create_podcast_episode_uses_stable_guid_and_lufs_target(
    audio_source: Path,
) -> None:
    episode = create_podcast_episode(
        PodcastEpisodeCreate(
            asset_id="council-2026-05-14",
            channel_id="gov-ch12",
            title="Council Meeting",
            portal_url="https://portal.example/watch/council",
            source_media_url=audio_source.as_uri(),
            signed_transcript_url="https://portal.example/records/council.pdf",
            summary="Budget hearing and public comment.",
            chapters=[PodcastChapter(t=15, title="Call to order")],
        )
    )

    assert episode.audio_url.endswith("/council-2026-05-14.mp3")
    assert episode.rss_guid.startswith("civiccast:podcast:council-2026-05-14")
    assert episode.loudness_lufs == -16.0
    assert episode.transcript_url == "https://portal.example/records/council.pdf"


def test_podcast_rss_contains_enclosure_chapters_and_transcript_link(
    audio_source: Path,
) -> None:
    episode = create_podcast_episode(
        PodcastEpisodeCreate(
            asset_id="council-2026-05-14",
            channel_id="gov-ch12",
            title="Council Meeting",
            portal_url="https://portal.example/watch/council",
            source_media_url=audio_source.as_uri(),
            signed_transcript_url="https://portal.example/records/council.pdf",
            summary="Budget hearing and public comment.",
            chapters=[PodcastChapter(t=15, title="Call to order")],
        )
    )

    audio_file = (
        audio_source.parent
        / "podcasts"
        / f"{hashlib.sha256(episode.asset_id.encode()).hexdigest()[:32]}.mp3"
    )
    xml = render_podcast_rss(
        channel_id="gov-ch12",
        episodes=[episode],
        enclosure_bytes={episode.asset_id: audio_file.stat().st_size},
    )

    assert validate_podcast_rss(xml) == []
    assert "audio/mpeg" in xml
    assert 'length="' in xml
    assert "Call to order" in xml
    assert "records/council.pdf" in xml


def test_podcast_store_lists_by_channel(audio_source: Path) -> None:
    store = InMemoryPodcastStore()
    episode = create_podcast_episode(
        PodcastEpisodeCreate(
            asset_id="council-2026-05-14",
            channel_id="gov-ch12",
            title="Council Meeting",
            portal_url="https://portal.example/watch/council",
            source_media_url=audio_source.as_uri(),
        )
    )

    store.upsert_episode(episode)

    assert store.get_episode("council-2026-05-14") == episode
    assert store.list_for_channel("gov-ch12") == [episode]
    assert store.list_for_channel("other") == []
