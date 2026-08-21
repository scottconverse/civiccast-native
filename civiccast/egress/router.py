# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Staff API for channel egress configuration and daemon control."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from civiccast.auth.models import OperatorIdentity
from civiccast.auth.roles import require_any_role
from civiccast.egress.caption_proof import build_caption_status_provider
from civiccast.egress.compliance import (
    ComplianceProbeResult,
    DeviceProbeResult,
    TsduckStatus,
    locate_tsduck,
    probe_device,
    read_last_probe,
    run_compliance_probe,
)
from civiccast.egress.headend import (
    HeadendProfile,
    apply_headend_profile,
    get_headend_profile,
    list_headend_profiles,
)
from civiccast.egress.loudness_plan import ChannelLoudnessPlan, build_loudness_plan
from civiccast.egress.models import (
    CaptionStatus,
    EgressCaptionProofSample,
    EgressCommand,
    EgressCommandAction,
    EgressConfig,
    EgressHealthSample,
    EgressProofEvent,
    EgressSchemaCurrency,
    EgressSinkSpec,
    EgressState,
    EgressStateRow,
    ManualRouteState,
    TakeoverSession,
)
from civiccast.egress.store import EgressStore
from civiccast.egress.takeover_service import (
    AlreadyLiveError,
    NotInTakeoverError,
    TakeoverNotReadyError,
    TakeoverService,
)


def get_egress_store() -> EgressStore | None:
    """FastAPI dependency for the active egress store.

    The app factory overrides this when durable storage is ready. The default
    import-time value is ``None`` so router import does not open a database.
    """


def get_takeover_service() -> TakeoverService | None:
    """FastAPI dependency for the live-takeover service (S5).

    The app factory overrides this when durable storage is ready; the default
    import-time value is ``None`` so router import does not open a database. The
    handlers translate None into HTTP 503.
    """


def get_egress_work_dir() -> Path:
    """DI seam: where per-channel egress artifacts (incl. compliance results) live."""

    from civiccast.egress.automation import default_egress_work_dir

    return default_egress_work_dir()


def get_compliance_prober() -> Any:
    """DI seam: callable(config, seconds) -> ComplianceProbeResult.

    The default runs the real BYO-TSDuck probe; tests override this so the
    API contract needs neither TSDuck nor a live stream.
    """

    def _prober(config: EgressConfig, seconds: int) -> ComplianceProbeResult:
        return run_compliance_probe(config, seconds=seconds, work_dir=get_egress_work_dir())

    return _prober


def get_device_prober() -> Any:
    """DI seam: callable(host, ports) -> DeviceProbeResult."""

    def _prober(host: str, ports: list[int]) -> DeviceProbeResult:
        return probe_device(host, ports=ports)

    return _prober


public_router = APIRouter(prefix="/api/public/egress", tags=["public", "egress"])
staff_router = APIRouter(prefix="/api/staff/egress", tags=["staff", "egress"])
_DB_NOT_READY_DESCRIPTION = "Durable storage not ready -- run Setup storage or set DATABASE_URL"
_DB_NOT_READY_DETAIL = (
    "Durable storage is not ready. Open Setup and choose Prepare storage, "
    "or set DATABASE_URL for a technical deployment."
)


class EgressCommandRequest(BaseModel):
    """Operator command request; server fills id, time, and actor."""

    model_config = ConfigDict(extra="forbid")

    action: EgressCommandAction


class EgressCommandResponse(BaseModel):
    """Acknowledgement for a queued egress command."""

    model_config = ConfigDict(extra="forbid")

    command: EgressCommand
    queued: bool


class TakeoverRequest(BaseModel):
    """Operator request to take a channel live (S5). Actor comes from auth."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=2000)
    path_id: str | None = Field(default=None, max_length=160)
    duration_seconds: float = Field(default=3600.0, gt=0)


class HandbackRequest(BaseModel):
    """Operator request to return a channel from takeover to its schedule."""

    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(default=None, max_length=2000)


class PublicEgressNowResponse(BaseModel):
    """Viewer-safe current egress status for one channel."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str
    state: EgressState
    current_source_label: str | None = None
    updated_at: datetime
    caption_status: CaptionStatus = "not-verified"
    seconds_on_air: int = 0


