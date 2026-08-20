# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Publish workflow orchestration and dashboard state derivation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from civiccast.cable.package import (
    CABLE_PACKAGE_SURFACE_ID,
    CablePackageError,
    build_cable_file_package_for_asset,
)
from civiccast.platform.broker import BrokerEvent
from civiccast.platform.providers import (
    PROVIDER_KIND_INTERNET_ARCHIVE,
    PROVIDER_KIND_LOCAL_NAS,
    PROVIDER_KIND_YOUTUBE,
    ProviderRegistry,
    default_registry,
)
from civiccast.podcast.models import PodcastEpisodeCreate
from civiccast.podcast.service import create_podcast_episode
from civiccast.publish.credentials import CredentialProvider, DeterministicCredentialProvider
from civiccast.publish.models import (
    PublishApprovalRequest,
    PublishAssetStatus,
    PublishAuditEvent,
    PublishDashboardResponse,
    PublishDashboardStateValue,
    PublishDashboardSummary,
    PublishPreflightCheck,
    PublishPreflightResponse,
    PublishRetryRequest,
    PublishRunRecord,
    PublishSurfaceKindValue,
    PublishSurfaceStatus,
)
from civiccast.publish.store import PublishStore
from civiccast.schedule.models import StaffAssetRow
from civiccast.subscribe.models import NotificationPayload

PUBLIC_RECORD_POLICIES = {"meeting", "permanent"}


def _is_public_record(asset: StaffAssetRow) -> bool:
    return asset.retention_policy in PUBLIC_RECORD_POLICIES


def build_publish_approved_event(status: PublishAssetStatus) -> BrokerEvent:
    """Build the documented event emitted after a successful publish approval."""

    return BrokerEvent(
        subject="publish.asset.approved",
        payload={
            "asset_id": status.asset_id,
            "status": status.dashboard_state,
            "surfaces": [
                {
                    "id": surface.id,
                    "state": surface.state,
                    "health": surface.health,
                    "required": surface.required,
                }
                for surface in status.surfaces
            ],
        },
    )


def _event(
    *,
    asset_id: str,
    surface: PublishSurfaceStatus,
    action: Literal["approved", "started", "succeeded", "failed", "retried", "overridden"],
    operator_id: str,
    message: str,
    at: datetime,
) -> PublishAuditEvent:
    return PublishAuditEvent(
        event_id=f"{asset_id}:{surface.id}:{action}:{int(at.timestamp())}",
        asset_id=asset_id,
        surface_id=surface.id,
        action=action,
        operator_id=operator_id,
        occurred_at=at,
        message=message,
        url=surface.url,
        path=surface.path,
        verification_hash=surface.verification_hash,
    )


def _blocked_portal_surface(asset: StaffAssetRow) -> PublishSurfaceStatus:
    if asset.manifest_url:
        return PublishSurfaceStatus(
            id="portal",
            label="Portal",
            kind="canonical",
            state="pending",
            required=True,
            approval="pending",
            url=asset.manifest_url,
            health="warning",
            message="Portal publish is waiting for operator approval.",
            next_step="Approve publish to make the canonical portal URL public.",
        )
    return PublishSurfaceStatus(
        id="portal",
        label="Portal",
        kind="canonical",
        state="blocked",
        required=True,
        approval="pending",
        health="error",
        message="The portal cannot publish this asset until an HLS manifest exists.",
        next_step="Run the packager or fix ingest so manifest_url exists, then retry approval.",
    )


def _pending_surface(
    *,
    surface_id: str,
    label: str,
    kind: PublishSurfaceKindValue,
    required: bool,
    message: str,
    next_step: str,
) -> PublishSurfaceStatus:
    return PublishSurfaceStatus(
        id=surface_id,
        label=label,
        kind=kind,
        state="pending",
        required=required,
        approval="pending",
        health="warning" if required else "unknown",
        message=message,
        next_step=next_step,
    )


