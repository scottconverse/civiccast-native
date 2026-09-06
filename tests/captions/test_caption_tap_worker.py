# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Caption tap worker tests (Beta sprint B6, decision #1 option A).

The worker consumes the egress audio fork's rolling WAV segments
(``<tap_root>/<channel_id>/chunk-NNNNNN.wav``), feeds them through the
existing live caption seam (pipeline → stabilization → durable review
queue), and moves consumed segments aside so a scan never double-feeds.
House worker shape: env settings with fail-fast ``from_env``, injected
runtime, ``run_once``/``run_forever`` survive-and-log loop.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
import wave
from collections.abc import Callable, Iterable
from pathlib import Path
from types import SimpleNamespace

import pytest

from civiccast.captions.models import AudioChunk, CaptionHypothesis, CustomVocabulary
from civiccast.captions.review import InMemoryCaptionReviewStore
from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
from civiccast.captions.tap_backoff import CaptionBackoffPolicy
from civiccast.captions.tap_worker import (
    CaptionTapWorker,
    CaptionTapWorkerSettings,
    build_tap_worker,
    default_max_channel_workers,
)
from civiccast.egress.caption_embed import load_caption_cues_from_timed_text
from civiccast.egress.caption_feed import CaptionFeedWorker


class _ScriptedRuntime:
    """Yields one hypothesis per chunk; text is per-call scripted."""

    def __init__(self, text: str = "the council will come to order") -> None:
        self.text = text
        self.seen_chunks: list[AudioChunk] = []

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        for chunk in chunks:
            self.seen_chunks.append(chunk)
            yield CaptionHypothesis(
                source_id=f"{chunk.chunk_id}-tap",
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                text=self.text,
                confidence=0.9,
            )


class _ConcurrencyProbeRuntime(_ScriptedRuntime):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._active = 0
        self.max_active = 0

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        with self._lock:
            self._active += 1
            self.max_active = max(self.max_active, self._active)
        try:
            time.sleep(0.05)
            yield from super().transcribe(chunks, vocabulary=vocabulary)
        finally:
            with self._lock:
                self._active -= 1


