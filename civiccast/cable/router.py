# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI routes for software channel and CTV beta contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse

from civiccast.auth.roles import ALL_OPERATOR_ROLES, require_any_role
from civiccast.cable.channel import (
    HLS_OUTPUT_NOT_ENABLED_NEXT_STEP,
    ChannelNowNext,
    ChannelPlayoutPlan,
    ChannelProfile,
    ChannelProofLog,
    CtvFeed,
    build_channel_now_next,
    build_channel_playout_plan,
    build_channel_proof_log,
    build_ctv_feed,
    channel_has_hls_sink,
    default_channel_profiles,
    get_channel_profile,
    local_live_manifest_path,
    resolve_live_outputs,
)
from civiccast.captions.live_sidecar import active_caption_sidecar
from civiccast.egress.automation import default_egress_work_dir
from civiccast.egress.router import get_egress_store
from civiccast.schedule.models import SCHEDULE_STATE_SCHEDULED, ScheduleItemResponse
from civiccast.schedule.router import get_schedule_store

public_router = APIRouter(prefix="/api/public/channels", tags=["public", "channels"])
staff_router = APIRouter(prefix="/api/staff/cable/channels", tags=["staff", "cable"])


@public_router.get(
    "",
    response_model=list[ChannelProfile],
    summary="List public linear channel profiles",
)
def list_public_channels(egress_store: Any = Depends(get_egress_store)) -> list[ChannelProfile]:
    return resolve_live_outputs(default_channel_profiles(), egress_store)


@public_router.get(
    "/{channel_id}/live.m3u8",
    response_class=RedirectResponse,
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    summary="Redirect to the channel's live HLS manifest",
    responses={
        307: {"description": "Redirects to /media/live/{channel_id}/playlist.m3u8"},
        404: {"description": "Unknown channel, or HLS web output is not enabled for it"},
    },
)
def public_channel_live_manifest(
    channel_id: str,
    egress_store: Any = Depends(get_egress_store),
) -> RedirectResponse:
    """Make the advertised ``/api/public/channels/{id}/live.m3u8`` URL true.

    The Channels screen, the CTV feed and the app-platform schedule feed all
    print this URL. It used to be a bare string with no route behind it (404
    for every channel, on air or not — beta.5 walkthrough). Now it redirects
    to the manifest ``civiccast.stream.media_router`` really serves when the
    channel has an ``hls`` egress sink, and otherwise answers 404 with a
    ``detail`` that names the fix.
    """
    if get_channel_profile(channel_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel profile not found: {channel_id}",
        )
    if not channel_has_hls_sink(channel_id, egress_store):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{HLS_OUTPUT_NOT_ENABLED_NEXT_STEP} (channel: {channel_id})",
        )
    return RedirectResponse(
        url=local_live_manifest_path(channel_id),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


@public_router.get(
    "/ctv/feed",
    response_model=CtvFeed,
    summary="Read the reference connected-TV feed",
)
def public_ctv_feed(station_name: str = "CivicCast Test Station") -> CtvFeed:
    return build_ctv_feed(station_name=station_name)


@public_router.get(
    "/{channel_id}/captions.vtt",
    response_class=Response,
    summary="Read the current public WebVTT captions for a channel",
    responses={
        200: {
            "description": "Current live WebVTT captions; Cache-Control: no-store",
            "content": {"text/vtt": {"schema": {"type": "string"}}},
        },
        404: {"description": "Channel or live caption feed not found"},
    },
)
def public_channel_captions_vtt(
    channel_id: str,
    work_dir: Path = Depends(default_egress_work_dir),
) -> Response:
    _channel_now_next_or_404(channel_id)
    root = work_dir.expanduser().resolve()
    sidecar = active_caption_sidecar(root, channel_id).resolve()
    try:
        sidecar.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc
    try:
        content = sidecar.read_bytes()
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Live captions for channel {channel_id!r} are not available.",
        ) from exc
    return Response(
        content=content,
        media_type="text/vtt",
        headers={"Cache-Control": "no-store"},
    )


@public_router.get(
    "/{channel_id}/now-next",
    response_model=ChannelNowNext,
    summary="Read public now/next state for a channel",
    responses={404: {"description": "Channel profile not found"}},
)
def public_channel_now_next(channel_id: str) -> ChannelNowNext:
    return _channel_now_next_or_404(channel_id)


@staff_router.get(
    "",
    response_model=list[ChannelProfile],
    summary="List operator channel profiles",
    dependencies=[Depends(require_any_role(*ALL_OPERATOR_ROLES))],
)
def list_staff_channels(egress_store: Any = Depends(get_egress_store)) -> list[ChannelProfile]:
    return resolve_live_outputs(default_channel_profiles(), egress_store)


@staff_router.get(
    "/{channel_id}/now-next",
    response_model=ChannelNowNext,
    summary="Read operator now/next state for a channel",
    responses={404: {"description": "Channel profile not found"}},
    dependencies=[Depends(require_any_role(*ALL_OPERATOR_ROLES))],
)
def staff_channel_now_next(channel_id: str) -> ChannelNowNext:
    return _channel_now_next_or_404(channel_id)


@staff_router.get(
    "/{channel_id}/proof-log",
    response_model=ChannelProofLog,
    summary="Read channel playout proof log",
    responses={404: {"description": "Channel profile not found"}},
    dependencies=[Depends(require_any_role(*ALL_OPERATOR_ROLES))],
)
def staff_channel_proof_log(channel_id: str) -> ChannelProofLog:
    try:
        return build_channel_proof_log(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@staff_router.get(
    "/{channel_id}/playout-plan",
    response_model=ChannelPlayoutPlan,
    summary="Read channel schedule-to-playout plan",
    responses={404: {"description": "Channel profile not found"}},
    dependencies=[Depends(require_any_role(*ALL_OPERATOR_ROLES))],
)
def staff_channel_playout_plan(
    channel_id: str,
    schedule_store: Any = Depends(get_schedule_store),
) -> ChannelPlayoutPlan:
    try:
        rows: list[ScheduleItemResponse] | None = None
        if schedule_store is not None:
            rows = cast(
                list[ScheduleItemResponse],
                schedule_store.list(channel_id=channel_id, states=(SCHEDULE_STATE_SCHEDULED,)),
            )
        return build_channel_playout_plan(channel_id, schedule_items=rows)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _channel_now_next_or_404(channel_id: str) -> ChannelNowNext:
    try:
        return build_channel_now_next(channel_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