def build_initial_surfaces(asset: StaffAssetRow) -> list[PublishSurfaceStatus]:
    """Build per-surface approval rows before a publish run exists."""
    public_record = _is_public_record(asset)
    return [
        _blocked_portal_surface(asset),
        _pending_surface(
            surface_id="internet-archive",
            label="Internet Archive",
            kind="archive",
            required=public_record,
            message=(
                "Internet Archive proof is required before archive verification."
                if public_record
                else "Internet Archive is optional for this non-public-record asset."
            ),
            next_step="Approve IA publish or enter an audit-logged override.",
        ),
        _pending_surface(
            surface_id="local-nas-rsync",
            label="Local NAS rsync",
            kind="archive",
            required=public_record,
            message=(
                "Rsync/hash local NAS proof is required before archive verification."
                if public_record
                else "Local NAS rsync proof is optional for this non-public-record asset."
            ),
            next_step="Approve local NAS rsync archive or enter an audit-logged override.",
        ),
        _pending_surface(
            surface_id="local-nas-zfs",
            label="Local NAS ZFS",
            kind="archive",
            required=public_record,
            message=(
                "ZFS send/hash local NAS proof is required before archive verification."
                if public_record
                else "Local NAS ZFS proof is optional for this non-public-record asset."
            ),
            next_step="Approve local NAS ZFS archive or enter an audit-logged override.",
        ),
        _pending_surface(
            surface_id="youtube-live",
            label="YouTube Live",
            kind="reach",
            required=False,
            message="YouTube Live is a reach surface; failures must not block the portal.",
            next_step="Approve YouTube Live fanout or leave it pending.",
        ),
        _pending_surface(
            surface_id="youtube-vod",
            label="YouTube VOD",
            kind="reach",
            required=False,
            message="YouTube VOD is a reach surface; failures degrade independently.",
            next_step="Approve YouTube VOD upload or leave it pending.",
        ),
        _pending_surface(
            surface_id="podcast",
            label="Podcast episode",
            kind="audience",
            required=False,
            message="Podcast RSS is an audience surface generated after operator approval.",
            next_step="Approve podcast generation or leave it pending for later audio review.",
        ),
        _pending_surface(
            surface_id="subscriber-notifications",
            label="Subscriber notifications",
            kind="audience",
            required=False,
            message="Confirmed subscribers receive notices after publish; failures do not block archive.",
            next_step="Approve notification dispatch after the public portal and podcast links are ready.",
        ),
        _pending_surface(
            surface_id=CABLE_PACKAGE_SURFACE_ID,
            label="Cable file package",
            kind="record",
            required=False,
            message=(
                "Cable file package creates a local ZIP with media, captions, metadata, "
                "and hashes for PEG/headend handoff."
            ),
            next_step=(
                "Configure a cable package output folder and caption sidecar folder, then "
                "approve this surface for headend handoff."
            ),
        ),
    ]


def build_publish_preflight(
    asset: StaffAssetRow,
    credential_provider: CredentialProvider | None = None,
) -> PublishPreflightResponse:
    """Return approval readiness for every v0.7 publish surface."""
    provider = credential_provider or DeterministicCredentialProvider()
    checks: list[PublishPreflightCheck] = []
    for surface in build_initial_surfaces(asset):
        if surface.id == "portal":
            health: Literal["ok", "error"] = "ok" if asset.manifest_url else "error"
            checks.append(
                PublishPreflightCheck(
                    id=surface.id,
                    label=surface.label,
                    kind=surface.kind,
                    required=surface.required,
                    health=health,
                    message=(
                        "Portal manifest is packaged and ready."
                        if asset.manifest_url
                        else "Portal manifest is missing for this asset."
                    ),
                    next_step=(
                        "Approve portal publication when review is complete."
                        if asset.manifest_url
                        else "Run the packager or fix ingest so manifest_url exists."
                    ),
                )
            )
            continue
        credential = provider.check_surface(surface.id)
        checks.append(
            PublishPreflightCheck(
                id=surface.id,
                label=surface.label,
                kind=surface.kind,
                required=surface.required,
                health="ok" if credential.healthy else "error",
                credential_reference=credential.reference,
                message=credential.message,
                next_step=credential.next_step,
            )
        )
    ready = all(check.health == "ok" for check in checks if check.required)
    return PublishPreflightResponse(asset_id=asset.asset_id, ready=ready, checks=checks)


def _apply_override(
    surface: PublishSurfaceStatus,
    justification: str,
    at: datetime,
) -> PublishSurfaceStatus:
    return surface.model_copy(
        update={
            "state": "overridden",
            "approval": "overridden",
            "health": "warning",
            "completed_at": at,
            "message": f"{surface.label} was skipped with an audit-logged override.",
            "next_step": "Review the override justification before closing the public record.",
            "override_justification": justification,
        }
    )


