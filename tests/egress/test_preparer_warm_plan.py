# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""U60: ``SourcePreparer.warm_plan`` -- the off-air look-ahead warm.

The automation's dispatch tick hands the daemon the plan for a boundary whose
own dispatch is still a full rollover lead away (see
``tests/egress/test_automation_plan_warm_lookahead.py`` for the walk itself and
``_warm_upcoming_plan`` in ``civiccast/egress/automation.py``). The daemon
resolves the channel's STORE config and calls ``warm_plan``, which must put
whole-asset conforms for that plan's assets on the warm queue -- so that the
reload's synchronous, air-blocking ``prepare`` later finds a genuine cache HIT
instead of paying the cold conform inline.

Live C10, 2026-09-27: a 290s government item whose first-time conform took
383.6s. The plan ran to EOS with no reload in flight, the worker held the slate
~100s, and the next boundary inherited the delay.

What these tests pin, in order of how much they'd hurt to get wrong:

* The look-ahead does NOT conform anything on the calling thread -- the tick
  gets a queued job and returns. The station's dispatcher must never block.
* The artifact it produces is the SAME artifact the air path would have
  produced: same cache key, untrimmed, promoted through the real whole-asset
  gate. A look-ahead that populated the cache with something the air path
  would not have written would be worse than no look-ahead at all.
* It yields: lowered priority (``-threads 1``) and a duration-scaled budget.
* It can never make things worse -- a failure is one warning and a 6h backoff
  on that key, never an exception into the tick, and never a second concurrent
  encode of an asset the air path is already warming.

No station is touched; the ffmpeg runner is a counter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import civiccast.egress.preparer as preparer_module
from civiccast.egress.models import (
    EgressConfig,
    EgressSourcePlan,
    EgressSourceSegment,
)
from civiccast.egress.preparer import SourcePreparer
from civiccast.stream._ffmpeg import FfmpegResult
from tests.egress import test_preparer as preparer_tests

_ASSET_SECONDS = 3600.0


def _plan_for(*segments: EgressSourceSegment) -> EgressSourcePlan:
    return EgressSourcePlan(channel_id="gov", segments=list(segments))


def _config() -> EgressConfig:
    """The U25/gov fixture's config, unchanged -- one definition in this suite."""

    return preparer_tests._config()


def _asset(tmp_path: Path, name: str = "long-recording.mp4") -> Path:
    source = tmp_path / name
    if not source.exists():
        source.write_text("fake long media", encoding="utf-8")
    return source


def _segment(source: Path, *, label: str = "Council meeting", seconds: float = 290.0):
    return EgressSourceSegment(label=label, path=str(source), duration_seconds=seconds)


def _preparer(
    tmp_path: Path,
    *,
    calls: list[list[str]] | None = None,
    jobs: list | None = None,
    runner=None,
    scheduler=None,
) -> SourcePreparer:
    """The GStreamer wiring: ``playout_trim_supported`` left at its False default."""

    if runner is None:
        runner = preparer_tests._counting_runner([] if calls is None else calls)
    if scheduler is None:
        scheduler = ([] if jobs is None else jobs).append
    return SourcePreparer(
        work_dir=tmp_path / "work",
        ffmpeg_runner=runner,
        loudness_checker=lambda **_kwargs: preparer_tests._loudness(),
        warm_scheduler=scheduler,
    )


def _probe(monkeypatch: pytest.MonkeyPatch, seconds: float | None) -> None:
    """The warm job probes the asset on the warm worker, never on the tick."""

    monkeypatch.setattr(
        preparer_module, "probe_media_duration_seconds", lambda *_a, **_k: seconds
    )


def _cache_paths(preparer: SourcePreparer, source: Path, config: EgressConfig):
    key = preparer._cache_key(source, config)
    assert key is not None
    cache_dir = preparer._cache_dir()
    return key, cache_dir / f"{key}.ts", cache_dir / f"{key}.json"


