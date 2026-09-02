# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""FastAPI router for the operator publish dashboard."""

from __future__ import annotations

import logging
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from civiccast.activitypub.remote import ActivityPubDeliveryClient, ActivityPubRemoteError
from civiccast.activitypub.service import deliver_publish_activity, record_publish_activity
from civiccast.activitypub.store import ActivityPubStore
from civiccast.auth.roles import require_any_role
from civiccast.captions.vod_job import OfflineCaptionJobStore, enqueue_offline_caption_job
from civiccast.live.recording_paths import local_recording_path
from civiccast.live.router import get_live_finalization_worker
from civiccast.platform.broker import BrokerClient, get_broker_client
from civiccast.platform.providers import ProviderRegistry, default_registry
from civiccast.platform.stores import resolve_app_store
from civiccast.publish.models import (
    PublishApprovalRequest,
    PublishAssetStatus,
    PublishDashboardResponse,
    PublishPreflightResponse,
    PublishRetryRequest,
    PublishRunRecord,
)
from civiccast.publish.service import (
    PublishConfigurationError,
    approve_publish,
    build_publish_approved_event,
    build_publish_asset_status,
    build_publish_dashboard,
    build_publish_preflight,
    retry_publish_surface,
)
from civiccast.publish.store import PublishStore
from civiccast.publish.targets import ChannelAssociationLookup
from civiccast.schedule.models import StaffAssetRow
from civiccast.schedule.paths import resolve_vod_package_dir
from civiccast.schedule.router import get_postgres_store
from civiccast.subscribe.outcome_store import NotificationDeliveryStore
from civiccast.subscribe.router import (
    get_notification_delivery_store,
    get_publication_target_lookup,
    get_subscribe_store,
)
from civiccast.subscribe.store import SubscribeStore

_LOG = logging.getLogger(__name__)

staff_router = APIRouter(prefix="/api/staff/publish", tags=["staff", "publish"])


def _resolve_local_recording(finalization_worker: Any, asset_id: str) -> Path | None:
    """Resolve the asset's local recording file for full-media publishing.

    Live recordings share their asset_id with the live session, so the
    finalization job's ``recording_uri`` names the local file (Beta B5).
    Returns None for non-live assets, unwired workers (ephemeral mode), or a
    missing file — callers fall back to the deterministic verification
    payload.
    """

    if finalization_worker is None:
        return None
    try:
        job_status = finalization_worker.get_status(asset_id)
    except Exception:
        return None
    if job_status is None or not job_status.recording_uri:
        return None
    path = local_recording_path(job_status.recording_uri)
    if path is None or not path.exists():
        return None
    return path


_DB_NOT_READY_DESCRIPTION = "Durable storage not ready -- run Setup storage or set DATABASE_URL"
_DB_NOT_READY_DETAIL = (
    "Durable storage is not ready. Open Setup and choose Prepare storage, "
    "or set DATABASE_URL for a technical deployment."
)


def _apply_portal_visibility(
    *,
    asset_store: Any,
    publish_store: PublishStore,
    asset_id: str,
    staff_asset: StaffAssetRow,
    record: PublishRunRecord,
) -> tuple[StaffAssetRow, PublishRunRecord]:
    """Make Portal visibility and its recorded surface outcome agree.

    Provider surfaces may succeed independently, but Portal is not reported as
    successful unless the canonical asset row actually becomes public. A
    failed visibility write is persisted as a retryable Portal failure while
    the resident asset remains private.
    """
    portal = next((surface for surface in record.surfaces if surface.id == "portal"), None)
    if portal is None or portal.state != "succeeded":
        return staff_asset, record
    try:
        published = cast(
            StaffAssetRow,
            asset_store.mark_published(asset_id, published_at=datetime.now(UTC)),
        )
    except Exception:
        failed_portal = portal.model_copy(
            update={
                "state": "failed",
                "health": "warning",
                "message": "Portal publication could not make the recording public.",
                "next_step": (
                    "The recording remains private. Check durable storage, then retry "
                    "the Portal surface."
                ),
            }
        )
        corrected = record.model_copy(
            update={
                "surfaces": [
                    failed_portal if surface.id == "portal" else surface
                    for surface in record.surfaces
                ]
            }
        )
        return staff_asset, publish_store.upsert_run(corrected)
    return published, record