class _FakeClock:
    """A ``time.monotonic``-shaped clock the test drives explicitly.

    The backoff windows are minutes long; nothing here is allowed to sleep.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _write_wav(path: Path, *, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = int(TAP_SAMPLE_RATE_HZ * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(TAP_SAMPLE_RATE_HZ)
        handle.writeframes(b"\x01\x00" * frame_count)


def _worker(  # type: ignore[no-untyped-def]
    tap_root: Path,
    runtime: _ScriptedRuntime,
    store: InMemoryCaptionReviewStore,
    *,
    segment_seconds: float = 1.0,
    atomic_segments: bool = False,
    max_channel_workers: int | None = None,
    backoff_policy: CaptionBackoffPolicy | None = None,
    is_enabled: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] | None = None,
):
    return CaptionTapWorker(
        tap_root=tap_root,
        caption_work_dir=tap_root.parent / "egress",
        runtime=runtime,
        review_store=store,
        segment_seconds=segment_seconds,
        atomic_segments=atomic_segments,
        max_channel_workers=max_channel_workers,
        backoff_policy=backoff_policy,
        is_enabled=is_enabled,
        monotonic=monotonic,
    )


def _active_vtt(tap_root: Path, channel_id: str) -> Path:
    return tap_root.parent / "egress" / channel_id / "captions" / "active.vtt"


class TestCaptionTapWorker:
    def test_atomic_gstreamer_segment_is_consumed_without_waiting_for_a_newer_file(
        self,
        tmp_path: Path,
    ) -> None:
        tap_root = tmp_path / "tap"
        _write_wav(tap_root / "gov-ch12" / "chunk-000000.wav")
        runtime = _ScriptedRuntime()
        worker = _worker(
            tap_root,
            runtime,
            InMemoryCaptionReviewStore(),
            atomic_segments=True,
        )

        result = worker.run_once()

        assert result.consumed_segments == 1
        assert len(runtime.seen_chunks) == 1
        assert (tap_root / "gov-ch12" / "processed" / "chunk-000000.wav").is_file()

    def test_default_five_second_segments_form_overlapping_stable_windows(
        self,
        tmp_path: Path,
    ) -> None:
        tap_root = tmp_path / "tap"
        for index in range(3):
            _write_wav(
                tap_root / "gov-ch12" / f"chunk-{index:06d}.wav",
                seconds=5.0,
            )
        runtime = _ScriptedRuntime()
        store = InMemoryCaptionReviewStore()
        worker = _worker(
            tap_root,
            runtime,
            store,
            segment_seconds=5.0,
        )

        result = worker.run_once()

        assert result.consumed_segments == 2
        assert len(runtime.seen_chunks) == 2
        assert runtime.seen_chunks[0].start_seconds == 0.0
        assert runtime.seen_chunks[1].start_seconds == 1.0
        assert runtime.seen_chunks[1].end_seconds == 10.0
        assert len(store.list()) == 1
        assert _active_vtt(tap_root, "gov-ch12").is_file()

    def test_settled_segments_become_durable_review_items(self, tmp_path: Path) -> None:
        tap_root = tmp_path / "tap"
        # Two settled segments (a newer one exists after each) + the newest,
        # possibly still being written by ffmpeg, which must NOT be consumed.
        _write_wav(tap_root / "gov-ch12" / "chunk-000000.wav")
        _write_wav(tap_root / "gov-ch12" / "chunk-000001.wav")
        _write_wav(tap_root / "gov-ch12" / "chunk-000002.wav")
        runtime = _ScriptedRuntime()
        store = InMemoryCaptionReviewStore()
        worker = _worker(tap_root, runtime, store)

        result = worker.run_once()

        assert result.consumed_segments == 2
        assert len(runtime.seen_chunks) == 2
        assert runtime.seen_chunks[0].sample_rate_hz == TAP_SAMPLE_RATE_HZ
        # Chunk timing comes from the segment index (segment_seconds=1.0).
        assert runtime.seen_chunks[0].start_seconds == 0.0
        assert runtime.seen_chunks[1].start_seconds == 0.0
        items = store.list()
        assert items, "stable cues must land in the durable review queue"
        assert all(item.asset_id == "gov-ch12" for item in items)
        assert items[0].audio_evidence_available is True
        sidecar = _active_vtt(tap_root, "gov-ch12")
        assert sidecar.is_file()
        cues = load_caption_cues_from_timed_text(sidecar, source_id="gov-ch12")
        assert [(cue.text, cue.start_seconds, cue.end_seconds) for cue in cues] == [
            ("the council will come to order", 0.0, 2.0)
        ]

    def test_active_sidecar_is_the_caption_feed_input(self, tmp_path: Path) -> None:
        tap_root = tmp_path / "tap"
        for index in range(3):
            _write_wav(tap_root / "gov-ch12" / f"chunk-{index:06d}.wav")
        runtime = _ScriptedRuntime()
        store = InMemoryCaptionReviewStore()
        tap_worker = _worker(tap_root, runtime, store)

        tap_worker.run_once()

        sent: list[dict[str, object]] = []
        feed_worker = CaptionFeedWorker(
            work_dir=tap_root.parent / "egress",
            on_air_channels=lambda: ["gov-ch12"],
            caption_cue_provider=lambda channel_id: load_caption_cues_from_timed_text(
                _active_vtt(tap_root, channel_id),
                source_id=channel_id,
            ),
            send_caption_cue=lambda channel_id, _work_dir, **cue: (
                sent.append({"channel_id": channel_id, **cue}) or True
            ),
        )

        result = feed_worker.run_once()

        assert result.cues_sent == 1
        delivery_id = sent[0].pop("delivery_id")
        assert str(uuid.UUID(str(delivery_id))) == delivery_id
        assert sent == [
            {
                "channel_id": "gov-ch12",
                "text": "the council will come to order",
                "pts_seconds": 0.0,
                "duration_seconds": 2.0,
            }
        ]

    def test_consumed_segments_are_not_reprocessed(self, tmp_path: Path) -> None:
        tap_root = tmp_path / "tap"
        _write_wav(tap_root / "gov-ch12" / "chunk-000000.wav")
        _write_wav(tap_root / "gov-ch12" / "chunk-000001.wav")
        runtime = _ScriptedRuntime()
        store = InMemoryCaptionReviewStore()
        worker = _worker(tap_root, runtime, store)

        first = worker.run_once()
        second = worker.run_once()

        assert first.consumed_segments == 1
        assert second.consumed_segments == 0
        assert len(runtime.seen_chunks) == 1

    def test_multiple_channels_keep_separate_caption_streams(self, tmp_path: Path) -> None:
        tap_root = tmp_path / "tap"
        for channel in ("gov-ch12", "edu-ch20"):
            _write_wav(tap_root / channel / "chunk-000000.wav")
            _write_wav(tap_root / channel / "chunk-000001.wav")
        runtime = _ScriptedRuntime()
        store = InMemoryCaptionReviewStore()
        worker = _worker(tap_root, runtime, store)

        worker.run_once()
        # Settle the second segment of each channel and keep going.
        for channel in ("gov-ch12", "edu-ch20"):
            _write_wav(tap_root / channel / "chunk-000002.wav")
        worker.run_once()

        asset_ids = {item.asset_id for item in store.list()}
        assert asset_ids == {"gov-ch12", "edu-ch20"}
        for channel in asset_ids:
            cues = load_caption_cues_from_timed_text(
                _active_vtt(tap_root, channel),
                source_id=channel,
            )
            assert [cue.text for cue in cues] == ["the council will come to order"]

    def test_channels_are_transcribed_concurrently(self, tmp_path: Path) -> None:
        tap_root = tmp_path / "tap"
        for channel in ("public", "education", "government"):
            _write_wav(tap_root / channel / "chunk-000000.wav")
            _write_wav(tap_root / channel / "chunk-000001.wav")
        runtime = _ConcurrencyProbeRuntime()
        # Explicit: the DEFAULT bound is a flat 1, station-wide, regardless of
        # core count (see test_default_concurrency_is_always_one_channel_station_wide
        # and test_asr_concurrency_is_bounded_by_cpu_count). This test is
        # about the executor actually running channels in parallel when the
        # bound allows it, so it states the bound it is testing rather than
        # relying on the default.
        worker = _worker(
            tap_root,
            runtime,
            InMemoryCaptionReviewStore(),
            max_channel_workers=3,
        )

        result = worker.run_once()

        assert result.consumed_segments == 3
        assert runtime.max_active == 3

    def test_asr_concurrency_is_bounded_by_cpu_count(self, tmp_path: Path) -> None:
        """The whole point of the bound: three ON_AIR channels, one at a time.

        MEASURED field failure this guards (tester DESKTOP-VBMA6O5, three
        channels ON_AIR, CPU-only): three channels transcribing at once, each
        faster-whisper model built with ``cpu_threads=0`` (every core), the
        control plane at ~247% of a core, and the playout workers restarted by
        their own 10-second stall watchdog.
        """

        tap_root = tmp_path / "tap"
        for channel in ("public", "education", "government"):
            _write_wav(tap_root / channel / "chunk-000000.wav")
            _write_wav(tap_root / channel / "chunk-000001.wav")
        runtime = _ConcurrencyProbeRuntime()
        worker = _worker(
            tap_root,
            runtime,
            InMemoryCaptionReviewStore(),
            max_channel_workers=1,
        )

        result = worker.run_once()

        # Bounded, not dropped: every channel is still transcribed in this
        # same scan, just never simultaneously.
        assert result.consumed_segments == 3
        assert sorted(result.channels) == ["education", "government", "public"]
        assert runtime.max_active == 1

    def test_default_concurrency_is_always_one_channel_station_wide(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Item 79: the default is a flat 1, regardless of core count.

        Tightened from the previous "one channel per 8 CPUs, max 3" formula.
        Read this as knob hardening, not as a standalone fix for the original
        DESKTOP-VBMA6O5 field defect (see the module docstring): every
        channel already shares one speech recognition model instance built
        with CTranslate2's ``inter_threads=1``, so the previous default of 3
        never actually ran 3 concurrent inferences -- that model-level queue
        was already serializing them.
        """

        monkeypatch.setattr("civiccast.captions.tap_worker.os.cpu_count", lambda: 4)
        assert default_max_channel_workers() == 1
        monkeypatch.setattr("civiccast.captions.tap_worker.os.cpu_count", lambda: 8)
        assert default_max_channel_workers() == 1
        monkeypatch.setattr("civiccast.captions.tap_worker.os.cpu_count", lambda: 32)
        assert default_max_channel_workers() == 1
        # `os.cpu_count()` is documented as possibly None; still 1.
        monkeypatch.setattr("civiccast.captions.tap_worker.os.cpu_count", lambda: None)
        assert default_max_channel_workers() == 1

    def test_default_concurrency_env_override_still_works(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The documented ``CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS`` override
        is read by ``CaptionTapWorkerSettings.from_env``, not by
        ``default_max_channel_workers`` itself -- confirm the settings seam
        still honours a value above the new flat default."""

        from civiccast.captions.tap_worker import CaptionTapWorkerSettings

        monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", "/tmp/does-not-need-to-exist")
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_MAX_CHANNEL_WORKERS", "3")

        settings = CaptionTapWorkerSettings.from_env()

        assert settings.max_channel_workers == 3

    def test_startup_logs_cpu_count_and_the_chosen_sizing_in_one_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Item 79: one line at tap start records what box a run happened on.

        `getattr(runtime, "cpu_threads", "n/a")` reads the live sizing off
        whatever runtime was injected -- a real `FasterWhisperRuntime` has the
        attribute, the `_ScriptedRuntime` test double used elsewhere in this
        module does not, so this test uses a small stand-in that does.
        """

        monkeypatch.setattr("civiccast.captions.tap_worker.os.cpu_count", lambda: 8)

        class _RuntimeWithCpuThreads(_ScriptedRuntime):
            cpu_threads = 1

        with caplog.at_level("INFO", logger="civiccast.captions.tap_worker"):
            _worker(
                tmp_path / "tap",
                _RuntimeWithCpuThreads(),
                InMemoryCaptionReviewStore(),
                max_channel_workers=1,
            )

        assert "Caption tap starting" in caplog.text
        assert "cpu_count=8" in caplog.text
        assert "max_channel_workers=1" in caplog.text
        assert "live_cpu_threads=1" in caplog.text

    def test_backlog_fails_closed_instead_of_publishing_stale_captions(
        self,
        tmp_path: Path,
    ) -> None:
        tap_root = tmp_path / "tap"
        for index in range(4):
            _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
        runtime = _ScriptedRuntime()
        worker = _worker(tap_root, runtime, InMemoryCaptionReviewStore())
        active = _active_vtt(tap_root, "government")
        active.parent.mkdir(parents=True, exist_ok=True)
        active.write_text(
            "WEBVTT\n\nold\n00:00:00.000 --> 00:00:01.000\nstale caption\n",
            encoding="utf-8",
        )

        result = worker.run_once()

        assert result.consumed_segments == 0
        assert getattr(result, "dropped_overload_segments", 0) == 3
        assert getattr(result, "overloaded_channels", ()) == ("government",)
        assert load_caption_cues_from_timed_text(active, source_id="government") == []
        # DISCARDED, not filed under `overload/`. Nothing ever swept that
        # directory (the retention policy tap sweep reads `processed/` only)
        # and no review row referenced it, so it grew without bound on a
        # chronically overloaded station -- see TestCaptionTapPlayoutProtection
        # for the two-pause-cycle proof.
        assert not (tap_root / "government" / "overload").exists()
        assert not list((tap_root / "government").glob("chunk-00000[012].wav"))
        status_path = tap_root.parent / "egress" / "government" / "captions" / "runtime-status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        # An overload now OPENS A BACKOFF PAUSE rather than merely reporting
        # itself and retrying on the next scan, so the operator-visible state
        # is "paused" and it says when captions will be attempted again.
        assert status["state"] == "paused"
        assert status["backlog_segments"] == 3
        assert status["consecutive_overloads"] == 1
        assert status["resume_in_seconds"] > 0
        assert result.paused_channels == ("government",)

    def test_the_operator_switch_stops_asr_without_a_restart(self, tmp_path: Path) -> None:
        """``StationProfile.live_captions_enabled`` is read every scan.

        An activated native station forces ``CIVICCAST_CAPTION_TAP=inline``
        into its environment, so this switch is the operator's only way to
        stop live captioning -- and it has to take effect on a station that is
        ON AIR, without restarting the control plane.
        """

        tap_root = tmp_path / "tap"
        enabled = [True]
        runtime = _ScriptedRuntime()
        worker = _worker(
            tap_root,
            runtime,
            InMemoryCaptionReviewStore(),
            is_enabled=lambda: enabled[0],
        )
        active = _active_vtt(tap_root, "government")

        for index in range(3):
            _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
        assert worker.run_once().consumed_segments == 2
        assert len(runtime.seen_chunks) == 2
        assert load_caption_cues_from_timed_text(active, source_id="government") != []

        enabled[0] = False
        for index in range(3, 4):
            _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
        disabled = worker.run_once()

        assert disabled.consumed_segments == 0
        assert len(runtime.seen_chunks) == 2
        # Nothing on air claims to be captioned any more...
        assert load_caption_cues_from_timed_text(active, source_id="government") == []
        status_path = tap_root.parent / "egress" / "government" / "captions" / "runtime-status.json"
        assert json.loads(status_path.read_text(encoding="utf-8"))["state"] == "disabled"
        # ...and the forked audio is DELETED rather than filed as evidence: a
        # station that switched live captions off has not asked CivicCast to
        # keep a rolling recording of its broadcast audio.
        assert not (tap_root / "government" / "overload").exists()
        assert sorted(path.name for path in (tap_root / "government").glob("chunk-*.wav")) == [
            "chunk-000003.wav"
        ]

        # Switching it back on resumes, still without a restart.
        enabled[0] = True
        for index in range(4, 6):
            _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
        assert worker.run_once().consumed_segments == 2

    def test_an_overloaded_channel_spends_no_asr_while_paused(self, tmp_path: Path) -> None:
        """The pause must be real: not one sample reaches the runtime.

        The field defect was not that overload went undetected -- it was that
        the worker detected overload, cleared the captions, dropped the audio,
        logged CRITICAL, and then immediately tried again, forever, at full
        CPU. Backing off is what makes "captions are best effort" true.
        """

        tap_root = tmp_path / "tap"
        clock = _FakeClock()
        policy = CaptionBackoffPolicy(base_seconds=60.0, monotonic=clock)
        runtime = _ScriptedRuntime()
        worker = _worker(
            tap_root,
            runtime,
            InMemoryCaptionReviewStore(),
            backoff_policy=policy,
        )

        for index in range(4):
            _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
        first = worker.run_once()
        assert first.overloaded_channels == ("government",)
        assert runtime.seen_chunks == []

        # Second scan, still inside the 60s window: a fresh, WITHIN-capacity
        # backlog arrives and is still not transcribed.
        clock.advance(2.0)
        for index in range(4, 6):
            _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
        second = worker.run_once()

        assert second.paused_channels == ("government",)
        assert second.overloaded_channels == ()
        assert second.consumed_segments == 0
        assert runtime.seen_chunks == []
        # Drained, not hoarded: a paused channel must not fill the disk while
        # the audio tap keeps publishing a segment every few seconds into it.
        # The per-scan drain DELETES (`overload/` is swept by nothing); only
        # the one-off move that opened the pause files evidence there.
        assert second.dropped_overload_segments == 2
        assert not (tap_root / "government" / "overload").exists()
        assert not list((tap_root / "government").glob("chunk-00000[034].wav"))

        status_path = tap_root.parent / "egress" / "government" / "captions" / "runtime-status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["state"] == "paused"
        assert status["resume_in_seconds"] == 58.0

    def test_captions_resume_after_the_backoff_window_when_the_backlog_is_clear(
        self,
        tmp_path: Path,
    ) -> None:
        tap_root = tmp_path / "tap"
        clock = _FakeClock()
        policy = CaptionBackoffPolicy(base_seconds=60.0, monotonic=clock)
        runtime = _ScriptedRuntime()
        worker = _worker(
            tap_root,
            runtime,
            InMemoryCaptionReviewStore(),
            backoff_policy=policy,
        )

        for index in range(4):
            _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
        worker.run_once()

        clock.advance(61.0)
        for index in range(4, 6):
            _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
        resumed = worker.run_once()

        assert resumed.paused_channels == ()
        assert resumed.consumed_segments == 2
        assert len(runtime.seen_chunks) == 2
        status_path = tap_root.parent / "egress" / "government" / "captions" / "runtime-status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["state"] == "within-capacity"

    def test_a_repeated_overload_escalates_the_pause(self, tmp_path: Path) -> None:
        tap_root = tmp_path / "tap"
        clock = _FakeClock()
        policy = CaptionBackoffPolicy(base_seconds=60.0, monotonic=clock)
        worker = _worker(
            tap_root,
            _ScriptedRuntime(),
            InMemoryCaptionReviewStore(),
            backoff_policy=policy,
        )
        status_path = tap_root.parent / "egress" / "government" / "captions" / "runtime-status.json"

        next_index = 0
        for expected_pause in (60.0, 120.0, 240.0):
            for _ in range(4):
                _write_wav(tap_root / "government" / f"chunk-{next_index:06d}.wav")
                next_index += 1
            worker.run_once()
            status = json.loads(status_path.read_text(encoding="utf-8"))
            assert status["state"] == "paused"
            assert status["resume_in_seconds"] == expected_pause
            clock.advance(expected_pause + 1.0)

    def test_the_overload_is_logged_once_per_pause_not_every_scan(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """663 caption lines in one control-plane log is the defect.

        The overload line was CRITICAL and repeated every ~30s for all three
        channels while the actual casualty -- a playout worker restarting --
        was buried in it. One WARNING per pause window, and nothing at all
        while the pause holds.
        """

        tap_root = tmp_path / "tap"
        clock = _FakeClock()
        worker = _worker(
            tap_root,
            _ScriptedRuntime(),
            InMemoryCaptionReviewStore(),
            backoff_policy=CaptionBackoffPolicy(base_seconds=60.0, monotonic=clock),
        )

        with caplog.at_level(logging.DEBUG, logger="civiccast.captions.tap_worker"):
            for index in range(4):
                _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
            worker.run_once()
            for scan in range(5):
                clock.advance(2.0)
                for index in range(4 + scan * 2, 6 + scan * 2):
                    _write_wav(tap_root / "government" / f"chunk-{index:06d}.wav")
                worker.run_once()

        overload_records = [
            record for record in caplog.records if "Caption tap overload" in record.getMessage()
        ]
        assert len(overload_records) == 1
        assert overload_records[0].levelno == logging.WARNING
        assert not [record for record in caplog.records if record.levelno >= logging.CRITICAL]

    def test_a_bad_segment_is_quarantined_not_fatal(self, tmp_path: Path) -> None:
        tap_root = tmp_path / "tap"
        bad = tap_root / "gov-ch12" / "chunk-000000.wav"
        bad.parent.mkdir(parents=True)
        bad.write_bytes(b"this is not a wav file")
        _write_wav(tap_root / "gov-ch12" / "chunk-000001.wav")
        _write_wav(tap_root / "gov-ch12" / "chunk-000002.wav")
        runtime = _ScriptedRuntime()
        store = InMemoryCaptionReviewStore()
        worker = _worker(tap_root, runtime, store)

        result = worker.run_once()

        # The good settled segment was still consumed.
        assert result.consumed_segments == 1
        assert result.quarantined_segments == 1
        assert len(runtime.seen_chunks) == 1

    def test_discovers_unbounded_chunk_indices_after_six_digit_rollover(
        self,
        tmp_path: Path,
    ) -> None:
        """`chunk-%06d` is minimum width, so 1000000 must not disappear."""

        tap_root = tmp_path / "tap"
        for index in (999999, 1_000_000):
            _write_wav(tap_root / "government" / f"chunk-{index}.wav")
        runtime = _ScriptedRuntime()
        worker = _worker(
            tap_root,
            runtime,
            InMemoryCaptionReviewStore(),
            atomic_segments=True,
        )

        result = worker.run_once()

        assert result.consumed_segments == 2
        assert [chunk.chunk_id for chunk in runtime.seen_chunks] == [
            "government-tap-999999",
            "government-tap-1000000-overlap",
        ]
        assert [chunk.start_seconds for chunk in runtime.seen_chunks] == [999999.0, 999999.0]
        assert sorted(
            path.name for path in (tap_root / "government" / "processed").glob("*.wav")
        ) == ["chunk-1000000.wav", "chunk-999999.wav"]

    def test_quarantines_restarted_chunk_collision_instead_of_overwriting_evidence(
        self,
        tmp_path: Path,
    ) -> None:
        tap_root = tmp_path / "tap"
        original = tap_root / "government" / "chunk-000007.wav"
        _write_wav(original)
        worker = _worker(
            tap_root,
            _ScriptedRuntime(),
            InMemoryCaptionReviewStore(),
            atomic_segments=True,
        )
        assert worker.run_once().consumed_segments == 1

        # A restarted producer reused the same index with distinct bytes.
        _write_wav(original, seconds=2.0)
        restarted_worker = _worker(
            tap_root,
            _ScriptedRuntime(),
            InMemoryCaptionReviewStore(),
            atomic_segments=True,
        )

        result = restarted_worker.run_once()

        assert result.consumed_segments == 0
        assert result.quarantined_segments == 1
        assert (tap_root / "government" / "collision" / "chunk-000007.wav").is_file()


class TestCaptionTapPlayoutProtection:
    """The four behaviours that keep captions from costing the station its air."""

    def test_retention_still_prunes_while_live_captions_are_switched_off(
        self, tmp_path: Path
    ) -> None:
        """Turning captions off is a decision about FUTURE transcription.

        It is not a licence to stop deleting audio the station has already
        recorded. Gating the retention sweep behind the enabled check froze
        every retention clock (spec 4.3) for as long as the switch was off.
        """

        tap_root = tmp_path / "tap"
        _write_wav(tap_root / "government" / "chunk-000000.wav")
        _write_wav(tap_root / "government" / "chunk-000001.wav")

        enforced: list[Path] = []

        class _RecordingRetention:
            def enforce_discovered(self, *, tap_root, review_store, segment_seconds):  # type: ignore[no-untyped-def]
                enforced.append(tap_root)
                return SimpleNamespace(ready=True, refusal_reason=None)

            def record_event(self, **_kwargs: object) -> None:  # pragma: no cover
                return None

        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tap_root.parent / "egress",
            runtime=_ScriptedRuntime(),
            review_store=InMemoryCaptionReviewStore(),
            segment_seconds=1.0,
            retention_policy=_RecordingRetention(),  # type: ignore[arg-type]
            is_enabled=lambda: False,
        )

        result = worker.run_once()

        assert result.consumed_segments == 0  # captions really are off
        assert enforced == [tap_root]  # ...and retention really did run

    def test_a_chronically_overloaded_channel_retains_no_audio_across_pause_cycles(
        self, tmp_path: Path
    ) -> None:
        """`<channel>/overload/` was swept by nothing, and it grew forever.

        The retention policy tap sweep reads `processed/` only, so BOTH the
        move that opened a pause and the per-scan drain that followed it piled
        raw broadcast audio into `overload/` with no retention clock on it and
        no review row referencing it. On a station that cannot keep up -- the
        one case this whole change exists for -- that repeats every pause
        cycle, forever. This drives TWO full cycles and asserts that nothing
        accumulates on either path.
        """

        tap_root = tmp_path / "tap"
        clock = _FakeClock()
        channel = tap_root / "government"
        worker = _worker(
            tap_root,
            _ScriptedRuntime(),
            InMemoryCaptionReviewStore(),
            backoff_policy=CaptionBackoffPolicy(base_seconds=60.0, monotonic=clock),
            monotonic=clock,
        )

        next_index = 0
        for cycle in range(2):
            # Overload -> opens a pause (60s, then 120s).
            for _ in range(4):
                _write_wav(channel / f"chunk-{next_index:06d}.wav")
                next_index += 1
            result = worker.run_once()
            assert result.overloaded_channels == ("government",), f"cycle {cycle}"

            # Several scans inside the pause window -> per-scan drain.
            for _ in range(5):
                clock.advance(2.0)
                for _ in range(2):
                    _write_wav(channel / f"chunk-{next_index:06d}.wav")
                    next_index += 1
                worker.run_once()

            # Nothing retained, on either path, in either cycle.
            assert not (channel / "overload").exists(), f"cycle {cycle}"
            clock.advance(60.0 * (2**cycle) + 1.0)

        # The tap directory itself never accumulated either: at most the one
        # unsettled newest segment is left behind.
        assert len(list(channel.glob("chunk-*.wav"))) <= 1

    def test_the_retention_sweep_runs_on_its_own_slower_cadence(self, tmp_path: Path) -> None:
        """Retention enforces a schedule in DAYS; it must not run 30x a minute.

        `enforce_discovered` lists review rows from the database and SHA-256s
        every chunk it considers. At the 2-second scan cadence that is a query
        plus a pass over the recorded audio 30 times a minute, forever.
        """

        tap_root = tmp_path / "tap"
        tap_root.mkdir(parents=True)
        clock = _FakeClock()
        sweeps: list[float] = []

        class _CountingRetention:
            def enforce_discovered(self, **_kwargs: object):  # type: ignore[no-untyped-def]
                sweeps.append(clock.now)
                return SimpleNamespace(ready=True, refusal_reason=None)

            def record_event(self, **_kwargs: object) -> None:  # pragma: no cover
                return None

        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tap_root.parent / "egress",
            runtime=_ScriptedRuntime(),
            review_store=InMemoryCaptionReviewStore(),
            segment_seconds=1.0,
            retention_policy=_CountingRetention(),  # type: ignore[arg-type]
            monotonic=clock,
        )

        # The FIRST scan always sweeps -- a station must not wait a minute
        # after startup to start honouring its retention schedule.
        worker.run_once()
        assert sweeps == [0.0]

        for _ in range(29):  # 58 seconds of 2-second scans
            clock.advance(2.0)
            worker.run_once()
        assert sweeps == [0.0]

        clock.advance(4.0)
        worker.run_once()
        assert sweeps == [0.0, 62.0]

    def test_a_storage_refusal_is_not_forgotten_between_retention_sweeps(
        self, tmp_path: Path
    ) -> None:
        """Failing closed must survive the cadence.

        A scan that skips the sweep must keep the last verdict, not quietly
        revert to "ready" and start captioning again on storage the policy
        already refused.
        """

        tap_root = tmp_path / "tap"
        _write_wav(tap_root / "government" / "chunk-000000.wav")
        _write_wav(tap_root / "government" / "chunk-000001.wav")
        clock = _FakeClock()
        runtime = _ScriptedRuntime()

        class _RefusingRetention:
            def enforce_discovered(self, **_kwargs: object):  # type: ignore[no-untyped-def]
                return SimpleNamespace(ready=False, refusal_reason="disk full")

            def record_event(self, **_kwargs: object) -> None:  # pragma: no cover
                return None

        worker = CaptionTapWorker(
            tap_root=tap_root,
            caption_work_dir=tap_root.parent / "egress",
            runtime=runtime,
            review_store=InMemoryCaptionReviewStore(),
            segment_seconds=1.0,
            retention_policy=_RefusingRetention(),  # type: ignore[arg-type]
            monotonic=clock,
        )

        assert worker.run_once().consumed_segments == 0
        clock.advance(2.0)  # inside the sweep cadence: no fresh verdict
        assert worker.run_once().consumed_segments == 0
        assert runtime.seen_chunks == []
        status_path = tap_root.parent / "egress" / "government" / "captions" / "runtime-status.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        assert status["state"] == "storage-refused"
        assert status["refusal_reason"] == "disk full"

    def test_an_unchanged_status_is_not_rewritten_every_scan(self, tmp_path: Path) -> None:
        """A steady state is not news; a durable write per scan is a cost."""

        tap_root = tmp_path / "tap"
        clock = _FakeClock()
        worker = _worker(
            tap_root,
            _ScriptedRuntime(),
            InMemoryCaptionReviewStore(),
            is_enabled=lambda: False,
            monotonic=clock,
        )
        _write_wav(tap_root / "government" / "chunk-000000.wav")
        _write_wav(tap_root / "government" / "chunk-000001.wav")
        status_path = tap_root.parent / "egress" / "government" / "captions" / "runtime-status.json"

        worker.run_once()
        first = json.loads(status_path.read_text(encoding="utf-8"))["updated_at"]

        for _ in range(5):
            clock.advance(2.0)
            _write_wav(tap_root / "government" / f"chunk-{uuid.uuid4().int % 900000:06d}.wav")
            worker.run_once()

        assert json.loads(status_path.read_text(encoding="utf-8"))["updated_at"] == first

        # ...but it does not go stale forever: a heartbeat republishes it.
        clock.advance(31.0)
        _write_wav(tap_root / "government" / "chunk-000900.wav")
        _write_wav(tap_root / "government" / "chunk-000901.wav")
        worker.run_once()
        assert json.loads(status_path.read_text(encoding="utf-8"))["updated_at"] != first

    def test_switching_captions_off_clears_a_channel_with_no_tap_directory(
        self, tmp_path: Path
    ) -> None:
        """Clear by the CHANNEL SET, not by tap-directory presence.

        A channel whose tap directory was never created (or was already swept)
        has no directory to iterate -- yet it can still be serving a stale
        `active.vtt` from before the switch was thrown. Captions on air that
        nothing is producing any more is the exact failure the fail-closed
        clear exists to prevent.
        """

        tap_root = tmp_path / "tap"
        tap_root.mkdir(parents=True)
        stale = _active_vtt(tap_root, "education")
        stale.parent.mkdir(parents=True)
        stale.write_text(
            "WEBVTT\n\nold\n00:00:00.000 --> 00:00:01.000\nstale caption\n",
            encoding="utf-8",
        )
        worker = _worker(
            tap_root,
            _ScriptedRuntime(),
            InMemoryCaptionReviewStore(),
            is_enabled=lambda: False,
        )

        result = worker.run_once()

        assert result.channels == ()  # no tap directory for this channel at all
        assert load_caption_cues_from_timed_text(stale, source_id="education") == []


