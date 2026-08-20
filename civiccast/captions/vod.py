# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Offline (VOD) caption production -- the legal-compliance caption path.

Live captioning (:mod:`civiccast.captions.tap_worker`) is a *best-effort
accessibility* surface: it guesses in realtime and corrects later. This
module is the other one -- captions on the **published file**, which is
what the law actually asks a PEG station for. CivicCast One's keystone K3.

Nothing here is a new caption engine. Every step reuses the piece the live
path already uses:

============================  =========================================
step                          reused piece
============================  =========================================
extract mono caption audio    :func:`civiccast.stream._ffmpeg.run_ffmpeg`
                              at :data:`civiccast.captions.tap
                              .TAP_SAMPLE_RATE_HZ`
slice into runtime chunks     :func:`civiccast.captions.benchmark
                              .load_wav_chunks`
transcribe + queue for review :class:`civiccast.captions.worker
                              .LiveCaptionWorker`
render WebVTT                 :func:`civiccast.captions.webvtt
                              .render_webvtt` (via the publisher below)
attach to the HLS package     :func:`civiccast.captions.hls
                              .attach_caption_tracks_to_package`
============================  =========================================

Two things differ from live, and both are deliberate:

**Single-pass stabilization.** :class:`~civiccast.captions.stabilize
.CaptionStabilizer` defaults to ``stable_windows=2`` because a live
hypothesis is a guess that the next overlapping window may revise. Offline
there is no next window -- the file is finite and each region is
transcribed exactly once -- so a two-window contract would commit nothing
until ``flush()``, and ``flush()`` marks everything low-confidence
regardless of what the model actually reported. Offline therefore runs
``stable_windows=1``, which commits on first observation and lets
``low_confidence`` mean what it says: the *model's* confidence fell below
the threshold. See :data:`OFFLINE_STABLE_WINDOWS`.

**Operator approval gates publication.** Spec §4.1: "No AI-generated
content reaches a public surface ... without explicit operator review.
Captions ... all pass through a review queue. Auto-publish is not an
available operator setting." Live cannot honor that literally (the cue is
on screen before a human could read it). VOD can, and does:
:func:`transcribe_asset_captions` only fills the review queue, and
:func:`attach_reviewed_captions` publishes **only** cues an operator
approved or edited -- rejected cues are dropped, and pending cues hold the
whole track back.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from civiccast.captions.benchmark import load_wav_chunks
from civiccast.captions.hls import (
    CaptionHlsTrack,
    CaptionHlsTrackOutput,
    attach_caption_tracks_to_package,
)
from civiccast.captions.live_sidecar import LiveWebVttPublisher
from civiccast.captions.models import AudioChunk, CaptionCue, CustomVocabulary
from civiccast.captions.pipeline import CaptionPipeline
from civiccast.captions.review import CaptionReviewAudioEvidence, CaptionReviewStore
from civiccast.captions.review_media import write_caption_review_audio_evidence
from civiccast.captions.runtime import CaptionRuntime
from civiccast.captions.stabilize import CaptionStabilizer
from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
from civiccast.captions.worker import AudioEvidenceFactory, LiveCaptionWorker
from civiccast.stream._ffmpeg import FfmpegError, FfmpegNotFoundError, run_ffmpeg
from civiccast.stream.config import ABR_LADDER, HLS_SEGMENT_DURATION, SLATE_RENDITION
from civiccast.stream.packager import RenditionOutput, VodPackageResult

__all__ = [
    "OFFLINE_CAPTION_CHUNK_SECONDS",
    "OFFLINE_CAPTION_LANGUAGE",
    "OFFLINE_CAPTION_LANGUAGE_NAME",
    "OFFLINE_REVIEWER_NOTE",
    "OFFLINE_STABLE_WINDOWS",
    "AttachedCaptions",
    "OfflineCaptionAudioError",
    "OfflineCaptionPackageError",
    "OfflineTranscription",
    "ReviewedCaptions",
    "attach_reviewed_captions",
    "extract_caption_audio",
    "published_caption_sidecar",
    "resolve_vod_package",
    "reviewed_caption_cues",
    "transcribe_asset_captions",
]

#: Seconds of audio handed to the runtime per call. Whisper's own encoder
#: window is 30 s; anything shorter throws away context the model would
#: otherwise use, and offline has no latency budget to protect (unlike the
#: live tap, which uses 5 s so a cue reaches the screen in time).
OFFLINE_CAPTION_CHUNK_SECONDS = 30.0
#: Offline transcribes each region of audio exactly once -- see the module
#: docstring. One observation therefore *is* the final answer.
OFFLINE_STABLE_WINDOWS = 1
OFFLINE_CAPTION_LANGUAGE = "en"
OFFLINE_CAPTION_LANGUAGE_NAME = "English"
OFFLINE_REVIEWER_NOTE = "Auto-generated for the published recording by the local caption model."

