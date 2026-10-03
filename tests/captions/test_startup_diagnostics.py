# SPDX-License-Identifier: Apache-2.0
"""Opt-in startup receipts must observe, not change caption behavior."""

import concurrent.futures
import json
import logging
import wave
from types import SimpleNamespace

import pytest

from civiccast.captions import tap_worker as tap
from civiccast.captions.review import InMemoryCaptionReviewStore


def make_worker(tmp_path, monkeypatch, enabled=True):
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP", "inline")
    monkeypatch.setenv("CIVICCAST_CAPTION_TAP_DIR", str(tmp_path / "tap"))
    monkeypatch.setenv("CIVICCAST_CAPTION_STARTUP_DIAGNOSTICS", str(int(enabled)))
    return tap.build_tap_worker(
        settings=tap.CaptionTapWorkerSettings.from_env(),
        runtime=SimpleNamespace(),
        review_store=InMemoryCaptionReviewStore(),
        caption_work_dir=tmp_path / "egress",
    )


def receipts(caplog):
    return [
        json.loads(r.message.removeprefix("Caption startup diagnostic "))
        for r in caplog.records
        if r.message.startswith("Caption startup diagnostic ")
    ]


def test_opt_in_reset_and_initial_retention_emit_real_receipts(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker(tmp_path, monkeypatch)
    worker.begin_channel_session("public")
    worker.run_once()
    events = receipts(caplog)
    assert {e["phase"] for e in events} >= {"reset_complete", "retention_begin", "retention_end"}
    reset = next(e for e in events if e["phase"] == "reset_complete")
    assert reset["discarded"] == 0 and reset["generation"] == 1
    assert all(e["mono_ns"] > 0 and e["pid"] > 0 and e["thread_id"] for e in events)


def test_default_off(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker(tmp_path, monkeypatch, enabled=False)
    monkeypatch.delenv("CIVICCAST_CAPTION_STARTUP_DIAGNOSTICS")
    assert tap.CaptionTapWorkerSettings.from_env().startup_diagnostics is False
    worker.begin_channel_session("public")
    worker.run_once()
    assert receipts(caplog) == []


def test_reset_error_is_unchanged(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker(tmp_path, monkeypatch)
    error = OSError("private path must not enter diagnostic")

    def fail(_channel):
        raise error

    monkeypatch.setattr(worker, "_begin_channel_session_locked", fail)
    with pytest.raises(OSError) as caught:
        worker.begin_channel_session("public")
    assert caught.value is error
    events = receipts(caplog)
    assert events
    assert events[-1]["error_class"] == "OSError"
    assert "private path" not in json.dumps(events)


def test_prepare_batch_and_backlog_receipts(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker(tmp_path, monkeypatch)
    worker._runtime = SimpleNamespace(prepare=lambda: None, transcribe=lambda *a, **k: iter(()))
    channel = tmp_path / "tap" / "public"
    channel.mkdir(parents=True)
    for index in (1, 2):
        with wave.open(str(channel / f"chunk-{index:06d}.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00\x00" * 16000)
    result = worker.run_once()
    assert result.consumed_segments == 1
    events = receipts(caplog)
    phases = [e["phase"] for e in events]
    assert phases.index("retention_end") < phases.index("backlog_snapshot")
    assert phases.index("backlog_snapshot") < phases.index("prepare_begin")
    assert phases.index("prepare_end") < phases.index("batch_begin") < phases.index("batch_end")
    snapshot = next(e for e in events if e["phase"] == "backlog_snapshot")
    assert snapshot["indices"] == [1] and snapshot["atomic_segments"] is False
    assert str(tmp_path) not in json.dumps(events)


def test_prepare_error_logged_and_propagated_unchanged(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker(tmp_path, monkeypatch)
    error = RuntimeError("SECRET")
    with pytest.raises(RuntimeError) as caught, worker._startup_phase("prepare"):
        raise error
    assert caught.value is error
    assert receipts(caplog)[-1]["error_class"] == "RuntimeError"
    assert "SECRET" not in json.dumps(receipts(caplog))


def test_failed_retention_receipt_preserves_fail_closed(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker(tmp_path, monkeypatch)

    def fail(**_kwargs):
        raise OSError("private")

    worker._retention_policy = SimpleNamespace(enforce_discovered=fail)
    worker.run_once()
    end = next(e for e in receipts(caplog) if e["phase"] == "retention_end")
    assert end["ready"] is False and end["error_class"] == "OSError"
    assert worker._retention_ready is False
    assert worker._retention_verified is False


def test_diagnostic_logger_failure_cannot_replace_original_error(tmp_path, monkeypatch):
    worker = make_worker(tmp_path, monkeypatch)

    def broken_logger(*_args, **_kwargs):
        raise OSError("handler failed")

    monkeypatch.setattr(tap._LOG, "info", broken_logger)
    worker.begin_channel_session("public")
    error = ValueError("original")
    with pytest.raises(ValueError) as caught, worker._startup_phase("prepare"):
        raise error
    assert caught.value is error


def test_count_and_time_bounds_and_metadata_limit(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker(tmp_path, monkeypatch)
    segments = [(i, tmp_path / "secret.wav") for i in range(5000)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: worker._startup_event("backlog", segments=segments), range(600)))
    events = receipts(caplog)
    assert len(events) == 512
    assert len({e["sequence"] for e in events}) == 512
    assert all(e["indices"] == list(range(16)) and e["indices_truncated"] for e in events)
    caplog.clear()
    worker = make_worker(tmp_path, monkeypatch)
    monkeypatch.setattr(tap.time, "monotonic_ns", lambda: worker._startup_deadline_ns)
    worker._startup_event("expired")
    assert receipts(caplog) == []


def test_off_never_reads_diagnostic_clock_or_advances_budget(tmp_path, monkeypatch):
    worker = make_worker(tmp_path, monkeypatch, enabled=False)

    def forbidden_clock():
        pytest.fail("default-off diagnostic read clock")

    monkeypatch.setattr(tap.time, "monotonic_ns", forbidden_clock)
    worker.begin_channel_session("public")
    worker.run_once()
    assert next(worker._startup_sequence) == 0
