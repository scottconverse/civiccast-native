# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U69: the caption tap's always-on, bounded-rate shed diagnostic.

Three layers are proven here:

* the collector's own contract -- the two events, the required fields, the
  per-(channel, event) rate limit, the bounded batch record, the failure-proof
  logging and probe paths, and the disable switch;
* the :class:`PhaseSampleForwarder` -- that it forwards every phase unchanged
  (so opting into phase timing still yields the same records), samples exactly
  the stabilize phase, and never swallows the tap's own exceptions;
* the tap integration -- that a real over-limit episode produces a streak-start
  line and then a shed line with the fields an operator needs, that a
  deliberately broken diagnostic cannot change what the tap sheds or commits,
  and that the disabled diagnostic is inert.
"""

from __future__ import annotations

import json
import logging
import wave
from collections.abc import Callable, Iterable, Iterator
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from civiccast.captions import tap_shed_diagnostic as tsd
from civiccast.captions.models import AudioChunk, CaptionHypothesis, CustomVocabulary
from civiccast.captions.review import InMemoryCaptionReviewStore
from civiccast.captions.tap import TAP_SAMPLE_RATE_HZ
from civiccast.captions.tap_shed_diagnostic import (
    SHED_DIAGNOSTIC_ENV_VAR,
    NullShedDiagnostic,
    PhaseSampleForwarder,
    ShedDiagnosticCollector,
    shed_diagnostic_from_env,
)
from civiccast.captions.tap_worker import CaptionTapWorker

_PREFIX = "Caption tap shed diagnostic "


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------
class _FakeClock:
    """A ``time.monotonic``-shaped clock the test drives explicitly."""

    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


class _FakePsutil:
    """A psutil stand-in: no real process scan, fully deterministic."""

    IDLE_PRIORITY_CLASS = 64
    BELOW_NORMAL_PRIORITY_CLASS = 16384
    NORMAL_PRIORITY_CLASS = 32
    ABOVE_NORMAL_PRIORITY_CLASS = 32768
    HIGH_PRIORITY_CLASS = 128
    REALTIME_PRIORITY_CLASS = 256

    def __init__(
        self,
        *,
        threads: int = 42,
        nice: int = NORMAL_PRIORITY_CLASS,
        processes: Iterable[tuple[str, int, int]] = (),
    ) -> None:
        self._threads = threads
        self._nice = nice
        self._processes = list(processes)

    def Process(self) -> Any:
        return SimpleNamespace(num_threads=lambda: self._threads, nice=lambda: self._nice)

    def process_iter(self, attrs: list[str]) -> Iterator[Any]:
        for name, pid, nice in self._processes:
            yield SimpleNamespace(pid=pid, info={"name": name, "nice": nice})


class _ExplodingPsutil:
    """psutil that raises on every access, to prove the unavailable path."""

    def Process(self) -> Any:
        raise RuntimeError("psutil is broken")

    def process_iter(self, attrs: list[str]) -> Iterator[Any]:
        raise RuntimeError("psutil is broken")


def _fake_gpu() -> dict[str, object]:
    return {
        "available": True,
        "devices": [
            {"name": "Fake GPU", "util_pct": 88, "mem_used_mb": 4096, "mem_total_mb": 8192}
        ],
    }


def _collector(
    clock: _FakeClock,
    *,
    psutil_module: object | None = None,
    gpu_probe: Callable[[], dict[str, object]] | None = _fake_gpu,
    **kwargs: object,
) -> ShedDiagnosticCollector:
    """A collector whose every probe is injected: no real process/GPU I/O."""

    return ShedDiagnosticCollector(
        monotonic=clock,
        process_time=clock,  # a fake CPU clock keeps the cpu_s_window assertions exact
        psutil_module=psutil_module if psutil_module is not None else _FakePsutil(),
        gpu_probe=gpu_probe,
        **kwargs,  # type: ignore[arg-type]
    )


def _payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for record in caplog.records:
        message = record.getMessage()
        if not message.startswith(_PREFIX):
            continue
        remainder = message[len(_PREFIX) :]
        # The hook-failure debug line shares the prefix but is not a payload.
        if not remainder.startswith("{"):
            continue
        payloads.append(json.loads(remainder))
    return payloads


def _streak_start(collector: object, *, channel: str = "education", **overrides: object) -> None:
    fields: dict[str, object] = {
        "channel": channel,
        "queue_depth": 7,
        "oldest_queue_age_seconds": 31.4,
        "max_backlog_segments": 2,
        "overload_streak": 1,
        "persistence_scans": 15,
    }
    fields.update(overrides)
    collector.note_streak_start(**fields)  # type: ignore[attr-defined]


def _shed(collector: object, *, channel: str = "education", **overrides: object) -> None:
    fields: dict[str, object] = {
        "channel": channel,
        "queue_depth": 7,
        "oldest_queue_age_seconds": 31.4,
        "shed_count": 5,
        "kept": 2,
        "skipped_seconds": 25.0,
        "max_backlog_segments": 2,
        "overload_streak": 15,
        "persistence_scans": 15,
    }
    fields.update(overrides)
    collector.note_shed(**fields)  # type: ignore[attr-defined]


def _write_wav(path: Path, *, seconds: float = 1.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame_count = int(TAP_SAMPLE_RATE_HZ * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(TAP_SAMPLE_RATE_HZ)
        handle.writeframes(b"\x01\x00" * frame_count)


class _ScriptedRuntime:
    """Yields one hypothesis per chunk, like the real live seam."""

    def __init__(self, text: str = "the council will come to order") -> None:
        self.text = text

    def transcribe(
        self,
        chunks: Iterable[AudioChunk],
        vocabulary: CustomVocabulary | None = None,
    ) -> Iterable[CaptionHypothesis]:
        for chunk in chunks:
            yield CaptionHypothesis(
                source_id=f"{chunk.chunk_id}-tap",
                start_seconds=chunk.start_seconds,
                end_seconds=chunk.end_seconds,
                text=self.text,
                confidence=0.9,
            )


def _tap(
    tap_root: Path,
    *,
    clock: _FakeClock,
    diagnostic: object,
    runtime: object | None = None,
    overload_persistence_scans: int = 3,
    max_backlog_segments: int = 2,
) -> CaptionTapWorker:
    return CaptionTapWorker(
        tap_root=tap_root,
        caption_work_dir=tap_root.parent / "egress",
        runtime=(runtime if runtime is not None else _ScriptedRuntime()),  # type: ignore[arg-type]
        review_store=InMemoryCaptionReviewStore(),
        segment_seconds=1.0,
        atomic_segments=False,
        max_channel_workers=1,
        max_backlog_segments=max_backlog_segments,
        overload_persistence_scans=overload_persistence_scans,
        catch_up_shed_limit=3,
        catch_up_shed_window_seconds=300.0,
        monotonic=clock,
        shed_diagnostic=diagnostic,  # type: ignore[arg-type]
    )


def _drive_over_limit_episode(
    worker: CaptionTapWorker,
    tap_root: Path,
    channel_id: str,
    *,
    scans: int = 3,
    first_index: int = 0,
    writes_per_scan: int = 4,
) -> int:
    """Write fresh audio before each scan so every scan stays over the limit."""

    index = first_index
    for _scan in range(scans):
        for _ in range(writes_per_scan):
            _write_wav(tap_root / channel_id / f"chunk-{index:06d}.wav")
            index += 1
        worker.run_once()
    return index


# ---------------------------------------------------------------------------
# The collector's own contract.
# ---------------------------------------------------------------------------
class TestShedDiagnosticCollector:
    def test_streak_start_emits_every_required_field(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        _streak_start(_collector(clock))

        payloads = _payloads(caplog)
        assert len(payloads) == 1
        payload = payloads[0]
        assert payload["event"] == "over-limit-streak-start"
        assert payload["channel"] == "education"
        assert payload["queue_depth"] == 7
        assert payload["oldest_queue_age_s"] == 31.4
        assert payload["max_backlog_segments"] == 2
        assert payload["overload_streak"] == 1
        assert payload["persistence_scans"] == 15
        # Process + thread state, the ffmpeg census, and the GPU verdict.
        assert isinstance(payload["pid"], int)
        assert payload["process"]["threads"] == 42
        assert payload["process"]["priority_class"] == "NORMAL_PRIORITY_CLASS"
        assert "cpu_s_window" in payload["process"]
        assert "ffmpeg" in payload and "gpu" in payload
        assert payload["gpu"]["available"] is True
        # The batch record and the ASR in-call state are always present.
        assert payload["batches"] == []
        assert payload["batches_total"] == 0
        assert payload["asr_in_call"] is False
        assert payload["asr_call_s"] is None
        assert payload["suppressed_since_last"] == 0

    def test_shed_emits_every_required_field(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        _shed(_collector(clock))

        payloads = _payloads(caplog)
        assert len(payloads) == 1
        payload = payloads[0]
        assert payload["event"] == "catch-up-shed"
        assert payload["channel"] == "education"
        assert payload["queue_depth"] == 7
        assert payload["oldest_queue_age_s"] == 31.4
        assert payload["overload_streak"] == 15
        assert payload["shed"] == {"count": 5, "kept": 2, "skipped_s": 25.0}

    def test_the_line_is_rate_limited_per_channel_per_event(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        collector = _collector(clock)

        _streak_start(collector)
        clock.advance(5.0)
        _streak_start(collector)  # inside the window -> suppressed, counted
        clock.advance(26.0)  # 31 s after the first line
        _streak_start(collector)

        payloads = _payloads(caplog)
        assert len(payloads) == 2
        assert payloads[1]["suppressed_since_last"] == 1

    def test_the_two_events_are_rate_limited_independently(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A streak start and the shed it leads to must both print.

        This is the deliberate deviation from a strict per-channel limit: the
        two events are one persistence window apart by construction, so a single
        channel budget would systematically suppress the shed line -- the one
        line the whole diagnostic exists to produce. The bound is therefore per
        (channel, event): at most two lines per channel per window.
        """

        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        collector = _collector(clock)

        _streak_start(collector)
        clock.advance(1.0)
        _shed(collector)

        assert [payload["event"] for payload in _payloads(caplog)] == [
            "over-limit-streak-start",
            "catch-up-shed",
        ]

    def test_batch_records_are_bounded_and_carry_the_four_durations(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        collector = _collector(clock, max_batch_records=3)

        for index in range(10):
            collector.note_stabilize("education", 0.5 + index)
            collector.record_batch(
                channel="education",
                wait_seconds=0.1,
                feed_seconds=0.2,
                asr_seconds=1.0 + index,
            )
        _shed(collector)

        payload = _payloads(caplog)[0]
        assert payload["batches_retained"] == 3
        assert payload["batches_total"] == 10
        assert len(payload["batches"]) == 3
        # The newest three, each pairing its stabilize sample with its batch.
        assert [record["asr_s"] for record in payload["batches"]] == [8.0, 9.0, 10.0]
        assert [record["stabilize_s"] for record in payload["batches"]] == [7.5, 8.5, 9.5]
        assert payload["batches"][0]["wait_s"] == 0.1
        assert payload["batches"][0]["feed_s"] == 0.2

    def test_the_asr_call_state_is_reported_and_cleared(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        collector = _collector(clock)

        collector.asr_started(channel="education")
        clock.advance(3.25)
        _streak_start(collector)

        payload = _payloads(caplog)[0]
        assert payload["asr_in_call"] is True
        assert payload["asr_call_s"] == 3.25

        collector.asr_finished(channel="education")
        clock.advance(1.0)
        _shed(collector)

        assert _payloads(caplog)[1]["asr_in_call"] is False
        assert _payloads(caplog)[1]["asr_call_s"] is None

    def test_a_broken_log_handler_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        clock = _FakeClock()
        collector = _collector(clock)

        def broken(*args: object, **kwargs: object) -> None:
            raise RuntimeError("logging is broken")

        monkeypatch.setattr(tsd._LOG, "info", broken)
        # Neither event may propagate out of the diagnostic.
        _streak_start(collector)
        _shed(collector)

    def test_probe_failures_report_unavailable(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        collector = _collector(
            clock,
            psutil_module=_ExplodingPsutil(),
            gpu_probe=lambda: (_ for _ in ()).throw(RuntimeError("gpu is broken")),
        )
        _streak_start(collector)

        payload = _payloads(caplog)[0]
        assert payload["process"]["threads"] is None
        assert payload["process"]["priority_class"] == "unavailable"
        assert payload["ffmpeg"] == {"unavailable": "psutil-error"}
        assert payload["gpu"] == {"available": False, "reason": "gpu-probe-failed"}

    def test_missing_psutil_is_reported_not_assumed(
        self, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()

        def no_psutil() -> object:
            raise ImportError("no psutil here")

        collector = ShedDiagnosticCollector(monotonic=clock, gpu_probe=_fake_gpu)
        monkeypatch.setattr(collector, "_psutil_resolved", True)
        monkeypatch.setattr(collector, "_psutil_handle", None)
        _shed(collector)

        payload = _payloads(caplog)[0]
        assert payload["ffmpeg"] == {"unavailable": "psutil-not-installed"}
        assert payload["process"]["threads"] is None
        assert no_psutil  # the monkeypatched absence is the point, not the function

    def test_the_ffmpeg_census_is_box_wide_not_children_only(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        psutil = _FakePsutil(
            processes=[
                ("ffmpeg.exe", 991, _FakePsutil.BELOW_NORMAL_PRIORITY_CLASS),
                ("ffmpeg.exe", 992, _FakePsutil.NORMAL_PRIORITY_CLASS),
                ("python.exe", 8123, _FakePsutil.NORMAL_PRIORITY_CLASS),
            ]
        )
        _shed(_collector(clock, psutil_module=psutil))

        ffmpeg = _payloads(caplog)[0]["ffmpeg"]
        assert ffmpeg["count"] == 2
        assert [proc["pid"] for proc in ffmpeg["procs"]] == [991, 992]
        assert ffmpeg["procs"][0]["priority_class"] == "BELOW_NORMAL_PRIORITY_CLASS"

    def test_the_environment_probe_is_coalesced_across_channels(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        clock = _FakeClock()

        calls = 0

        def counting_gpu() -> dict[str, object]:
            nonlocal calls
            calls += 1
            return _fake_gpu()

        collector = _collector(clock, gpu_probe=counting_gpu)
        _streak_start(collector, channel="education")
        _streak_start(collector, channel="government")
        _streak_start(collector, channel="public")

        assert len(_payloads(caplog)) == 3
        assert calls == 1, "one probe refresh must serve every channel in the scan"

    def test_the_rate_limit_key_space_is_bounded(self, caplog: pytest.LogCaptureFixture) -> None:
        """A channel churn must not grow the bookkeeping without bound.

        The limiter keeps at most two keys per channel slot -- one per event --
        so driving more channels than the bound can only produce that many
        lines. Nothing here raises or grows; the oldest keys are dropped.
        """

        caplog.set_level(logging.INFO)
        clock = _FakeClock()
        collector = _collector(clock)

        for index in range(40):
            clock.advance(31.0)
            _streak_start(collector, channel=f"channel-{index}")

        payloads = _payloads(caplog)
        assert len(payloads) == tsd._MAX_CHANNELS * 2

    def test_the_env_switch_disables_the_diagnostic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for value in ("0", "false", "no", "off", "OFF"):
            monkeypatch.setenv(SHED_DIAGNOSTIC_ENV_VAR, value)
            assert isinstance(shed_diagnostic_from_env(), NullShedDiagnostic), value

    def test_an_absent_or_truthy_env_var_keeps_it_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(SHED_DIAGNOSTIC_ENV_VAR, raising=False)
        assert isinstance(shed_diagnostic_from_env(), ShedDiagnosticCollector)
        monkeypatch.setenv(SHED_DIAGNOSTIC_ENV_VAR, "1")
        assert isinstance(shed_diagnostic_from_env(), ShedDiagnosticCollector)

    def test_the_null_diagnostic_reads_no_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def forbidden() -> float:
            raise AssertionError("the disabled diagnostic must not read a clock")

        monkeypatch.setattr(tsd.time, "monotonic", forbidden)
        diagnostic = NullShedDiagnostic()
        assert diagnostic.samples_phases is False
        diagnostic.record_batch(channel="x", wait_seconds=0, feed_seconds=0, asr_seconds=0)
        diagnostic.note_stabilize("x", 0.0)
        diagnostic.asr_started(channel="x")
        diagnostic.asr_finished(channel="x")
        _streak_start(diagnostic)
        _shed(diagnostic)


class TestTheDecodeSplitFields:
    """BETA.10 U71. ``asr_s`` said how long the whole call took, but not where
    the time went: a slow decode and a slow publish looked identical, and a
    faster-whisper fallback pass (which re-decodes at a higher temperature) was
    invisible. Each batch record now also carries the decode proper
    (``transcribe_s``, measured by the runtime), the remainder of the call
    (``other_process_batch_s``), the audio the VAD actually kept
    (``duration_after_vad``) and the highest decode temperature the model
    returned (``max_segment_temperature``, above ``0.0`` exactly when the
    fallback list was walked).
    """

    def test_the_decode_fields_are_recorded_and_persist_is_derived(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        collector = _collector(_FakeClock())
        collector.note_stabilize("education", 0.4)
        collector.record_batch(
            channel="education",
            wait_seconds=0.1,
            feed_seconds=0.2,
            asr_seconds=5.833,
            transcribe_seconds=5.3,
            duration_after_vad_seconds=4.988,
            max_segment_temperature=0.32,
        )
        _shed(collector)

        record = _payloads(caplog)[0]["batches"][0]
        assert record["asr_s"] == 5.833
        assert record["transcribe_s"] == 5.3
        assert record["duration_after_vad"] == 4.988
        # Above zero: the model walked its temperature fallback list.
        assert record["max_segment_temperature"] == 0.32
        # other_process_batch_s is exactly asr - transcribe - stabilize.
        assert record["other_process_batch_s"] == round(5.833 - 5.3 - 0.4, 3)
        # The whole payload must survive the JSON round trip the emitter does.
        assert json.loads(json.dumps(_payloads(caplog)[0]))["batches"][0] == record

    def test_a_single_pass_decode_reports_a_zero_not_an_absent_temperature(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        collector = _collector(_FakeClock())
        collector.note_stabilize("education", 0.25)
        collector.record_batch(
            channel="education",
            wait_seconds=0.0,
            feed_seconds=0.0,
            asr_seconds=3.0,
            transcribe_seconds=2.5,
            max_segment_temperature=0.0,
        )
        _shed(collector)

        record = _payloads(caplog)[0]["batches"][0]
        # ``0.0`` is the meaningful "one pass" value; collapsing it to null
        # would make the common case indistinguishable from "no segments".
        assert record["max_segment_temperature"] == 0.0
        assert record["other_process_batch_s"] == round(3.0 - 2.5 - 0.25, 3)

    def test_a_batch_without_the_decode_numbers_still_serialises_with_nulls(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        collector = _collector(_FakeClock())
        collector.note_stabilize("education", 0.5)
        collector.record_batch(
            channel="education", wait_seconds=0.0, feed_seconds=0.1, asr_seconds=2.0
        )
        _shed(collector)

        payload = _payloads(caplog)[0]
        record = payload["batches"][0]
        for field_name in (
            "transcribe_s",
            "other_process_batch_s",
            "duration_after_vad",
            "max_segment_temperature",
        ):
            assert field_name in record, field_name
            assert record[field_name] is None, field_name
        # The pre-U71 fields keep their old values and shape.
        assert record["wait_s"] == 0.0
        assert record["feed_s"] == 0.1
        assert record["asr_s"] == 2.0
        assert record["stabilize_s"] == 0.5
        assert json.loads(json.dumps(payload))["batches"][0] == record

    def test_persist_is_unknown_unless_both_of_its_terms_are_known(self) -> None:
        collector = _collector(_FakeClock())
        # transcribe known, stabilize never sampled -> a residual would be wrong.
        collector.record_batch(
            channel="a",
            wait_seconds=0.0,
            feed_seconds=0.0,
            asr_seconds=2.0,
            transcribe_seconds=1.5,
        )
        # stabilize sampled, transcribe unknown -> same.
        collector.note_stabilize("b", 0.25)
        collector.record_batch(channel="b", wait_seconds=0.0, feed_seconds=0.0, asr_seconds=2.0)

        assert collector._batches["a"][0]["transcribe_s"] == 1.5
        assert collector._batches["a"][0]["other_process_batch_s"] is None
        assert collector._batches["b"][0]["transcribe_s"] is None
        assert collector._batches["b"][0]["other_process_batch_s"] is None


class TestShedDiagnosticEnvSpelling:
    """BETA.10 U71. U69 shipped the disable switch reading only the one-C
    ``CIVICAST_CAPTION_TAP_SHED_DIAGNOSTIC``, so an operator who set it the way
    the station's service registry writes variables -- the two-C
    ``CIVICCAST_CAPTION_TAP_SHED_DIAGNOSTIC`` -- got a silently inert switch and
    kept the diagnostic running.  The resolution now goes through
    ``env_vars.resolve_renamed_env``: registry spelling primary, one-C still read
    as a legacy fallback, two-C wins when both are set.
    """

    _PRIMARY = "CIVICCAST_CAPTION_TAP_SHED_DIAGNOSTIC"
    _LEGACY = "CIVICAST_CAPTION_TAP_SHED_DIAGNOSTIC"
    _LOGGER = "civiccast.captions.tap_shed_diagnostic"

    @pytest.fixture(autouse=True)
    def _fresh_one_time_latch(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tsd, "_RENAMED_ENV_WARNED", set(), raising=False)

    def test_the_registry_spelling_is_the_two_c_one(self) -> None:
        """Machine-checkable, since ``CIVICAST`` and ``CIVICCAST`` render almost
        identically: the primary prefix is 9 characters, the legacy one's is 8."""

        assert SHED_DIAGNOSTIC_ENV_VAR == self._PRIMARY
        assert tsd.LEGACY_SHED_DIAGNOSTIC_ENV_VAR == self._LEGACY
        assert len(SHED_DIAGNOSTIC_ENV_VAR.split("_", 1)[0]) == 9
        assert len(tsd.LEGACY_SHED_DIAGNOSTIC_ENV_VAR.split("_", 1)[0]) == 8

    def test_the_registry_spelling_disables_the_diagnostic(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """RED before this change: only the two-C name set, the switch was inert
        and the real collector came back."""

        monkeypatch.delenv(self._LEGACY, raising=False)
        monkeypatch.setenv(self._PRIMARY, "0")

        with caplog.at_level(logging.WARNING, logger=self._LOGGER):
            assert isinstance(shed_diagnostic_from_env(), NullShedDiagnostic)

        assert caplog.records == []

    def test_the_legacy_spelling_still_disables_it_and_warns_once(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.delenv(self._PRIMARY, raising=False)
        monkeypatch.setenv(self._LEGACY, "0")

        with caplog.at_level(logging.WARNING, logger=self._LOGGER):
            assert isinstance(shed_diagnostic_from_env(), NullShedDiagnostic)
            assert isinstance(shed_diagnostic_from_env(), NullShedDiagnostic)

        deprecations = [record for record in caplog.records if self._LEGACY in record.getMessage()]
        assert len(deprecations) == 1, [record.getMessage() for record in caplog.records]
        assert self._PRIMARY in deprecations[0].getMessage()

    def test_the_registry_spelling_wins_when_both_are_set(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv(self._LEGACY, "1")  # would keep the diagnostic on
        monkeypatch.setenv(self._PRIMARY, "0")  # wins: off

        with caplog.at_level(logging.WARNING, logger=self._LOGGER):
            assert isinstance(shed_diagnostic_from_env(), NullShedDiagnostic)

        conflicts = [record for record in caplog.records if "both set" in record.getMessage()]
        assert len(conflicts) == 1, [record.getMessage() for record in caplog.records]
        assert self._PRIMARY in conflicts[0].getMessage()
        assert self._LEGACY in conflicts[0].getMessage()

    def test_a_whitespace_registry_value_falls_through_to_the_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(self._PRIMARY, "   ")
        monkeypatch.setenv(self._LEGACY, "0")

        assert isinstance(shed_diagnostic_from_env(), NullShedDiagnostic)

    def test_an_absent_pair_still_keeps_the_diagnostic_on(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(self._PRIMARY, raising=False)
        monkeypatch.delenv(self._LEGACY, raising=False)

        assert isinstance(shed_diagnostic_from_env(), ShedDiagnosticCollector)


# ---------------------------------------------------------------------------
# The phase forwarder.
# ---------------------------------------------------------------------------
class _RecordingPhases:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.summarised = 0

    def phase(self, name: str, **kwargs: object) -> AbstractContextManager[None]:
        self.calls.append((name, kwargs))
        return nullcontext()

    def wait(self, phase: str, **kwargs: object) -> AbstractContextManager[None]:
        return nullcontext()

    def summarise(self, *, force: bool = False) -> dict[str, object]:
        self.summarised += 1
        return {"ok": True}


class _BrokenPhases:
    def phase(self, name: str, **kwargs: object) -> AbstractContextManager[None]:
        raise RuntimeError("inner phase is broken")

    def wait(self, phase: str, **kwargs: object) -> AbstractContextManager[None]:
        raise RuntimeError("inner wait is broken")

    def summarise(self, *, force: bool = False) -> dict[str, object]:
        raise RuntimeError("inner summarise is broken")


class TestPhaseSampleForwarder:
    def test_it_forwards_every_phase_and_samples_stabilize(self) -> None:
        inner = _RecordingPhases()
        samples: list[tuple[str, float]] = []
        clock = _FakeClock()
        forwarder = PhaseSampleForwarder(
            inner, lambda channel, seconds: samples.append((channel, seconds)), monotonic=clock
        )

        with forwarder.phase("runtime_transcribe", channel="education"):
            clock.advance(2.5)

        # Forwarded unchanged, and NOT sampled: only the stabilize phase is.
        assert inner.calls == [("runtime_transcribe", {"channel": "education"})]
        assert samples == []

        with forwarder.phase("caption_stabilize", channel="education"):
            clock.advance(0.25)

        assert samples == [("education", 0.25)]

    def test_it_does_not_swallow_the_body_exception(self) -> None:
        samples: list[tuple[str, float]] = []
        clock = _FakeClock()
        forwarder = PhaseSampleForwarder(
            _RecordingPhases(),
            lambda channel, seconds: samples.append((channel, seconds)),
            monotonic=clock,
        )

        with (
            pytest.raises(ValueError, match="asr blew up"),
            forwarder.phase("caption_stabilize", channel="education"),
        ):
            clock.advance(1.0)
            raise ValueError("asr blew up")

        # The body raised, and the sample was still taken on the way out.
        assert samples == [("education", 1.0)]

    def test_it_survives_a_broken_inner_collector(self) -> None:
        forwarder = PhaseSampleForwarder(_BrokenPhases(), lambda channel, seconds: None)

        ran = False
        with forwarder.phase("caption_stabilize", channel="education"):
            ran = True
        assert ran, "a broken inner collector must not stop the tap's own work"

        with forwarder.wait("wait_session_lock", channel="education"):
            pass
        assert forwarder.summarise() == {}
        assert forwarder.summarise(force=True) == {}

    def test_a_raising_stabilize_sink_does_not_escape(self) -> None:
        def broken_sink(channel: str, seconds: float) -> None:
            raise RuntimeError("sink is broken")

        forwarder = PhaseSampleForwarder(_RecordingPhases(), broken_sink)
        with forwarder.phase("caption_stabilize", channel="education"):
            pass


# ---------------------------------------------------------------------------
# Tap integration.
# ---------------------------------------------------------------------------
class TestTapShedDiagnostic:
    def test_predecode_worker_failure_clears_previous_runtime_metrics(self, tmp_path, monkeypatch):
        clock = _FakeClock()
        collector = _collector(clock)

        class Runtime(_ScriptedRuntime):
            def __init__(self):
                super().__init__()
                self.last = {"transcribe_s": 99.0}

            def reset_decode_metrics(self):
                self.last = None

            def last_decode_metrics(self):
                return self.last

        runtime = Runtime()
        tap_root = tmp_path / "tap"
        worker = _tap(tap_root, clock=clock, diagnostic=collector, runtime=runtime)
        worker._sweep_retention()
        assert worker.wait_for_retention_sweep(timeout=5)
        path = tap_root / "education" / "chunk-000000.wav"
        _write_wav(path)
        error = RuntimeError("before runtime")

        def fail(*args, **kwargs):
            raise error

        monkeypatch.setattr(worker._worker_for("education"), "process_batch", fail)
        with pytest.raises(RuntimeError) as caught:
            worker._process_channel("education", path.parent, [(0, path)])
        assert caught.value is error
        assert collector._batches["education"][0]["transcribe_s"] is None

    def test_metrics_getter_property_failure_is_absent(self, tmp_path):
        class Runtime(_ScriptedRuntime):
            @property
            def last_decode_metrics(self):
                raise RuntimeError("getter property")

        worker = _tap(
            tmp_path / "tap", clock=_FakeClock(), diagnostic=NullShedDiagnostic(), runtime=Runtime()
        )
        try:
            result = worker._last_decode_metrics()
        except RuntimeError as error:
            result = error
        assert result is None

    def test_the_tap_emits_a_streak_start_then_a_shed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        tap_root = tmp_path / "tap"
        channel = "education"
        (tap_root / channel).mkdir(parents=True)

        clock = _FakeClock()
        collector = _collector(clock)
        worker = _tap(tap_root, clock=clock, diagnostic=collector)

        _drive_over_limit_episode(worker, tap_root, channel, scans=3)

        payloads = _payloads(caplog)
        assert [payload["event"] for payload in payloads] == [
            "over-limit-streak-start",
            "catch-up-shed",
        ], "the first over-limit scan and the shed it led to must both be reported"

        streak, shed = payloads
        assert streak["channel"] == channel
        assert streak["overload_streak"] == 1
        assert streak["persistence_scans"] == 3
        assert streak["max_backlog_segments"] == 2
        assert streak["queue_depth"] > 2
        assert streak["oldest_queue_age_s"] >= 0.0

        assert shed["channel"] == channel
        assert shed["overload_streak"] == 3
        assert shed["persistence_scans"] == 3
        assert shed["shed"]["count"] > 0
        assert shed["shed"]["kept"] == 2
        assert shed["shed"]["skipped_s"] > 0.0
        # The batch evidence the line exists to carry: at least one real batch.
        assert shed["batches_total"] >= 1
        assert any(record["asr_s"] is not None for record in shed["batches"])

    def test_the_tap_records_the_four_batch_durations(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        tap_root = tmp_path / "tap"
        channel = "education"
        (tap_root / channel).mkdir(parents=True)

        clock = _FakeClock()
        collector = _collector(clock)
        worker = _tap(tap_root, clock=clock, diagnostic=collector)

        _write_wav(tap_root / channel / "chunk-000000.wav")
        _write_wav(tap_root / channel / "chunk-000001.wav")
        worker.run_once()

        collector.asr_finished(channel=channel)  # defensive: ensure a clean snapshot
        _shed(collector)

        records = _payloads(caplog)[0]["batches"]
        assert len(records) == 1
        record = records[0]
        # All four durations are present and non-negative: wait, feed, ASR, and
        # the stabilize sample the forwarder reported from inside the pipeline.
        for field_name in ("wait_s", "feed_s", "asr_s", "stabilize_s"):
            assert field_name in record, field_name
            assert record[field_name] is not None, field_name
            assert record[field_name] >= 0.0, field_name

    def test_the_decode_split_reaches_the_batch_record(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The runtime's numbers must survive the tap's hot path to the line."""

        caplog.set_level(logging.INFO)
        tap_root = tmp_path / "tap"
        channel = "education"
        (tap_root / channel).mkdir(parents=True)

        clock = _FakeClock()

        class _DecodingRuntime(_ScriptedRuntime):
            def transcribe(
                self,
                chunks: Iterable[AudioChunk],
                vocabulary: CustomVocabulary | None = None,
            ) -> Iterable[CaptionHypothesis]:
                # Burn six wall seconds in the decode so the tap's own ``asr_s``
                # is larger than the decode it contains, as on the real path.
                clock.advance(6.0)
                yield from super().transcribe(chunks, vocabulary=vocabulary)

            def last_decode_metrics(self) -> dict[str, object]:
                return {
                    "transcribe_s": 5.3,
                    "duration_after_vad": 4.988,
                    "max_segment_temperature": 0.4,
                }

        collector = _collector(clock)
        worker = _tap(tap_root, clock=clock, diagnostic=collector, runtime=_DecodingRuntime())

        _write_wav(tap_root / channel / "chunk-000000.wav")
        _write_wav(tap_root / channel / "chunk-000001.wav")
        worker.run_once()

        collector.asr_finished(channel=channel)
        _shed(collector)

        record = _payloads(caplog)[0]["batches"][0]
        assert record["transcribe_s"] == 5.3
        assert record["duration_after_vad"] == 4.988
        assert record["max_segment_temperature"] == 0.4
        # other_process_batch_s is derived inside the collector from the tap's own numbers.
        assert record["other_process_batch_s"] == pytest.approx(
            record["asr_s"] - 5.3 - record["stabilize_s"], abs=1e-3
        )

    def test_a_metrics_getter_that_raises_does_not_break_the_tap(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        tap_root = tmp_path / "tap"
        channel = "education"
        (tap_root / channel).mkdir(parents=True)

        class _ExplodingGetterRuntime(_ScriptedRuntime):
            def last_decode_metrics(self) -> None:
                raise RuntimeError("the metrics getter blew up")

        clock = _FakeClock()
        collector = _collector(clock)
        worker = _tap(
            tap_root, clock=clock, diagnostic=collector, runtime=_ExplodingGetterRuntime()
        )

        _drive_over_limit_episode(worker, tap_root, channel, scans=3)

        payloads = _payloads(caplog)
        assert payloads, "a broken metrics getter must not suppress the shed line"
        records = payloads[-1]["batches"]
        assert records, "the batch records must still be emitted"
        # The measurement is absent, and it says so rather than inventing zeros.
        for record in records:
            assert record["transcribe_s"] is None
            assert record["other_process_batch_s"] is None
            assert record["duration_after_vad"] is None
            assert record["max_segment_temperature"] is None

    def test_the_queue_age_is_measured_once_per_event_not_per_batch(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The added cost is bounded to the two rare events, not the hot path.

        The brief's "no I/O on the audio hot path" is preserved: the queue age
        (which stats every queued segment) is computed exactly once when a
        streak starts and once when a shed fires -- never once per batch.
        """

        caplog.set_level(logging.INFO)
        tap_root = tmp_path / "tap"
        channel = "education"
        (tap_root / channel).mkdir(parents=True)

        clock = _FakeClock()
        collector = _collector(clock)
        worker = _tap(tap_root, clock=clock, diagnostic=collector)

        age_calls: list[object] = []
        monkeypatch.setattr(
            worker,
            "_oldest_queue_age_seconds",
            lambda segments: age_calls.append(segments) or 0.0,
        )

        _drive_over_limit_episode(worker, tap_root, channel, scans=3)

        payloads = _payloads(caplog)
        assert [payload["event"] for payload in payloads] == [
            "over-limit-streak-start",
            "catch-up-shed",
        ]
        assert len(age_calls) == 2, "one measurement per event, never per batch"
        batches = payloads[-1]["batches_total"]
        assert batches > 2, "more batches ran than the two queue-age measurements"

    def test_a_broken_diagnostic_never_breaks_the_tap(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.DEBUG)
        tap_root = tmp_path / "tap"
        channel = "education"
        (tap_root / channel).mkdir(parents=True)

        class _ExplodingDiagnostic:
            samples_phases = True

            def __getattr__(self, name: str) -> Callable[..., None]:
                def boom(**kwargs: object) -> None:
                    raise RuntimeError(f"diagnostic {name} exploded")

                return boom

        clock = _FakeClock()
        worker = _tap(tap_root, clock=clock, diagnostic=_ExplodingDiagnostic())

        _drive_over_limit_episode(worker, tap_root, channel, scans=3)

        # The tap's own shed still happened...
        warnings = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("Caption tap catch-up for channel")
        ]
        assert warnings, "the shed itself must be unaffected by a broken diagnostic"
        # ...the diagnostic produced no line at all...
        assert _payloads(caplog) == []
        # ...and every failure was caught and logged at debug, not raised.
        hook_failures = [
            record
            for record in caplog.records
            if record.getMessage().startswith("Caption tap shed diagnostic hook")
        ]
        assert hook_failures

    def test_a_disabled_diagnostic_is_inert_in_the_tap(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        tap_root = tmp_path / "tap"
        channel = "education"
        (tap_root / channel).mkdir(parents=True)

        clock = _FakeClock()
        worker = _tap(tap_root, clock=clock, diagnostic=NullShedDiagnostic())

        result = worker.run_once()  # a first scan keeps the tap's own machinery live
        assert result is not None
        _drive_over_limit_episode(worker, tap_root, channel, scans=3, first_index=4)

        assert _payloads(caplog) == [], "the disabled diagnostic must emit nothing"
        warnings = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("Caption tap catch-up for channel")
        ]
        assert warnings, "the shed itself is unchanged when the diagnostic is off"

    def test_the_stabilize_phase_reaches_the_collector_through_the_worker(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO)
        tap_root = tmp_path / "tap"
        channel = "education"
        (tap_root / channel).mkdir(parents=True)

        clock = _FakeClock()
        collector = _collector(clock)
        worker = _tap(tap_root, clock=clock, diagnostic=collector)

        _write_wav(tap_root / channel / "chunk-000000.wav")
        _write_wav(tap_root / channel / "chunk-000001.wav")
        worker.run_once()

        # The forwarder is what the per-channel worker got, and it sampled the
        # stabilize phase rather than passing a bare collector down.
        assert worker._worker_phase_timing is not worker._phase_timing
        assert isinstance(worker._worker_phase_timing, PhaseSampleForwarder)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 10**400, "bad", None])
def test_invalid_optional_fields_emit_finite_json_null(caplog, bad):
    caplog.set_level(logging.INFO)
    collector = _collector(_FakeClock())
    collector.note_stabilize("education", bad)
    collector.record_batch(
        channel="education",
        wait_seconds=bad,
        feed_seconds=bad,
        asr_seconds=bad,
        transcribe_seconds=bad,
        duration_after_vad_seconds=bad,
        max_segment_temperature=bad,
    )
    _shed(collector)
    record = _payloads(caplog)[0]["batches"][0]
    assert record["transcribe_s"] is None
    assert record["duration_after_vad"] is None
    assert record["max_segment_temperature"] is None
    assert record["other_process_batch_s"] is None
    assert record["stabilize_s"] is None
    assert "persist_s" not in record
    assert set(record) == {
        "wait_s",
        "feed_s",
        "asr_s",
        "stabilize_s",
        "transcribe_s",
        "duration_after_vad",
        "max_segment_temperature",
        "other_process_batch_s",
    }
    json.dumps(_payloads(caplog)[0], allow_nan=False)


def test_retention_hard_ceiling_and_negative_residual_are_not_guessed():
    collector = _collector(_FakeClock(), max_batch_records=10**6)
    for channel in range(100):
        for _batch in range(20):
            collector.note_stabilize(str(channel), 2)
            collector.record_batch(
                channel=str(channel),
                wait_seconds=0,
                feed_seconds=0,
                asr_seconds=1,
                transcribe_seconds=3,
            )
    assert len(collector._batches) == 16
    assert all(len(records) == 8 for records in collector._batches.values())
    assert all(
        records[-1]["other_process_batch_s"] is None for records in collector._batches.values()
    )


def test_sampling_clock_failure_does_not_change_body_or_exception():
    def clock():
        raise RuntimeError("measurement clock")

    forwarder = PhaseSampleForwarder(_RecordingPhases(), lambda *a: None, monotonic=clock)
    executed = []
    try:
        with forwarder.phase("caption_stabilize", channel="education"):
            executed.append(True)
    except RuntimeError:
        pass
    assert executed == [True]
    error = RuntimeError("pipeline error")
    with (
        pytest.raises(RuntimeError) as caught,
        forwarder.phase("caption_stabilize", channel="education"),
    ):
        raise error
    assert caught.value is error


@pytest.mark.parametrize("hook", ["note", "get", "reset"])
def test_diagnostic_failure_logger_cannot_escape(tmp_path, monkeypatch, hook):
    import civiccast.captions.tap_worker as tap_module

    class Broken:
        def __getattr__(self, name):
            raise RuntimeError("measurement")

    worker = _tap(tmp_path / "tap", clock=_FakeClock(), diagnostic=NullShedDiagnostic())
    worker._runtime = Broken()
    worker._shed_diagnostic = Broken()

    def debug(*args, **kwargs):
        raise RuntimeError("logger")

    monkeypatch.setattr(tap_module._LOG, "debug", debug)
    failure = None
    try:
        if hook == "note":
            worker._note_shed_diagnostic("asr_started", channel="education")
        elif hook == "get":
            assert worker._last_decode_metrics() is None
        else:
            worker._reset_decode_metrics()
    except RuntimeError as error:
        failure = error
    assert failure is None
