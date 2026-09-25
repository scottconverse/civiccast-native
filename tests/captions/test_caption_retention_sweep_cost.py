# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""A steady-state retention sweep stats the archive, it does not re-read it.

MEASURED 2026-09-24 on a synthetic 9,996-file archive shaped like the live
station (5,000 chunks at the live measured 160,044-byte size plus 4,998
matching evidence WAVs), instrumenting every phase of ``_discover_candidates``:
the warm sweep cost 11.3-12.1 s, of which SHA-256 was 6.8 s and
``_wav_duration`` 1.0 s.  Both are pure functions of a file's CONTENT, and the
archive under them is written once and never edited -- the tap parks a settled
chunk in ``processed/`` and the evidence writer does an atomic replace -- so
re-deriving them from scratch every 60 s, forever, is pure waste on the volume
whose contention is the defect.

These tests pin the reuse: a digest or duration is reused only while the file's
size and mtime are unchanged, a vanished file's entry is dropped rather than
served, and the tamper-checked evidence verification stays a read of the
CURRENT bytes -- cached only within one sweep, so that two review rows sharing
one evidence WAV do not each re-hash it.
"""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from civiccast.captions import retention, review_media
from civiccast.captions.models import CaptionCue
from civiccast.captions.review import (
    CaptionReviewAudioEvidence,
    CaptionReviewItemCreate,
    InMemoryCaptionReviewStore,
)

_CHUNK_SECONDS = 5.0
_SAMPLE_RATE = 16_000


def _write_wav(path: Path, *, seconds: float) -> bytes:
    """Write a WAV and return the bytes ON DISK (header included)."""

    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"\x00\x00" * int(_SAMPLE_RATE * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SAMPLE_RATE)
        handle.writeframes(payload)
    return path.read_bytes()


class _Counter:
    """Counts calls to a module-level helper without changing its behavior."""

    def __init__(self, owner: Any, name: str) -> None:
        self.calls = 0
        self._owner = owner
        self._name = name

    def install(self, monkeypatch: pytest.MonkeyPatch) -> _Counter:
        original = getattr(self._owner, self._name)

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.calls += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(self._owner, self._name, counted)
        return self


class _Archive:
    """One channel's chunks plus one evidence WAV per chunk, with review rows."""

    def __init__(self, root: Path, *, chunks: int = 3, channel: str = "public") -> None:
        self.tap_root = root / "caption-tap"
        self.storage_root = root / "egress"
        self.channel = channel
        self.store = InMemoryCaptionReviewStore()
        self.chunk_paths: list[Path] = []
        self.evidence_paths: list[Path] = []
        for index in range(chunks):
            chunk = self.tap_root / channel / "processed" / f"chunk-{index:06d}.wav"
            _write_wav(chunk, seconds=_CHUNK_SECONDS)
            self.chunk_paths.append(chunk)
            evidence_path = (
                self.storage_root / channel / "captions" / "evidence" / f"ev-{index:04x}.wav"
            )
            payload = _write_wav(evidence_path, seconds=2 * _CHUNK_SECONDS)
            self.evidence_paths.append(evidence_path)
            self._create_row(
                review_item_id=f"asset-{index}:cue",
                evidence_path=evidence_path,
                payload=payload,
                start_seconds=index * _CHUNK_SECONDS,
                evidence_start=max(0.0, index * _CHUNK_SECONDS - 2.0),
            )

    def _create_row(
        self,
        *,
        review_item_id: str,
        evidence_path: Path,
        payload: bytes,
        start_seconds: float,
        evidence_start: float,
        sha256: str | None = None,
        source_bytes: int | None = None,
    ) -> None:
        self.store.create(
            CaptionReviewItemCreate(
                review_item_id=review_item_id,
                asset_id=self.channel,
                cue=CaptionCue(
                    cue_id=review_item_id.split(":")[-1],
                    start_seconds=start_seconds,
                    end_seconds=start_seconds + 1.0,
                    text="synthetic",
                    confidence=0.9,
                ),
                audio_evidence=CaptionReviewAudioEvidence(
                    source_path=str(evidence_path.resolve()),
                    source_start_seconds=evidence_start,
                    source_sha256=sha256 or hashlib.sha256(payload).hexdigest(),
                    source_bytes=source_bytes or len(payload),
                ),
            )
        )

    def add_row_sharing(
        self,
        *,
        evidence_path: Path,
        payload: bytes,
        start_seconds: float,
        review_item_id: str,
        sha256: str | None = None,
    ) -> None:
        self._create_row(
            review_item_id=review_item_id,
            evidence_path=evidence_path,
            payload=payload,
            start_seconds=start_seconds,
            evidence_start=0.0,
            sha256=sha256,
        )

    def policy(self) -> retention.CaptionEvidenceRetentionPolicy:
        return retention.CaptionEvidenceRetentionPolicy.from_system(storage_root=self.storage_root)

    def sweep(self, policy: retention.CaptionEvidenceRetentionPolicy) -> list[dict[str, object]]:
        return policy._discover_candidates(
            tap_root=self.tap_root,
            review_store=self.store,
            segment_seconds=_CHUNK_SECONDS,
        )


