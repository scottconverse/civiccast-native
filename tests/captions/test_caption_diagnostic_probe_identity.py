# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U75 consumer, bounded concurrency and resident-code contracts."""

import importlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from civiccast.captions import runtime as runtime_module
from civiccast.captions import tap_shed_diagnostic as tsd
from tests.captions.test_caption_decode_measurements import chunk, segment
from tests.captions.test_caption_tap_shed_diagnostic import (
    _collector,
    _FakeClock,
    _payloads,
    _streak_start,
    _tap,
    _write_wav,
)


def identity():
    try:
        return importlib.import_module("civiccast.captions.diagnostic_identity")
    except ModuleNotFoundError:
        return None


@pytest.fixture(autouse=True)
def proof_enabled_and_owned_teardown(monkeypatch):
    helper = identity()
    if helper and hasattr(helper, "_PROOF_ENABLED"):
        monkeypatch.setattr(helper, "_PROOF_ENABLED", True)
        monkeypatch.setattr(helper, "_THREADS", {})
        monkeypatch.setattr(helper, "_SEEN", set())
    yield
    if helper and hasattr(helper, "_THREADS"):
        for thread in helper._THREADS.values():
            if thread.ident is not None:
                thread.join(2)
                assert not thread.is_alive(), "test-owned identity thread not released"


def wait_receipts(helper):
    for thread in getattr(helper, "_THREADS", {}).values():
        if thread.ident is not None:
            thread.join(2)
            assert not thread.is_alive()


def test_event_probe_never_waits_and_is_single_flight(caplog):
    caplog.set_level(logging.INFO)
    entered, release, returned = (threading.Event() for _ in range(3))
    calls = []
    clock = _FakeClock()

    def blocked():
        calls.append(1)
        entered.set()
        assert release.wait(5), "controlled probe teardown deadline"
        return {"available": False}

    collector = _collector(clock, gpu_probe=blocked, min_interval_seconds=0)
    caller = threading.Thread(
        target=lambda: (_streak_start(collector), returned.set()), daemon=True
    )
    caller.start()
    try:
        assert entered.wait(2)
        assert returned.wait(0.5), "event waited for native probe"
        clock.advance(0.2)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: _streak_start(collector, channel=str(n)), range(16)))
        assert calls == [1]
        payload = _payloads(caplog)[-1]
        assert payload["probe_status"] == "pending"
        assert payload["probe_inflight_s"] == 0.2
        assert payload["probe_refresh_s"] is None
        assert payload["sampling_elapsed_s"] >= 0
    finally:
        release.set()
        caller.join(2)
        worker = getattr(collector, "_probe_thread", None)
        if worker:
            worker.join(2)


def test_completed_probe_duration_cache_and_stale(caplog):
    caplog.set_level(logging.INFO)
    clock = _FakeClock()

    def probe():
        clock.advance(0.125)
        return {"available": True, "devices": []}

    collector = _collector(clock, gpu_probe=probe, min_interval_seconds=0)
    _streak_start(collector)
    worker = getattr(collector, "_probe_thread", None)
    if worker:
        worker.join(2)
    _streak_start(collector)
    payload = _payloads(caplog)[-1]
    assert payload.get("probe_status") == "fresh"
    assert payload["probe_refresh_s"] == 0.125
    assert payload["probe_cache_age_s"] == 0
    assert payload["probe_inflight_s"] is None


