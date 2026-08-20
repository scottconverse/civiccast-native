# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Podcast episode generation using deterministic local proof adapters."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from civiccast.podcast.models import PodcastEpisode, PodcastEpisodeCreate


def create_podcast_episode(request: PodcastEpisodeCreate) -> PodcastEpisode:
    """Create a deterministic podcast episode proof for CI and local runs."""
    digest = hashlib.sha256(f"{request.asset_id}:{request.source_media_url}".encode()).hexdigest()
    return PodcastEpisode(
        episode_id=f"pod-{digest[:24]}",
        asset_id=request.asset_id,
        channel_id=request.channel_id,
        title=request.title,
        audio_url=f"https://portal.example/podcast/audio/{request.asset_id}.mp3",
        rss_guid=f"civiccast:podcast:{request.asset_id}:{digest[:16]}",
        duration_seconds=3600,
        loudness_lufs=-16.0,
        chapters=request.chapters,
        transcript_url=request.signed_transcript_url,
        summary=request.summary,
        published_at=datetime.now(UTC),
    )
