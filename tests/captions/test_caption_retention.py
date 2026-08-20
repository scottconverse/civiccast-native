# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Owner-approved retention, reserve, and audit contracts for caption evidence."""

from __future__ import annotations

import wave
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path

import pytest

NOW = datetime(2026, 7, 28, 18, 0, tzinfo=UTC)
GIB = 1024**3


def _policy_type() -> type[object]:
    """Load the planned policy lazily so each contract has its own RED result."""

    try:
        module = import_module("civiccast.captions.retention")
    except ModuleNotFoundError:
        pytest.fail(
            "CaptionEvidenceRetentionPolicy is absent: the approved retention "
            "implementation has not been added."
        )
    policy = getattr(module, "CaptionEvidenceRetentionPolicy", None)
    assert policy is not None, "retention module must export CaptionEvidenceRetentionPolicy"
    return policy


def _candidate(
    path: Path,
    *,
    kind: str,
    status: str,
    aged: timedelta,
    sha256: str,
) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"caption evidence")
    return {
        "path": path.resolve(),
        "kind": kind,
        "review_status": status,
        "resolved_at": NOW - aged if status != "pending" else None,
        "created_at": NOW - aged,
        "sha256": sha256,
        "bytes": path.stat().st_size,
        "low_confidence": status == "pending",
    }


def _policy(*, volume_bytes: int = 500 * GIB, free_bytes: int = 100 * GIB) -> object:
    return _policy_type()(volume_bytes=volume_bytes, free_bytes=free_bytes)


class TestCaptionEvidenceRetentionPolicy:
    @pytest.mark.parametrize(
        ("volume_bytes", "expected_cap_bytes", "expected_reserve_bytes"),
        (
            (50 * GIB, 10 * GIB, 20 * GIB),
            (500 * GIB, 100 * GIB, 50 * GIB),
        ),
    )
    def test_owner_defaults_enforce_age_cap_and_reserve(
        self,
        volume_bytes: int,
        expected_cap_bytes: int,
        expected_reserve_bytes: int,
    ) -> None:
        policy = _policy(volume_bytes=volume_bytes, free_bytes=expected_reserve_bytes)

        assert policy.raw_chunk_max_age == timedelta(hours=24)
        assert policy.resolved_evidence_max_age == timedelta(days=90)
        assert policy.max_storage_bytes == expected_cap_bytes
        assert policy.minimum_free_bytes == expected_reserve_bytes

    def test_prunes_oldest_resolved_evidence_before_newer_resolved_evidence(
        self,
        tmp_path: Path,
    ) -> None:
        oldest = _candidate(
            tmp_path / "evidence" / "oldest.wav",
            kind="review-evidence",
            status="approved",
            aged=timedelta(days=91),
            sha256="a" * 64,
        )
        newer = _candidate(
            tmp_path / "evidence" / "newer.wav",
            kind="review-evidence",
            status="approved",
            aged=timedelta(days=91) - timedelta(seconds=1),
            sha256="b" * 64,
        )

        result = _policy().enforce(candidates=[newer, oldest], now=NOW)

        assert result.deleted_paths == (oldest["path"], newer["path"])
        assert result.ready is True

    def test_preserves_unresolved_low_confidence_evidence_even_when_expired(
        self,
        tmp_path: Path,
    ) -> None:
        protected = _candidate(
            tmp_path / "evidence" / "unresolved.wav",
            kind="review-evidence",
            status="pending",
            aged=timedelta(days=365),
            sha256="c" * 64,
        )

        result = _policy().enforce(candidates=[protected], now=NOW)

        assert protected["path"] not in result.deleted_paths
        assert result.protected_paths == (protected["path"],)
        assert Path(str(protected["path"])).is_file()

    def test_refuses_caption_readiness_and_requests_slate_when_protected_evidence_blocks_reserve(
        self,
        tmp_path: Path,
    ) -> None:
        protected = _candidate(
            tmp_path / "evidence" / "legal-hold.wav",
            kind="review-evidence",
            status="pending",
            aged=timedelta(days=365),
            sha256="d" * 64,
        )

        result = _policy(volume_bytes=100 * GIB, free_bytes=1 * GIB).enforce(
            candidates=[protected],
            now=NOW,
        )

        assert result.ready is False
        assert result.refusal_reason == "free-space-reserve-unrestorable"
        assert result.requires_fallback_slate is True
        assert protected["path"] in result.protected_paths

    def test_audit_receipt_records_outcome_reason_and_content_hash(self, tmp_path: Path) -> None:
        expired = _candidate(
            tmp_path / "processed" / "chunk-000000.wav",
            kind="raw-chunk",
            status="approved",
            aged=timedelta(hours=25),
            sha256="e" * 64,
        )
        expired["derived_evidence_verified"] = True

        result = _policy().enforce(candidates=[expired], now=NOW)

        assert result.audit_records == (
            {
                "outcome": "pruned",
                "reason": "raw-chunk-expired-after-derived-evidence",
                "path": str(expired["path"]),
                "sha256": "e" * 64,
            },
        )

    def test_preserves_resolved_evidence_younger_than_ninety_days(self, tmp_path: Path) -> None:
        recent = _candidate(
            tmp_path / "evidence" / "recent-approved.wav",
            kind="review-evidence",
            status="approved",
            aged=timedelta(days=89, hours=23),
            sha256="1" * 64,
        )

        result = _policy().enforce(candidates=[recent], now=NOW)

        assert result.deleted_paths == ()
        assert Path(str(recent["path"])).is_file()

    def test_keeps_raw_chunk_until_derived_evidence_is_verified(self, tmp_path: Path) -> None:
        raw = _candidate(
            tmp_path / "processed" / "chunk-000000.wav",
            kind="raw-chunk",
            status="approved",
            aged=timedelta(hours=25),
            sha256="f" * 64,
        )
        raw["derived_evidence_verified"] = False

        result = _policy().enforce(candidates=[raw], now=NOW)

        assert result.deleted_paths == ()
        assert Path(str(raw["path"])).is_file()