def get_publish_store(request: Request) -> PublishStore:
    return cast(PublishStore, resolve_app_store(request, "publish_store", surface="Publish store"))


def get_provider_registry(request: Request) -> ProviderRegistry:
    """Resolve the app's single provider registry (WP-03 plan items 1 and 8).

    Preflight and approval both depend on this so they read the exact same
    registry within one process -- they cannot disagree about whether a
    surface's real-provider configuration is valid. Falls back to
    ``default_registry()`` for an app instance that never wired
    ``app.state.provider_registry`` (this never fails: registering the
    shipped mock/real factories is itself side-effect-free).
    """

    return cast(
        ProviderRegistry,
        getattr(request.app.state, "provider_registry", None) or default_registry(),
    )


def get_caption_job_store(request: Request) -> OfflineCaptionJobStore | None:
    """Resolve the offline caption job queue, or ``None`` when unavailable."""

    return cast(
        "OfflineCaptionJobStore | None",
        resolve_app_store(request, "caption_job_store", surface="Offline caption job store"),
    )


def _queue_offline_captions(
    caption_job_store: OfflineCaptionJobStore | None,
    staff_asset: StaffAssetRow,
) -> None:
    """Queue captioning for a recording that just became public (K3).

    Publishing is the trigger because "captioned published files" is the
    legal obligation the offline caption path exists to meet — the moment
    a recording becomes a public record is the moment its captions become
    owed. The job transcribes with the station's staged caption model and
    files every cue in the operator review queue; nothing reaches the
    resident-facing package until an operator has decided on it.

    Deliberately best-effort: captioning is asynchronous work that trails
    publication, so a queueing failure is logged and the publish response
    still reflects what actually published. The operator sees the gap on
    the caption review queue, and re-approving the asset re-queues it.
    """

    if caption_job_store is None or staff_asset.published_at is None:
        return
    source_path = Path(staff_asset.file_path) if staff_asset.file_path else None
    # KNOWN FOLLOW-UP (out of CivicCast One v1 scope, owner-approved to
    # defer -- see "Known follow-ups" in docs/ops/background-workers.md):
    # resolve_vod_package_dir only knows the UPLOAD packaging convention
    # (.civiccast-packages/<asset_id> under the upload root). A
    # LIVE-finalized recording packages to a different, unrelated path
    # instead (<recording_path.parent>/<live_session_id>-hls/, recorded on
    # LiveFinalizationJob.local_package_manifest_path -- see
    # civiccast.live.finalization_worker.LiveFinalizationWorker
    # ._package_once and civiccast.stream.media_router
    # ._package_dir_for_asset, which already knows to prefer it). One v1
    # only reaches this function from an uploaded-and-published asset (LIVE
    # broadcast is deferred keystone K4), so that mismatch is unreachable
    # today: transcription (stage one) doesn't need the package directory
    # and would still succeed, but attach (stage two) would fail every
    # retry against a package directory that was never written, and the
    # job would land in `failed` with the recording permanently
    # uncaptioned. Fix when K4 lands: mirror media_router's fallback here.
    package_dir = resolve_vod_package_dir(staff_asset.asset_id)
    if source_path is None or package_dir is None:
        _LOG.info(
            "Skipped offline captioning for %s: no local source file or upload storage.",
            staff_asset.asset_id,
        )
        return
    try:
        enqueue_offline_caption_job(
            caption_job_store,
            asset_id=staff_asset.asset_id,
            source_path=source_path,
            package_dir=package_dir,
        )
    except Exception:
        _LOG.exception(
            "Published %s but could not queue its offline captions.", staff_asset.asset_id
        )


def get_activitypub_store(request: Request) -> ActivityPubStore:
    return cast(
        ActivityPubStore,
        resolve_app_store(request, "activitypub_store", surface="ActivityPub store"),
    )


def get_activitypub_delivery_client(request: Request) -> ActivityPubDeliveryClient:
    return cast(ActivityPubDeliveryClient, request.app.state.activitypub_delivery_client)


def _require_asset_store(postgres_store: Any) -> Any:
    if postgres_store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_DB_NOT_READY_DETAIL,
        )
    return postgres_store


