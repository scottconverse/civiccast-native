# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the offline (VOD) caption job -- CivicCast One keystone K3.

The model runtime is faked the way every other caption suite fakes it: a
local class satisfying the ``CaptionRuntime`` protocol structurally. FFmpeg
is faked at the ``run_ffmpeg`` seam so the real chunking, stabilization,
review-queue, and HLS-attach code all execute for real.
"""

from __future__ import annotations

import shutil
import wave
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import civiccast.captions.vod as vod_module
from civiccast.captions.hls import CaptionHlsTrack, write_hls_caption_track
from civiccast.captions.models import AudioChunk, CaptionCue, CaptionHypothesis, CustomVocabulary
from civiccast.captions.retention import CaptionEvidenceRetentionPolicy, CaptionRetentionResult
from civiccast.captions.review import (
    CaptionReviewDecision,
    CaptionReviewEdit,
    CaptionReviewItemAlreadyExistsError,
    CaptionReviewItemCreate,
    CaptionReviewItemResponse,
    InMemoryCaptionReviewStore,
)
from civiccast.captions.vod import (
    OfflineCaptionAudioError,
    OfflineCaptionPackageError,
    attach_reviewed_captions,
    extract_caption_audio,
    published_caption_sidecar,
    published_spanish_caption_sidecar,
    queue_translated_captions,
    resolve_vod_package,
    reviewed_caption_cues,
    transcribe_asset_captions,
)
from civiccast.captions.vod_job import (
    ALL_ENGLISH_REJECTED_REMEDIATION,
    ALL_SPANISH_REJECTED_REMEDIATION,
    CAPTIONS_OFF_TEST_OVERRIDE_ENV,
    MISSING_TRANSLATOR_REMEDIATION,
    OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
    OFFLINE_CAPTION_JOB_STATE_COMPLETE,
    OFFLINE_CAPTION_JOB_STATE_FAILED,
    OFFLINE_CAPTION_JOB_STATE_PENDING,
    InMemoryOfflineCaptionJobStore,
    OfflineCaptionJobRecord,
    OfflineCaptionJobSettings,
    OfflineCaptionJobWorker,
    enqueue_offline_caption_job,
)
from civiccast.stream._ffmpeg import FfmpegResult
from civiccast.stream.config import ABR_LADDER, SLATE_RENDITION
from civiccast.translate.service import DeterministicSpanishTranslator

_ASSET_ID = "council-2026-08-16"


# ---------------------------------------------------------------------------
# fixtures / fakes
# ---------------------------------------------------------------------------


class _ScriptedRuntime:
    """Yields one hypothesis per chunk; text and confidence are scripted."""

    def __init__(
        self,
        texts: list[str] | None = None,
        *,
        confidence: float = 0.94,
    ) -> None:
        self.texts = texts
        self.confidence = confidence
        self.seen_chunks: list[AudioChunk] = []
        self.seen_vocabulary: CustomVocabulary | None = None

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        if vocabulary is not None:
            self.seen_vocabulary = vocabulary
        for chunk in chunks:
            index = len(self.seen_chunks)
            self.seen_chunks.append(chunk)
            text = (
                self.texts[index % len(self.texts)]
                if self.texts
                else f"agenda item {index + 1} is carried"
            )
            yield CaptionHypothesis(
                source_id=f"{chunk.chunk_id}-offline",
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                text=text,
                confidence=self.confidence,
            )


class _ExplodingRuntime:
    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        raise RuntimeError("caption model failed to load")
        yield  # pragma: no cover - unreachable, keeps the generator signature


def _write_wav(path: Path, *, sample_rate: int = 16_000, seconds: float = 4.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * int(sample_rate * seconds))
    return path


@pytest.fixture
def fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stand in for the extraction subprocess by copying the source WAV.

    The test fixtures are already mono 16-bit PCM WAV, so copying gives the
    downstream chunk loader exactly the shape real extraction produces.
    """

    def _run(args: list[str], **_kwargs: object) -> FfmpegResult:
        shutil.copyfile(args[args.index("-i") + 1], args[-1])
        return FfmpegResult(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(vod_module, "run_ffmpeg", _run)


def _package(root: Path) -> Path:
    """Write a minimal but real HLS package tree for an asset."""

    package_dir = root / _ASSET_ID
    for config in (*ABR_LADDER, SLATE_RENDITION):
        playlist = package_dir / config.name / "playlist.m3u8"
        playlist.parent.mkdir(parents=True, exist_ok=True)
        playlist.write_text("#EXTM3U\n#EXT-X-ENDLIST\n", encoding="utf-8")
    (package_dir / "playlist.m3u8").write_text("#EXTM3U\n", encoding="utf-8")
    return package_dir


def _cue(cue_id: str, start: float, end: float, text: str) -> CaptionCue:
    return CaptionCue(
        cue_id=cue_id,
        start_seconds=start,
        end_seconds=end,
        text=text,
        confidence=0.93,
    )


def _approve_all(store: InMemoryCaptionReviewStore, asset_id: str = _ASSET_ID) -> None:
    for item in store.list(asset_id=asset_id):
        store.approve(item.review_item_id, CaptionReviewDecision())


# ---------------------------------------------------------------------------
# audio extraction
# ---------------------------------------------------------------------------


class TestExtractCaptionAudio:
    def test_requests_mono_16khz_pcm_matching_the_live_tap(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, list[str]] = {}

        def _run(args: list[str], **_kwargs: object) -> FfmpegResult:
            seen["args"] = args
            Path(args[-1]).write_bytes(b"RIFF")
            return FfmpegResult(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(vod_module, "run_ffmpeg", _run)

        extract_caption_audio(tmp_path / "meeting.mp4", tmp_path / "out" / "meeting.wav")

        args = seen["args"]
        assert args[args.index("-ar") + 1] == "16000"
        assert args[args.index("-ac") + 1] == "1"
        assert args[args.index("-c:a") + 1] == "pcm_s16le"
        assert "-vn" in args

    def test_nonzero_exit_is_an_actionable_error_not_a_silent_empty_track(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            vod_module,
            "run_ffmpeg",
            lambda _args, **_kw: FfmpegResult(returncode=1, stdout="", stderr="boom"),
        )

        with pytest.raises(OfflineCaptionAudioError, match="could not read audio"):
            extract_caption_audio(tmp_path / "meeting.mp4", tmp_path / "meeting.wav")


# ---------------------------------------------------------------------------
# stage one: transcription -> review queue
# ---------------------------------------------------------------------------


class TestTranscribeAssetCaptions:
    def test_single_pass_audio_commits_every_cue_to_the_review_queue(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=6.0)
        review_store = InMemoryCaptionReviewStore()

        result = transcribe_asset_captions(
            _ScriptedRuntime(["motion carries", "roll call begins", "meeting adjourned"]),
            review_store,
            asset_id=_ASSET_ID,
            source_path=source,
            chunk_seconds=2.0,
        )

        # Offline transcribes each region once, so every chunk commits --
        # a live two-window stabilizer would have committed nothing here.
        assert result.chunk_count == 3
        assert len(result.cues) == 3
        assert [cue.text for cue in result.cues] == [
            "motion carries",
            "roll call begins",
            "meeting adjourned",
        ]
        queued = review_store.list(asset_id=_ASSET_ID)
        assert len(queued) == 3
        assert {item.status for item in queued} == {"pending"}
        assert result.created_review_item_ids == [item.review_item_id for item in queued]

    def test_model_confidence_drives_low_confidence_not_a_flush_artifact(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=4.0)
        review_store = InMemoryCaptionReviewStore()

        result = transcribe_asset_captions(
            _ScriptedRuntime(["inaudible cross talk"], confidence=0.4),
            review_store,
            asset_id=_ASSET_ID,
            source_path=source,
            chunk_seconds=2.0,
        )

        assert result.cues and all(cue.low_confidence for cue in result.cues)

        confident = InMemoryCaptionReviewStore()
        clear = transcribe_asset_captions(
            _ScriptedRuntime(["the motion carries"], confidence=0.97),
            confident,
            asset_id=_ASSET_ID,
            source_path=source,
            chunk_seconds=2.0,
        )
        assert clear.cues and not any(cue.low_confidence for cue in clear.cues)

    def test_low_confidence_cue_retains_approvable_audio_evidence(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        """A low-confidence offline cue must not be stuck forever.

        The review store's ``require_low_confidence_approval_evidence`` (and
        the operator console's ReviewQueueScreen, which disables the
        Approve button without it) both require retained, verifiable audio
        before a low-confidence cue can be approved. Without a durable
        ``audio_evidence_factory`` the extracted WAV is deleted with the
        offline transcription's temp dir, so the review row is created with
        no evidence and can never be approved -- an operator is stuck.
        """
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        review_store = InMemoryCaptionReviewStore()

        result = transcribe_asset_captions(
            _ScriptedRuntime(["inaudible cross talk"], confidence=0.4),
            review_store,
            asset_id=_ASSET_ID,
            source_path=source,
            package_dir=package_dir,
            chunk_seconds=2.0,
        )

        assert result.cues and all(cue.low_confidence for cue in result.cues)
        queued = review_store.list(asset_id=_ASSET_ID)
        assert queued
        assert all(item.audio_evidence_available for item in queued)

        evidence_dir = package_dir / "captions" / "evidence"
        assert evidence_dir.is_dir()
        assert list(evidence_dir.glob("*.wav"))

        # The real proof: approval must actually succeed, not just report
        # ``audio_evidence_available``.
        for item in queued:
            approved = review_store.approve(
                item.review_item_id,
                CaptionReviewDecision(low_confidence_acknowledged=True),
            )
            assert approved.status == "approved"

    def test_publishes_nothing_by_itself(self, tmp_path: Path, fake_ffmpeg: None) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=4.0)
        package_dir = _package(tmp_path / "packages")

        transcribe_asset_captions(
            _ScriptedRuntime(),
            InMemoryCaptionReviewStore(),
            asset_id=_ASSET_ID,
            source_path=source,
            chunk_seconds=2.0,
        )

        # Spec §4.1: no AI text on a public surface without operator review.
        assert not (package_dir / "captions").exists()
        assert "SUBTITLES" not in (package_dir / "playlist.m3u8").read_text(encoding="utf-8")

    def test_rerun_reports_duplicates_instead_of_clobbering_decisions(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=4.0)
        review_store = InMemoryCaptionReviewStore()
        runtime = _ScriptedRuntime(["motion carries"])

        first = transcribe_asset_captions(
            runtime,
            review_store,
            asset_id=_ASSET_ID,
            source_path=source,
            chunk_seconds=2.0,
        )
        _approve_all(review_store)
        second = transcribe_asset_captions(
            _ScriptedRuntime(["motion carries"]),
            review_store,
            asset_id=_ASSET_ID,
            source_path=source,
            chunk_seconds=2.0,
        )

        assert second.created_review_item_ids == []
        assert sorted(second.duplicate_review_item_ids) == sorted(first.created_review_item_ids)
        assert {item.status for item in review_store.list(asset_id=_ASSET_ID)} == {"approved"}

    def test_silent_recording_produces_no_cues(self, tmp_path: Path, fake_ffmpeg: None) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=4.0)
        review_store = InMemoryCaptionReviewStore()

        class _SilentRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                return []

        result = transcribe_asset_captions(
            _SilentRuntime(),
            review_store,
            asset_id=_ASSET_ID,
            source_path=source,
            chunk_seconds=2.0,
        )

        assert result.cues == []
        assert review_store.list(asset_id=_ASSET_ID) == []


# ---------------------------------------------------------------------------
# the approval gate
# ---------------------------------------------------------------------------


class TestReviewedCaptionCues:
    def test_pending_rows_hold_the_track_back(self) -> None:
        store = InMemoryCaptionReviewStore()
        _seed_review_items(store, ["one", "two"])
        store.approve(f"{_ASSET_ID}:cue-a", CaptionReviewDecision())

        reviewed = reviewed_caption_cues(store, _ASSET_ID)

        assert reviewed.pending == 1
        assert reviewed.review_complete is False

    def test_edited_text_wins_and_rejected_cues_are_dropped(self) -> None:
        store = InMemoryCaptionReviewStore()
        _seed_review_items(store, ["motoin carries", "roll call", "cross talk"])
        store.edit(f"{_ASSET_ID}:cue-a", CaptionReviewEdit(text="Motion carries."))
        store.approve(f"{_ASSET_ID}:cue-b", CaptionReviewDecision())
        store.reject(f"{_ASSET_ID}:cue-c", CaptionReviewDecision())

        reviewed = reviewed_caption_cues(store, _ASSET_ID)

        assert reviewed.review_complete is True
        assert [cue.text for cue in reviewed.cues] == ["Motion carries.", "roll call"]
        assert (reviewed.approved, reviewed.edited, reviewed.rejected) == (1, 1, 1)


def _seed_review_items(store: InMemoryCaptionReviewStore, texts: list[str]) -> None:
    from civiccast.captions.review import CaptionReviewItemCreate

    for index, text in enumerate(texts):
        cue_id = f"cue-{chr(ord('a') + index)}"
        store.create(
            CaptionReviewItemCreate(
                review_item_id=f"{_ASSET_ID}:{cue_id}",
                asset_id=_ASSET_ID,
                cue=_cue(cue_id, index * 2.0, index * 2.0 + 1.8, text),
            )
        )


# ---------------------------------------------------------------------------
# stage two: attach to the published package
# ---------------------------------------------------------------------------


class TestAttachReviewedCaptions:
    def test_writes_hls_track_manifest_entry_and_flat_sidecar(self, tmp_path: Path) -> None:
        package_dir = _package(tmp_path / "packages")

        attached = attach_reviewed_captions(
            package_dir,
            [_cue("cue-000000", 0.0, 1.8, "Motion carries."), _cue("cue-000001", 2.0, 3.6, "Aye.")],
        )

        manifest = (package_dir / "playlist.m3u8").read_text(encoding="utf-8")
        assert "#EXT-X-MEDIA:TYPE=SUBTITLES" in manifest
        assert 'URI="captions/en/playlist.m3u8"' in manifest
        assert 'SUBTITLES="subtitles"' in manifest
        assert (package_dir / "captions" / "en" / "playlist.m3u8").is_file()

        sidecar = published_caption_sidecar(package_dir)
        assert attached.sidecar_path == sidecar
        body = sidecar.read_text(encoding="utf-8")
        assert body.startswith("WEBVTT")
        assert "Motion carries." in body and "Aye." in body
        assert attached.cue_count == 2

    def test_only_renditions_present_on_disk_are_redeclared(self, tmp_path: Path) -> None:
        package_dir = _package(tmp_path / "packages")
        shutil.rmtree(package_dir / "1080p")

        resolved = resolve_vod_package(package_dir)

        assert [rendition.config.name for rendition in resolved.renditions] == [
            "720p",
            "480p",
            "240p",
            "slate",
        ]

    def test_unpackaged_asset_is_refused_with_an_actionable_error(self, tmp_path: Path) -> None:
        with pytest.raises(OfflineCaptionPackageError, match="No packaged media"):
            resolve_vod_package(tmp_path / "nothing-here")

    def test_refuses_to_publish_an_empty_track(self, tmp_path: Path) -> None:
        package_dir = _package(tmp_path / "packages")

        with pytest.raises(ValueError, match="At least one reviewed cue"):
            attach_reviewed_captions(package_dir, [])


# ---------------------------------------------------------------------------
# the job/worker
# ---------------------------------------------------------------------------


def _worker(
    job_store: InMemoryOfflineCaptionJobStore,
    review_store: InMemoryCaptionReviewStore,
    runtime: object,
    *,
    tmp_path: Path,
    max_attempts: int = 3,
) -> OfflineCaptionJobWorker:
    return OfflineCaptionJobWorker(
        job_store,
        review_store,
        runtime_factory=lambda: runtime,  # type: ignore[arg-type,return-value]
        settings=OfflineCaptionJobSettings(
            max_attempts=max_attempts,
            backoff_seconds=60.0,
            chunk_seconds=2.0,
            # TEST FIXTURE ONLY. Spanish is required in every shipping
            # profile -- OfflineCaptionJobSettings.from_env cannot produce
            # this value, and CIVICCAST_OFFLINE_CAPTION_SPANISH=off now
            # raises rather than setting it (see
            # TestSpanishIsNotOptional). It is set here so the tests in
            # TestOfflineCaptionJobWorker can exercise the ENGLISH half of
            # the two-phase job on its own; the Spanish half, and the fact
            # that it cannot be skipped, are covered by
            # TestTwoPhaseSpanishWorker and TestSpanishIsNotOptional.
            spanish_enabled=False,
        ),
        # A real (not mocked) policy scoped to the test's own tmp_path --
        # OfflineCaptionJobWorker defaults this to the real VOD package root
        # under CIVICCAST_UPLOAD_DIR (resolve_vod_package_root) when not
        # given, which every test here must avoid touching.
        retention_policy=CaptionEvidenceRetentionPolicy.from_system(
            storage_root=tmp_path / "egress"
        ),
    )


class TestOfflineCaptionJobWorker:
    def test_enqueue_is_idempotent_per_asset(self, tmp_path: Path) -> None:
        store = InMemoryOfflineCaptionJobStore()
        kwargs = {
            "asset_id": _ASSET_ID,
            "source_path": tmp_path / "meeting.wav",
            "package_dir": tmp_path / "packages" / _ASSET_ID,
        }

        first = enqueue_offline_caption_job(store, **kwargs)  # type: ignore[arg-type]
        second = enqueue_offline_caption_job(store, **kwargs)  # type: ignore[arg-type]

        assert first.job_id == second.job_id
        assert first.state == OFFLINE_CAPTION_JOB_STATE_PENDING

    def test_full_run_transcribes_waits_for_review_then_publishes(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=4.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = _worker(
            job_store, review_store, _ScriptedRuntime(["motion carries", "aye"]), tmp_path=tmp_path
        )
        job = enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )

        # Stage one: transcribe and queue for review; nothing published.
        # (Retained per-cue audio evidence *does* land under
        # package_dir/captions/evidence/ at this stage -- see
        # TestTranscribeAssetCaptions.test_low_confidence_cue_retains_approvable_audio_evidence
        # -- so the negative assertion checks the actual publish artifacts,
        # not just directory existence.)
        after_transcribe = worker.run_once()[0]
        assert after_transcribe.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert after_transcribe.cue_count == 2
        assert not published_caption_sidecar(package_dir).exists()
        assert "SUBTITLES" not in (package_dir / "playlist.m3u8").read_text(encoding="utf-8")

        # A poll while the operator is still deciding must not publish.
        waiting = worker.run_once()[0]
        assert waiting.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert not published_caption_sidecar(package_dir).exists()
        assert "SUBTITLES" not in (package_dir / "playlist.m3u8").read_text(encoding="utf-8")

        _approve_all(review_store)

        published = worker.run_once()[0]
        assert published.job_id == job.job_id
        assert published.state == OFFLINE_CAPTION_JOB_STATE_COMPLETE
        assert published.published_cue_count == 2
        assert published.next_attempt_at is None
        assert "#EXT-X-MEDIA:TYPE=SUBTITLES" in (package_dir / "playlist.m3u8").read_text(
            encoding="utf-8"
        )
        assert "motion carries" in published_caption_sidecar(package_dir).read_text(
            encoding="utf-8"
        )

    def test_operator_edits_are_what_reach_the_published_file(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = _worker(
            job_store, review_store, _ScriptedRuntime(["motoin carrys"]), tmp_path=tmp_path
        )
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()

        queued = review_store.list(asset_id=_ASSET_ID)
        review_store.edit(queued[0].review_item_id, CaptionReviewEdit(text="Motion carries."))
        worker.run_once()

        body = published_caption_sidecar(package_dir).read_text(encoding="utf-8")
        assert "Motion carries." in body
        assert "motoin carrys" not in body

    def test_a_fully_rejected_queue_holds_the_job_instead_of_completing(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        """Rejecting every English cue must not mark the recording captioned.

        This used to complete with ``published_cue_count == 0``: a published
        recording reported as done by the caption job while carrying no track
        in any language. Same failure shape as an English-only publish, so it
        gets the same treatment -- held, with the operator's move on the row.
        """
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = _worker(job_store, review_store, _ScriptedRuntime(["garbled"]), tmp_path=tmp_path)
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()

        for item in review_store.list(asset_id=_ASSET_ID):
            review_store.reject(item.review_item_id, CaptionReviewDecision())
        held = worker.run_once()[0]

        assert held.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert held.last_error == ALL_ENGLISH_REJECTED_REMEDIATION
        # Held on a human decision, so the retry budget is untouched.
        assert held.attempts == 0
        assert held.published_cue_count == 0
        # Retained review audio evidence lands under package_dir/captions/
        # even though nothing was published -- see the comment in
        # test_full_run_transcribes_waits_for_review_then_publishes.
        assert not published_caption_sidecar(package_dir).exists()
        assert "SUBTITLES" not in (package_dir / "playlist.m3u8").read_text(encoding="utf-8")

        # Idempotent hold (the poll runs every 60s while the operator
        # decides): a second tick with nothing changed rewrites nothing.
        again = worker.run_once()[0]
        assert again.updated_at == held.updated_at
        assert again.last_error == ALL_ENGLISH_REJECTED_REMEDIATION

    def test_a_silent_recording_completes_without_review_work(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()

        class _SilentRuntime:
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                return []

        worker = _worker(job_store, review_store, _SilentRuntime(), tmp_path=tmp_path)
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )

        done = worker.run_once()[0]

        assert done.state == OFFLINE_CAPTION_JOB_STATE_COMPLETE
        assert done.cue_count == 0

    def test_transcription_failure_backs_off_then_gives_up_loudly(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        job_store = InMemoryOfflineCaptionJobStore()
        worker = _worker(
            job_store,
            InMemoryCaptionReviewStore(),
            _ExplodingRuntime(),
            max_attempts=2,
            tmp_path=tmp_path,
        )
        now = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
        enqueue_offline_caption_job(
            job_store,
            asset_id=_ASSET_ID,
            source_path=source,
            package_dir=tmp_path / "packages" / _ASSET_ID,
            now=now,
        )

        first = worker.run_once(now=now)[0]
        assert first.state == OFFLINE_CAPTION_JOB_STATE_PENDING
        assert first.attempts == 1
        assert first.next_attempt_at == now + timedelta(seconds=60)
        assert "caption model failed to load" in first.last_error

        # Not due yet -- the backoff is honored, not ignored.
        assert worker.run_once(now=now + timedelta(seconds=30)) == []

        second = worker.run_once(now=now + timedelta(seconds=90))[0]
        assert second.state == OFFLINE_CAPTION_JOB_STATE_FAILED
        assert second.next_attempt_at is None
        assert second.last_error

    def test_attach_failure_does_not_burn_the_transcription_budget(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = _worker(
            job_store, review_store, _ScriptedRuntime(["motion carries"]), tmp_path=tmp_path
        )
        # Deliberately points at a directory with no package in it.
        enqueue_offline_caption_job(
            job_store,
            asset_id=_ASSET_ID,
            source_path=source,
            package_dir=tmp_path / "packages" / _ASSET_ID,
        )
        transcribed = worker.run_once()[0]
        assert transcribed.attempts == 0

        _approve_all(review_store)
        failed = worker.run_once()[0]

        assert failed.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert failed.attempts == 1
        assert "No packaged media" in failed.last_error

    def test_the_model_is_only_loaded_when_there_is_work(self, tmp_path: Path) -> None:
        loads: list[int] = []

        def _factory() -> _ScriptedRuntime:
            loads.append(1)
            return _ScriptedRuntime()

        worker = OfflineCaptionJobWorker(
            InMemoryOfflineCaptionJobStore(),
            InMemoryCaptionReviewStore(),
            runtime_factory=_factory,  # type: ignore[arg-type]
            settings=OfflineCaptionJobSettings(),
            retention_policy=CaptionEvidenceRetentionPolicy.from_system(
                storage_root=tmp_path / "egress"
            ),
        )

        assert worker.run_once() == []
        assert loads == []


class _RetentionSweepSpy:
    """Records ``enforce_discovered`` calls; never touches disk.

    Structurally satisfies the one method ``OfflineCaptionJobWorker`` calls
    on its injected ``CaptionEvidenceRetentionPolicy`` -- duck-typed the
    same way ``_ScriptedRuntime``/``_ExplodingRuntime`` stand in for
    ``CaptionRuntime`` elsewhere in this file.
    """

    def __init__(
        self,
        *,
        raises: bool = False,
        ready: bool = True,
        refusal_reason: str | None = None,
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._raises = raises
        self._ready = ready
        self._refusal_reason = refusal_reason

    def enforce_discovered(
        self,
        *,
        tap_root: Path | None,
        review_store: object,
        segment_seconds: float,
    ) -> CaptionRetentionResult:
        self.calls.append(
            {
                "tap_root": tap_root,
                "review_store": review_store,
                "segment_seconds": segment_seconds,
            }
        )
        if self._raises:
            raise RuntimeError("disk is on fire")
        return CaptionRetentionResult(
            ready=self._ready,
            refusal_reason=self._refusal_reason,
            requires_fallback_slate=not self._ready,
        )


class TestOfflineCaptionJobRetentionSweep:
    """Audit finding (MAJOR): offline caption evidence WAVs never pruned
    without a live channel.

    ``CaptionEvidenceRetentionPolicy`` (civiccast/captions/retention.py)
    prunes retained audio-evidence WAVs, but its only caller was the live
    channel readiness tick in tap_worker.py -- a station doing offline/VOD
    captioning with no airing live channel never pruned these WAVs. These
    tests pin that ``OfflineCaptionJobWorker.run_once`` now triggers the
    same sweep, on the same review store, every tick -- and that a sweep
    failure never fails the caption job it runs alongside.
    """

    def test_run_once_sweeps_retention_even_with_no_due_work(self) -> None:
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        spy = _RetentionSweepSpy()
        worker = OfflineCaptionJobWorker(
            job_store,
            review_store,
            runtime_factory=lambda: _ScriptedRuntime(),  # type: ignore[arg-type,return-value]
            settings=OfflineCaptionJobSettings(),
            retention_policy=spy,  # type: ignore[arg-type]
        )

        assert worker.run_once() == []

        assert len(spy.calls) == 1
        assert spy.calls[0]["tap_root"] is None
        assert spy.calls[0]["review_store"] is review_store

    def test_run_once_sweeps_retention_alongside_real_job_processing(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        spy = _RetentionSweepSpy()
        worker = OfflineCaptionJobWorker(
            job_store,
            review_store,
            runtime_factory=lambda: _ScriptedRuntime(["motion carries"]),  # type: ignore[arg-type,return-value]
            settings=OfflineCaptionJobSettings(chunk_seconds=2.0),
            retention_policy=spy,  # type: ignore[arg-type]
        )
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )

        processed = worker.run_once()

        assert len(processed) == 1
        assert processed[0].state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert len(spy.calls) == 1

    def test_a_retention_sweep_failure_never_fails_the_caption_job(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = OfflineCaptionJobWorker(
            job_store,
            review_store,
            runtime_factory=lambda: _ScriptedRuntime(["motion carries"]),  # type: ignore[arg-type,return-value]
            settings=OfflineCaptionJobSettings(chunk_seconds=2.0),
            retention_policy=_RetentionSweepSpy(raises=True),  # type: ignore[arg-type]
        )
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )

        processed = worker.run_once()

        assert len(processed) == 1
        assert processed[0].state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW

    def test_run_once_skips_all_job_processing_when_retention_refuses_storage(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        """Audit finding (P1, vod_job.py:516): the refusal used to be

        discarded and ``run_once`` transcribed every due job regardless of
        what the sweep found. Mirrors
        ``CaptionTapWorker.run_once``'s own predicate: a clean not-ready
        result (free-space reserve breached, or the storage cap still
        exceeded after pruning) must gate processing so this worker stops
        creating new evidence WAVs under storage pressure -- both stage one
        (transcription, which writes evidence) and stage two (publish, so a
        job never half-advances on a tick the policy refused).
        """

        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        spy = _RetentionSweepSpy(ready=False, refusal_reason="storage-cap-unrestorable")
        worker = OfflineCaptionJobWorker(
            job_store,
            review_store,
            runtime_factory=lambda: _ScriptedRuntime(["motion carries"]),  # type: ignore[arg-type,return-value]
            settings=OfflineCaptionJobSettings(chunk_seconds=2.0),
            retention_policy=spy,  # type: ignore[arg-type]
        )
        job = enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )

        processed = worker.run_once()

        # Empty/unchanged processed list on refusal, consistent with
        # CaptionTapWorker's own refusal behavior.
        assert processed == []
        assert len(spy.calls) == 1
        still_pending = job_store.get(job.job_id)
        assert still_pending is not None
        assert still_pending.state == OFFLINE_CAPTION_JOB_STATE_PENDING
        assert still_pending.attempts == 0
        # No evidence WAV was created for this tick -- the whole point of
        # the gate.
        assert not (package_dir / "captions" / "evidence").exists()

        # Once storage recovers, the same due job proceeds normally.
        spy._ready = True  # simulate the next tick's re-measured free space
        resumed = worker.run_once()
        assert len(resumed) == 1
        assert resumed[0].job_id == job.job_id
        assert resumed[0].state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW

    def test_defaults_to_the_real_policy_against_the_offline_evidence_volume(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No injected policy -- production wiring (app.py) relies on this
        default.

        Audit finding (P1, vod_job.py:538): the default used to be built
        against ``default_egress_work_dir()`` -- the *live* tap volume --
        which can be a different filesystem than where offline evidence
        WAVs actually land (``<package_dir>/captions/evidence/*.wav``,
        under the VOD package tree). The default must instead measure the
        VOD package root: ``resolve_vod_package_root(CIVICCAST_UPLOAD_DIR)``,
        the same resolution every queued job's own ``package_dir`` already
        uses (civiccast.publish.router._queue_offline_captions via
        resolve_vod_package_dir).

        The default must also still not be built until the first tick: see
        ``test_run_once_sweeps_retention_even_with_no_due_work``'s sibling
        assertion in the pre-fix version of this test -- constructing the
        worker itself must never touch the filesystem.
        """

        upload_dir = tmp_path / "uploads"
        egress_dir = tmp_path / "egress"
        monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(upload_dir))
        # A decoy on a conceptually "different volume" -- if the worker
        # still measured this directory instead, this test would not catch
        # it turning up empty (both are real local tmp dirs), so the
        # meaningful assertion below is which directory got created/
        # measured, not a cross-filesystem free-space difference.
        monkeypatch.setenv("CIVICCAST_EGRESS_WORK_DIR", str(egress_dir))
        worker = OfflineCaptionJobWorker(
            InMemoryOfflineCaptionJobStore(),
            InMemoryCaptionReviewStore(),
            runtime_factory=lambda: _ScriptedRuntime(),  # type: ignore[arg-type,return-value]
            settings=OfflineCaptionJobSettings(),
        )

        assert worker._retention_policy is None
        assert not upload_dir.exists()
        assert not egress_dir.exists()

        assert worker.run_once() == []

        assert isinstance(worker._retention_policy, CaptionEvidenceRetentionPolicy)
        expected_root = (upload_dir / ".civiccast-packages").resolve()
        assert worker._retention_policy._storage_root == expected_root
        assert expected_root.is_dir()
        # The live tap volume was never touched by the offline worker's
        # default policy.
        assert not egress_dir.exists()

    def test_missing_upload_dir_is_a_logged_sweep_failure_not_a_crash(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No ``CIVICCAST_UPLOAD_DIR`` configured -- no queued job could

        have a real ``package_dir`` in this configuration (see
        ``_queue_offline_captions``), so this is only reachable before any
        real job exists. It must not crash the worker or be treated as a
        storage refusal; ``_retention_policy_instance`` raises, caught by
        ``_sweep_retention``'s existing try/except, same as any other sweep
        failure.
        """

        monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
        monkeypatch.delenv("CIVICCAST_VOD_PACKAGE_DIR", raising=False)
        worker = OfflineCaptionJobWorker(
            InMemoryOfflineCaptionJobStore(),
            InMemoryCaptionReviewStore(),
            runtime_factory=lambda: _ScriptedRuntime(),  # type: ignore[arg-type,return-value]
            settings=OfflineCaptionJobSettings(),
        )

        assert worker.run_once() == []
        assert worker._retention_policy is None


class TestOfflineCaptionJobSettings:
    def test_rejects_an_unknown_mode_at_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_JOB", "maybe")

        with pytest.raises(ValueError, match="CIVICCAST_OFFLINE_CAPTION_JOB"):
            OfflineCaptionJobSettings.from_env()

    def test_rejects_a_non_positive_poll_interval(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_POLL_SECONDS", "0")

        with pytest.raises(ValueError, match="greater than zero"):
            OfflineCaptionJobSettings.from_env()

    def test_off_mode_is_accepted_only_with_the_test_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``off`` is reachable for tests, and ONLY for tests.

        See TestCaptionsCannotBeSwitchedOff for the station-facing half: the
        same value without this override refuses to start.
        """

        monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_JOB", "off")
        monkeypatch.setenv(CAPTIONS_OFF_TEST_OVERRIDE_ENV, "1")

        assert OfflineCaptionJobSettings.from_env().mode == "off"


class TestCaptionTrackReuse:
    def test_offline_attach_produces_the_same_track_shape_as_the_live_helper(
        self, tmp_path: Path
    ) -> None:
        """The offline path must not fork the HLS caption writer."""

        package_dir = _package(tmp_path / "packages")
        cues = [_cue("cue-000000", 0.0, 1.8, "Motion carries.")]

        attach_reviewed_captions(package_dir, cues)
        expected = write_hls_caption_track(CaptionHlsTrack(cues=cues), tmp_path / "reference")

        assert (package_dir / "captions" / "en" / "playlist.m3u8").read_text(
            encoding="utf-8"
        ) == expected.playlist_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# recorded-Spanish captions (owner requirement: a published recording carries
# an operator-reviewed Spanish track alongside English)
# ---------------------------------------------------------------------------


def _approve_language(
    store: InMemoryCaptionReviewStore,
    language: str,
    *,
    asset_id: str = _ASSET_ID,
) -> list[str]:
    """Approve every pending row in one language queue; return the ids."""

    approved: list[str] = []
    for item in store.list(asset_id=asset_id, language=language):
        if item.status == "pending":
            store.approve(item.review_item_id, CaptionReviewDecision())
            approved.append(item.review_item_id)
    return approved


class TestQueueTranslatedCaptions:
    def test_spanish_rows_are_queued_low_confidence_false_and_approvable_without_audio(
        self,
    ) -> None:
        """THE LANDMINE. A Spanish cue is a translation with no ASR audio.

        ``require_low_confidence_approval_evidence`` blocks approval of any
        low_confidence cue lacking retained audio evidence -- so if Spanish
        rows were queued low_confidence=True they could NEVER be approved and
        the Spanish track would deadlock. This proves they are queued
        low_confidence=False and can be approved with no audio evidence at
        all (no acknowledgement, no retained WAV).
        """

        review_store = InMemoryCaptionReviewStore()
        english_cues = [
            _cue("cue-000000", 0.0, 1.8, "motion carries"),
            _cue("cue-000001", 2.0, 3.6, "public comment"),
        ]

        queued = queue_translated_captions(
            review_store,
            asset_id=_ASSET_ID,
            cues=english_cues,
            provider=DeterministicSpanishTranslator(),
        )

        spanish_rows = review_store.list(asset_id=_ASSET_ID, language="es")
        assert len(spanish_rows) == 2
        assert [row.review_item_id for row in spanish_rows] == queued.created_review_item_ids
        # Every Spanish row is low_confidence=False and carries no audio
        # evidence -- the two facts that together prove the landmine is
        # defused.
        assert all(not row.low_confidence for row in spanish_rows)
        assert all(not row.audio_evidence_available for row in spanish_rows)

        # The real proof: approval SUCCEEDS with a bare decision (no
        # low_confidence_acknowledged, no evidence) -- which would raise
        # CaptionReviewAudioEvidenceRequiredError for a low_confidence cue.
        for row in spanish_rows:
            approved = review_store.approve(row.review_item_id, CaptionReviewDecision())
            assert approved.status == "approved"

    def test_spanish_rows_are_scoped_to_es_and_do_not_pollute_the_english_queue(
        self,
    ) -> None:
        review_store = InMemoryCaptionReviewStore()
        # Seed an English row the way transcription would.
        from civiccast.captions.review import CaptionReviewItemCreate

        review_store.create(
            CaptionReviewItemCreate(
                review_item_id=f"{_ASSET_ID}:cue-000000",
                asset_id=_ASSET_ID,
                cue=_cue("cue-000000", 0.0, 1.8, "motion carries"),
            )
        )

        queue_translated_captions(
            review_store,
            asset_id=_ASSET_ID,
            cues=[_cue("cue-000000", 0.0, 1.8, "motion carries")],
            provider=DeterministicSpanishTranslator(),
        )

        english = review_store.list(asset_id=_ASSET_ID, language="en")
        spanish = review_store.list(asset_id=_ASSET_ID, language="es")
        assert [row.review_item_id for row in english] == [f"{_ASSET_ID}:cue-000000"]
        assert [row.review_item_id for row in spanish] == [f"{_ASSET_ID}:cue-000000:es"]
        # reviewed_caption_cues gates per-language: the two queues never mix.
        assert reviewed_caption_cues(review_store, _ASSET_ID, language="en").total == 1
        assert reviewed_caption_cues(review_store, _ASSET_ID, language="es").total == 1

    def test_rerun_reports_duplicates_instead_of_reclobbering_spanish_decisions(
        self,
    ) -> None:
        review_store = InMemoryCaptionReviewStore()
        english_cues = [_cue("cue-000000", 0.0, 1.8, "motion carries")]

        first = queue_translated_captions(
            review_store,
            asset_id=_ASSET_ID,
            cues=english_cues,
            provider=DeterministicSpanishTranslator(),
        )
        _approve_language(review_store, "es")
        second = queue_translated_captions(
            review_store,
            asset_id=_ASSET_ID,
            cues=english_cues,
            provider=DeterministicSpanishTranslator(),
        )

        assert second.created_review_item_ids == []
        assert second.duplicate_review_item_ids == first.created_review_item_ids
        assert {row.status for row in review_store.list(asset_id=_ASSET_ID, language="es")} == {
            "approved"
        }

    def test_translate_then_attach_produces_two_tracks_and_two_sidecars(
        self, tmp_path: Path
    ) -> None:
        package_dir = _package(tmp_path / "packages")
        english_cues = [_cue("cue-000000", 0.0, 1.8, "motion carries")]
        spanish_cues = [_cue("cue-000000:es", 0.0, 1.8, "la mocion se aprueba")]

        attached = attach_reviewed_captions(package_dir, english_cues, spanish_cues=spanish_cues)

        manifest = (package_dir / "playlist.m3u8").read_text(encoding="utf-8")
        assert manifest.count("#EXT-X-MEDIA:TYPE=SUBTITLES") == 2
        assert 'LANGUAGE="en"' in manifest and 'LANGUAGE="es"' in manifest
        assert (package_dir / "captions" / "en" / "playlist.m3u8").is_file()
        assert (package_dir / "captions" / "es" / "playlist.m3u8").is_file()

        assert attached.spanish_cue_count == 1
        assert attached.spanish_sidecar_path == published_spanish_caption_sidecar(package_dir)
        english_body = published_caption_sidecar(package_dir).read_text(encoding="utf-8")
        spanish_body = attached.spanish_sidecar_path.read_text(encoding="utf-8")
        assert "motion carries" in english_body
        assert "la mocion se aprueba" in spanish_body


def _spanish_worker(
    job_store: InMemoryOfflineCaptionJobStore,
    review_store: InMemoryCaptionReviewStore,
    runtime: object,
    *,
    tmp_path: Path,
    max_attempts: int = 3,
) -> OfflineCaptionJobWorker:
    """A fully wired worker: English transcription plus the required Spanish leg.

    Deliberately does NOT expose a ``spanish_enabled`` knob -- there is no
    shipping profile that turns the Spanish leg off, and a test helper that
    offered one would invite a test asserting behavior the product does not
    have. The one place the field is set to ``False`` is ``_worker`` above,
    which exercises the English half in isolation and says so.
    """

    return OfflineCaptionJobWorker(
        job_store,
        review_store,
        runtime_factory=lambda: runtime,  # type: ignore[arg-type,return-value]
        translation_provider_factory=DeterministicSpanishTranslator,
        settings=OfflineCaptionJobSettings(
            max_attempts=max_attempts,
            backoff_seconds=60.0,
            chunk_seconds=2.0,
        ),
        retention_policy=CaptionEvidenceRetentionPolicy.from_system(
            storage_root=tmp_path / "egress"
        ),
    )


class TestTwoPhaseSpanishWorker:
    def test_english_then_spanish_then_both_tracks_attached(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=4.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = _spanish_worker(
            job_store,
            review_store,
            _ScriptedRuntime(["motion carries", "public comment"]),
            tmp_path=tmp_path,
        )
        job = enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )

        # Stage one: transcribe English, queue for review.
        after_transcribe = worker.run_once()[0]
        assert after_transcribe.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert review_store.list(asset_id=_ASSET_ID, language="es") == []

        # A poll before English is decided must not publish or translate.
        assert worker.run_once()[0].state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert review_store.list(asset_id=_ASSET_ID, language="es") == []
        assert not published_caption_sidecar(package_dir).exists()

        # English approved -> the next poll queues Spanish for its OWN review
        # pass but publishes NOTHING (Spanish still pending).
        _approve_language(review_store, "en")
        gated = worker.run_once()[0]
        assert gated.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        spanish_rows = review_store.list(asset_id=_ASSET_ID, language="es")
        assert len(spanish_rows) == 2
        assert {row.status for row in spanish_rows} == {"pending"}
        assert not published_caption_sidecar(package_dir).exists()
        assert "SUBTITLES" not in (package_dir / "playlist.m3u8").read_text(encoding="utf-8")

        # Another poll while Spanish is under review still must not publish.
        assert worker.run_once()[0].state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert not published_caption_sidecar(package_dir).exists()

        # Spanish approved -> both tracks attach on the next poll.
        _approve_language(review_store, "es")
        published = worker.run_once()[0]
        assert published.job_id == job.job_id
        assert published.state == OFFLINE_CAPTION_JOB_STATE_COMPLETE
        assert published.published_cue_count == 2

        manifest = (package_dir / "playlist.m3u8").read_text(encoding="utf-8")
        assert manifest.count("#EXT-X-MEDIA:TYPE=SUBTITLES") == 2
        assert 'LANGUAGE="es"' in manifest
        assert published_caption_sidecar(package_dir).is_file()
        assert published_spanish_caption_sidecar(package_dir).is_file()
        spanish_body = published_spanish_caption_sidecar(package_dir).read_text(encoding="utf-8")
        # DeterministicSpanishTranslator maps these civic phrases.
        assert "la mocion se aprueba" in spanish_body
        assert "comentario publico" in spanish_body

    def test_translation_runs_once_not_on_every_poll(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        """Waiting on Spanish review must not re-invoke the model each poll."""

        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()

        class _CountingTranslator(DeterministicSpanishTranslator):
            calls = 0

            def translate_text(self, text: str, **kwargs: object) -> str:  # type: ignore[override]
                type(self).calls += 1
                return super().translate_text(text, **kwargs)  # type: ignore[arg-type]

        _CountingTranslator.calls = 0
        worker = OfflineCaptionJobWorker(
            job_store,
            review_store,
            runtime_factory=lambda: _ScriptedRuntime(["motion carries"]),  # type: ignore[arg-type,return-value]
            translation_provider_factory=_CountingTranslator,
            settings=OfflineCaptionJobSettings(chunk_seconds=2.0, backoff_seconds=60.0),
            retention_policy=CaptionEvidenceRetentionPolicy.from_system(
                storage_root=tmp_path / "egress"
            ),
        )
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()  # transcribe
        _approve_language(review_store, "en")
        worker.run_once()  # translate + queue Spanish
        assert _CountingTranslator.calls == 1
        worker.run_once()  # poll while Spanish pending
        worker.run_once()  # poll while Spanish pending
        assert _CountingTranslator.calls == 1  # never re-translated


class TestCdnRepublishGatesCompletion:
    """A green job must not sit on top of a stale CDN copy.

    Caption attach rewrites the LOCAL package. When the asset's package is
    served through a CDN, the job is only really done once the rewritten
    manifest and both caption tracks are back on that CDN -- so a republish
    failure fails the job (with the provider's message on the row) rather
    than completing it. Unit coverage of the republisher itself, including
    the "never CDN-published, do nothing" cases, is in
    tests/captions/test_caption_cdn_republish.py.
    """

    class _RecordingRepublisher:
        def __init__(self, error: Exception | None = None) -> None:
            self.calls: list[str] = []
            self._error = error

        def republish(self, *, asset_id: str, package_dir: Path, attached: object) -> str | None:
            self.calls.append(asset_id)
            if self._error is not None:
                raise self._error
            return "https://cdn.example.org/live/ls_abc/playlist.m3u8"

    def _run_to_attach(
        self,
        tmp_path: Path,
        republisher: object,
    ) -> tuple[OfflineCaptionJobRecord, Path]:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = OfflineCaptionJobWorker(
            job_store,
            review_store,
            runtime_factory=lambda: _ScriptedRuntime(["motion carries"]),  # type: ignore[arg-type,return-value]
            translation_provider_factory=DeterministicSpanishTranslator,
            cdn_republisher=republisher,  # type: ignore[arg-type]
            settings=OfflineCaptionJobSettings(
                max_attempts=3, backoff_seconds=60.0, chunk_seconds=2.0
            ),
            retention_policy=CaptionEvidenceRetentionPolicy.from_system(
                storage_root=tmp_path / "egress"
            ),
        )
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()
        _approve_language(review_store, "en")
        worker.run_once()  # queues Spanish
        _approve_language(review_store, "es")
        return worker.run_once()[0], package_dir

    def test_successful_republish_completes_the_job(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        republisher = self._RecordingRepublisher()
        row, package_dir = self._run_to_attach(tmp_path, republisher)

        assert row.state == OFFLINE_CAPTION_JOB_STATE_COMPLETE
        assert republisher.calls == [_ASSET_ID]
        assert published_spanish_caption_sidecar(package_dir).is_file()

    def test_republish_failure_blocks_completion_and_reports_why(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        republisher = self._RecordingRepublisher(RuntimeError("CDN refused the upload: 403"))
        row, _ = self._run_to_attach(tmp_path, republisher)

        assert row.state != OFFLINE_CAPTION_JOB_STATE_COMPLETE
        assert row.attempts == 1
        assert "CDN refused the upload: 403" in row.last_error


class TestTruncatedSpanishTrackNeverPublishes:
    """A Spanish queue that came back SHORT must never publish as complete.

    Reviewer's reproduction (PR #131): ``queue_translated_captions`` writes
    one review row per cue, so a store error partway through a long meeting
    leaves N of M rows behind. The old gate asked "does this asset have any
    Spanish rows?" -- it did -- so it never queued the rest, and once an
    operator decided those N it reported ``pending == 0`` and published an
    N-of-M Spanish track as ``complete``. Silent truncation of a legally
    required accessibility artifact.
    """

    class _FlakyStore(InMemoryCaptionReviewStore):
        """Fails every ``create`` after ``fail_after`` succeed, once."""

        def __init__(self, fail_after: int) -> None:
            super().__init__()
            self.fail_after = fail_after
            self.created = 0
            self.armed = True

        def create(self, payload: CaptionReviewItemCreate) -> CaptionReviewItemResponse:
            if self.armed and payload.language == "es":
                if self.created >= self.fail_after:
                    raise RuntimeError("review store write failed mid-batch")
                self.created += 1
            return super().create(payload)

    def _worker_for(
        self,
        job_store: InMemoryOfflineCaptionJobStore,
        review_store: InMemoryCaptionReviewStore,
        tmp_path: Path,
        transcript: list[str],
    ) -> OfflineCaptionJobWorker:
        return OfflineCaptionJobWorker(
            job_store,
            review_store,
            runtime_factory=lambda: _ScriptedRuntime(transcript),  # type: ignore[arg-type,return-value]
            translation_provider_factory=DeterministicSpanishTranslator,
            settings=OfflineCaptionJobSettings(
                max_attempts=4, backoff_seconds=60.0, chunk_seconds=2.0
            ),
            retention_policy=CaptionEvidenceRetentionPolicy.from_system(
                storage_root=tmp_path / "egress"
            ),
        )

    def test_three_of_six_spanish_rows_never_publishes_as_complete(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        transcript = [
            "motion carries",
            "public comment",
            "the meeting is called to order",
            "roll call",
            "second the motion",
            "meeting adjourned",
        ]
        source = _write_wav(tmp_path / "meeting.wav", seconds=len(transcript) * 2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = self._FlakyStore(fail_after=3)
        worker = self._worker_for(job_store, review_store, tmp_path, transcript)
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )

        worker.run_once()  # transcribe English
        english_rows = review_store.list(asset_id=_ASSET_ID, language="en")
        assert len(english_rows) == len(transcript)
        _approve_language(review_store, "en")

        # Translation dies after 3 of 6 Spanish rows.
        blocked = worker.run_once()[0]
        assert len(review_store.list(asset_id=_ASSET_ID, language="es")) == 3
        assert blocked.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert blocked.attempts == 1

        # The operator decides the 3 rows that DO exist. Under the old gate
        # this published a 3-of-6 Spanish track and marked the job complete.
        _approve_language(review_store, "es")
        still_blocked = worker.run_once(now=datetime.now(UTC) + timedelta(days=1))[0]
        assert still_blocked.state != OFFLINE_CAPTION_JOB_STATE_COMPLETE
        assert not published_spanish_caption_sidecar(package_dir).exists()
        assert "SUBTITLES" not in (package_dir / "playlist.m3u8").read_text(encoding="utf-8")

    def test_the_retry_queues_the_missing_cues_and_then_publishes_all_six(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        transcript = [
            "motion carries",
            "public comment",
            "the meeting is called to order",
            "roll call",
            "second the motion",
            "meeting adjourned",
        ]
        source = _write_wav(tmp_path / "meeting.wav", seconds=len(transcript) * 2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = self._FlakyStore(fail_after=3)
        worker = self._worker_for(job_store, review_store, tmp_path, transcript)
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()
        _approve_language(review_store, "en")
        worker.run_once()  # partial translation
        assert len(review_store.list(asset_id=_ASSET_ID, language="es")) == 3

        # Store recovers; the next attempt must queue the MISSING three, not
        # re-queue the whole batch and not give up.
        review_store.armed = False
        worker.run_once(now=datetime.now(UTC) + timedelta(days=1))
        spanish_rows = review_store.list(asset_id=_ASSET_ID, language="es")
        assert len(spanish_rows) == len(transcript)
        # Every Spanish row derives from a distinct English cue.
        assert len({row.cue.cue_id for row in spanish_rows}) == len(transcript)

        _approve_language(review_store, "es")
        done = worker.run_once(now=datetime.now(UTC) + timedelta(days=2))[0]
        assert done.state == OFFLINE_CAPTION_JOB_STATE_COMPLETE
        manifest = (package_dir / "playlist.m3u8").read_text(encoding="utf-8")
        assert manifest.count("#EXT-X-MEDIA:TYPE=SUBTITLES") == 2
        spanish_body = published_spanish_caption_sidecar(package_dir).read_text(encoding="utf-8")
        # The whole meeting is in the Spanish sidecar, first cue to last.
        assert "la mocion se aprueba" in spanish_body
        assert spanish_body.count("-->") == len(transcript)

    def test_the_short_queue_reason_on_the_row_names_the_shortfall(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        transcript = ["motion carries", "public comment", "roll call"]
        source = _write_wav(tmp_path / "meeting.wav", seconds=6.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = self._FlakyStore(fail_after=1)
        worker = self._worker_for(job_store, review_store, tmp_path, transcript)
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()
        _approve_language(review_store, "en")
        blocked = worker.run_once()[0]

        assert "1 of this recording's 3 approved" in blocked.last_error
        assert "civiccast doctor" in blocked.last_error

    def test_an_orphaned_spanish_row_neither_gates_nor_reaches_the_track(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        """A Spanish row whose English source was rejected after translation.

        It must not hold publication hostage (its decision is irrelevant) and
        must not appear on the published track (there is no English cue at
        that timestamp any more).
        """

        transcript = ["motion carries", "public comment"]
        source = _write_wav(tmp_path / "meeting.wav", seconds=4.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = self._worker_for(job_store, review_store, tmp_path, transcript)
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()
        _approve_language(review_store, "en")
        worker.run_once()  # queues both Spanish rows
        assert len(review_store.list(asset_id=_ASSET_ID, language="es")) == 2

        # The clerk goes back and rejects the SECOND English cue.
        english_rows = review_store.list(asset_id=_ASSET_ID, language="en")
        review_store.reject(english_rows[1].review_item_id, CaptionReviewDecision())
        # Only the FIRST Spanish cue is decided; the orphan stays pending.
        spanish_rows = review_store.list(asset_id=_ASSET_ID, language="es")
        review_store.approve(spanish_rows[0].review_item_id, CaptionReviewDecision())

        done = worker.run_once()[0]

        # The still-pending orphan did not gate the publish.
        assert done.state == OFFLINE_CAPTION_JOB_STATE_COMPLETE
        spanish_body = published_spanish_caption_sidecar(package_dir).read_text(encoding="utf-8")
        assert spanish_body.count("-->") == 1
        assert "comentario publico" not in spanish_body


class TestConcurrentTranslationTicks:
    """Two ticks racing to queue the same Spanish rows must not fail a job.

    Finding the Spanish queue short and queueing the missing cues is
    check-then-act with no row lock, so two workers (or a supervised tick
    overlapping a manual run) can both decide the same cue is missing. The
    guard is the same one the job-enqueue path uses: the DATABASE, via the
    ``review_item_id`` primary key. ``PostgresCaptionReviewStore.create``
    translates the losing insert's IntegrityError into
    ``CaptionReviewItemAlreadyExistsError``, which
    ``queue_translated_captions`` already records as a duplicate -- so the
    loser records duplicates instead of failing an otherwise-healthy job.

    RESIDUAL, documented rather than fixed: the losing tick still pays for
    the translation it computed before the insert lost, so a race costs
    duplicate model work (not duplicate rows, and not a failed job). Removing
    that would need a job-level lease, which is more machinery than a race
    this rare is worth; the durable outcome is already correct.
    """

    def test_the_losing_racer_records_duplicates_rather_than_failing(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=4.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()

        def _worker_instance() -> OfflineCaptionJobWorker:
            return OfflineCaptionJobWorker(
                job_store,
                review_store,
                runtime_factory=lambda: _ScriptedRuntime(["motion carries", "public comment"]),  # type: ignore[arg-type,return-value]
                translation_provider_factory=DeterministicSpanishTranslator,
                settings=OfflineCaptionJobSettings(
                    max_attempts=3, backoff_seconds=60.0, chunk_seconds=2.0
                ),
                retention_policy=CaptionEvidenceRetentionPolicy.from_system(
                    storage_root=tmp_path / "egress"
                ),
            )

        first, second = _worker_instance(), _worker_instance()
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        first.run_once()
        _approve_language(review_store, "en")

        # Two ticks over the same job, back to back: the second sees the rows
        # the first just wrote and must treat them as already queued.
        first.run_once()
        row = second.run_once()[0]

        assert row.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert row.last_error == ""
        spanish_rows = review_store.list(asset_id=_ASSET_ID, language="es")
        assert len(spanish_rows) == 2
        assert len({item.review_item_id for item in spanish_rows}) == 2

    def test_a_store_that_loses_the_insert_race_is_treated_as_a_duplicate(self) -> None:
        """The durable store's own guard, exercised directly.

        Mirrors what Postgres does under a real race: the row is already
        there when the losing session commits. The store must surface that as
        ``CaptionReviewItemAlreadyExistsError``, because that is the error
        ``queue_translated_captions`` knows how to absorb -- a raw DB error
        would escape and fail the caption job.
        """

        store = InMemoryCaptionReviewStore()
        cue = _cue("cue-000000:es", 0.0, 1.8, "la mocion se aprueba")
        payload = CaptionReviewItemCreate(
            review_item_id=f"{_ASSET_ID}:{cue.cue_id}",
            asset_id=_ASSET_ID,
            cue=cue,
            language="es",
        )
        store.create(payload)

        with pytest.raises(CaptionReviewItemAlreadyExistsError):
            store.create(payload)


class TestCaptionsCannotBeSwitchedOff:
    """Offline captioning is a legal obligation, not a performance option."""

    def test_off_refuses_to_start_without_the_test_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_JOB", "off")
        monkeypatch.delenv(CAPTIONS_OFF_TEST_OVERRIDE_ENV, raising=False)

        with pytest.raises(ValueError) as excinfo:
            OfflineCaptionJobSettings.from_env()

        message = str(excinfo.value)
        # Names the variable to remove and what the operator should do about
        # a broken caption model instead of switching captioning off.
        assert "CIVICCAST_OFFLINE_CAPTION_JOB" in message
        assert "civiccast doctor" in message
        assert "no caption track in any language" in message

    def test_inline_is_unaffected_by_the_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CIVICCAST_OFFLINE_CAPTION_JOB", raising=False)
        monkeypatch.delenv(CAPTIONS_OFF_TEST_OVERRIDE_ENV, raising=False)

        assert OfflineCaptionJobSettings.from_env().mode == "inline"

    def test_the_override_alone_does_not_switch_captions_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two coordinated variables, so neither can do it by accident."""

        monkeypatch.delenv("CIVICCAST_OFFLINE_CAPTION_JOB", raising=False)
        monkeypatch.setenv(CAPTIONS_OFF_TEST_OVERRIDE_ENV, "1")

        assert OfflineCaptionJobSettings.from_env().mode == "inline"


class TestSpanishIsNotOptional:
    """A caption-eligible recording cannot complete with English only.

    Owner requirement (Longmont is ~30% Latino): a published recording
    carries an operator-reviewed Spanish caption track alongside English.
    That is shipping behavior, not a station setting, so every route that
    used to reach a green English-only publish is pinned closed here:

    * the ``CIVICCAST_OFFLINE_CAPTION_SPANISH`` switch;
    * a station with no translation runtime wired;
    * an operator rejecting every Spanish cue.

    Each of the last two ends *blocked and actionable* -- the operator can
    read what to do off the job row -- never ``complete`` with one track.
    """

    def test_from_env_refuses_to_turn_spanish_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ("off", "0", "false", "no"):
            monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_SPANISH", value)
            with pytest.raises(ValueError, match="English captions only"):
                OfflineCaptionJobSettings.from_env()

    def test_from_env_rejects_an_unparseable_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_SPANISH", "maybe")
        with pytest.raises(ValueError, match="CIVICCAST_OFFLINE_CAPTION_SPANISH must be one of"):
            OfflineCaptionJobSettings.from_env()

    def test_from_env_always_enables_spanish(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CIVICCAST_OFFLINE_CAPTION_SPANISH", raising=False)
        assert OfflineCaptionJobSettings.from_env().spanish_enabled is True
        # A true value is the only supported behavior, so it is a no-op
        # rather than a failure -- and still yields Spanish enabled.
        monkeypatch.setenv("CIVICCAST_OFFLINE_CAPTION_SPANISH", "on")
        assert OfflineCaptionJobSettings.from_env().spanish_enabled is True

    def test_no_translation_runtime_blocks_instead_of_publishing_english(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = OfflineCaptionJobWorker(
            job_store,
            review_store,
            runtime_factory=lambda: _ScriptedRuntime(["motion carries"]),  # type: ignore[arg-type,return-value]
            # No translation_provider_factory: the station's translation
            # runtime is missing/broken.
            settings=OfflineCaptionJobSettings(
                max_attempts=2, backoff_seconds=60.0, chunk_seconds=2.0
            ),
            retention_policy=CaptionEvidenceRetentionPolicy.from_system(
                storage_root=tmp_path / "egress"
            ),
        )
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()
        _approve_language(review_store, "en")

        blocked = worker.run_once()[0]
        assert blocked.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert blocked.attempts == 1
        assert blocked.last_error == MISSING_TRANSLATOR_REMEDIATION
        # The remediation names the operator's move, not an internal symbol.
        assert "translation model" in blocked.last_error
        assert "spanish_enabled" not in blocked.last_error

        # Budget spent -> failed, and STILL nothing English-only published.
        exhausted = worker.run_once(now=datetime.now(UTC) + timedelta(days=1))[0]
        assert exhausted.state == OFFLINE_CAPTION_JOB_STATE_FAILED
        assert exhausted.last_error == MISSING_TRANSLATOR_REMEDIATION
        assert not published_caption_sidecar(package_dir).exists()
        assert "SUBTITLES" not in (package_dir / "playlist.m3u8").read_text(encoding="utf-8")

    def test_all_spanish_rejected_holds_the_job_instead_of_shipping_english(
        self, tmp_path: Path, fake_ffmpeg: None
    ) -> None:
        source = _write_wav(tmp_path / "meeting.wav", seconds=2.0)
        package_dir = _package(tmp_path / "packages")
        job_store = InMemoryOfflineCaptionJobStore()
        review_store = InMemoryCaptionReviewStore()
        worker = _spanish_worker(
            job_store, review_store, _ScriptedRuntime(["motion carries"]), tmp_path=tmp_path
        )
        enqueue_offline_caption_job(
            job_store, asset_id=_ASSET_ID, source_path=source, package_dir=package_dir
        )
        worker.run_once()
        _approve_language(review_store, "en")
        worker.run_once()  # queues Spanish
        for row in review_store.list(asset_id=_ASSET_ID, language="es"):
            review_store.reject(row.review_item_id, CaptionReviewDecision())

        held = worker.run_once()[0]
        assert held.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert held.last_error == ALL_SPANISH_REJECTED_REMEDIATION
        # Held, not failed: the retry budget is untouched because the block
        # is a human decision, not a transient fault.
        assert held.attempts == 0
        # Nothing published in either language.
        assert not published_caption_sidecar(package_dir).exists()
        assert not published_spanish_caption_sidecar(package_dir).exists()
        assert "SUBTITLES" not in (package_dir / "playlist.m3u8").read_text(encoding="utf-8")

        # The remediation is real: editing a rejected Spanish row is allowed
        # and finishes the publish with BOTH tracks on the next poll.
        rejected_row = review_store.list(asset_id=_ASSET_ID, language="es")[0]
        review_store.edit(
            rejected_row.review_item_id, CaptionReviewEdit(text="la mocion se aprueba")
        )
        done = worker.run_once()[0]
        assert done.state == OFFLINE_CAPTION_JOB_STATE_COMPLETE
        assert done.last_error == ""
        manifest = (package_dir / "playlist.m3u8").read_text(encoding="utf-8")
        assert manifest.count("#EXT-X-MEDIA:TYPE=SUBTITLES") == 2
        assert 'LANGUAGE="es"' in manifest
        assert published_caption_sidecar(package_dir).is_file()
        assert "la mocion se aprueba" in published_spanish_caption_sidecar(package_dir).read_text(
            encoding="utf-8"
        )