class StaffEgressChannelSummary(BaseModel):
    """Staff inventory row for one configured egress channel."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str
    enabled: bool
    sink_count: int
    state: EgressStateRow | None = None
    latest_health: EgressHealthSample | None = None


class StaffEgressChannelDetail(BaseModel):
    """Staff detail view for one egress channel."""

    model_config = ConfigDict(extra="forbid")

    config: EgressConfig
    state: EgressStateRow | None = None
    latest_health: EgressHealthSample | None = None


def _require_store(store: EgressStore | None, *, surface: str) -> EgressStore:
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{_DB_NOT_READY_DETAIL} Surface: {surface}.",
        )
    return store


@public_router.get(
    "/channels/{channel_id}/now",
    response_model=PublicEgressNowResponse,
    summary="Read viewer-safe current egress channel status",
    responses={
        404: {"description": "Egress channel is not on air"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def get_public_now(
    channel_id: str,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> PublicEgressNowResponse:
    store = _require_store(egress_store, surface="public egress now")
    state = store.read_state(channel_id)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Egress channel is not on air: {channel_id}",
        )
    latest_health = _latest_health(store, channel_id)
    return PublicEgressNowResponse(
        channel_id=channel_id,
        state=state.state,
        current_source_label=state.current_source_label,
        updated_at=state.updated_at,
        caption_status=latest_health.caption_status if latest_health else "not-verified",
        seconds_on_air=latest_health.seconds_on_air if latest_health else 0,
    )


@staff_router.get(
    "/channels",
    response_model=list[StaffEgressChannelSummary],
    summary="List configured egress channels",
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def list_channels(
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> list[StaffEgressChannelSummary]:
    store = _require_store(egress_store, surface="egress channels")
    summaries: list[StaffEgressChannelSummary] = []
    for config in store.list_configs():
        summaries.append(
            StaffEgressChannelSummary(
                channel_id=config.channel_id,
                enabled=config.enabled,
                sink_count=len(config.sinks),
                state=store.read_state(config.channel_id),
                latest_health=_latest_health(store, config.channel_id),
            )
        )
    return summaries


@staff_router.get(
    "/channels/{channel_id}",
    response_model=StaffEgressChannelDetail,
    summary="Read egress channel config, state, and latest health",
    responses={
        404: {"description": "Egress config not found"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def get_channel_detail(
    channel_id: str,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> StaffEgressChannelDetail:
    store = _require_store(egress_store, surface="egress channel detail")
    config = store.get_config(channel_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Egress config not found: {channel_id}",
        )
    return StaffEgressChannelDetail(
        config=config,
        state=store.read_state(channel_id),
        latest_health=_latest_health(store, channel_id),
    )


@staff_router.put(
    "/channels/{channel_id}/config",
    response_model=EgressConfig,
    summary="Create or replace an egress channel configuration",
    dependencies=[Depends(require_any_role("setup_admin"))],
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def upsert_config(
    channel_id: str,
    payload: EgressConfig,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> EgressConfig:
    """Persist one channel's egress config.

    The path id must match the body id so scripts cannot accidentally write a
    config under one channel while the body describes another.
    """
    store = _require_store(egress_store, surface="egress config")
    if payload.channel_id != channel_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Path channel_id {channel_id!r} does not match body "
                f"channel_id {payload.channel_id!r}."
            ),
        )
    store.upsert_config(payload)
    result = store.get_config(channel_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Egress config was not readable after save.",
        )
    return result


@staff_router.get(
    "/channels/{channel_id}/config",
    response_model=EgressConfig,
    summary="Read an egress channel configuration",
    responses={
        404: {"description": "Egress config not found"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def get_config(
    channel_id: str,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> EgressConfig:
    store = _require_store(egress_store, surface="egress config")
    result = store.get_config(channel_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Egress config not found: {channel_id}",
        )
    return result


@staff_router.get(
    "/channels/{channel_id}/loudness-plan",
    response_model=ChannelLoudnessPlan,
    summary="Resolve the per-sink loudness plan for a channel (S11b)",
    dependencies=[Depends(require_any_role("setup_admin", "support_admin"))],
    responses={
        404: {"description": "Egress config not found"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def get_loudness_plan(
    channel_id: str,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> ChannelLoudnessPlan:
    """Per-destination loudness plan: each sink's resolved target, standard
    label, and whether it diverges from the channel conform baseline."""
    store = _require_store(egress_store, surface="loudness plan")
    config = store.get_config(channel_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Egress config not found: {channel_id}",
        )
    return build_loudness_plan(config)


class CaptionStatusResponse(BaseModel):
    """Live caption decode-back status for one channel (S11a)."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str
    caption_status: CaptionStatus
    latest: EgressCaptionProofSample | None = None