#: ffmpeg wall-clock ceiling for audio extraction. Extraction is a stream
#: copy-to-PCM with no video decode of consequence, so even a multi-hour
#: council meeting finishes in minutes; an hour means something is wedged.
_AUDIO_EXTRACT_TIMEOUT_SECONDS = 3600.0


class OfflineCaptionAudioError(RuntimeError):
    """Caption audio could not be extracted from the asset's source media."""


class OfflineCaptionPackageError(RuntimeError):
    """The asset's HLS package is missing or unusable for caption attach."""


@dataclass(frozen=True)
class OfflineTranscription:
    """What one offline transcription pass produced for an asset."""

    asset_id: str
    #: Every cue the model committed, in playback order.
    cues: list[CaptionCue]
    #: Review rows newly created by this pass.
    created_review_item_ids: list[str]
    #: Review rows that already existed (a re-run over the same audio).
    duplicate_review_item_ids: list[str]
    chunk_count: int
    audio_seconds: float


@dataclass(frozen=True)
class ReviewedCaptions:
    """The operator's verdict on one asset's caption queue.

    ``cues`` carries only what an operator approved or edited, with the
    reviewed text substituted for the machine text. ``pending`` is the
    gate: while it is non-zero the asset's captions are not finished being
    reviewed and must not be published.
    """

    cues: list[CaptionCue] = field(default_factory=list)
    pending: int = 0
    approved: int = 0
    edited: int = 0
    rejected: int = 0

    @property
    def total(self) -> int:
        return self.pending + self.approved + self.edited + self.rejected

    @property
    def review_complete(self) -> bool:
        """True when every queued cue has an operator decision on it."""

        return self.total > 0 and self.pending == 0


@dataclass(frozen=True)
class AttachedCaptions:
    """Files written when a reviewed caption track was published."""

    #: Segmented WebVTT playlists written beside the video renditions, and
    #: the rewritten multivariant manifest they were declared in.
    hls_outputs: list[CaptionHlsTrackOutput]
    #: The whole-recording WebVTT file (the records/legal artifact).
    sidecar_path: Path
    cue_count: int


def published_caption_sidecar(package_dir: Path) -> Path:
    """Return the whole-recording WebVTT path inside an asset's package.

    Peer of :func:`civiccast.captions.live_sidecar.active_caption_sidecar`
    for VOD: one flat, complete WebVTT file a clerk (or a records request)
    can take away, next to the segmented track a player streams. Lives
    inside the package tree, so the existing published-gated
    ``/media/vod/{asset_id}/...`` route serves it with no new public
    surface and no second access-control rule to keep in sync.
    """

    return package_dir / "captions" / "captions.vtt"


