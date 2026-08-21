# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staff API for S7 media lifecycle & readiness.

Endpoint surface (spec §4 + §8 test plan):

* ``GET  /api/staff/assets/readiness-dashboard``       -- operator dashboard
* ``GET  /api/staff/assets/{asset_id}/readiness``      -- one asset's badge
* ``PUT  /api/staff/assets/{asset_id}/replace-source``  -- ReplaceMediaWorkflow
* ``PUT  /api/staff/assets/{asset_id}/legal-hold``      -- CLAUDE.md §4.6 gate
* ``GET/POST/PUT/DELETE /api/staff/media-lifecycle/watch-folder-configs``
* ``GET/POST/PUT/DELETE /api/staff/media-lifecycle/retention-policies``
* ``POST /api/staff/media-lifecycle/retention-policies/apply``
* ``GET  /api/staff/media-lifecycle/storage-budget``
* ``GET  /api/staff/media-lifecycle/missing-media``
* ``GET  /api/staff/media-lifecycle/audit-log``

Route-ordering note (mirrors the existing ``/assets/broken`` /
``/assets/duplicates`` comment in ``civiccast.schedule.router``):
``/assets/readiness-dashboard`` is a literal path competing with
``civiccast.schedule.router``'s ``GET /assets/{asset_id}``. Starlette
matches app-wide in registration order, so ``civiccast.app`` MUST
``include_router(media_lifecycle_staff_router)`` before
``include_router(schedule_staff_router)`` -- otherwise a request for
``/assets/readiness-dashboard`` would be swallowed by
``get_staff_asset(asset_id="readiness-dashboard")`` and 404.
``/{asset_id}/readiness``, ``/{asset_id}/replace-source``, and
``/{asset_id}/legal-hold`` are two path segments past ``/assets/``, so they
never collide with either the one-segment ``{asset_id}`` route or each
other, regardless of registration order.

DI: :func:`get_media_lifecycle_store` returns ``None`` until the app factory
wires a real :class:`~civiccast.schedule.media_lifecycle_store.MediaLifecycleStore`
(handlers translate ``None`` to 503), mirroring
``civiccast.schedule.autoschedule_router.get_autoschedule_service``.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any, cast

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from civiccast.auth.roles import require_any_role
from civiccast.schedule.ingest import (
    FfprobeNotFoundError,
    UnsupportedFormatError,
    hash_file,
    run_ffprobe,
    validate_ingest,
)
from civiccast.schedule.media_lifecycle_models import (
    AssetReadinessResponse,
    AssetRetentionPolicyInput,
    AssetRetentionPolicyResponse,
    LegalHoldInput,
    LifecycleAuditEntryResponse,
    MissingMediaAlertRow,
    ReadinessDashboardResponse,
    StorageBudgetResponse,
    WatchFolderConfigInput,
    WatchFolderConfigResponse,
)
from civiccast.schedule.media_lifecycle_store import (
    AssetNotFoundError,
    AssetRetentionPolicyNotFoundError,
    MediaLifecycleStore,
    WatchFolderConfigNotFoundError,
)

_WRITE_ROLES = ("publish_operator", "setup_admin")
_READ_ROLES = ("meeting_operator", "publish_operator", "support_admin")

_DB_NOT_READY_DETAIL = (
    "Durable storage is not ready. Open Setup and choose Prepare storage, "
    "or set DATABASE_URL for a technical deployment."
)


def get_media_lifecycle_store() -> Any:
    """FastAPI dependency for the media lifecycle store; see module docstring."""

    return None


def _require_store(store: Any) -> MediaLifecycleStore:
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_DB_NOT_READY_DETAIL
        )
    return cast(MediaLifecycleStore, store)


staff_router = APIRouter(prefix="/api/staff", tags=["media-lifecycle"])


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


@staff_router.get(
    "/assets/readiness-dashboard",
    response_model=ReadinessDashboardResponse,
    summary="Operator readiness dashboard across every asset",
    dependencies=[Depends(require_any_role(*_READ_ROLES))],
    responses={503: {"description": _DB_NOT_READY_DETAIL}},
)
def get_readiness_dashboard(
    store: Any = Depends(get_media_lifecycle_store),
) -> ReadinessDashboardResponse:
    return _require_store(store).dashboard()