@pytest.fixture(autouse=True)
def _placeholder_output_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same stub, same reason, as ``test_preparer.py``'s autouse fixture.

    Every ffmpeg runner in this suite is a placeholder-writer, so the preparer's
    U36 item-7 decodability check would reject each one it emits. This module
    deliberately leaves the REAL ``probe_media_duration_seconds`` question to
    individual tests (``_probe``), so only the emitted-file hook is stubbed.
    """

    monkeypatch.setattr(preparer_module, "_probe_prepared_segment_decodability", lambda _path: True)


# ---------------------------------------------------------------------------
# The tick gets a job, not a conform
# ---------------------------------------------------------------------------


def test_warm_plan_queues_the_work_and_does_not_conform_on_the_calling_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dispatcher's tick must return immediately -- it is on air-path time."""

    _probe(monkeypatch, _ASSET_SECONDS)
    calls: list[list[str]] = []
    jobs: list = []
    preparer = _preparer(tmp_path, calls=calls, jobs=jobs)
    source = _asset(tmp_path)

    preparer.warm_plan(_config(), _plan_for(_segment(source)))

    assert len(jobs) == 1
    assert calls == []  # nothing ran yet: the tick was not made to pay for it


def test_warm_plan_queues_one_job_per_segment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _probe(monkeypatch, _ASSET_SECONDS)
    jobs: list = []
    preparer = _preparer(tmp_path, jobs=jobs)
    first = _asset(tmp_path, "item-1.mp4")
    second = _asset(tmp_path, "item-2.mp4")

    preparer.warm_plan(
        _config(),
        _plan_for(
            _segment(first, label="Item 1"),
            _segment(second, label="Item 2"),
        ),
    )

    assert len(jobs) == 2


# ---------------------------------------------------------------------------
# The artifact is the air path's own
# ---------------------------------------------------------------------------


def test_the_warm_job_populates_the_airs_own_cache_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same key, untrimmed, promoted whole-asset -- and yielded on the way."""

    _probe(monkeypatch, _ASSET_SECONDS)
    calls: list[list[str]] = []
    jobs: list = []
    preparer = _preparer(tmp_path, calls=calls, jobs=jobs)
    source = _asset(tmp_path)
    config = _config()

    preparer.warm_plan(config, _plan_for(_segment(source)))
    jobs[0]()

    key, cache_ts, cache_meta = _cache_paths(preparer, source, config)
    assert cache_ts.is_file()
    assert cache_meta.is_file()

    meta = json.loads(cache_meta.read_text(encoding="utf-8"))
    assert meta["full_asset_conform"] is True
    assert meta["media_duration_seconds"] == _ASSET_SECONDS

    conform_args = calls[-1]
    assert "-ss" not in conform_args  # the cache unit is the FULL asset
    assert conform_args[conform_args.index("-t") : conform_args.index("-t") + 2] == [
        "-t",
        "3600",
    ]
    # ``lower_priority`` pins the whole-asset conform to a single thread so a
    # look-ahead can never starve the live encoder or the air path.
    assert conform_args[conform_args.index("-threads") : conform_args.index("-threads") + 2] == [
        "-threads",
        "1",
    ]
    # The scratch output is disposable; the cache entry is the point.
    assert "conform-cache" not in conform_args[-1]
    assert not list((tmp_path / "work" / "gov" / "warm").iterdir())
    assert key


def test_a_warmed_asset_makes_the_next_air_path_prepare_a_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: the reload's synchronous prepare sees a resident entry.

    Without the look-ahead this prepare is the 383.6s cold conform that put the
    slate on air. With it, the air path does one stream-copy and no re-encode.
    """

    _probe(monkeypatch, _ASSET_SECONDS)
    calls: list[list[str]] = []
    jobs: list = []
    preparer = _preparer(tmp_path, calls=calls, jobs=jobs)
    source = _asset(tmp_path)
    config = _config()

    preparer.warm_plan(config, _plan_for(_segment(source)))
    jobs[0]()
    calls.clear()
    jobs.clear()

    report = preparer.prepare(_plan_for(_segment(source)), config)

    assert len(calls) == 1  # one stream-copy, no re-encode
    copy_args = calls[0]
    assert copy_args[copy_args.index("-c") : copy_args.index("-c") + 2] == ["-c", "copy"]
    assert "-b:v" not in copy_args
    assert Path(report.source_plan.segments[0].path).is_file()
    assert jobs == []  # already warm; nothing re-queued


