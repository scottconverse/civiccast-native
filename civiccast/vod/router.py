# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI router for the public VOD embed API."""

from __future__ import annotations

import os
from typing import cast
from urllib.parse import quote, urljoin

from fastapi import APIRouter, Depends, HTTPException, Request, status

from civiccast.platform.stores import resolve_app_store
from civiccast.vod.embed import build_embed_html
from civiccast.vod.models import AssetEmbedResponse, public_manifest_reference
from civiccast.vod.store import AssetStore


def _portal_base(request: Request) -> str:
    """Return the public portal SPA origin used in embed URLs.

    Defaults to the API request's own base URL — correct for single-host
    deployments where API and portal are served from the same origin.
    Operators with the portal on a separate origin (the recommended
    production posture) set ``CIVICCAST_PORTAL_BASE`` to the public URL
    of the portal SPA, e.g. ``https://portal.your-station.org``.

    The Sprint 0.2 portal SPA serves a single page at ``/``; the embed
    URL therefore points at ``{portal_base}/?manifest=<url>``, NOT a
    per-asset path. Per-asset routing lands at rung 0.3 with the
    schedule module.
    """
    explicit = os.environ.get("CIVICCAST_PORTAL_BASE")
    if explicit:
        return explicit.rstrip("/")
    return str(request.base_url).rstrip("/")


def get_store(request: Request) -> AssetStore:
    """FastAPI dependency for the active asset store."""
    return cast(AssetStore, resolve_app_store(request, "asset_store", surface="Public asset store"))


router = APIRouter(prefix="/api/public", tags=["public"])


@router.get(
    "/embed/{asset_id}",
    response_model=AssetEmbedResponse,
    summary="Get embed snippet + manifest URL for a public asset",
    responses={
        404: {"description": "Asset not found"},
    },
)
def get_embed(
    asset_id: str,
    request: Request,
    store: AssetStore = Depends(get_store),
) -> AssetEmbedResponse:
    """Return the iframe snippet and metadata needed to embed an asset.

    Public — no auth. The asset's `manifest_url` is already on a public CDN
    so there is no information leak in returning it. Stations that want
    private/unlisted assets must mark them so in the asset store; this
    endpoint refuses to serve them (404).
    """
    asset = store.get(asset_id)
    if asset is None or asset.published_at is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset not found: {asset_id}",
        )

    # The portal SPA at civiccast/apps/portal-public consumes a manifest
    # via the ?manifest=<url> query string on its single root route. The
    # per-asset URL shape (/v/{asset_id}) is reserved for rung 0.3 when the
    # SPA grows real routing.
    manifest_reference = public_manifest_reference(asset.asset_id, asset.manifest_url)
    portal_manifest = manifest_reference
    if manifest_reference.startswith("/"):
        portal_manifest = urljoin(str(request.base_url), manifest_reference.lstrip("/"))
    portal_url = f"{_portal_base(request)}/?manifest={quote(portal_manifest, safe=':/?&=')}"

    embed_html = build_embed_html(
        portal_url=portal_url,
        title=asset.title,
    )

    return AssetEmbedResponse(
        asset_id=asset.asset_id,
        title=asset.title,
        manifest_url=manifest_reference,
        poster_url=asset.poster_url,
        portal_url=portal_url,  # type: ignore[arg-type]
        embed_html=embed_html,
    )