@staff_router.get(
    "/assets/{asset_id}/readiness",
    response_model=AssetReadinessResponse,
    summary="One asset's readiness badge state",
    dependencies=[Depends(require_any_role(*_READ_ROLES))],
    responses={404: {"description": "Asset not found"}, 503: {"description": _DB_NOT_READY_DETAIL}},
)
def get_asset_readiness(
    asset_id: str, store: Any = Depends(get_media_lifecycle_store)
) -> AssetReadinessResponse:
    resolved = _require_store(store)
    result = resolved.get_readiness(asset_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset not found: {asset_id}")
    return result


@staff_router.put(
    "/assets/{asset_id}/legal-hold",
    response_model=AssetReadinessResponse,
    summary="Set or clear a legal hold (blocks retention expiry per CLAUDE.md §4.6)",
    dependencies=[Depends(require_any_role("records_clerk", "support_admin"))],
    responses={404: {"description": "Asset not found"}, 503: {"description": _DB_NOT_READY_DETAIL}},
)
def set_legal_hold(
    asset_id: str, payload: LegalHoldInput, store: Any = Depends(get_media_lifecycle_store)
) -> AssetReadinessResponse:
    resolved = _require_store(store)
    try:
        resolved.set_legal_hold(asset_id, hold=payload.legal_hold, reason=payload.reason)
    except AssetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset not found: {asset_id}"
        ) from exc
    result = resolved.get_readiness(asset_id)
    assert result is not None  # just proven to exist above
    return result


# ---------------------------------------------------------------------------
# Replace-source (spec §2 net-new "ReplaceMediaWorkflow")
# ---------------------------------------------------------------------------