def _provider_failure(
    surface: PublishSurfaceStatus, *, at: datetime, exc: Exception
) -> PublishSurfaceStatus:
    """Record a provider delivery failure on the surface (cable-surface pattern).

    Real adapters can fail on the network; one bad surface must not 500 the
    whole approval. The surface stays retryable through the existing
    per-surface retry endpoint.
    """

    return surface.model_copy(
        update={
            "state": "failed",
            "approval": "approved",
            "health": "warning",
            "completed_at": at,
            "message": f"{surface.label} delivery failed; retry this surface.",
            "next_step": str(exc),
        }
    )


def approve_publish(
    *,
    asset: StaffAssetRow,
    request: PublishApprovalRequest,
    store: PublishStore,
    registry: ProviderRegistry | None = None,
    media_path: Path | None = None,
) -> PublishRunRecord:
    """Approve and execute the publish surfaces.

    Archive/reach clients resolve through the provider registry (Stage C):
    the deterministic mocks remain the configured defaults; real adapters are
    selected per kind with ``CIVICCAST_PROVIDER_*`` (Beta B5).

    ``media_path`` is the asset's local recording file when the caller could
    resolve one. Adapters that support full-media publishing
    (``upload_path`` / ``upload_vod_path``) receive it; the mocks keep the
    deterministic verification payload. A provider exception marks that
    surface ``failed`` (retryable via the existing per-surface retry) instead
    of failing the whole approval.
    """
    at = datetime.now(UTC)
    payload = f"{asset.asset_id}:{asset.title}".encode()
    overrides = {override.surface_id: override.justification for override in request.overrides}
    approved_ids = (
        set(request.approved_surface_ids)
        if request.approved_surface_ids is not None
        else {surface.id for surface in build_initial_surfaces(asset)}
    )
    resolved_registry = registry if registry is not None else default_registry()
    ia = resolved_registry.resolve(PROVIDER_KIND_INTERNET_ARCHIVE)
    nas = resolved_registry.resolve(PROVIDER_KIND_LOCAL_NAS)
    youtube = resolved_registry.resolve(PROVIDER_KIND_YOUTUBE)

    surfaces: list[PublishSurfaceStatus] = []
    events: list[PublishAuditEvent] = []
    nas_proof_pair: tuple[Any, Any] | None = None
    for surface in build_initial_surfaces(asset):
        if surface.id in overrides:
            updated = _apply_override(surface, overrides[surface.id], at)
            surfaces.append(updated)
            events.append(
                _event(
                    asset_id=asset.asset_id,
                    surface=updated,
                    action="overridden",
                    operator_id=request.operator_id,
                    message=updated.message,
                    at=at,
                )
            )
            continue
        if surface.id not in approved_ids:
            surfaces.append(surface)
            continue
        if surface.id == "portal" and asset.manifest_url:
            updated = surface.model_copy(
                update={
                    "state": "succeeded",
                    "approval": "approved",
                    "health": "ok",
                    "completed_at": at,
                    "message": "Canonical portal is public for this recording.",
                    "next_step": "Monitor archive and reach surfaces independently.",
                }
            )
        elif surface.id == "internet-archive":
            try:
                if media_path is not None and hasattr(ia, "upload_path"):
                    proof = ia.upload_path(asset_id=asset.asset_id, path=media_path)
                else:
                    proof = ia.upload(asset_id=asset.asset_id, payload=payload)
            except Exception as exc:
                updated = _provider_failure(surface, at=at, exc=exc)
            else:
                updated = surface.model_copy(
                    update={
                        "state": "succeeded",
                        "approval": "approved",
                        "health": "ok",
                        "url": proof.target_url_or_path,
                        "verification_hash": proof.verification_hash,
                        "completed_at": at,
                        "simulated": proof.simulated,
                        "message": (
                            "SIMULATED - no item was created at the Internet Archive. "
                            "An admin must set CIVICCAST_PROVIDER_INTERNET_ARCHIVE=real "
                            "with valid credentials before this counts as the legal archive."
                            if proof.simulated
                            else "Internet Archive item URL verifies hash-match."
                        ),
                        "next_step": (
                            "Ask an admin to enable the real Internet Archive provider."
                            if proof.simulated
                            else "Confirm local NAS proofs before archive verification."
                        ),
                    }
                )
        elif surface.id in {"local-nas-rsync", "local-nas-zfs"}:
            try:
                if nas_proof_pair is None:
                    # One archive run per approval: both NAS surfaces share the
                    # same copy+snapshot pair instead of archiving twice.
                    if media_path is not None and hasattr(nas, "archive_path"):
                        nas_proof_pair = nas.archive_path(asset_id=asset.asset_id, path=media_path)
                    else:
                        nas_proof_pair = nas.archive(asset_id=asset.asset_id, payload=payload)
            except Exception as exc:
                updated = _provider_failure(surface, at=at, exc=exc)
            else:
                proof = nas_proof_pair[0 if surface.id == "local-nas-rsync" else 1]
                updated = surface.model_copy(
                    update={
                        "state": "succeeded",
                        "approval": "approved",
                        "health": "ok",
                        "path": proof.target_url_or_path,
                        "verification_hash": proof.verification_hash,
                        "completed_at": at,
                        "simulated": proof.simulated,
                        "message": (
                            f"SIMULATED - {surface.label} did not write any file. "
                            "An admin must set CIVICCAST_PROVIDER_LOCAL_NAS=real before "
                            "this counts as the station's retained copy."
                            if proof.simulated
                            else f"{surface.label} wrote and verified a hash-matched copy."
                        ),
                        "next_step": (
                            "Ask an admin to enable the real local-NAS provider."
                            if proof.simulated
                            else "Keep both local NAS proofs with the archive evidence."
                        ),
                    }
                )
        elif surface.id == "youtube-live":
            try:
                youtube_live_proof = youtube.publish_live(asset_id=asset.asset_id)
            except Exception as exc:
                updated = _provider_failure(surface, at=at, exc=exc)
            else:
                updated = surface.model_copy(
                    update={
                        "state": "succeeded",
                        "approval": "approved",
                        "health": "ok",
                        "url": youtube_live_proof.url,
                        "completed_at": at,
                        "message": "YouTube Live RTMPS fanout proof succeeded.",
                        "next_step": "Treat this as reach evidence, not the system of record.",
                    }
                )
        elif surface.id == "youtube-vod":
            try:
                if media_path is not None and hasattr(youtube, "upload_vod_path"):
                    youtube_vod_proof = youtube.upload_vod_path(
                        asset_id=asset.asset_id, path=media_path
                    )
                else:
                    youtube_vod_proof = youtube.upload_vod(asset_id=asset.asset_id)
            except Exception as exc:
                updated = _provider_failure(surface, at=at, exc=exc)
            else:
                updated = surface.model_copy(
                    update={
                        "state": "succeeded",
                        "approval": "approved",
                        "health": "ok",
                        "url": youtube_vod_proof.url,
                        "completed_at": at,
                        "message": "YouTube VOD URL is available as a reach surface.",
                        "next_step": "Treat this as reach evidence, not the system of record.",
                    }
                )
        elif surface.id == "podcast":
            episode = create_podcast_episode(
                PodcastEpisodeCreate(
                    asset_id=asset.asset_id,
                    channel_id="government",
                    title=asset.title,
                    portal_url=asset.manifest_url
                    or f"https://portal.example/watch/{asset.asset_id}",
                    source_media_url=asset.manifest_url or f"file:///{asset.asset_id}.mp4",
                    signed_transcript_url=f"https://portal.example/records/{asset.asset_id}.pdf",
                    summary=f"Approved audio episode for {asset.title}.",
                    chapters=[],
                )
            )
            updated = surface.model_copy(
                update={
                    "state": "succeeded",
                    "approval": "approved",
                    "health": "ok",
                    "url": f"https://portal.example/podcast/{episode.channel_id}.xml",
                    "completed_at": at,
                    "message": "Podcast episode was generated at -16 LUFS and added to RSS.",
                    "next_step": "Validate the podcast RSS feed before public announcement.",
                }
            )
        elif surface.id == "subscriber-notifications":
            notification_payload = NotificationPayload(
                asset_id=asset.asset_id,
                title=asset.title,
                portal_url=asset.manifest_url or f"https://portal.example/watch/{asset.asset_id}",
                podcast_url="https://portal.example/podcast/government.xml",
                summary=f"New CivicCast recording published: {asset.title}.",
                published_at=at,
            )
            updated = surface.model_copy(
                update={
                    "state": "succeeded",
                    "approval": "approved",
                    "health": "ok",
                    "completed_at": at,
                    "message": (
                        "Subscriber notification payload prepared for "
                        f"{notification_payload.title}."
                    ),
                    "next_step": "Use the subscription dispatch proof to verify local mailbox/webhook delivery.",
                }
            )
        elif surface.id == CABLE_PACKAGE_SURFACE_ID:
            try:
                cable_package = build_cable_file_package_for_asset(asset)
            except CablePackageError as exc:
                updated = surface.model_copy(
                    update={
                        "state": "failed",
                        "approval": "approved",
                        "health": "warning",
                        "completed_at": at,
                        "message": "Cable file package was not created.",
                        "next_step": str(exc),
                    }
                )
            else:
                updated = surface.model_copy(
                    update={
                        "state": "succeeded",
                        "approval": "approved",
                        "health": "ok",
                        "path": str(cable_package.zip_path),
                        "verification_hash": cable_package.verification_hash,
                        "completed_at": at,
                        "message": "Cable file package ZIP and SHA-256 proof were created.",
                        "next_step": cable_package.next_step,
                    }
                )
        else:
            updated = surface
        surfaces.append(updated)
        if updated.state == "succeeded":
            events.append(
                _event(
                    asset_id=asset.asset_id,
                    surface=updated,
                    action="succeeded",
                    operator_id=request.operator_id,
                    message=updated.message,
                    at=at,
                )
            )

    record = PublishRunRecord(
        asset_id=asset.asset_id,
        operator_id=request.operator_id,
        operator_display_name=request.operator_display_name,
        approved_at=at,
        surfaces=surfaces,
        audit_events=events,
    )
    return store.upsert_run(record)