@staff_router.get(
    "/assets",
    response_model=PublishDashboardResponse,
    summary="List publish-dashboard status for every asset",
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def list_publish_assets(
    postgres_store: Any = Depends(get_postgres_store),
    publish_store: PublishStore = Depends(get_publish_store),
) -> PublishDashboardResponse:
    """Return per-asset three-tier publish status for the operator dashboard."""
    asset_store = _require_asset_store(postgres_store)
    assets = cast(list[StaffAssetRow], asset_store.list_all())
    return build_publish_dashboard(assets, publish_store)


@staff_router.get(
    "/assets/{asset_id}",
    response_model=PublishAssetStatus,
    summary="Get publish-dashboard status for one asset",
    responses={
        404: {"description": "Asset not found"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def get_publish_asset(
    asset_id: str,
    postgres_store: Any = Depends(get_postgres_store),
    publish_store: PublishStore = Depends(get_publish_store),
) -> PublishAssetStatus:
    """Return three-tier publish status for a single asset."""
    asset_store = _require_asset_store(postgres_store)
    asset = asset_store.get_staff_row(asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset not found: {asset_id}",
        )
    return build_publish_asset_status(
        cast(StaffAssetRow, asset),
        publish_store.get_run(asset_id),
    )


@staff_router.get(
    "/assets/{asset_id}/preflight",
    response_model=PublishPreflightResponse,
    summary="Check v0.7 publish readiness before operator approval",
    responses={
        404: {"description": "Asset not found"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def get_publish_preflight(
    asset_id: str,
    postgres_store: Any = Depends(get_postgres_store),
    provider_registry: ProviderRegistry = Depends(get_provider_registry),
    subscribe_store: SubscribeStore = Depends(get_subscribe_store),
    target_lookup: ChannelAssociationLookup | None = Depends(get_publication_target_lookup),
) -> PublishPreflightResponse:
    """Return portal, Internet Archive, NAS, YouTube, and subscriber readiness.

    Reads through the real provider registry (WP-03): every check here is the
    same non-secret, side-effect-free readiness ``approve_publish`` uses, so
    this response and what approval would actually do cannot disagree.
    """
    asset_store = _require_asset_store(postgres_store)
    asset = asset_store.get_staff_row(asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset not found: {asset_id}",
        )
    return build_publish_preflight(
        cast(StaffAssetRow, asset),
        registry=provider_registry,
        subscribe_store=subscribe_store,
        target_lookup=target_lookup,
    )


@staff_router.post(
    "/assets/{asset_id}/approve",
    response_model=PublishAssetStatus,
    summary="Approve and run the v0.7 three-tier publish workflow",
    dependencies=[Depends(require_any_role("publish_operator"))],
    responses={
        404: {"description": "Asset not found"},
        409: {"description": "Publish preflight blocked"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def approve_publish_asset(
    asset_id: str,
    request: PublishApprovalRequest,
    http_request: Request,
    postgres_store: Any = Depends(get_postgres_store),
    publish_store: PublishStore = Depends(get_publish_store),
    activitypub_store: ActivityPubStore = Depends(get_activitypub_store),
    activitypub_delivery_client: ActivityPubDeliveryClient = Depends(
        get_activitypub_delivery_client
    ),
    broker_client: BrokerClient = Depends(get_broker_client),
    finalization_worker: Any = Depends(get_live_finalization_worker),
    caption_job_store: OfflineCaptionJobStore | None = Depends(get_caption_job_store),
    provider_registry: ProviderRegistry = Depends(get_provider_registry),
    subscribe_store: SubscribeStore = Depends(get_subscribe_store),
    delivery_store: NotificationDeliveryStore | None = Depends(get_notification_delivery_store),
    target_lookup: ChannelAssociationLookup | None = Depends(get_publication_target_lookup),
) -> PublishAssetStatus:
    """Approve per-surface publication through the configured providers."""
    asset_store = _require_asset_store(postgres_store)
    asset = asset_store.get_staff_row(asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset not found: {asset_id}",
        )
    staff_asset = cast(StaffAssetRow, asset)
    if not staff_asset.manifest_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Publish preflight blocked: this asset has no manifest_url. "
                "Run the packager or fix ingest before approving publish."
            ),
        )
    try:
        record = approve_publish(
            asset=staff_asset,
            request=request,
            store=publish_store,
            media_path=_resolve_local_recording(finalization_worker, asset_id),
            registry=provider_registry,
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            target_lookup=target_lookup,
        )
    except PublishConfigurationError as exc:
        # WP-03: a selected surface's real-provider config is missing/invalid
        # -- a controlled 409 before any side effect, never an uncaught 500.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    staff_asset, record = _apply_portal_visibility(
        asset_store=asset_store,
        publish_store=publish_store,
        asset_id=asset_id,
        staff_asset=staff_asset,
        record=record,
    )
    _queue_offline_captions(caption_job_store, staff_asset)
    status_response = build_publish_asset_status(staff_asset, record)
    broker_client.publish(build_publish_approved_event(status_response))
    activitypub_config = http_request.app.state.activitypub_config
    if activitypub_config.federation_mode == "disabled":
        return status_response
    activity = record_publish_activity(
        base_url=activitypub_config.base_url or str(http_request.base_url).rstrip("/"),
        status=status_response,
        store=activitypub_store,
    )
    if activity is not None:
        with suppress(ActivityPubRemoteError):
            deliver_publish_activity(
                record=activity,
                store=activitypub_store,
                delivery_client=activitypub_delivery_client,
            )
    return status_response


@staff_router.post(
    "/assets/{asset_id}/surfaces/{surface_id}/retry",
    response_model=PublishAssetStatus,
    summary="Retry one v0.7 publish surface",
    dependencies=[Depends(require_any_role("publish_operator"))],
    responses={
        404: {"description": "Asset or surface not found"},
        409: {"description": "Publish preflight blocked"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def retry_publish_asset_surface(
    asset_id: str,
    surface_id: str,
    request: PublishRetryRequest,
    postgres_store: Any = Depends(get_postgres_store),
    publish_store: PublishStore = Depends(get_publish_store),
    caption_job_store: OfflineCaptionJobStore | None = Depends(get_caption_job_store),
    provider_registry: ProviderRegistry = Depends(get_provider_registry),
    subscribe_store: SubscribeStore = Depends(get_subscribe_store),
    delivery_store: NotificationDeliveryStore | None = Depends(get_notification_delivery_store),
    target_lookup: ChannelAssociationLookup | None = Depends(get_publication_target_lookup),
) -> PublishAssetStatus:
    """Retry a single surface without changing the rest of the publish run."""
    asset_store = _require_asset_store(postgres_store)
    asset = asset_store.get_staff_row(asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Asset not found: {asset_id}",
        )
    staff_asset = cast(StaffAssetRow, asset)
    if not staff_asset.manifest_url:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Publish retry blocked: this asset has no manifest_url. "
                "Run the packager or fix ingest before retrying publish."
            ),
        )
    try:
        record = retry_publish_surface(
            asset=staff_asset,
            surface_id=surface_id,
            request=request,
            store=publish_store,
            registry=provider_registry,
            subscribe_store=subscribe_store,
            delivery_store=delivery_store,
            target_lookup=target_lookup,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PublishConfigurationError as exc:
        # WP-03: the retried surface's real-provider config is missing/
        # invalid -- a controlled 409, same as the approve route, instead of
        # silently "retrying" a surface that was never going to succeed.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    staff_asset, record = _apply_portal_visibility(
        asset_store=asset_store,
        publish_store=publish_store,
        asset_id=asset_id,
        staff_asset=staff_asset,
        record=record,
    )
    # Only a Portal retry can be what makes the recording public when the
    # first approval failed, so only a Portal retry starts the caption
    # obligation. Any other surface (YouTube, Internet Archive, ...) retries
    # independently of captioning -- queueing here unconditionally would
    # re-transcribe an already-captioned asset every time an operator
    # retries an unrelated surface (audit finding 5).
    #
    # ``surface_id == "portal"`` alone is not enough: it only says which
    # surface was retried, not whether the retry actually made the asset
    # public. ``_apply_portal_visibility``'s docstring guarantees the
    # invariant this refinement leans on -- "Portal is not reported as
    # successful unless the canonical asset row actually becomes public" --
    # so a portal surface that is still not "succeeded" in the *returned*
    # record after that call (e.g. the retry's own ``asset_store
    # .mark_published`` write failed, same as the first-approval failure
    # path) means this retry did not publish anything, and must not start a
    # fresh transcription pass over a still-private recording.
    portal_became_public = any(
        surface.id == "portal" and surface.state == "succeeded" for surface in record.surfaces
    )
    if surface_id == "portal" and portal_became_public:
        _queue_offline_captions(caption_job_store, staff_asset)
    return build_publish_asset_status(staff_asset, record)