def test_actual_tap_runtime_and_collector_emit_once(tmp_path, monkeypatch, caplog):
    helper = identity()
    if helper:
        monkeypatch.setattr(helper, "_SEEN", set())
    caplog.set_level(logging.INFO)
    clock = _FakeClock()
    collector = _collector(clock)
    runtime = runtime_module.FasterWhisperRuntime(device="cpu", live=True)
    runtime._model = SimpleNamespace(transcribe=lambda *a, **kw: ([segment()], None))
    tap_root = tmp_path / "tap"
    tap = _tap(
        tap_root, clock=clock, diagnostic=collector, runtime=runtime, max_backlog_segments=20
    )
    for index in range(3):
        _write_wav(tap_root / "education" / f"chunk-{index:06d}.wav")
    tap.run_once()
    tap.run_once()
    _streak_start(collector)
    if collector._probe_thread:
        collector._probe_thread.join(2)
    wait_receipts(helper)
    receipts = [
        json.loads(r.getMessage().split(" ", 4)[4])
        for r in caplog.records
        if r.getMessage().startswith("Caption diagnostic executable receipt ")
    ]
    assert {r["module"] for r in receipts} == {"tap", "runtime", "collector"}, (
        "running path emitted no executable receipts"
    )
    assert len(receipts) == 3
    assert len({r["process_nonce"] for r in receipts}) == 1
    assert all(r["executing"]["sha256"] and r["status"] == "ok" for r in receipts)
    assert all(
        r["executing"]["qualname"] in {a["qualname"] for a in r["selected"]} for r in receipts
    )
    assert "motion carries" not in json.dumps(receipts)
    if helper:
        for receipt in receipts:
            source = Path(receipt["origin"]).read_text(encoding="utf-8")
            compiled = compile(
                source, "other-install-root.py", "exec", optimize=receipt["optimize"]
            )
            anchors = helper.compiled_anchors(compiled)
            for anchor in [receipt["executing"], *receipt["selected"]]:
                assert helper.fingerprint_code(anchors[anchor["qualname"]]) == anchor["sha256"]


def test_fingerprint_normalizes_paths_but_not_semantics():
    helper = identity()
    assert helper is not None, "resident code fingerprint absent"
    source = "def f(x):\n    try:\n        return x + 7\n    except ValueError:\n        return 9\n"
    first = helper.compiled_anchors(compile(source, "a.py", "exec"))["f"]
    shifted = helper.compiled_anchors(compile("\n\n" + source, "b.py", "exec"))["f"]
    changed = helper.compiled_anchors(compile(source.replace("+ 7", "+ 8"), "a.py", "exec"))["f"]
    assert helper.fingerprint_code(first) == helper.fingerprint_code(shifted)
    assert helper.fingerprint_code(first) != helper.fingerprint_code(changed)
    assert helper.fingerprint_code(first) != helper.fingerprint_code(
        first.replace(co_exceptiontable=b"")
    )


def test_disk_edit_cannot_relabel_resident_code(tmp_path):
    helper = identity()
    assert helper is not None
    path = tmp_path / "code.py"
    path.write_text("def f(): return 1\n", encoding="utf-8")
    namespace = {}
    exec(compile(path.read_text(), str(path), "exec"), namespace)
    resident = namespace["f"].__code__
    path.write_text("def f(): return 2\n", encoding="utf-8")
    expected = helper.compiled_anchors(compile(path.read_text(), str(path), "exec"))["f"]
    assert helper.fingerprint_code(resident) != helper.fingerprint_code(expected)


def test_identity_logger_and_hash_faults_preserve_decode(monkeypatch):
    helper = identity()
    assert helper is not None
    monkeypatch.setattr(helper, "_SEEN", set())
    monkeypatch.setattr(
        helper, "fingerprint_code", lambda code: (_ for _ in ()).throw(RuntimeError("hash"))
    )
    monkeypatch.setattr(
        helper._LOG, "info", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("log"))
    )
    runtime = runtime_module.FasterWhisperRuntime(device="cpu", live=True)
    runtime._model = SimpleNamespace(transcribe=lambda *a, **k: ([segment()], None))
    assert [h.text for h in runtime.transcribe([chunk()])] == ["motion carries"]
    error = RuntimeError("original decode")
    runtime._model = SimpleNamespace(transcribe=lambda *a, **k: (_ for _ in ()).throw(error))
    with pytest.raises(RuntimeError) as caught:
        list(runtime.transcribe([chunk()]))
    assert caught.value is error