# ---------------------------------------------------------------------------
# It can never make things worse
# ---------------------------------------------------------------------------


def test_warm_plan_skips_a_source_that_is_not_a_file(tmp_path: Path) -> None:
    """A recording still being written, or one already gone: nothing to warm."""

    jobs: list = []
    preparer = _preparer(tmp_path, jobs=jobs)

    preparer.warm_plan(
        _config(), _plan_for(_segment(tmp_path / "not-there-yet.mp4"))
    )

    assert jobs == []


def test_warm_plan_job_is_a_no_op_when_the_entry_is_already_genuine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _probe(monkeypatch, _ASSET_SECONDS)
    calls: list[list[str]] = []
    jobs: list = []
    preparer = _preparer(tmp_path, calls=calls, jobs=jobs)
    source = _asset(tmp_path)
    config = _config()
    plan = _plan_for(_segment(source))

    preparer.warm_plan(config, plan)
    jobs[0]()
    calls.clear()

    preparer.warm_plan(config, plan)
    jobs[1]()

    assert calls == []  # the second job found the cache already resident


def test_warm_plan_dedupes_against_a_warm_the_air_path_already_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Registration happens on the TICK, before any job runs.

    A second whole-asset encode racing the air path's own is the one outcome
    worse than a cold cache, so the key is claimed synchronously.
    """

    _probe(monkeypatch, _ASSET_SECONDS)
    jobs: list = []
    preparer = _preparer(tmp_path, jobs=jobs)
    source = _asset(tmp_path)
    config = _config()

    # The air path meets the asset first (a trimmed miss schedules a warm).
    preparer.prepare(_plan_for(_segment(source, seconds=120.0)), config)
    assert len(jobs) == 1

    preparer.warm_plan(config, _plan_for(_segment(source)))

    assert len(jobs) == 1  # the look-ahead declined; one warm in flight already


def test_warm_plan_skips_an_asset_whose_duration_cannot_be_probed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a duration the synthetic segment cannot claim to be whole-asset.

    Warming it anyway would mean guessing -- and a guess that fails the
    whole-asset gate would put a conform's worth of load on the warm worker for
    an entry that never gets promoted. Skip instead, and do not punish the key:
    an unprobeable asset is not a failed warm.
    """

    _probe(monkeypatch, None)
    calls: list[list[str]] = []
    jobs: list = []
    preparer = _preparer(tmp_path, calls=calls, jobs=jobs)
    source = _asset(tmp_path)
    config = _config()

    preparer.warm_plan(config, _plan_for(_segment(source)))
    jobs[0]()

    assert calls == []
    _key, cache_ts, _meta = _cache_paths(preparer, source, config)
    assert not cache_ts.exists()
    assert preparer._warm_backoff_until == {}


def test_a_failed_warm_is_one_backoff_window_not_a_retry_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _probe(monkeypatch, _ASSET_SECONDS)
    jobs: list = []
    config = _config()
    source = _asset(tmp_path)

    def failing_runner(args: list[str]) -> FfmpegResult:
        return FfmpegResult(returncode=1, stdout="", stderr="boom")

    preparer = _preparer(tmp_path, runner=failing_runner, jobs=jobs)
    key = preparer._cache_key(source, config)
    assert key is not None

    preparer.warm_plan(config, _plan_for(_segment(source)))
    jobs[0]()  # must not raise -- the failure is handled inside the job

    assert key in preparer._warm_backoff_until
    assert key not in preparer._warming

    preparer.warm_plan(config, _plan_for(_segment(source)))
    assert len(jobs) == 1  # inside the 6h window: no second attempt


def test_warm_plan_never_raises_when_the_queue_itself_is_down(tmp_path: Path) -> None:
    """The tick is on air-path time; a look-ahead fault must die inside it."""

    def failing_scheduler(_job) -> None:
        raise RuntimeError("scheduler is down")

    preparer = _preparer(tmp_path, scheduler=failing_scheduler)
    source = _asset(tmp_path)
    config = _config()
    key = preparer._cache_key(source, config)
    assert key is not None

    preparer.warm_plan(config, _plan_for(_segment(source)))  # must not raise

    assert key not in preparer._warming  # not left stuck for the life of the instance
