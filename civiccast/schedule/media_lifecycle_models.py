# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""SQLAlchemy 2.0 + Pydantic v2 models for S7 (media lifecycle & readiness).

Spec: ``docs/spec/3.0/sections/S7-media-lifecycle-and-readiness.md``. That
file was marked ``status: built`` in ``docs/spec/3.0/ROADMAP.status.yaml``
(step-12 evidence pointed only at the pre-existing upload/ingest/loudness/
retention-preset code) but none of the five net-new S7 entities existed on
disk — no ``MediaIngestJob``, ``TranscodeJob``, ``AssetReadiness``,
``WatchFolderConfig``, or ``AssetRetentionPolicy`` model, and no migration
past ``0075_offline_caption_jobs`` touched them. This module is the real
build closing that gap.

It also closes a second, previously-unflagged gap the repo's own
``CLAUDE.md`` "Archival behavior (§4.6)" non-negotiable requires but nothing
enforced: *"every public-record meeting publishes to portal + IA + local NAS
before being marked archive-complete."* ``civiccast.archive.models`` produces
:class:`~civiccast.archive.models.ArchiveProof` values but nothing persisted
them, and ``public_archive_complete`` (``civiccast/playback_policy/models.py``,
``civiccast/app_platform/models.py``) was an operator-settable bool with no
verification behind it. :class:`AssetArchiveProof` gives archive writes a
durable home; :class:`AssetReadiness.archive_complete` is computed by
:mod:`civiccast.schedule.media_lifecycle_worker` from verified, non-simulated
proof rows only — never operator-set directly. Legal holds
(``Asset.legal_hold``) are new too; the retention worker
(:mod:`civiccast.schedule.retention_worker`) skips held assets so they are
never flagged for disposition review while a hold is active.