def retry_publish_surface(
    *,
    asset: StaffAssetRow,
    surface_id: str,
    request: PublishRetryRequest,
    store: PublishStore,
) -> PublishRunRecord:
    """Retry one surface while preserving the rest of the publish run."""
    known_surface_ids = {surface.id for surface in build_initial_surfaces(asset)}
    if surface_id not in known_surface_ids:
        raise ValueError(f"Unknown publish surface: {surface_id}")
    previous = store.get_run(asset.asset_id)
    previous_surfaces = previous.surfaces if previous is not None else build_initial_surfaces(asset)
    previous_by_id = {surface.id: surface for surface in previous_surfaces}
    retried = approve_publish(
        asset=asset,
        request=PublishApprovalRequest(
            operator_id=request.operator_id,
            operator_display_name=request.operator_display_name,
            approved_surface_ids=[surface_id],
        ),
        store=InMemoryPublishStoreProxy(previous),
    )
    updated_surface = next(surface for surface in retried.surfaces if surface.id == surface_id)
    old_retry_count = previous_by_id.get(surface_id, updated_surface).retry_count
    updated_surface = updated_surface.model_copy(
        update={"retry_count": old_retry_count + 1, "last_attempt_at": datetime.now(UTC)}
    )
    merged = [
        updated_surface if surface.id == surface_id else surface for surface in previous_surfaces
    ]
    events = list(previous.audit_events if previous is not None else [])
    events.append(
        _event(
            asset_id=asset.asset_id,
            surface=updated_surface,
            action="retried",
            operator_id=request.operator_id,
            message=f"{updated_surface.label} was retried by the operator.",
            at=datetime.now(UTC),
        )
    )
    events.extend(retried.audit_events)
    return store.upsert_run(
        PublishRunRecord(
            asset_id=asset.asset_id,
            operator_id=request.operator_id,
            operator_display_name=request.operator_display_name,
            approved_at=previous.approved_at if previous is not None else retried.approved_at,
            surfaces=merged,
            audit_events=events,
        )
    )


