# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for the opt-in caption-tap PHASE TIMING collector.

The collector exists to answer "where does a scan's time go" (retention sweep
vs ASR vs file work vs lock WAITING) during the beta.9 N=3 stall investigation.
It must be invisible unless explicitly switched on, so these tests pin:

* the switch is default OFF;
* with the switch OFF no clock is read at all (so production timing cannot
  change) and the scan result is identical;
* with the switch ON, per-phase durations are aggregated with count/total/max;
* lock WAIT is recorded as its own phase, distinct from held-lock work;
* the collector is BOUNDED by both an event cap and a wall-clock window;
* a broken handler cannot change scan behaviour.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from civiccast.captions import phase_timing as pt
from civiccast.captions.phase_timing import (
    NullPhaseTimingCollector,
    PhaseTimingCollector,
    phase_timing_from_env,
)


def test_switch_is_default_off(monkeypatch):
    monkeypatch.delenv(pt.PHASE_TIMING_ENV_VAR, raising=False)
    assert isinstance(phase_timing_from_env(), NullPhaseTimingCollector)


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "  "])
def test_non_enabling_values_stay_inert(monkeypatch, value):
    monkeypatch.setenv(pt.PHASE_TIMING_ENV_VAR, value)
    assert isinstance(phase_timing_from_env(), NullPhaseTimingCollector)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_enabling_values_build_the_real_collector(monkeypatch, value):
    monkeypatch.setenv(pt.PHASE_TIMING_ENV_VAR, value)
    assert isinstance(phase_timing_from_env(), PhaseTimingCollector)


def test_off_reads_no_clock(monkeypatch):
    """With the switch off, even the clock must not be consulted."""

    def forbidden_clock():
        pytest.fail("default-off phase timing read the monotonic clock")

    monkeypatch.setattr(pt.time, "monotonic_ns", forbidden_clock)
    collector = NullPhaseTimingCollector()
    with collector.phase("asr_process_batch"):
        pass
    with collector.wait("wait_session_lock"):
        pass
    assert collector.summarise() == {}


def test_records_per_phase_count_total_and_max():
    collector = PhaseTimingCollector()
    for _ in range(3):
        with collector.phase("asr_process_batch"):
            pass
    with collector.wait("wait_session_lock"):
        pass
    summary = collector.summarise()
    assert summary["asr_process_batch"]["count"] == 3
    assert summary["wait_session_lock"]["count"] == 1
    assert summary["asr_process_batch"]["total_ms"] >= 0.0
    assert summary["asr_process_batch"]["max_ms"] >= 0.0


def test_lock_wait_is_a_separate_phase_from_work():
    collector = PhaseTimingCollector()
    with collector.wait("wait_retention_lock"):
        pass
    with collector.phase("retention_sweep_work"):
        pass
    summary = collector.summarise()
    assert "wait_retention_lock" in summary
    assert "retention_sweep_work" in summary


def test_summary_is_emitted_once(caplog):
    caplog.set_level(logging.INFO)
    collector = PhaseTimingCollector()
    with collector.phase("file_move_to_processed"):
        pass
    first = collector.summarise()
    second = collector.summarise()
    assert first
    assert second == {}
    lines = [
        r.message
        for r in caplog.records
        if r.message.startswith("Caption tap phase timing summary")
    ]
    assert len(lines) == 1
    payload = json.loads(lines[0].removeprefix("Caption tap phase timing summary "))
    assert payload["events"] >= 1
    assert "phases" in payload


def test_event_cap_bounds_recording():
    collector = PhaseTimingCollector(max_events=2)
    for _ in range(10):
        with collector.phase("asr_process_batch"):
            pass
    summary = collector.summarise()
    assert summary["asr_process_batch"]["count"] == 2


def test_window_bound_stops_recording(monkeypatch):
    """Past the wall-clock window the collector records nothing.

    The constructor takes its start stamp via ``time.monotonic_ns``, so the
    fake clock must be installed BEFORE construction for the window to apply.
    """

    clock = {"t": 0}

    def fake_ns():
        return clock["t"]

    monkeypatch.setattr(pt.time, "monotonic_ns", fake_ns)
    collector = PhaseTimingCollector(window_seconds=1.0)
    clock["t"] = 2_000_000_000  # 2s later, past the 1s window
    with collector.phase("asr_process_batch"):
        pass
    assert collector.summarise() == {}


def test_within_window_does_record(monkeypatch):
    clock = {"t": 0}

    def fake_ns():
        return clock["t"]

    monkeypatch.setattr(pt.time, "monotonic_ns", fake_ns)
    collector = PhaseTimingCollector(window_seconds=10.0)
    clock["t"] = 500_000_000  # 0.5s later, inside the window
    with collector.phase("asr_process_batch"):
        pass
    assert "asr_process_batch" in collector.summarise()


def test_broken_logging_cannot_raise(caplog, monkeypatch):
    collector = PhaseTimingCollector()
    with collector.phase("asr_process_batch"):
        pass

    def broken(*_a, **_k):
        raise OSError("handler failed")

    monkeypatch.setattr(pt._LOG, "info", broken)
    assert collector.summarise()  # must not raise


def test_switch_off_leaves_scan_behaviour_unchanged(tmp_path, monkeypatch):
    """The whole point: no switch, no change in what the scan does."""

    from civiccast.captions import tap_worker as tap
    from civiccast.captions.review import InMemoryCaptionReviewStore

    monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path / "tap"))
    monkeypatch.delenv(pt.PHASE_TIMING_ENV_VAR, raising=False)

    worker = tap.build_tap_worker(
        settings=tap.CaptionTapWorkerSettings.from_env(),
        runtime=SimpleNamespace(),
        review_store=InMemoryCaptionReviewStore(),
        caption_work_dir=tmp_path / "egress",
    )
    assert isinstance(worker._phase_timing, NullPhaseTimingCollector)
    # And the scan still runs and reports normally.
    result = worker.run_once()
    assert result.consumed_segments == 0
