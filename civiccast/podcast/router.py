# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI routes for v0.8 podcast episodes and feeds."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from civiccast.auth.roles import require_any_role
from civiccast.platform.stores import resolve_app_store
from civiccast.playback_policy.entitlements import ViewerTokenError, viewer_from_token
from civiccast.playback_policy.models import PlaybackPolicyEvaluationRequest
from civiccast.playback_policy.router import get_playback_policy_store
from civiccast.playback_policy.store import PlaybackPolicyStore
from civiccast.podcast.models import PodcastEpisode, PodcastEpisodeCreate
from civiccast.podcast.rss import render_podcast_rss
from civiccast.podcast.service import create_podcast_episode
from civiccast.podcast.store import PodcastStore

public_router = APIRouter(prefix="/api/public/podcast", tags=["public", "podcast"])
staff_router = APIRouter(prefix="/api/staff/podcast", tags=["staff", "podcast"])


def get_podcast_store(request: Request) -> PodcastStore:
    return cast(PodcastStore, resolve_app_store(request, "podcast_store", surface="Podcast store"))


@staff_router.post(
    "/episodes",
    response_model=PodcastEpisode,
    summary="Create deterministic v0.8 podcast episode proof",
    dependencies=[Depends(require_any_role("publish_operator", "support_admin"))],
)
def create_episode(
    request: PodcastEpisodeCreate,
    store: PodcastStore = Depends(get_podcast_store),
) -> PodcastEpisode:
    episode = create_podcast_episode(request)
    return store.upsert_episode(episode)


@public_router.get(
    "/{channel_id}.xml",
    summary="Read public podcast RSS feed",
)
def podcast_feed(
    channel_id: str,
    token: str | None = Query(default=None, max_length=5000),
    store: PodcastStore = Depends(get_podcast_store),
    playback_store: PlaybackPolicyStore = Depends(get_playback_policy_store),
) -> Response:
    policy = playback_store.get_policy("channel", channel_id)
    if policy.access_tier != "public":
        if not policy.authenticated_rss_enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Authenticated RSS is not enabled for this channel.",
            )
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="A signed viewer token is required for this podcast feed.",
            )
        try:
            viewer = viewer_from_token(token)
        except (ValueError, ViewerTokenError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        decision = playback_store.evaluate(
            PlaybackPolicyEvaluationRequest(
                asset_id=f"{channel_id}-podcast-feed",
                channel_id=channel_id,
                viewer=viewer,
            )
        )
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=decision.reason,
            )
    xml = render_podcast_rss(channel_id=channel_id, episodes=store.list_for_channel(channel_id))
    return Response(content=xml, media_type="application/rss+xml")