class InMemoryPublishStoreProxy:
    """Tiny throwaway store so retry can reuse the single-surface executor."""

    def __init__(self, previous: PublishRunRecord | None) -> None:
        self._previous = previous
        self._record: PublishRunRecord | None = None

    def get_run(self, asset_id: str) -> PublishRunRecord | None:
        if self._previous is not None and self._previous.asset_id == asset_id:
            return self._previous
        return None

    def get_runs(self, asset_ids: Sequence[str]) -> dict[str, PublishRunRecord]:
        found = {}
        for asset_id in asset_ids:
            record = self.get_run(asset_id)
            if record is not None:
                found[asset_id] = record
        return found

    def upsert_run(self, record: PublishRunRecord) -> PublishRunRecord:
        self._record = record
        return record


def _dashboard_state(
    *,
    surfaces: list[PublishSurfaceStatus],
    public_record_required: bool,
) -> tuple[PublishDashboardStateValue, str]:
    portal = next(surface for surface in surfaces if surface.id == "portal")
    archive = [surface for surface in surfaces if surface.kind == "archive" and surface.required]
    reach = [surface for surface in surfaces if surface.kind in {"reach", "audience"}]
    required_failed = any(surface.required and surface.state == "failed" for surface in surfaces)
    pending_required = any(
        surface.required and surface.state in {"pending", "running"} for surface in surfaces
    )
    archive_verified = bool(archive) and all(
        surface.state in {"succeeded", "overridden"} for surface in archive
    )
    reach_failed = any(surface.state == "failed" for surface in reach)

    if portal.state == "blocked":
        return "preflight_blocked", "Preflight blocked"
    if required_failed:
        return "failed_needs_action", "Failed - needs action"
    if portal.state in {"pending", "running"}:
        return "draft", "Draft"
    if portal.state == "succeeded" and pending_required:
        return "archive_pending", "Archive pending"
    if portal.state == "succeeded" and reach_failed:
        return "reach_degraded", "Reach degraded"
    if public_record_required and archive_verified:
        return "archive_verified", "Archive verified"
    if portal.state == "succeeded":
        return "complete", "Complete"
    return "publishing", "Publishing"


