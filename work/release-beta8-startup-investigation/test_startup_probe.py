# SPDX-License-Identifier: Apache-2.0
"""Diagnostic scheduling probes, not live-station acceptance or fixes."""

import concurrent.futures
import importlib.util
import threading
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "tap_probe_fixtures",
    Path(__file__).resolve().parents[2] / "tests/captions/test_caption_tap_worker.py",
)
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


@pytest.mark.parametrize("arrivals", [2, 3])
def test_first_retention_blocks_fresh_session_gate(tmp_path, arrivals):
    tap = tmp_path / "tap"
    tap.mkdir()
    policy = fixtures._SlowRetentionPolicy(delay_seconds=10)
    policy.release = threading.Event()
    runtime = fixtures._ScriptedRuntime()
    worker = fixtures.CaptionTapWorker(
        tap_root=tap,
        caption_work_dir=tmp_path / "egress",
        runtime=runtime,
        review_store=fixtures.InMemoryCaptionReviewStore(),
        retention_policy=policy,
        atomic_segments=True,
    )
    worker.begin_channel_session("public")
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(worker.run_once)
        try:
            assert policy.entered.wait(5)
            assert not result.done()
            for index in range(arrivals):
                fixtures._write_wav(tap / "public" / f"chunk-{index:06d}.wav", seconds=5)
        finally:
            policy.release.set()
        observed = result.result(timeout=10)
    assert observed.overloaded_channels == (("public",) if arrivals > 2 else ())
    assert observed.consumed_segments == (0 if arrivals > 2 else arrivals)
    assert len(runtime.seen_chunks) == (0 if arrivals > 2 else arrivals)


def test_model_preparation_can_accumulate_next_scan_overload(tmp_path):
    tap = tmp_path / "tap"
    tap.mkdir()
    entered, release = threading.Event(), threading.Event()

    class ColdRuntime(fixtures._ScriptedRuntime):
        def prepare(self):
            entered.set()
            assert release.wait(10)

    runtime = ColdRuntime()
    worker = fixtures.CaptionTapWorker(
        tap_root=tap,
        caption_work_dir=tmp_path / "egress",
        runtime=runtime,
        review_store=fixtures.InMemoryCaptionReviewStore(),
        atomic_segments=True,
    )
    worker.begin_channel_session("public")
    fixtures._write_wav(tap / "public/chunk-000000.wav", seconds=5)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(worker.run_once)
        try:
            assert entered.wait(5)
            for index in range(1, 4):
                fixtures._write_wav(tap / "public" / f"chunk-{index:06d}.wav", seconds=5)
        finally:
            release.set()
        assert result.result(timeout=10).consumed_segments == 1
    observed = worker.run_once()
    assert observed.overloaded_channels == ("public",)
    assert observed.consumed_segments == 0
    assert len(runtime.seen_chunks) == 1