class TestCaptionTapWorkerSettings:
    def test_defaults_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CIVICCAST_CAPTION_TAP", raising=False)
        settings = CaptionTapWorkerSettings.from_env()
        assert settings.mode == "off"

    def test_inline_requires_the_tap_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
        monkeypatch.delenv("CIVICCAST_CAPTION_TAP_DIR", raising=False)
        with pytest.raises(ValueError, match="CIVICCAST_CAPTION_TAP_DIR"):
            CaptionTapWorkerSettings.from_env()

    def test_invalid_mode_fails_fast(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "sometimes")
        with pytest.raises(ValueError, match="CIVICCAST_CAPTION_TAP"):
            CaptionTapWorkerSettings.from_env()

    def test_inline_with_dir_parses(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path))
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_POLL_SECONDS", "2.5")
        monkeypatch.setenv("CIVICCAST_CAPTION_TAP_ATOMIC", "1")
        settings = CaptionTapWorkerSettings.from_env()
        assert settings.mode == "inline"
        assert settings.tap_root == tmp_path
        assert settings.poll_seconds == 2.5
        assert settings.atomic_segments is True

    def test_channel_concurrency_does_not_multiply_whisper_model_residency(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """max_channel_workers must NOT reach the runtime's num_workers.

        This test previously asserted the opposite -- `{"num_workers": 3}` --
        under the name "default runtime is configured for parallel channel
        workers". That name states the belief that produced the defect: that
        faster-whisper's num_workers is how many channels get processed at
        once. It is not. It is CTranslate2's inter_threads, which keeps a
        SEPARATE REPLICA OF THE MODEL per worker, so the default asked for
        three copies of large-v3 resident simultaneously.

        Channel concurrency is unaffected and comes from somewhere else
        entirely: the ThreadPoolExecutor in CaptionTapWorker._scan_once, which
        still runs max_channel_workers channels in parallel. They now share
        one model.

        Open, and deliberately not claimed here: whether this is THE cause of
        the 16 GB field failure (fine for two segments, then a climb toward
        12 GB producing nothing until it timed out, twice). The shape and
        magnitude fit and TESTER2 is measuring it, but the conflation of two
        unrelated quantities is worth fixing on its own terms either way.
        """

        captured: dict[str, object] = {}
        runtime = _ScriptedRuntime()

        def runtime_factory(**kwargs: object) -> _ScriptedRuntime:
            captured.update(kwargs)
            return runtime

        monkeypatch.setattr(
            "civiccast.captions.runtime.FasterWhisperRuntime",
            runtime_factory,
        )
        settings = CaptionTapWorkerSettings(
            mode="inline",
            tap_root=tmp_path / "tap",
            max_channel_workers=3,
        )

        build_tap_worker(
            settings,
            InMemoryCaptionReviewStore(),
            caption_work_dir=tmp_path / "egress",
        )

        # The runtime is constructed with NO worker override: it keeps its
        # own default of 1. Asserting the whole dict (not just the absence of
        # a key) is deliberate -- it also catches a future caller quietly
        # reintroducing the multiplier under a different argument name.
        #
        # What the live tap DOES pass is the CPU budget, and only that: one
        # CTranslate2 intra-thread and greedy decoding. The batch/VOD defaults
        # (`cpu_threads=0`, i.e. every core, and beam 5) are what produced the
        # measured field failure -- ~247% of a core against three playout
        # workers being killed by their own stall watchdog.
        #
        # It asks for that sizing by declaring itself LIVE, not by passing a
        # kwargs bundle: this construction branch is dead in the native
        # service (the app pre-builds the runtime through
        # `civiccast.ai_models.runtime.build_caption_runtime` and injects it),
        # so kwargs here proved nothing about the product. `live=True` is a
        # property of the runtime and travels with it through BOTH paths --
        # see tests/ai_models/test_runtime_wiring.py for the app's own call.
        assert captured == {"live": True}

    def test_native_station_rejects_the_unaccepted_vulkan_runtime(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_NATIVE_STATION", "1")
        monkeypatch.setenv("CIVICCAST_CAPTION_RUNTIME", "whispercpp-vulkan")
        monkeypatch.setenv(
            "CIVICCAST_WHISPER_CPP_EXE",
            str(tmp_path / "caption-pack" / "whisper-cli.exe"),
        )
        monkeypatch.setenv(
            "CIVICCAST_WHISPER_CPP_MODEL_PATH",
            str(tmp_path / "caption-pack" / "ggml-large-v3-q5_0.bin"),
        )
        settings = CaptionTapWorkerSettings(
            mode="inline",
            tap_root=tmp_path / "tap",
        )

        with pytest.raises(ValueError, match="accepted faster-whisper"):
            build_tap_worker(
                settings,
                InMemoryCaptionReviewStore(),
                caption_work_dir=tmp_path / "egress",
            )

    def test_unknown_caption_runtime_fails_fast(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setenv("CIVICCAST_CAPTION_RUNTIME", "mystery")
        settings = CaptionTapWorkerSettings(
            mode="inline",
            tap_root=tmp_path / "tap",
        )

        with pytest.raises(ValueError, match="CIVICCAST_CAPTION_RUNTIME"):
            build_tap_worker(
                settings,
                InMemoryCaptionReviewStore(),
                caption_work_dir=tmp_path / "egress",
            )