def extract_caption_audio(source_path: Path, destination: Path) -> Path:
    """Extract mono 16 kHz signed-16-bit PCM WAV caption audio from media.

    Same audio shape the live tap forks off the egress encoder
    (:mod:`civiccast.captions.tap`), so both paths feed the caption runtime
    identical input. Goes through :func:`~civiccast.stream._ffmpeg
    .run_ffmpeg`, the repo's single ffmpeg seam (ADR 0007).
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = run_ffmpeg(
            [
                "-nostdin",
                "-i",
                str(source_path),
                "-vn",
                "-map",
                "0:a:0?",
                "-ar",
                str(TAP_SAMPLE_RATE_HZ),
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "-f",
                "wav",
                str(destination),
            ],
            timeout=_AUDIO_EXTRACT_TIMEOUT_SECONDS,
        )
    except FfmpegNotFoundError as exc:
        raise OfflineCaptionAudioError(
            "FFmpeg is not available, so CivicCast cannot read the recording's audio "
            "to caption it. Repair the bundled FFmpeg runtime and run 'civiccast doctor'."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise OfflineCaptionAudioError(
            f"Reading audio from {source_path.name} timed out after "
            f"{_AUDIO_EXTRACT_TIMEOUT_SECONDS:.0f}s."
        ) from exc
    except FfmpegError as exc:  # pragma: no cover - run_ffmpeg reports via returncode
        raise OfflineCaptionAudioError(str(exc)) from exc
    if result.returncode != 0 or not destination.is_file():
        raise OfflineCaptionAudioError(
            f"CivicCast could not read audio from {source_path.name} for captioning. "
            f"FFmpeg exited {result.returncode}."
        )
    return destination


def _offline_audio_evidence_factory(
    chunk: AudioChunk,
    package_dir: Path,
) -> AudioEvidenceFactory:
    """Return one lazy evidence writer bound to this chunk's offline ASR window.

    Mirrors :meth:`civiccast.captions.tap_worker.CaptionTapWorker
    ._audio_evidence_factory` -- the review store's
    :func:`~civiccast.captions.review.require_low_confidence_approval_evidence`
    rejects low-confidence approval without retained audio evidence, and the
    operator console's review screen disables approval to match, so a
    low-confidence offline cue needs the same durable per-cue WAV the live
    path writes. The only difference is *where* it lands: the live tap
    writes under its channel work directory, which outlives the process;
    offline extracts caption audio into a temp dir that is deleted at the
    end of :func:`transcribe_asset_captions`, so the durable root here is
    the asset's HLS package directory instead -- the same directory
    :func:`attach_reviewed_captions` later writes ``captions/captions.vtt``
    into, and the one part of an offline job that persists past this call.
    """

    evidence: CaptionReviewAudioEvidence | None = None

    def write_once(_cue: CaptionCue) -> CaptionReviewAudioEvidence:
        nonlocal evidence
        if evidence is None:
            digest = hashlib.sha256(chunk.chunk_id.encode("utf-8")).hexdigest()[:24]
            evidence = write_caption_review_audio_evidence(
                chunk,
                package_dir / "captions" / "evidence" / f"{digest}.wav",
            )
        return evidence

    return write_once


def transcribe_asset_captions(
    runtime: CaptionRuntime,
    review_store: CaptionReviewStore,
    *,
    asset_id: str,
    source_path: Path,
    package_dir: Path | None = None,
    vocabulary: CustomVocabulary | None = None,
    chunk_seconds: float = OFFLINE_CAPTION_CHUNK_SECONDS,
    reviewer_note: str = OFFLINE_REVIEWER_NOTE,
) -> OfflineTranscription:
    """Transcribe a recording and queue every cue for operator review.

    Publishes nothing. The caption track only reaches a resident once an
    operator has decided on the queued rows and
    :func:`attach_reviewed_captions` runs -- spec §4.1's
    approve-before-publish non-negotiable.

    Re-running over the same asset is safe: review-item ids are derived
    from ``(asset_id, cue_id)``, so already-queued cues come back as
    ``duplicate_review_item_ids`` instead of overwriting an operator's
    decision.

    ``package_dir``, when given, retains a durable per-cue WAV alongside
    each review row (see :func:`_offline_audio_evidence_factory`) so a
    low-confidence cue can actually be approved later -- without it, the
    extracted audio is gone (deleted with the temp dir) by the time an
    operator opens the review queue, and low-confidence approval is
    permanently blocked. It is optional only because some callers (unit
    tests exercising transcription in isolation, or callers with nowhere
    durable to write) don't have a package directory to hang evidence off
    of yet; the real job worker (:mod:`civiccast.captions.vod_job`) always
    supplies it.
    """

    with tempfile.TemporaryDirectory(prefix="civiccast-offline-captions-") as work_dir:
        wav_path = extract_caption_audio(source_path, Path(work_dir) / f"{asset_id}.wav")
        chunks = load_wav_chunks(wav_path, chunk_seconds=chunk_seconds)

        # LiveCaptionWorker is named for the path that first needed it, but
        # it is the module's runtime -> stabilizer -> review-queue seam and
        # is reused here rather than forked. ``package=None`` keeps it off
        # the HLS write path entirely: offline publication is gated on
        # review, and happens in attach_reviewed_captions instead.
        worker = LiveCaptionWorker(
            runtime,
            review_store,
            asset_id=asset_id,
            vocabulary=vocabulary,
            reviewer_note=reviewer_note,
            pipeline=CaptionPipeline(
                runtime,
                stabilizer=CaptionStabilizer(stable_windows=OFFLINE_STABLE_WINDOWS),
            ),
        )
        created: list[str] = []
        duplicates: list[str] = []
        for chunk in chunks:
            audio_evidence_factory = (
                _offline_audio_evidence_factory(chunk, package_dir)
                if package_dir is not None
                else None
            )
            batch = worker.process_batch([chunk], audio_evidence_factory=audio_evidence_factory)
            created.extend(item.review_item_id for item in batch.committed_review_items)
            duplicates.extend(batch.duplicate_review_item_ids)
        # Nothing should remain pending at stable_windows=1, but flushing is
        # the module's end-of-audio contract and is safe when empty.
        final = worker.flush()
        created.extend(item.review_item_id for item in final.committed_review_items)
        duplicates.extend(final.duplicate_review_item_ids)

        audio_seconds = chunks[-1].end_seconds - chunks[0].start_seconds if chunks else 0.0
        return OfflineTranscription(
            asset_id=asset_id,
            cues=worker.committed_cues(),
            created_review_item_ids=created,
            duplicate_review_item_ids=duplicates,
            chunk_count=len(chunks),
            audio_seconds=audio_seconds,
        )


def reviewed_caption_cues(review_store: CaptionReviewStore, asset_id: str) -> ReviewedCaptions:
    """Collect an asset's operator-decided cues and count what is left.

    Approved and edited rows become publishable cues carrying the
    *reviewed* text (an edit is the operator's correction and is what must
    air). Rejected rows are dropped -- a rejection means "this text is
    wrong", and publishing it anyway would defeat the review. Pending rows
    are counted, not published.
    """

    cues: list[CaptionCue] = []
    pending = approved = edited = rejected = 0
    for item in review_store.list(asset_id=asset_id):
        if item.status == "pending":
            pending += 1
            continue
        if item.status == "rejected":
            rejected += 1
            continue
        if item.status == "approved":
            approved += 1
        else:
            edited += 1
        text = (item.reviewed_text or item.cue.text).strip()
        if not text:
            # An operator cleared the text: treat it as a removal rather
            # than shipping an empty cue (CaptionCue forbids empty text).
            continue
        cues.append(item.cue.model_copy(update={"text": text}))
    cues.sort(key=lambda cue: (cue.start_seconds, cue.end_seconds, cue.cue_id))
    return ReviewedCaptions(
        cues=cues,
        pending=pending,
        approved=approved,
        edited=edited,
        rejected=rejected,
    )


def resolve_vod_package(package_dir: Path) -> VodPackageResult:
    """Rebuild a :class:`VodPackageResult` for an already-written package.

    The packager returns this object once, at package time, and the staff
    endpoint keeps only the resulting manifest URL. Captioning happens
    later (after review), so the attach helper's package handle has to be
    reconstructed from what is actually on disk.

    Only renditions whose variant playlist really exists are included --
    the rewritten manifest must describe the package that is there, not
    the ladder the packager was configured with.
    """

    package_dir = package_dir.expanduser().resolve()
    manifest_path = package_dir / "playlist.m3u8"
    if not manifest_path.is_file():
        raise OfflineCaptionPackageError(
            f"No packaged media found at {package_dir}; package the recording before "
            "attaching captions."
        )
    renditions = [
        RenditionOutput(config=config, playlist_path=playlist)
        for config in (*ABR_LADDER, SLATE_RENDITION)
        if (playlist := package_dir / config.name / "playlist.m3u8").is_file()
    ]
    if not renditions:
        raise OfflineCaptionPackageError(
            f"The package at {package_dir} has no readable video renditions, so a caption "
            "track cannot be declared against it."
        )
    return VodPackageResult(
        manifest_path=manifest_path,
        renditions=renditions,
        output_dir=package_dir,
    )


def attach_reviewed_captions(
    package_dir: Path,
    cues: list[CaptionCue],
    *,
    language: str = OFFLINE_CAPTION_LANGUAGE,
    name: str = OFFLINE_CAPTION_LANGUAGE_NAME,
    segment_duration: int = HLS_SEGMENT_DURATION,
) -> AttachedCaptions:
    """Publish reviewed cues onto an asset's packaged VOD output.

    Writes both artifacts a station needs: the segmented WebVTT track the
    player selects (declared in the multivariant manifest by the existing
    :func:`~civiccast.captions.hls.attach_caption_tracks_to_package`), and
    the flat whole-recording ``captions.vtt`` the records office keeps.

    Callers must have checked :attr:`ReviewedCaptions.review_complete`
    first; this function does not re-derive the approval gate, it enacts
    the decision.

    KNOWN FOLLOW-UP (out of CivicCast One v1 scope, owner-approved to
    defer -- see "Known follow-ups" in docs/ops/background-workers.md):
    every write here is **local disk only**, inside ``package_dir``. That
    is correct and complete for One v1, which serves VOD from the local
    portal origin. It is a gap only for a CDN-backed deployment
    (``CIVICCAST_CDN_PROVIDER``) whose package already pushed to the CDN
    before caption review finished -- the CDN-served copy never gets the
    caption track or the rewritten manifest entry that declares it, since
    nothing here re-runs the CDN upload
    (:meth:`civiccast.live.finalization_worker.LiveFinalizationWorker
    ._upload_package`). Fix when CDN-backed deployments are in scope.
    """

    if not cues:
        raise ValueError("At least one reviewed cue is required to publish a caption track.")
    package = resolve_vod_package(package_dir)
    hls_outputs = attach_caption_tracks_to_package(
        package,
        [CaptionHlsTrack(cues=cues, language=language, name=name)],
        segment_duration=segment_duration,
    )
    sidecar_path = published_caption_sidecar(package.output_dir)
    # Same atomic write the live sidecar uses: a resident or a clerk never
    # reads a half-written WebVTT file.
    LiveWebVttPublisher(sidecar_path).publish(cues)
    return AttachedCaptions(
        hls_outputs=hls_outputs,
        sidecar_path=sidecar_path,
        cue_count=len(cues),
    )