@staff_router.get(
    "/channels/{channel_id}/caption-status",
    response_model=CaptionStatusResponse,
    summary="Live CEA-608/708 caption decode-back status (S11a)",
    dependencies=[Depends(require_any_role("setup_admin", "meeting_operator", "support_admin"))],
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def get_caption_status(
    channel_id: str,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> CaptionStatusResponse:
    """Operator-facing caption status: ``on`` only when the latest decode-back proof
    is a fresh PASS (fail-closed), plus the latest proof sample for the drawer."""
    store = _require_store(egress_store, surface="caption status")
    caption_status = build_caption_status_provider(store)(channel_id)
    return CaptionStatusResponse(
        channel_id=channel_id,
        caption_status=caption_status,
        latest=store.latest_caption_proof_sample(channel_id),
    )


@staff_router.get(
    "/channels/{channel_id}/caption-proofs",
    response_model=list[EgressCaptionProofSample],
    summary="Recent CEA-608/708 caption decode-back proof samples (S11a)",
    dependencies=[Depends(require_any_role("setup_admin", "meeting_operator", "support_admin"))],
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def get_caption_proofs(
    channel_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> list[EgressCaptionProofSample]:
    store = _require_store(egress_store, surface="caption proofs")
    return store.recent_caption_proof_samples(channel_id, limit)


class HeadendProfileApplyRequest(BaseModel):
    """Apply one named headend delivery profile to a channel (CA-6)."""

    model_config = ConfigDict(extra="forbid")

    profile_id: str
    destination_uri: str
    muxrate_kbps: int | None = None
    keep_existing_sinks: bool = False


@staff_router.get(
    "/headend-profiles",
    response_model=list[HeadendProfile],
    summary="List named cable-headend delivery profiles (vendor-doc sourced)",
)
def headend_profiles() -> list[HeadendProfile]:
    # Static product surface: works before durable storage is prepared so
    # a station can read the requirements while still setting up.
    return list_headend_profiles()


@staff_router.post(
    "/channels/{channel_id}/config/headend-profile",
    response_model=EgressConfig,
    summary="Apply a headend delivery profile to a channel's egress config",
    dependencies=[Depends(require_any_role("setup_admin"))],
    responses={
        404: {"description": "Unknown headend profile"},
        422: {"description": "Destination does not satisfy the profile's transport"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def apply_headend_profile_to_channel(
    channel_id: str,
    payload: HeadendProfileApplyRequest,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> EgressConfig:
    store = _require_store(egress_store, surface="headend profile")
    profile = get_headend_profile(payload.profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown headend profile: {payload.profile_id}",
        )
    base = store.get_config(channel_id)
    fresh = base is None
    if base is None:
        # First-time setup path: the applied profile replaces the
        # placeholder sink, so a station can go from nothing to a
        # headend-ready config in one call.
        base = EgressConfig(
            channel_id=channel_id,
            enabled=True,
            slate_message="CivicCast is preparing the channel.",
            sinks=[
                EgressSinkSpec(
                    kind="file",
                    label="Cable headend",
                    uri=f"build/egress/{channel_id}-headend-placeholder.ts",
                )
            ],
        )
    try:
        updated = apply_headend_profile(
            base,
            profile,
            destination_uri=payload.destination_uri,
            muxrate_kbps_override=payload.muxrate_kbps,
            keep_existing_sinks=payload.keep_existing_sinks and not fresh,
        )
    except (ValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    store.upsert_config(updated)
    result = store.get_config(channel_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Egress config was not readable after save.",
        )
    return result


class ComplianceProbeRequest(BaseModel):
    """Bounded TSDuck verification run (CA-7)."""

    model_config = ConfigDict(extra="forbid")

    seconds: int = 10


class HeadendChannelReadiness(BaseModel):
    """Readiness summary for one udp-ts channel."""

    model_config = ConfigDict(extra="forbid")

    channel_id: str
    destination: str
    last_probe: ComplianceProbeResult | None = None


class HeadendReadinessResponse(BaseModel):
    """TSDuck availability + per-channel last probe results."""

    model_config = ConfigDict(extra="forbid")

    tsduck: TsduckStatus
    channels: list[HeadendChannelReadiness]


class DeviceProbeRequest(BaseModel):
    """TCP reachability probe of a headend appliance's management surface."""

    model_config = ConfigDict(extra="forbid")

    host: str
    ports: list[int] = Field(default_factory=lambda: [80, 443])


class NdiReadinessResponse(BaseModel):
    """BYO-NDI posture: the station's ffmpeg wire + live relay statuses."""

    model_config = ConfigDict(extra="forbid")

    byo_ffmpeg_configured: bool
    byo_ffmpeg_path: str | None = None
    next_step: str = ""
    relays: list[Any] = Field(default_factory=list)


@staff_router.get(
    "/ndi-readiness",
    response_model=NdiReadinessResponse,
    summary="BYO-NDI readiness and supervised relay statuses",
)
def ndi_readiness() -> NdiReadinessResponse:
    import os

    from civiccast.egress.ndi_relay import all_relay_statuses

    byo_path = os.environ.get("CIVICCAST_NDI_FFMPEG") or None
    next_step = (
        ""
        if byo_path
        else (
            "Set CIVICCAST_NDI_FFMPEG to the station's NDI-capable FFmpeg "
            "build to enable NDI output. CivicCast's bundled ffmpeg cannot "
            "include the NDI muxer (NewTek license) — see the NDI runbook "
            "section."
        )
    )
    return NdiReadinessResponse(
        byo_ffmpeg_configured=byo_path is not None,
        byo_ffmpeg_path=byo_path,
        next_step=next_step,
        relays=[status.model_dump() for status in all_relay_statuses()],
    )


class SdiReadinessResponse(BaseModel):
    """BYO-SDI posture: the station's ffmpeg wire + live relay statuses."""

    model_config = ConfigDict(extra="forbid")

    byo_ffmpeg_configured: bool
    byo_ffmpeg_path: str | None = None
    next_step: str = ""
    relays: list[Any] = Field(default_factory=list)


@staff_router.get(
    "/sdi-readiness",
    response_model=SdiReadinessResponse,
    summary="BYO-SDI readiness and supervised relay statuses",
)
def sdi_readiness() -> SdiReadinessResponse:
    import os

    from civiccast.egress.sdi_relay import all_relay_statuses

    byo_path = os.environ.get("CIVICCAST_SDI_FFMPEG") or None
    next_step = (
        ""
        if byo_path
        else (
            "Set CIVICCAST_SDI_FFMPEG to the station's DeckLink-capable "
            "FFmpeg build to enable SDI output. CivicCast's bundled ffmpeg "
            "cannot include the decklink muxer (Blackmagic SDK license) — "
            "see the SDI runbook section, or use the OBS bridge."
        )
    )
    return SdiReadinessResponse(
        byo_ffmpeg_configured=byo_path is not None,
        byo_ffmpeg_path=byo_path,
        next_step=next_step,
        relays=[status.model_dump() for status in all_relay_statuses()],
    )


@staff_router.get(
    "/headend-readiness",
    response_model=HeadendReadinessResponse,
    summary="TSDuck availability and last stream-verification results",
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def headend_readiness(
    egress_store: EgressStore | None = Depends(get_egress_store),
    work_dir: Path = Depends(get_egress_work_dir),
) -> HeadendReadinessResponse:
    store = _require_store(egress_store, surface="headend readiness")
    channels: list[HeadendChannelReadiness] = []
    for config in store.list_configs():
        udp_sinks = [sink for sink in config.sinks if sink.kind == "udp-ts"]
        if not udp_sinks:
            continue
        channels.append(
            HeadendChannelReadiness(
                channel_id=config.channel_id,
                destination=udp_sinks[0].uri,
                last_probe=read_last_probe(config.channel_id, work_dir),
            )
        )
    return HeadendReadinessResponse(tsduck=locate_tsduck(), channels=channels)


@staff_router.post(
    "/channels/{channel_id}/compliance-probe",
    response_model=ComplianceProbeResult,
    summary="Run a bounded TSDuck verification of the channel's headend stream",
    dependencies=[Depends(require_any_role("setup_admin"))],
    responses={
        404: {"description": "Egress config not found"},
        422: {"description": "Channel has no udp-ts headend sink"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def run_channel_compliance_probe(
    channel_id: str,
    payload: ComplianceProbeRequest,
    egress_store: EgressStore | None = Depends(get_egress_store),
    prober: Any = Depends(get_compliance_prober),
) -> ComplianceProbeResult:
    store = _require_store(egress_store, surface="compliance probe")
    config = store.get_config(channel_id)
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Egress config not found: {channel_id}",
        )
    try:
        return prober(config, payload.seconds)  # type: ignore[no-any-return]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@staff_router.post(
    "/headend-device-probe",
    response_model=DeviceProbeResult,
    summary="TCP reachability probe of a headend appliance",
    dependencies=[Depends(require_any_role("setup_admin"))],
)
def run_headend_device_probe(
    payload: DeviceProbeRequest,
    prober: Any = Depends(get_device_prober),
) -> DeviceProbeResult:
    return prober(payload.host, payload.ports)  # type: ignore[no-any-return]


class GstreamerRepairResponse(BaseModel):
    """Outcome of the 'repair GStreamer runtime & restore full egress' recovery
    action (degraded-mode tier 5)."""

    model_config = ConfigDict(extra="forbid")

    triggered: bool = Field(description="A signed re-stage was launched.")
    closure_healthy: bool = Field(description="The closure verifies clean right now.")
    remedy: str = Field(
        description=("already-healthy | restage-launched | installer-missing | launch-failed")
    )
    detail: str
    pid: int | None = None


@staff_router.post(
    "/repair-gstreamer",
    response_model=GstreamerRepairResponse,
    summary="Repair the GStreamer runtime and restore full egress (no reinstall)",
    dependencies=[Depends(require_any_role("setup_admin", "support_admin"))],
)
def repair_gstreamer_runtime() -> GstreamerRepairResponse:
    """Operator recovery for a station degraded onto the FFmpeg egress engine by
    a corrupt GStreamer closure.

    Re-verifies the closure in place. If it is healthy again (the common
    transient AV-quarantine cause), nothing destructive runs and GStreamer
    egress restores on the next control-plane environment re-derivation. If it
    still has missing bytes, launches the installer's signed, scoped
    ``native-app-payload`` re-stage DETACHED; on the service's next start the
    re-derived environment re-verifies the healthy closure and GStreamer egress
    AUTO-RESTORES. Never a reinstall.

    Backend-only in this change; no React built here. See
    ``next-cleanup.md`` for the operator console button this route is
    waiting on.
    """

    # Imported lazily so the egress router module graph stays light and the
    # native install-layout resolution is only touched when a repair is asked
    # for (this endpoint is Windows-native; the resolver reads sys.executable).
    from civiccast.native.gstreamer_repair import trigger_gstreamer_repair

    outcome = trigger_gstreamer_repair()
    return GstreamerRepairResponse(
        triggered=outcome.triggered,
        closure_healthy=outcome.healthy,
        remedy=outcome.remedy,
        detail=outcome.detail,
        pid=outcome.pid,
    )


@staff_router.post(
    "/channels/{channel_id}/commands",
    response_model=EgressCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue an egress daemon command",
    dependencies=[Depends(require_any_role("meeting_operator"))],
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def queue_command(
    channel_id: str,
    payload: EgressCommandRequest,
    request: Request,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> EgressCommandResponse:
    store = _require_store(egress_store, surface="egress commands")
    command = EgressCommand(
        channel_id=channel_id,
        action=payload.action,
        issued_at=datetime.now(UTC),
        issued_by=_staff_operator_id(request),
        command_id=f"egress-{uuid.uuid4()}",
    )
    store.enqueue_command(command)
    return EgressCommandResponse(command=command, queued=True)


# --- S5 Force Matrix: live takeover / handback ---


@staff_router.post(
    "/channels/{channel_id}/takeover",
    response_model=TakeoverSession,
    status_code=status.HTTP_201_CREATED,
    summary="Take a channel live (override the schedule)",
    dependencies=[Depends(require_any_role("meeting_operator", "setup_admin"))],
    responses={
        409: {"description": "Channel is already under live takeover"},
        422: {"description": "No ready live source could be prepared"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def begin_takeover(
    channel_id: str,
    payload: TakeoverRequest,
    request: Request,
    service: TakeoverService | None = Depends(get_takeover_service),
) -> TakeoverSession:
    svc = _require_takeover_service(service)
    identity = _staff_operator(request)
    try:
        return svc.take(
            channel_id=channel_id,
            operator_id=identity.operator_id,
            operator_name=identity.operator_display_name,
            reason=payload.reason,
            path_id=payload.path_id,
            duration_seconds=payload.duration_seconds,
        )
    except AlreadyLiveError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except TakeoverNotReadyError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@staff_router.delete(
    "/channels/{channel_id}/takeover",
    response_model=TakeoverSession,
    summary="Return a channel from live takeover to its schedule",
    dependencies=[Depends(require_any_role("meeting_operator", "setup_admin"))],
    responses={
        404: {"description": "Channel is not currently under live takeover"},
        503: {"description": _DB_NOT_READY_DESCRIPTION},
    },
)
def end_takeover(
    channel_id: str,
    request: Request,
    service: TakeoverService | None = Depends(get_takeover_service),
    payload: HandbackRequest | None = None,
) -> TakeoverSession:
    svc = _require_takeover_service(service)
    identity = _staff_operator(request)
    try:
        return svc.handback(
            channel_id=channel_id,
            operator_id=identity.operator_id,
            notes=payload.notes if payload is not None else None,
        )
    except NotInTakeoverError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@staff_router.get(
    "/channels/{channel_id}/takeover-state",
    response_model=ManualRouteState,
    summary="Read the channel's manual-route (takeover) state",
    dependencies=[Depends(require_any_role("meeting_operator", "setup_admin"))],
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def get_takeover_state(
    channel_id: str,
    service: TakeoverService | None = Depends(get_takeover_service),
) -> ManualRouteState:
    return _require_takeover_service(service).state(channel_id)


@staff_router.get(
    "/channels/{channel_id}/takeover-audit",
    response_model=list[TakeoverSession],
    summary="Read the channel's live-takeover audit log (admin)",
    dependencies=[Depends(require_any_role("setup_admin"))],
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def get_takeover_audit(
    channel_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    service: TakeoverService | None = Depends(get_takeover_service),
) -> list[TakeoverSession]:
    return _require_takeover_service(service).audit(channel_id, limit=limit)


@staff_router.get(
    "/channels/{channel_id}/state",
    response_model=EgressStateRow | None,
    summary="Read the last-known egress daemon state",
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def get_state(
    channel_id: str,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> EgressStateRow | None:
    store = _require_store(egress_store, surface="egress state")
    return store.read_state(channel_id)


@staff_router.get(
    "/channels/{channel_id}/health",
    response_model=list[EgressHealthSample],
    summary="Read recent egress health samples",
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def get_recent_health(
    channel_id: str,
    limit: int = Query(default=20, ge=1, le=500),
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> list[EgressHealthSample]:
    store = _require_store(egress_store, surface="egress health")
    return store.recent_health(channel_id, limit)


@staff_router.get(
    "/channels/{channel_id}/schema-currency",
    response_model=EgressSchemaCurrency,
    summary="Whether the channel's persisted egress data matches the running schema",
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def get_schema_currency(
    channel_id: str,
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> EgressSchemaCurrency:
    store = _require_store(egress_store, surface="egress schema currency")
    return EgressSchemaCurrency.from_latest_sample(channel_id, _latest_health(store, channel_id))


@staff_router.get(
    "/channels/{channel_id}/proof",
    response_model=list[EgressProofEvent],
    summary="Read recent egress as-aired proof events",
    responses={503: {"description": _DB_NOT_READY_DESCRIPTION}},
)
def get_recent_proof_events(
    channel_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    egress_store: EgressStore | None = Depends(get_egress_store),
) -> list[EgressProofEvent]:
    store = _require_store(egress_store, surface="egress proof")
    return store.recent_proof_events(channel_id, limit)


def _staff_operator(request: Request) -> OperatorIdentity:
    identity = getattr(request.state, "operator_identity", None)
    if not isinstance(identity, OperatorIdentity):
        raise TypeError("Staff auth middleware did not attach an OperatorIdentity.")
    return identity


def _staff_operator_id(request: Request) -> str:
    return _staff_operator(request).operator_id


def _require_takeover_service(service: TakeoverService | None) -> TakeoverService:
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{_DB_NOT_READY_DETAIL} Surface: live takeover.",
        )
    return service


def _latest_health(store: EgressStore, channel_id: str) -> EgressHealthSample | None:
    samples = store.recent_health(channel_id, 1)
    return samples[0] if samples else None