def _digests_by_path(candidates: list[dict[str, object]]) -> dict[Path, str]:
    return {Path(str(row["path"])): str(row["sha256"]) for row in candidates}


class TestAFileIsReadOnceWhileItIsUnchanged:
    def test_a_second_sweep_rehashes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _Archive(tmp_path)
        policy = archive.policy()
        counter = _Counter(retention, "_sha256").install(monkeypatch)

        archive.sweep(policy)
        assert counter.calls == len(archive.chunk_paths), "first sweep must hash every chunk"

        archive.sweep(policy)
        assert counter.calls == len(archive.chunk_paths), (
            "an unchanged archive must not be re-hashed on the next sweep"
        )

    def test_a_changed_mtime_forces_a_rehash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _Archive(tmp_path)
        policy = archive.policy()
        counter = _Counter(retention, "_sha256").install(monkeypatch)
        archive.sweep(policy)
        before = counter.calls

        touched = archive.chunk_paths[1]
        stats = touched.stat()
        os.utime(touched, ns=(stats.st_atime_ns, stats.st_mtime_ns + 1_000_000_000))

        archive.sweep(policy)
        assert counter.calls - before == 1, "only the file whose mtime moved is re-read"

    def test_a_changed_size_forces_a_rehash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _Archive(tmp_path)
        policy = archive.policy()
        counter = _Counter(retention, "_sha256").install(monkeypatch)
        archive.sweep(policy)
        before = counter.calls

        # Different content, different size, and the SAME mtime: size alone
        # must be enough to distrust the cached digest.
        rewritten = archive.chunk_paths[1]
        stats = rewritten.stat()
        _write_wav(rewritten, seconds=_CHUNK_SECONDS * 2)
        os.utime(rewritten, ns=(stats.st_atime_ns, stats.st_mtime_ns))

        archive.sweep(policy)
        assert counter.calls - before == 1

        after = _digests_by_path(archive.sweep(policy))
        expected = hashlib.sha256(rewritten.read_bytes()).hexdigest()
        assert after[rewritten.resolve()] == expected

    def test_a_vanished_files_entry_is_dropped_not_served(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _Archive(tmp_path)
        policy = archive.policy()
        counter = _Counter(retention, "_sha256").install(monkeypatch)
        first = _digests_by_path(archive.sweep(policy))

        gone = archive.chunk_paths[1]
        stats = gone.stat()
        original_digest = first[gone.resolve()]
        gone.unlink()

        # The sweep that no longer sees the file must forget it ...
        archive.sweep(policy)

        # ... so that a DIFFERENT file that reuses the same path, the same size
        # and the same mtime is hashed afresh instead of inheriting the digest
        # of the bytes that used to live there.
        fresh_payload = b"\x00\x00" * int(_SAMPLE_RATE * _CHUNK_SECONDS)
        replacement = b"\x01\x00" + fresh_payload[2:]
        gone.write_bytes(replacement)
        os.utime(gone, ns=(stats.st_atime_ns, stats.st_mtime_ns))

        before = counter.calls
        after = _digests_by_path(archive.sweep(policy))

        assert counter.calls - before == 1, "the replacement file must be read, not assumed"
        assert after[gone.resolve()] == hashlib.sha256(replacement).hexdigest()
        assert after[gone.resolve()] != original_digest

    def test_the_wav_duration_is_probed_once_per_unchanged_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _Archive(tmp_path)
        policy = archive.policy()
        counter = _Counter(retention, "_probe_wav_duration").install(monkeypatch)

        archive.sweep(policy)
        archive.sweep(policy)

        # One probe per chunk plus one per unique evidence WAV, on the FIRST
        # sweep only; the second sweep re-derives none of them.
        expected = len(archive.chunk_paths) + len(archive.evidence_paths)
        assert counter.calls == expected

    def test_the_cache_belongs_to_the_policy_object(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _Archive(tmp_path)
        policy = archive.policy()
        counter = _Counter(retention, "_sha256").install(monkeypatch)

        archive.sweep(policy)
        first = counter.calls
        archive.sweep(policy)
        assert counter.calls == first, "the same policy object shares one cache"

        other = archive.policy()
        archive.sweep(other)
        assert counter.calls == 2 * first, "a second policy object starts cold"


class TestEvidenceVerificationStaysATamperCheck:
    def test_rows_sharing_one_evidence_wav_verify_it_once_per_sweep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _Archive(tmp_path, chunks=0)
        shared = archive.storage_root / archive.channel / "captions" / "evidence" / "shared.wav"
        payload = _write_wav(shared, seconds=10.0)
        for index in range(3):
            archive.add_row_sharing(
                evidence_path=shared,
                payload=payload,
                start_seconds=index * 1.0,
                review_item_id=f"shared-asset:cue-{index}",
            )
        policy = archive.policy()
        counter = _Counter(review_media, "_sha256").install(monkeypatch)

        candidates = archive.sweep(policy)

        assert len(candidates) == 1
        assert counter.calls == 1, "one file, one hash -- not one per review row"

    def test_a_row_whose_recorded_digest_no_longer_matches_is_still_dropped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A stale row (its recorded digest is not the file's) must be skipped
        # exactly as it is today: the reuse is keyed on the RECORDED identity
        # as well as the path, so a row that disagrees gets its own check.
        archive = _Archive(tmp_path, chunks=0)
        shared = archive.storage_root / archive.channel / "captions" / "evidence" / "shared.wav"
        payload = _write_wav(shared, seconds=10.0)
        archive.add_row_sharing(
            evidence_path=shared, payload=payload, start_seconds=0.0, review_item_id="a:cue"
        )
        archive.add_row_sharing(
            evidence_path=shared,
            payload=payload,
            start_seconds=1.0,
            review_item_id="b:cue",
            sha256="0" * 64,
        )
        policy = archive.policy()
        counter = _Counter(review_media, "_sha256").install(monkeypatch)

        candidates = archive.sweep(policy)

        assert len(candidates) == 1, (
            "only the row whose recorded identity matches the file is evidence; "
            "the stale row's copy of it is not"
        )
        assert counter.calls == 2, "the disagreeing row gets its own verification"

    def test_a_tampered_evidence_file_still_fails_verification(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _Archive(tmp_path, chunks=0)
        shared = archive.storage_root / archive.channel / "captions" / "evidence" / "shared.wav"
        payload = _write_wav(shared, seconds=10.0)
        archive.add_row_sharing(
            evidence_path=shared, payload=payload, start_seconds=0.0, review_item_id="a:cue"
        )
        policy = archive.policy()
        archive.sweep(policy)

        # Same length, so a size-only check would miss it entirely.
        tampered = b"\x01\x00" + payload[2:]
        shared.write_bytes(tampered)

        candidates = archive.sweep(policy)

        # It is no longer evidence for the row (so it is not a review-evidence
        # candidate); the leftover file shows up as unclassified file content.
        assert [row for row in candidates if row["kind"] == "review-evidence"] == [], (
            "a changed recording is not evidence"
        )

    def test_a_tamper_between_the_first_and_second_row_is_not_masked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The reuse is scoped to ONE sweep. A change made after a sweep must be
        # seen by the NEXT sweep even if the file's size and mtime are restored.
        archive = _Archive(tmp_path, chunks=0)
        shared = archive.storage_root / archive.channel / "captions" / "evidence" / "shared.wav"
        payload = _write_wav(shared, seconds=10.0)
        archive.add_row_sharing(
            evidence_path=shared, payload=payload, start_seconds=0.0, review_item_id="a:cue"
        )
        policy = archive.policy()
        assert len(archive.sweep(policy)) == 1

        stats = shared.stat()
        shared.write_bytes(b"\x01\x00" + payload[2:])
        os.utime(shared, ns=(stats.st_atime_ns, stats.st_mtime_ns))

        after = archive.sweep(policy)
        assert [row for row in after if row["kind"] == "review-evidence"] == []


def _now() -> datetime:
    return datetime(2026, 9, 24, tzinfo=UTC)


def test_the_sweep_still_reports_every_candidate_exactly_once(tmp_path: Path) -> None:
    """The reuse must not change WHICH candidates a sweep returns."""

    archive = _Archive(tmp_path, chunks=4)
    policy = archive.policy()

    first = _digests_by_path(archive.sweep(policy))
    second = _digests_by_path(archive.sweep(policy))

    assert first == second
    assert set(first) == {path.resolve() for path in archive.chunk_paths} | {
        path.resolve() for path in archive.evidence_paths
    }


def test_the_sweep_still_prunes_aged_evidence(tmp_path: Path) -> None:
    """A cached digest must not stop an aged file from being deleted."""

    archive = _Archive(tmp_path, chunks=1)
    policy = archive.policy()
    archive.sweep(policy)

    aged = archive.evidence_paths[0]
    old = _now() - retention.CaptionEvidenceRetentionPolicy.resolved_evidence_max_age
    result = policy.enforce(
        candidates=[
            {
                "path": aged.resolve(),
                "kind": "review-evidence",
                "review_status": "approved",
                "resolved_at": old,
                "created_at": old,
                "sha256": hashlib.sha256(aged.read_bytes()).hexdigest(),
                "bytes": aged.stat().st_size,
                "low_confidence": False,
            }
        ],
        now=_now(),
    )

    assert result.deleted_paths == (aged.resolve(),)
    assert not aged.is_file()