def build_publish_asset_status(
    asset: StaffAssetRow,
    record: PublishRunRecord | None = None,
) -> PublishAssetStatus:
    public_record_required = _is_public_record(asset)
    surfaces = record.surfaces if record is not None else build_initial_surfaces(asset)
    dashboard_state, dashboard_label = _dashboard_state(
        surfaces=surfaces,
        public_record_required=public_record_required,
    )
    canonical_public = any(
        surface.id == "portal" and surface.state == "succeeded" for surface in surfaces
    )
    archive_surfaces = [
        surface for surface in surfaces if surface.kind == "archive" and surface.required
    ]
    archive_verified = bool(archive_surfaces) and all(
        surface.state in {"succeeded", "overridden"} for surface in archive_surfaces
    )
    reach_degraded = canonical_public and any(
        surface.kind == "reach" and surface.state == "failed" for surface in surfaces
    )
    needs_operator_action = any(
        surface.required and surface.state in {"blocked", "failed"} for surface in surfaces
    )
    return PublishAssetStatus(
        asset_id=asset.asset_id,
        title=asset.title,
        dashboard_state=dashboard_state,
        dashboard_label=dashboard_label,
        canonical_public=canonical_public,
        archive_verified=archive_verified,
        reach_degraded=reach_degraded,
        needs_operator_action=needs_operator_action,
        public_record_required=public_record_required,
        published_at=asset.published_at,
        surfaces=surfaces,
    )


def build_publish_dashboard(
    assets: list[StaffAssetRow],
    store: PublishStore | None = None,
) -> PublishDashboardResponse:
    # One batched fetch, not one query per asset. This list is unbounded (it is
    # every meeting the station has ever recorded), so a per-row lookup made the
    # dashboard's cost grow forever -- GauntletGate PE-1.
    # One batched fetch, not one query per asset. This list is unbounded (it is
    # every meeting the station has ever recorded), so a per-row lookup made the
    # dashboard's cost grow forever -- GauntletGate PE-1.
    runs = {} if store is None else store.get_runs([asset.asset_id for asset in assets])
    rows = [build_publish_asset_status(asset, runs.get(asset.asset_id)) for asset in assets]
    summary = PublishDashboardSummary(
        total_assets=len(rows),
        draft=sum(1 for row in rows if row.dashboard_state == "draft"),
        portal_live=sum(1 for row in rows if row.canonical_public),
        archive_verified=sum(1 for row in rows if row.archive_verified),
        degraded=sum(1 for row in rows if row.reach_degraded),
        needs_operator_action=sum(1 for row in rows if row.needs_operator_action),
    )
    return PublishDashboardResponse(summary=summary, assets=rows)