@staff_router.put(
    "/assets/{asset_id}/replace-source",
    response_model=AssetReadinessResponse,
    summary="Swap out an asset's backing file; the old file is archived, not deleted",
    dependencies=[Depends(require_any_role(*_WRITE_ROLES))],
    responses={
        404: {"description": "Asset not found"},
        422: {"description": "Unsupported file format"},
        503: {"description": _DB_NOT_READY_DETAIL},
    },
)
async def replace_asset_source(
    asset_id: str,
    file: UploadFile = File(..., description="Replacement video file."),
    store: Any = Depends(get_media_lifecycle_store),
) -> AssetReadinessResponse:
    """Corrupt or wrong source file? Replace it -- old file is archived, not deleted.

    Unlike ``POST /api/staff/assets/{asset_id}/relink`` (which requires the
    replacement to match the original's duration/codec within a tolerance --
    "same recording, re-encoded"), this endpoint accepts ANY validated file:
    the spec's own scenario is "recording is corrupt, need a different file
    entirely." A fresh ffprobe validation still runs; only the tolerance
    check is skipped.
    """

    resolved = _require_store(store)
    upload_dir_str = os.environ.get("CIVICCAST_UPLOAD_DIR")
    if not upload_dir_str:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload directory not configured. Set CIVICCAST_UPLOAD_DIR.",
        )
    existing = resolved.get_readiness(asset_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Asset not found: {asset_id}")

    upload_dir = Path(upload_dir_str).resolve()
    asset_dir = (upload_dir / asset_id).resolve()
    incoming_dir = (upload_dir / ".incoming").resolve()
    if not asset_dir.is_relative_to(upload_dir) or not incoming_dir.is_relative_to(upload_dir):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid asset_id."
        )

    raw_name = file.filename or "replacement"
    base_name = PurePosixPath(raw_name.replace("\\", "/")).name or "replacement"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", base_name) or "replacement"
    if safe_name in (".", ".."):
        safe_name = "replacement"
    dest_path = (asset_dir / safe_name).resolve()
    if not dest_path.is_relative_to(asset_dir):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid filename.")

    await asyncio.to_thread(incoming_dir.mkdir, parents=True, exist_ok=True)
    temp_path = (incoming_dir / f"{asset_id}-{uuid.uuid4().hex}.replace").resolve()

    max_bytes = int(os.environ.get("CIVICCAST_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024 * 1024)))
    written = 0
    try:
        with temp_path.open("wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    f.close()
                    await asyncio.to_thread(temp_path.unlink, missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"Upload exceeds maximum size of {max_bytes} bytes.",
                    )
                await asyncio.to_thread(f.write, chunk)
    finally:
        await file.close()

    success = False
    try:
        try:
            ffprobe_result = await asyncio.to_thread(run_ffprobe, temp_path)
        except FfprobeNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        try:
            validate_ingest(ffprobe_result)
        except UnsupportedFormatError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.reason
            ) from exc

        # Archive the old file (rename aside, never delete) before the new
        # file takes its place -- spec DONE criteria #8: "old file archived,
        # new file validated." Any existing file already in the asset's
        # directory (whatever its name) is the prior source; the new upload
        # has already been staged at ``temp_path``, not yet moved into
        # ``asset_dir``, so this glob only ever sees the OLD file(s).
        archived_old_path: str | None = None
        await asyncio.to_thread(asset_dir.mkdir, parents=True, exist_ok=True)
        for candidate in asset_dir.glob("*"):
            if candidate.is_file() and candidate != dest_path and not candidate.name.startswith(
                f"{asset_id}.replaced-"
            ):
                archived_name = f"{asset_id}.replaced-{uuid.uuid4().hex[:8]}-{candidate.name}"
                archived_path = asset_dir / archived_name
                await asyncio.to_thread(os.replace, candidate, archived_path)
                archived_old_path = str(archived_path)

        await asyncio.to_thread(os.replace, temp_path, dest_path)

        try:
            content_hash = await asyncio.to_thread(hash_file, dest_path)
        except OSError:
            content_hash = None

        await asyncio.to_thread(
            resolved.apply_replace_source,
            asset_id,
            new_file_path=str(dest_path),
            file_size_bytes=dest_path.stat().st_size,
            codec_video=ffprobe_result.codec_video,
            codec_audio=ffprobe_result.codec_audio,
            width_px=ffprobe_result.width_px,
            height_px=ffprobe_result.height_px,
            bitrate_bps=ffprobe_result.bitrate_bps,
            format_name=ffprobe_result.format_name,
            duration_seconds=ffprobe_result.duration_seconds,
            content_hash=content_hash,
            thumbnail_path=None,
            archived_old_path=archived_old_path,
        )
        success = True
    finally:
        if not success:
            await asyncio.to_thread(temp_path.unlink, missing_ok=True)

    result = resolved.get_readiness(asset_id)
    assert result is not None
    return result


# ---------------------------------------------------------------------------
# Watch-folder configs
# ---------------------------------------------------------------------------

watch_folder_router = APIRouter(prefix="/media-lifecycle", tags=["media-lifecycle"])


@watch_folder_router.get(
    "/watch-folder-configs",
    response_model=list[WatchFolderConfigResponse],
    summary="List configured auto-ingest watch folders",
    dependencies=[Depends(require_any_role(*_READ_ROLES))],
)
def list_watch_folder_configs(
    store: Any = Depends(get_media_lifecycle_store),
) -> list[WatchFolderConfigResponse]:
    return _require_store(store).list_watch_folder_configs()


@watch_folder_router.post(
    "/watch-folder-configs",
    response_model=WatchFolderConfigResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a watch folder (local disk, USB, or NAS/SMB path)",
    dependencies=[Depends(require_any_role(*_WRITE_ROLES))],
)
def create_watch_folder_config(
    payload: WatchFolderConfigInput, store: Any = Depends(get_media_lifecycle_store)
) -> WatchFolderConfigResponse:
    return _require_store(store).create_watch_folder_config(payload)


@watch_folder_router.put(
    "/watch-folder-configs/{config_id}",
    response_model=WatchFolderConfigResponse,
    summary="Update a watch folder config",
    dependencies=[Depends(require_any_role(*_WRITE_ROLES))],
    responses={404: {"description": "Watch folder config not found"}},
)
def update_watch_folder_config(
    config_id: str, payload: WatchFolderConfigInput, store: Any = Depends(get_media_lifecycle_store)
) -> WatchFolderConfigResponse:
    try:
        return _require_store(store).update_watch_folder_config(config_id, payload)
    except WatchFolderConfigNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Watch folder config not found: {config_id}"
        ) from exc


@watch_folder_router.delete(
    "/watch-folder-configs/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a watch folder config",
    dependencies=[Depends(require_any_role(*_WRITE_ROLES))],
    responses={404: {"description": "Watch folder config not found"}},
)
def delete_watch_folder_config(
    config_id: str, store: Any = Depends(get_media_lifecycle_store)
) -> None:
    try:
        _require_store(store).delete_watch_folder_config(config_id)
    except WatchFolderConfigNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Watch folder config not found: {config_id}"
        ) from exc


# ---------------------------------------------------------------------------
# Retention policy automation
# ---------------------------------------------------------------------------


@watch_folder_router.get(
    "/retention-policies",
    response_model=list[AssetRetentionPolicyResponse],
    summary="List retention automation rules",
    dependencies=[Depends(require_any_role(*_READ_ROLES, "records_clerk"))],
)
def list_retention_policies(
    store: Any = Depends(get_media_lifecycle_store),
) -> list[AssetRetentionPolicyResponse]:
    return _require_store(store).list_retention_policies()


