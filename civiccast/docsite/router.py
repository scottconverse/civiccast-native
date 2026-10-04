# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI router for the in-product operator manual.

Public (no staff bearer token) on purpose: this is the same read-only
documentation content that already ships publicly in docs/USER-MANUAL.md and
its rendered PDF/DOCX, and an operator who is stuck mid-setup or mid-error
(including on the un-authenticated First Setup screen) is exactly who needs
to reach it without first needing to already be signed in.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from civiccast.docsite.models import ManualDocument
from civiccast.docsite.service import ManualUnavailableError, load_manual, load_manual_asset

router = APIRouter(prefix="/api/public/manual", tags=["manual"])


@router.get("/assets/{name}", include_in_schema=False)
def get_manual_asset(name: str) -> Response:
    try:
        data, media_type = load_manual_asset(name)
    except OSError as exc:
        raise HTTPException(status_code=404, detail="Manual image unavailable") from exc
    return Response(
        data,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )


@router.get("", response_model=ManualDocument, summary="Get the in-product operator manual")
def get_manual() -> ManualDocument:
    try:
        return load_manual()
    except ManualUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
