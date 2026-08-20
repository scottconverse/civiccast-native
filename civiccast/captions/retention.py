# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Fail-closed retention policy for local caption evidence."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import wave
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from civiccast.captions.review import CaptionReviewStore
from civiccast.captions.review_media import (
    CaptionReviewClipError,
    verify_caption_review_audio_evidence,
)

_GIB = 1024**3
_RAW_CHUNK_MAX_AGE = timedelta(hours=24)
_RESOLVED_EVIDENCE_MAX_AGE = timedelta(days=90)
_AUDIT_LOCKS: dict[Path, threading.RLock] = {}
_AUDIT_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class CaptionRetentionResult:
    """The deletion receipt and the readiness decision consumed by egress."""

    ready: bool
    refusal_reason: str | None
    requires_fallback_slate: bool
    deleted_paths: tuple[Path, ...] = ()
    protected_paths: tuple[Path, ...] = ()
    audit_records: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class _Candidate:
    path: Path
    kind: str
    review_status: str
    low_confidence: bool
    created_at: datetime
    resolved_at: datetime | None
    sha256: str
    bytes: int
    derived_evidence_verified: bool


class CaptionEvidenceRetentionPolicy:
    """Apply the owner-approved lifecycle without deleting protected evidence."""

    raw_chunk_max_age = _RAW_CHUNK_MAX_AGE
    resolved_evidence_max_age = _RESOLVED_EVIDENCE_MAX_AGE

    def __init__(
        self,
        *,
        volume_bytes: int,
        free_bytes: int,
        audit_path: Path | None = None,
        storage_root: Path | None = None,
    ) -> None:
        self.volume_bytes = volume_bytes
        self.free_bytes = free_bytes
        self.max_storage_bytes = min(100 * _GIB, volume_bytes // 5)
        self.minimum_free_bytes = max(20 * _GIB, volume_bytes // 10)
        self._audit_path = audit_path.expanduser().resolve() if audit_path is not None else None
        self._storage_root = (
            storage_root.expanduser().resolve()
            if storage_root is not None
            else self._audit_path.parent
            if self._audit_path is not None
            else None
        )

    @classmethod
    def from_system(
        cls, *, storage_root: Path, audit_path: Path | None = None
    ) -> CaptionEvidenceRetentionPolicy:
        """Construct from the actual volume that holds the retained evidence."""

        root = storage_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(root)
        return cls(
            volume_bytes=usage.total,
            free_bytes=usage.free,
            audit_path=audit_path or root / "caption-retention-audit.jsonl",
            storage_root=root,
        )

    def enforce(
        self,
        *,
        candidates: Iterable[Mapping[str, object]],
        now: datetime | None = None,
    ) -> CaptionRetentionResult:
        """Prune only verified/expired evidence and refuse unsafe storage states."""

        observed_at = _utc(now or datetime.now(UTC))
        normalized = tuple(_normalize_candidate(candidate) for candidate in candidates)
        protected = tuple(
            candidate.path
            for candidate in normalized
            if candidate.kind == "review-evidence"
            and candidate.low_confidence
            and candidate.review_status == "pending"
        )
        eligible = sorted(
            (candidate for candidate in normalized if _is_eligible(candidate, observed_at)),
            key=lambda candidate: (
                0 if candidate.kind == "review-evidence" else 1,
                _utc(candidate.resolved_at or candidate.created_at),
                str(candidate.path),
            ),
        )
        deleted: list[Path] = []
        records: list[dict[str, object]] = []
        for candidate in eligible:
            if not candidate.path.is_file():
                continue
            try:
                candidate.path.unlink()
            except OSError:
                continue
            deleted.append(candidate.path)
            records.append(
                {
                    "outcome": "pruned",
                    "reason": _prune_reason(candidate),
                    "path": str(candidate.path),
                    "sha256": candidate.sha256,
                }
            )

        remaining_bytes = sum(
            candidate.bytes for candidate in normalized if candidate.path not in set(deleted)
        )
        free_after_prune = self.free_bytes + sum(
            candidate.bytes for candidate in normalized if candidate.path in set(deleted)
        )
        refusal_reason: str | None = None
        if free_after_prune < self.minimum_free_bytes:
            refusal_reason = "free-space-reserve-unrestorable"
        elif remaining_bytes > self.max_storage_bytes:
            refusal_reason = "storage-cap-unrestorable"
        if refusal_reason is not None:
            records.append(
                {
                    "outcome": "storage-refused",
                    "reason": refusal_reason,
                    "path": "",
                    "sha256": "",
                }
            )
        self._append_audit_records(records)
        return CaptionRetentionResult(
            ready=refusal_reason is None,
            refusal_reason=refusal_reason,
            requires_fallback_slate=refusal_reason is not None,
            deleted_paths=tuple(deleted),
            protected_paths=protected,
            audit_records=tuple(records),
        )

    def enforce_discovered(
        self,
        *,
        tap_root: Path | None,
        review_store: CaptionReviewStore,
        segment_seconds: float,
    ) -> CaptionRetentionResult:
        """Classify real persisted review/evidence state on the local volume."""

        self._refresh_system_capacity()
        if (
            tap_root is not None
            and tap_root.is_dir()
            and self._storage_root is not None
            and self._storage_root.is_dir()
            and tap_root.resolve().stat().st_dev != self._storage_root.stat().st_dev
        ):
            # dict[str, object] explicitly: inferred from this all-str literal
            # it would be dict[str, str], which _append_audit_records and
            # CaptionRetentionResult.audit_records both reject -- dict is
            # invariant, so a narrower value type is not a subtype.
            record: dict[str, object] = {
                "outcome": "storage-refused",
                "reason": "caption-storage-volumes-diverge",
                "path": "",
                "sha256": "",
            }
            self._append_audit_records((record,))
            return CaptionRetentionResult(
                ready=False,
                refusal_reason="caption-storage-volumes-diverge",
                requires_fallback_slate=True,
                audit_records=(record,),
            )
        candidates = self._discover_candidates(
            tap_root=tap_root,
            review_store=review_store,
            segment_seconds=segment_seconds,
        )
        return self.enforce(candidates=candidates)

    def _refresh_system_capacity(self) -> None:
        if self._storage_root is None:
            return
        usage = shutil.disk_usage(self._storage_root)
        self.volume_bytes = usage.total
        self.free_bytes = usage.free
        self.max_storage_bytes = min(100 * _GIB, usage.total // 5)
        self.minimum_free_bytes = max(20 * _GIB, usage.total // 10)

    def record_event(self, *, outcome: str, reason: str, path: Path, sha256: str) -> None:
        """Record non-destructive retention decisions such as segment collisions."""

        self._append_audit_records(
            (
                {
                    "outcome": outcome,
                    "reason": reason,
                    "path": str(path.expanduser().resolve()),
                    "sha256": sha256,
                },
            )
        )

    def _discover_candidates(
        self,
        *,
        tap_root: Path | None,
        review_store: CaptionReviewStore,
        segment_seconds: float,
    ) -> list[dict[str, object]]:
        evidence_by_path: dict[Path, dict[str, object]] = {}
        verified_windows: dict[str, list[tuple[float, float]]] = {}
        for item in review_store.list():
            evidence = review_store.get_audio_evidence(item.review_item_id)
            if evidence is None:
                continue
            try:
                evidence_path = verify_caption_review_audio_evidence(evidence)
                duration = _wav_duration(evidence_path)
            except CaptionReviewClipError:
                continue
            item_resolved_at = item.updated_at if item.status != "pending" else None
            candidate = evidence_by_path.get(evidence_path)
            if candidate is None:
                candidate = {
                    "path": evidence_path,
                    "kind": "review-evidence",
                    "review_status": item.status,
                    "resolved_at": item_resolved_at,
                    "created_at": item.created_at,
                    "sha256": evidence.source_sha256,
                    "bytes": evidence.source_bytes,
                    "low_confidence": item.low_confidence,
                }
                evidence_by_path[evidence_path] = candidate
            else:
                candidate["low_confidence"] = (
                    bool(candidate["low_confidence"]) or item.low_confidence
                )
                if item.status == "pending":
                    candidate["review_status"] = "pending"
                    candidate["resolved_at"] = None
                elif candidate["review_status"] != "pending":
                    # One offline ASR chunk (or one live tap segment) can
                    # attach the SAME evidence WAV to several cues
                    # (_offline_audio_evidence_factory /
                    # CaptionTapWorker._audio_evidence_factory each write
                    # the file once and reuse it across every cue from that
                    # window). Coalescing by path must not let an early
                    # decision on one of those cues start the 90-day clock
                    # while a later cue sharing the same file is still
                    # unresolved-at-merge-time or was resolved after it
                    # (audit finding, P2): keep the LATEST resolution
                    # timestamp seen across every row sharing this path,
                    # not the first one processed -- order-independent,
                    # since every row is visited regardless of
                    # review_store.list()'s ordering.
                    existing_resolved_at = cast("datetime | None", candidate["resolved_at"])
                    if item_resolved_at is not None and (
                        existing_resolved_at is None or item_resolved_at > existing_resolved_at
                    ):
                        candidate["resolved_at"] = item_resolved_at
            verified_windows.setdefault(item.asset_id, []).append(
                (evidence.source_start_seconds, evidence.source_start_seconds + duration)
            )

        candidates = list(evidence_by_path.values())
        known_evidence_paths = set(evidence_by_path)
        if self._storage_root is not None and self._storage_root.is_dir():
            for evidence_path in sorted(self._storage_root.glob("*/captions/evidence/*.wav")):
                resolved_path = evidence_path.resolve()
                if resolved_path in known_evidence_paths or not resolved_path.is_file():
                    continue
                candidates.append(
                    {
                        "path": resolved_path,
                        "kind": "unclassified-evidence",
                        "review_status": "pending",
                        "resolved_at": None,
                        "created_at": datetime.fromtimestamp(resolved_path.stat().st_mtime, UTC),
                        "sha256": _sha256(resolved_path),
                        "bytes": resolved_path.stat().st_size,
                        "low_confidence": False,
                    }
                )
        if tap_root is None or not tap_root.is_dir():
            return candidates
        for channel_dir in sorted(path for path in tap_root.iterdir() if path.is_dir()):
            for raw_path in sorted((channel_dir / "processed").glob("chunk-*.wav")):
                index = _chunk_index(raw_path)
                if index is None or not raw_path.is_file():
                    continue
                start = index * segment_seconds
                duration = _wav_duration(raw_path)
                verified = any(
                    evidence_start <= start and start + duration <= evidence_end
                    for evidence_start, evidence_end in verified_windows.get(channel_dir.name, ())
                )
                candidates.append(
                    {
                        "path": raw_path.resolve(),
                        "kind": "raw-chunk",
                        "review_status": "pending",
                        "resolved_at": None,
                        "created_at": datetime.fromtimestamp(raw_path.stat().st_mtime, UTC),
                        "sha256": _sha256(raw_path),
                        "bytes": raw_path.stat().st_size,
                        "low_confidence": False,
                        "derived_evidence_verified": verified,
                    }
                )
        return candidates

    def _append_audit_records(self, records: Iterable[dict[str, object]]) -> None:
        if self._audit_path is None:
            return
        payload = "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)
        if not payload:
            return
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        lock = _audit_lock(self._audit_path)
        with lock:
            descriptor = os.open(self._audit_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY)
            try:
                os.write(descriptor, payload.encode("utf-8"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def build_caption_readiness_provider(
    *,
    tap_root: Path | None,
    review_store: CaptionReviewStore,
    storage_root: Path,
    segment_seconds: float = 5.0,
) -> Any:
    """Build the real storage/readiness provider used before egress starts."""

    policy = CaptionEvidenceRetentionPolicy.from_system(storage_root=storage_root)

    def _provider(channel_id: str) -> CaptionRetentionResult:
        result = policy.enforce_discovered(
            tap_root=tap_root,
            review_store=review_store,
            segment_seconds=segment_seconds,
        )
        if not result.ready:
            # The egress gate can run before the next tap-worker poll. Clear the
            # published sidecar at this same refusal boundary, never after a
            # program encoder has already been allowed to start.
            from civiccast.captions.live_sidecar import publish_caption_runtime_status

            publish_caption_runtime_status(
                storage_root,
                channel_id,
                state="storage-refused",
                backlog_segments=0,
                max_backlog_segments=0,
                refusal_reason=result.refusal_reason,
            )
        return result

    return _provider


def _normalize_candidate(candidate: Mapping[str, object]) -> _Candidate:
    path = Path(str(candidate["path"])).expanduser().resolve()
    return _Candidate(
        path=path,
        kind=str(candidate["kind"]),
        review_status=str(candidate["review_status"]),
        low_confidence=bool(candidate.get("low_confidence", False)),
        created_at=_utc(candidate["created_at"]),
        resolved_at=_utc(candidate["resolved_at"]) if candidate.get("resolved_at") else None,
        sha256=str(candidate["sha256"]),
        bytes=int(str(candidate["bytes"])),
        derived_evidence_verified=bool(candidate.get("derived_evidence_verified", False)),
    )


def _is_eligible(candidate: _Candidate, now: datetime) -> bool:
    if candidate.kind == "raw-chunk":
        return (
            candidate.derived_evidence_verified
            and now - _utc(candidate.created_at) >= _RAW_CHUNK_MAX_AGE
        )
    return (
        candidate.kind == "review-evidence"
        and candidate.review_status != "pending"
        and now - _utc(candidate.resolved_at or candidate.created_at) >= _RESOLVED_EVIDENCE_MAX_AGE
    )


def _prune_reason(candidate: _Candidate) -> str:
    if candidate.kind == "raw-chunk":
        return "raw-chunk-expired-after-derived-evidence"
    return "resolved-evidence-expired"


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("caption retention timestamps must be datetimes")
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _chunk_index(path: Path) -> int | None:
    stem = path.stem
    prefix = "chunk-"
    if not stem.startswith(prefix) or not stem[len(prefix) :].isdigit():
        return None
    return int(stem[len(prefix) :])


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            return handle.getnframes() / rate if rate else 0.0
    except (OSError, EOFError, wave.Error):
        return 0.0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _audit_lock(path: Path) -> threading.RLock:
    with _AUDIT_LOCKS_GUARD:
        return _AUDIT_LOCKS.setdefault(path, threading.RLock())


__all__ = [
    "CaptionEvidenceRetentionPolicy",
    "CaptionRetentionResult",
    "build_caption_readiness_provider",
]