@watch_folder_router.post(
    "/retention-policies",
    response_model=AssetRetentionPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a retention automation rule",
    dependencies=[Depends(require_any_role("records_clerk", "setup_admin"))],
)
def create_retention_policy(
    payload: AssetRetentionPolicyInput, store: Any = Depends(get_media_lifecycle_store)
) -> AssetRetentionPolicyResponse:
    return _require_store(store).create_retention_policy(payload)


@watch_folder_router.put(
    "/retention-policies/{policy_id}",
    response_model=AssetRetentionPolicyResponse,
    summary="Update a retention automation rule",
    dependencies=[Depends(require_any_role("records_clerk", "setup_admin"))],
    responses={404: {"description": "Retention policy not found"}},
)
def update_retention_policy(
    policy_id: str, payload: AssetRetentionPolicyInput, store: Any = Depends(get_media_lifecycle_store)
) -> AssetRetentionPolicyResponse:
    try:
        return _require_store(store).update_retention_policy(policy_id, payload)
    except AssetRetentionPolicyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Retention policy not found: {policy_id}"
        ) from exc


@watch_folder_router.delete(
    "/retention-policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a retention automation rule",
    dependencies=[Depends(require_any_role("records_clerk", "setup_admin"))],
    responses={404: {"description": "Retention policy not found"}},
)
def delete_retention_policy(policy_id: str, store: Any = Depends(get_media_lifecycle_store)) -> None:
    try:
        _require_store(store).delete_retention_policy(policy_id)
    except AssetRetentionPolicyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Retention policy not found: {policy_id}"
        ) from exc


@watch_folder_router.post(
    "/retention-policies/apply",
    summary="Apply enabled retention rules to every asset now",
    dependencies=[Depends(require_any_role("records_clerk", "setup_admin"))],
)
def apply_retention_policies(store: Any = Depends(get_media_lifecycle_store)) -> dict[str, int]:
    return {"assets_changed": _require_store(store).apply_retention_policies()}


# ---------------------------------------------------------------------------
# Storage budget
# ---------------------------------------------------------------------------


@watch_folder_router.get(
    "/storage-budget",
    response_model=StorageBudgetResponse,
    summary="Storage used vs the configured budget, by retention tier",
    dependencies=[Depends(require_any_role(*_READ_ROLES))],
)
def get_storage_budget(store: Any = Depends(get_media_lifecycle_store)) -> StorageBudgetResponse:
    raw_budget = os.environ.get("CIVICCAST_MEDIA_STORAGE_BUDGET_BYTES", "").strip()
    budget_bytes = int(raw_budget) if raw_budget else None
    return _require_store(store).storage_budget(budget_bytes=budget_bytes)


# ---------------------------------------------------------------------------
# Missing media
# ---------------------------------------------------------------------------


def get_missing_media_reader() -> Any:
    """DI seam for the live missing-media join; wired to the lifecycle worker."""

    return None


@watch_folder_router.get(
    "/missing-media",
    response_model=list[MissingMediaAlertRow],
    summary="Scheduled items whose backing asset is not ready within the horizon",
    dependencies=[Depends(require_any_role(*_READ_ROLES))],
)
def list_missing_media(reader: Any = Depends(get_missing_media_reader)) -> list[MissingMediaAlertRow]:
    if reader is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=_DB_NOT_READY_DETAIL
        )
    return [MissingMediaAlertRow(**row) for row in reader.list_missing_media()]


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


@watch_folder_router.get(
    "/audit-log",
    response_model=list[LifecycleAuditEntryResponse],
    summary="Media lifecycle worker audit trail (dry-run entries included)",
    dependencies=[Depends(require_any_role(*_READ_ROLES))],
)
def list_audit_log(
    asset_id: str | None = None,
    limit: int = 100,
    store: Any = Depends(get_media_lifecycle_store),
) -> list[LifecycleAuditEntryResponse]:
    return _require_store(store).list_audit_log(asset_id=asset_id, limit=limit)


# ``staff_router`` is the single router civiccast.app registers. It carries
# the ``/assets/...`` sub-resource routes directly and folds in every
# ``/media-lifecycle/...`` route from ``watch_folder_router`` above (kept as
# a separate APIRouter above purely for this file's own readability).
staff_router.include_router(watch_folder_router)