Table ownership at a glance (all new in this module's migration):

* ``media_ingest_jobs``       -- durable record of one ingest operation
* ``transcode_jobs``          -- durable record of one ingest-time transcode
* ``asset_readiness``         -- one denormalized row per asset (badge state)
* ``watch_folder_configs``    -- operator-configured auto-ingest directories
* ``asset_retention_policies``-- automation rules ("this series -> this policy")
* ``asset_archive_proofs``    -- durable, verified :class:`ArchiveProof` rows
* ``media_lifecycle_audit_log``-- append-only trail of worker actions (dry-run
  entries included, tagged ``dry_run=true``, so an operator can review what a
  dry run *would* have done before flipping the worker to apply mode)

Two columns are added to the existing ``assets`` table: ``legal_hold`` and
``legal_hold_reason``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from civiccast.db import Base

# ---------------------------------------------------------------------------
# Constants (state machines, mirroring the ``ASSET_STATE_*`` convention in
# civiccast.schedule.models)
# ---------------------------------------------------------------------------

INGEST_SOURCE_HTTP_UPLOAD = "http_upload"
INGEST_SOURCE_WATCH_FOLDER = "watch_folder"
INGEST_SOURCE_LIVE_FINALIZATION = "live_finalization"
_INGEST_SOURCE_KINDS = (
    INGEST_SOURCE_HTTP_UPLOAD,
    INGEST_SOURCE_WATCH_FOLDER,
    INGEST_SOURCE_LIVE_FINALIZATION,
)

JOB_STATUS_PENDING = "pending"
JOB_STATUS_RUNNING = "running"
JOB_STATUS_COMPLETED = "completed"
JOB_STATUS_FAILED = "failed"
_JOB_STATUSES = (JOB_STATUS_PENDING, JOB_STATUS_RUNNING, JOB_STATUS_COMPLETED, JOB_STATUS_FAILED)

READINESS_NOT_READY = "not_ready"
READINESS_PENDING_TRANSCODE = "pending_transcode"
READINESS_TRANSCODING = "transcoding"
READINESS_READY = "ready"
READINESS_MISSING_FILE = "missing_file"
READINESS_REJECTED = "rejected"
_READINESS_STATES = (
    READINESS_NOT_READY,
    READINESS_PENDING_TRANSCODE,
    READINESS_TRANSCODING,
    READINESS_READY,
    READINESS_MISSING_FILE,
    READINESS_REJECTED,
)

LOUDNESS_OK = "ok"
LOUDNESS_FAILED = "failed"
LOUDNESS_NOT_CHECKED = "not_checked"
_LOUDNESS_STATUSES = (LOUDNESS_OK, LOUDNESS_FAILED, LOUDNESS_NOT_CHECKED)

# Open decision #1 in the S7 spec ("how many transcodes per asset acceptable
# for a 100-asset station?") is unresolved -- surfaced to Scott, not picked
# silently (per CLAUDE.md "Open decisions" policy). The spec's own suggested
# default set names three formats, phrased as a question the spec itself
# never closes ("h264_720p_5mbps (proxy), h265_1080p_8mbps (archive),
# h264_mezzanine (SDI)?" -- S7 spec Open decision #1, with "h264-only for
# simplicity" offered as the named alternative).
#
# ADR 0007 amendment (2026-08-24, S7 resource-posture audit) resolves this
# to the named alternative, for two independent reasons, not one silent
# choice standing in for both:
#
# 1. LICENSE: h265_1080p_8mbps shipped with a bare "libx265" (GPL) literal.
#    civiccast never links a GPL encoder into the product (ADR 0007's own
#    compliance section; enforced by tests/policy/test_ffmpeg_h264_encoder.py
#    and the native-ffmpeg-pack's gpl_negative_control build check). H.264
#    has a real GPL-free resolution path (resolve_h264_encoder(): hardware ->
#    h264_mf -> libopenh264). HEVC has no such path anywhere in this tree --
#    no hevc_mf/hevc_nvenc resolver exists -- so there is no sanctioned way
#    to honor an HEVC transcode target today. Removed rather than shipped
#    opt-in-but-broken; a future ADR can add a real HEVC resolver if operator
#    demand justifies the engineering.
# 2. RESOURCE POSTURE: seeding every configured format unconditionally for
#    every validated asset, dispatched synchronously in the worker thread
#    with ffmpeg's full 6-hour default timeout, is a large amount of
#    unsupervised transcoding against the same box that serves operator
#    requests (see MediaLifecycleWorkerSettings' docstring). The default
#    seed set is now the single most broadly useful web rendition;
#    `h264_mezzanine` (near-lossless, -crf 12, the heaviest of the three) is
#    opt-in via CIVICCAST_TRANSCODE_FORMATS, not seeded by default.
#
# Per-station override unchanged: CIVICCAST_TRANSCODE_FORMATS
# (comma-separated) lets an operator opt back into a wider ladder --
# including a self-provided HEVC pipeline once one exists.
DEFAULT_TRANSCODE_FORMATS: tuple[str, ...] = ("h264_720p_5mbps",)

# Archive proof target types, mirroring civiccast.archive.models.ArchiveProof.
ARCHIVE_TARGET_INTERNET_ARCHIVE = "internet_archive"
_ARCHIVE_TARGET_LOCAL_NAS = (
    "local_nas_rsync",
    "local_nas_zfs",
    "local_nas_copy",
    "local_nas_snapshot_copy",
)
_ARCHIVE_TARGET_TYPES = (ARCHIVE_TARGET_INTERNET_ARCHIVE, *_ARCHIVE_TARGET_LOCAL_NAS)

RETENTION_POLICIES = ("default", "permanent", "meeting", "short")


def _uuid_key() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# ORM models
# ---------------------------------------------------------------------------


class MediaIngestJob(Base):
    """Durable record of an async ingest operation (upload or watch-folder)."""

    __tablename__ = "media_ingest_jobs"
    __table_args__ = (
        CheckConstraint(
            "source_kind IN ('http_upload', 'watch_folder', 'live_finalization')",
            name="media_ingest_jobs_source_kind_check",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="media_ingest_jobs_status_check",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="media_ingest_jobs_progress_check",
        ),
        Index("ix_media_ingest_jobs_asset_id", "asset_id"),
        Index("ix_media_ingest_jobs_status", "status"),
    )

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid_key)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JOB_STATUS_PENDING, server_default=JOB_STATUS_PENDING
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class TranscodeJob(Base):
    """One ingest-time transcode/proxy render for an asset."""

    __tablename__ = "transcode_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="transcode_jobs_status_check",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="transcode_jobs_progress_check",
        ),
        Index("ix_transcode_jobs_asset_id", "asset_id"),
        Index("ix_transcode_jobs_status", "status"),
    )

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid_key)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    output_format: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=JOB_STATUS_PENDING, server_default=JOB_STATUS_PENDING
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class AssetReadiness(Base):
    """Denormalized "ready for air" badge state, one row per asset.

    Spec Open decision #3 ("denormalize for dashboard speed, or compute
    on-the-fly?") is resolved here as denormalize -- a station-scale library
    (hundreds, not millions, of assets) makes the write cost (spec estimates
    1-2ms per recompute) trivially affordable, and the readiness dashboard is
    exactly the kind of "operator has 5 seconds before air" surface that must
    not run an aggregate query over transcode/ingest job tables per request.

    ``archive_complete`` and its three ``archive_*_verified_at`` columns are
    the S7 build's answer to CLAUDE.md's §4.6 archival non-negotiable --
    they are written ONLY by
    :meth:`civiccast.schedule.media_lifecycle_worker.MediaLifecycleWorker._recompute_one`
    from verified, non-simulated :class:`AssetArchiveProof` rows (+ the
    asset's own published portal manifest), never accepted as operator
    input. A row here does not exist until the worker (or the store's
    ``ensure_readiness_row``) creates it; the read path treats "no row yet"
    as ``not_ready``.
    """

    __tablename__ = "asset_readiness"
    __table_args__ = (
        CheckConstraint(
            "readiness_state IN ('not_ready', 'pending_transcode', 'transcoding', "
            "'ready', 'missing_file', 'rejected')",
            name="asset_readiness_state_check",
        ),
        CheckConstraint(
            "loudness_status IS NULL OR loudness_status IN ('ok', 'failed', 'not_checked')",
            name="asset_readiness_loudness_status_check",
        ),
    )

    asset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    readiness_state: Mapped[str] = mapped_column(
        String(20), nullable=False, default=READINESS_NOT_READY, server_default=READINESS_NOT_READY
    )
    readiness_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    loudness_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    measured_lufs: Mapped[float | None] = mapped_column(
        Numeric(6, 2, asdecimal=False), nullable=True
    )
    archive_portal_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archive_ia_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archive_nas_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    archive_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class WatchFolderConfig(Base):
    """One operator-configured auto-ingest directory (local/USB/NAS/SMB)."""

    __tablename__ = "watch_folder_configs"
    __table_args__ = (
        CheckConstraint(
            "settle_window_seconds >= 1", name="watch_folder_configs_settle_window_check"
        ),
        CheckConstraint(
            "retention_policy_default IS NULL OR retention_policy_default IN "
            "('default', 'permanent', 'meeting', 'short')",
            name="watch_folder_configs_retention_check",
        ),
    )

    config_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid_key)
    monitor_path: Mapped[str] = mapped_column(Text, nullable=False)
    import_naming_pattern: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    # D13 (spec §10) SMB resilience: two consecutive stable polls before a
    # file is considered write-complete. Operator-configurable per the
    # spec's resolution note ("remaining tuning -- settle-window duration --
    # is operator-configurable").
    settle_window_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, server_default="10"
    )
    retention_policy_default: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_scan_files_found: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class AssetRetentionPolicy(Base):
    """Automation rule: assets matching a criterion get a retention policy.

    v1 match criterion is ``meeting_body`` (matches the spec's own example:
    "all meeting recordings in this series -> retention_policy=meeting").
    Broader query matching (the S18 ``AssetQuery`` shape used by
    auto-schedule) is a documented follow-up, not silently expanded here.
    """

    __tablename__ = "asset_retention_policies"
    __table_args__ = (
        CheckConstraint(
            "retention_policy IN ('default', 'permanent', 'meeting', 'short')",
            name="asset_retention_policies_policy_check",
        ),
    )

    policy_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid_key)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    match_meeting_body: Mapped[str | None] = mapped_column(String(120), nullable=True)
    retention_policy: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class AssetArchiveProof(Base):
    """A durable, verified :class:`civiccast.archive.models.ArchiveProof`.

    Nothing wrote ``ArchiveProof`` anywhere before this table -- it was
    produced and consumed in-memory by the release-proof/soak tooling only
    (``civiccast/publish/proof.py``, ``civiccast/archive/*``). Per-asset
    archival never had a durable verification record. ``simulated=True``
    proofs (the default mock IA/NAS clients) are stored too, but the worker
    never counts them toward ``AssetReadiness.archive_complete`` -- a
    station running the mock providers must not show a false "archived"
    badge.
    """

    __tablename__ = "asset_archive_proofs"
    __table_args__ = (
        CheckConstraint(
            "target_type IN ('internet_archive', 'local_nas_rsync', 'local_nas_zfs', "
            "'local_nas_copy', 'local_nas_snapshot_copy')",
            name="asset_archive_proofs_target_type_check",
        ),
        Index("ix_asset_archive_proofs_asset_id", "asset_id"),
    )

    proof_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid_key)
    asset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_url_or_path: Mapped[str] = mapped_column(Text, nullable=False)
    verification_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    simulated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MediaLifecycleAuditEntry(Base):
    """Append-only audit trail for every worker action, dry-run or applied.

    A dry run writes the SAME entries an apply run would, tagged
    ``dry_run=True`` and with no underlying row mutated -- so an operator can
    review exactly what the worker would have done before switching
    ``CIVICCAST_MEDIA_LIFECYCLE_WORKER_DRY_RUN`` off.
    """

    __tablename__ = "media_lifecycle_audit_log"
    __table_args__ = (Index("ix_media_lifecycle_audit_log_asset_id", "asset_id"),)

    entry_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid_key)
    asset_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_now,
        server_default=text("CURRENT_TIMESTAMP"),
    )