def _write_evidence_wav(path: Path, *, sample_rate: int = 16_000, seconds: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return path


class TestSharedEvidenceCoalescing:
    """Audit finding (P2, retention.py:489 / vod_job.py:489): shared evidence

    retained until the LATEST cue expires, not the FIRST.

    ``_offline_audio_evidence_factory`` (civiccast/captions/vod.py) and
    ``CaptionTapWorker._audio_evidence_factory`` (civiccast/captions/
    tap_worker.py) each write ONE evidence WAV per ASR window and reuse it
    across every cue that window produced. ``_discover_candidates``
    coalesces review rows onto one candidate per evidence path -- these
    tests pin that the coalesced candidate's ``resolved_at`` is the LATEST
    resolution timestamp across every row sharing the path, order-
    independent, rather than whichever row happened to be visited first.
    Shared by both the live tap and the offline job (both call
    ``enforce_discovered`` -> ``_discover_candidates``), so a regression
    here would affect both paths.
    """

    @staticmethod
    def _shared_evidence(path: Path) -> object:
        from civiccast.captions.review import CaptionReviewAudioEvidence

        wav_path = _write_evidence_wav(path)
        payload = wav_path.read_bytes()
        import hashlib

        return CaptionReviewAudioEvidence(
            source_path=str(wav_path.resolve()),
            source_start_seconds=0.0,
            source_sha256=hashlib.sha256(payload).hexdigest(),
            source_bytes=len(payload),
        )

    def _seed_two_cues_sharing_one_evidence_file(
        self,
        tmp_path: Path,
        *,
        early_resolved_at: datetime,
        late_resolved_at: datetime,
        create_early_first: bool,
    ) -> object:
        from civiccast.captions.models import CaptionCue
        from civiccast.captions.review import CaptionReviewItemCreate, InMemoryCaptionReviewStore

        evidence = self._shared_evidence(tmp_path / "evidence" / "shared.wav")
        store = InMemoryCaptionReviewStore()

        def _create(review_item_id: str, start: float) -> str:
            store.create(
                CaptionReviewItemCreate(
                    review_item_id=review_item_id,
                    asset_id="council-2026-08-16",
                    cue=CaptionCue(
                        cue_id=review_item_id.split(":")[-1],
                        start_seconds=start,
                        end_seconds=start + 1.0,
                        text="agenda item",
                        confidence=0.9,
                    ),
                    audio_evidence=evidence,
                )
            )
            return review_item_id

        order = (
            ["council-2026-08-16:cue-early", "council-2026-08-16:cue-late"]
            if create_early_first
            else ["council-2026-08-16:cue-late", "council-2026-08-16:cue-early"]
        )
        for review_item_id in order:
            start = 0.0 if "early" in review_item_id else 1.0
            _create(review_item_id, start)

        # Resolve both rows, backdating each row's updated_at directly --
        # InMemoryCaptionReviewStore always stamps datetime.now(UTC), and
        # this test needs deterministic, independently ordered resolution
        # timestamps to prove the merge is order-independent.
        for review_item_id, resolved_at in (
            ("council-2026-08-16:cue-early", early_resolved_at),
            ("council-2026-08-16:cue-late", late_resolved_at),
        ):
            item = store._items[review_item_id]
            store._items[review_item_id] = item.model_copy(
                update={
                    "status": "approved",
                    "reviewed_text": item.original_text,
                    "updated_at": resolved_at,
                }
            )
        return store

    @pytest.mark.parametrize("create_early_first", (True, False))
    def test_coalesced_resolved_at_is_the_latest_row_not_the_first_processed(
        self, tmp_path: Path, create_early_first: bool
    ) -> None:
        early_resolved_at = NOW - timedelta(days=100)
        late_resolved_at = NOW - timedelta(days=5)
        store = self._seed_two_cues_sharing_one_evidence_file(
            tmp_path,
            early_resolved_at=early_resolved_at,
            late_resolved_at=late_resolved_at,
            create_early_first=create_early_first,
        )
        policy = _policy_type()(volume_bytes=500 * GIB, free_bytes=100 * GIB)

        candidates = policy._discover_candidates(
            tap_root=None, review_store=store, segment_seconds=5.0
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate["review_status"] != "pending"
        # Before the fix, resolved_at stayed pinned to whichever row was
        # visited first -- with create_early_first=True that was the EARLY
        # row (100 days ago), which would make the shared WAV eligible for
        # pruning at the 90-day mark even though the LATE cue (5 days ago)
        # still needs it. The fix keeps the latest timestamp regardless of
        # visit order.
        assert candidate["resolved_at"] == late_resolved_at

    def test_shared_evidence_is_not_yet_eligible_while_the_later_cue_is_recent(
        self, tmp_path: Path
    ) -> None:
        """End-to-end proof via ``enforce``, not just the raw candidate dict.

        The early cue resolved 100 days ago (past the 90-day max age on its
        own); the late cue sharing the same WAV resolved 5 days ago. The
        shared file must survive this sweep -- it would have been pruned
        under the pre-fix "first row wins" merge.
        """

        early_resolved_at = NOW - timedelta(days=100)
        late_resolved_at = NOW - timedelta(days=5)
        store = self._seed_two_cues_sharing_one_evidence_file(
            tmp_path,
            early_resolved_at=early_resolved_at,
            late_resolved_at=late_resolved_at,
            create_early_first=True,
        )
        policy = _policy_type()(volume_bytes=500 * GIB, free_bytes=100 * GIB)
        candidates = policy._discover_candidates(
            tap_root=None, review_store=store, segment_seconds=5.0
        )

        result = policy.enforce(candidates=candidates, now=NOW)

        shared_path = candidates[0]["path"]
        assert result.deleted_paths == ()
        assert Path(str(shared_path)).is_file()