def test_receipt_latch_bounded_across_instances(monkeypatch, caplog):
    helper = identity()
    assert helper is not None
    monkeypatch.setattr(helper, "_SEEN", set())
    caplog.set_level(logging.INFO)

    def work(_):
        runtime = runtime_module.FasterWhisperRuntime(device="cpu", live=True)
        list(runtime.transcribe([]))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, range(32)))
    wait_receipts(helper)
    records = [
        r
        for r in caplog.records
        if r.getMessage().startswith("Caption diagnostic executable receipt ")
    ]
    assert len(records) == 1
    assert {"runtime"} == helper._SEEN


def test_thread_start_fault_latches_without_retry(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    collector = _collector(_FakeClock(), min_interval_seconds=0)
    calls = []

    def fail(self):
        calls.append(1)
        raise RuntimeError("start")

    monkeypatch.setattr(threading.Thread, "start", fail)
    for _ in range(8):
        _streak_start(collector)
    assert calls == [1]
    assert _payloads(caplog)[-1]["probe_status"] == "unavailable"


def test_thread_constructor_fault_latches_without_losing_event(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    collector = _collector(_FakeClock(), min_interval_seconds=0)
    calls = []

    def fail(**kwargs):
        calls.append(1)
        raise RuntimeError("constructor")

    monkeypatch.setattr(tsd, "threading", SimpleNamespace(Thread=fail))
    _streak_start(collector)
    _streak_start(collector)
    assert calls == [1]
    assert len(_payloads(caplog)) == 2
    assert all(p["probe_status"] == "unavailable" for p in _payloads(caplog))
    assert all(p["probe_inflight_s"] is None for p in _payloads(caplog))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_clock_cannot_escape_or_publish_false_fresh(value, caplog):
    caplog.set_level(logging.INFO)
    collector = tsd.ShedDiagnosticCollector(monotonic=lambda: value)
    _streak_start(collector)
    assert _payloads(caplog) == []
    assert collector._probe_thread is None


def test_refresh_failure_and_bounded_probe_result(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    collector = _collector(
        _FakeClock(),
        min_interval_seconds=0,
        gpu_probe=lambda: {
            "available": True,
            "speech": "private",
            "devices": [{"name": "a" * 10000, "util_pct": float("nan"), "speech": "private"}]
            * 1000,
        },
    )
    _streak_start(collector)
    collector._probe_thread.join(2)
    _streak_start(collector)
    payload = _payloads(caplog)[-1]
    assert len(payload["gpu"]["devices"]) == 8
    assert all(len(d["name"]) == 160 and d["util_pct"] is None for d in payload["gpu"]["devices"])
    assert "private" not in json.dumps(payload)
    clock = _FakeClock()
    failed = _collector(clock, min_interval_seconds=0)
    monkeypatch.setattr(
        failed, "_process_snapshot", lambda now: (_ for _ in ()).throw(RuntimeError("probe"))
    )
    _streak_start(failed)
    failed._probe_thread.join(2)
    assert failed._environment is None and failed._probe_status == "unavailable"


def test_fingerprint_budget_and_unknown_key(monkeypatch):
    helper = identity()
    monkeypatch.setattr(helper, "_SEEN", set())
    code = (lambda: None).__code__
    with pytest.raises(ValueError, match="budget"):
        helper.fingerprint_code(code.replace(co_consts=(b"x" * 300000,)))
    helper.note_executing("unbounded-custom-module", code, object())
    assert set() == helper._SEEN


def test_actual_frame_and_replaced_lookup_report_mismatch(monkeypatch, caplog):
    helper = identity()
    monkeypatch.setattr(helper, "_SEEN", set())
    caplog.set_level(logging.INFO)
    runtime = runtime_module.FasterWhisperRuntime(device="cpu", live=True)
    old_bound = runtime.transcribe
    monkeypatch.setattr(
        runtime,
        "transcribe",
        SimpleNamespace(__func__=SimpleNamespace(__code__=(lambda: "changed").__code__)),
    )
    list(old_bound([]))
    wait_receipts(helper)
    receipt = json.loads(
        next(
            r.getMessage().split(" ", 4)[4]
            for r in caplog.records
            if r.getMessage().startswith("Caption diagnostic executable receipt ")
        )
    )
    assert receipt["status"] == "mismatch"
    assert receipt["executing_matches_selected"] is False