# ---------------------------------------------------------------------------
# Pydantic response / request models (API contract, mirrors S7 spec §4)
# ---------------------------------------------------------------------------

ReadinessState = Literal[
    "not_ready", "pending_transcode", "transcoding", "ready", "missing_file", "rejected"
]
LoudnessStatus = Literal["ok", "failed", "not_checked"]


class InFlightTranscodeJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    output_format: str
    progress_percent: int
    estimated_remaining_secs: int | None = None


class AssetReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    asset_id: str
    readiness_state: ReadinessState
    readiness_reason: str | None
    loudness_status: LoudnessStatus | None
    measured_lufs: float | None
    in_flight_transcode_jobs: list[InFlightTranscodeJob] = Field(default_factory=list)
    archive_complete: bool
    archive_portal_verified: bool
    archive_ia_verified: bool
    archive_nas_verified: bool
    legal_hold: bool
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ReadinessDashboardRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    title: str
    readiness_state: ReadinessState
    readiness_reason: str | None
    in_flight_jobs_count: int


class ReadinessDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_assets: int
    ready_count: int
    transcoding_count: int
    missing_count: int
    rejected_count: int
    by_asset: list[ReadinessDashboardRow]


class MissingMediaAlertRow(BaseModel):
    """One scheduled item whose backing asset is not ready within the horizon."""

    model_config = ConfigDict(extra="forbid")

    schedule_id: str
    asset_id: str
    asset_title: str
    channel_id: str
    scheduled_start: datetime
    asset_state: str
    reason: str

    @field_validator("scheduled_start")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class WatchFolderConfigInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monitor_path: str = Field(..., min_length=1, max_length=4096)
    import_naming_pattern: str | None = Field(default=None, max_length=200)
    enabled: bool = True
    settle_window_seconds: int = Field(default=10, ge=1, le=3600)
    retention_policy_default: str | None = Field(default=None)

    @field_validator("retention_policy_default")
    @classmethod
    def _valid_policy(cls, value: str | None) -> str | None:
        if value is not None and value not in RETENTION_POLICIES:
            raise ValueError(f"retention_policy_default must be one of {RETENTION_POLICIES}")
        return value


class WatchFolderConfigResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    config_id: str
    monitor_path: str
    import_naming_pattern: str | None
    enabled: bool
    settle_window_seconds: int
    retention_policy_default: str | None
    last_scanned_at: datetime | None
    last_scan_files_found: int
    created_at: datetime
    updated_at: datetime

    @field_validator("last_scanned_at", "created_at", "updated_at")
    @classmethod
    def _aware_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class AssetRetentionPolicyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    match_meeting_body: str | None = Field(default=None, max_length=120)
    retention_policy: str
    priority: int = Field(default=0, ge=0, le=10_000)
    enabled: bool = True

    @field_validator("retention_policy")
    @classmethod
    def _valid_policy(cls, value: str) -> str:
        if value not in RETENTION_POLICIES:
            raise ValueError(f"retention_policy must be one of {RETENTION_POLICIES}")
        return value


class AssetRetentionPolicyResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    policy_id: str
    name: str
    match_meeting_body: str | None
    retention_policy: str
    priority: int
    enabled: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class StorageBudgetTierRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_policy: str
    asset_count: int
    bytes_used: int


class StorageBudgetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_bytes_used: int
    budget_bytes: int | None
    percent_used: float | None
    by_retention_policy: list[StorageBudgetTierRow]


class LifecycleAuditEntryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    entry_id: str
    asset_id: str | None
    action: str
    detail: str
    dry_run: bool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class LegalHoldInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_hold: bool
    reason: str | None = Field(default=None, max_length=2000)
