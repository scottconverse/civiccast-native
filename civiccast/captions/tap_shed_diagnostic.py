# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Always-on, bounded-rate shed diagnostic for the live caption tap (U69).

Field need (beta.10, 2026-09-28/10-02). Reading U68's sections 2 and 9 together:

* the tap discarded spoken audio 13 times in 8 hours ("Caption tap catch-up ...
  Discarded the oldest N segments"), so a channel was inaudible to the review
  queue for the span it shed;
* 46 % of the 87 shed windows had NO preparation running at all, so the
  preparation/ASR contention story cannot by itself explain them;
* the transcribe call itself stalls -- a 5 s batch measured p90 3.7 s and max
  21 s, with queue depth 1 in the long ones, i.e. the stall is INSIDE the ASR
  call, not queueing in front of it;
* and both diagnostics that exist are opt-in and self-exhausting
  (:mod:`civiccast.captions.phase_timing` caps at 4000 events / 600 s;
  :mod:`civiccast.captions.tap_batch_diagnostic` at 2000 records / 900 s), so
  63 of those 87 sheds happened with no instrumentation attached at all.

This module answers "what was the box doing when this channel went over and when
it shed", and nothing else. It is deliberately ALWAYS ON -- an opt-in diagnostic
would reproduce the coverage gap that made this unit necessary -- and it pays
for that by being hard-bounded and cheap (see DESIGN CONSTRAINTS).

THE LOG LINE. One INFO record per event, message
``Caption tap shed diagnostic <json>``. Two events:

* ``over-limit-streak-start`` -- the FIRST scan on which a channel's settled
  backlog was over ``max_backlog_segments``. The persistence window has not
  run out yet at this point, so this line marks the beginning of a suspect
  episode, not a shed.
* ``catch-up-shed`` -- a U23 catch-up shed actually fired: the oldest settled
  audio was discarded and captioning resumed at the newest segments.

Fields, and how to read them::

    Caption tap shed diagnostic {"event": "catch-up-shed", "channel": "education",
      "pid": 8123,
      "queue_depth": 7,                # settled segments the gate SAW
      "oldest_queue_age_s": 31.4,      # age of the oldest settled segment then
      "max_backlog_segments": 2,       # the configured limit
      "overload_streak": 15,           # consecutive over-limit scans
      "persistence_scans": 15,         # the configured window
      "shed": {"count": 5, "kept": 2, "skipped_s": 25.0},
      "batches": [{"wait_s": 0.0, "feed_s": 0.012, "asr_s": 5.833,
                   "stabilize_s": 0.041}, ...],   # last 8 segment batches
      "batches_total": 412, "batches_retained": 8,
      "asr_in_call": true, "asr_call_s": 3.21,   # transcribe thread state NOW
      "suppressed_since_last": 0,
      "process": {"cpu_s_window": 12.9, "cpu_pct": 21.5, "wall_s": 30.0,
                  "threads": 47, "priority_class": "NORMAL_PRIORITY_CLASS"},
      "ffmpeg": {"count": 2, "procs": [{"name": "ffmpeg.exe", "pid": 991,
                  "priority_class": "BELOW_NORMAL_PRIORITY_CLASS"}]},
      "gpu": {"available": true, "devices": [{"name": "NVIDIA RTX 4070",
                  "util_pct": 88, "mem_used_mb": 4096, "mem_total_mb": 8192}]}}

Reading it: ``batches`` separates the four costs of one segment -- waiting for
the channel's session lock (``wait_s``), reading and overlap-joining the WAV
(``feed_s``), the ASR call itself (``asr_s``) and the two-window stabilization
(``stabilize_s``). A shed with a large ``asr_s`` and a low ``process.cpu_pct``
is a stalled/serialized ASR call; a shed with a high ``cpu_pct``, a thread count
in the hundreds and several ``ffmpeg`` processes at ``NORMAL`` priority is the
box being starved by preparation. ``asr_in_call``/``asr_call_s`` say whether the
channel's transcribe thread was inside the ASR call when this line was written,
and for how long -- a value that only grows across consecutive lines is a hung
call. ``process.priority_class`` is what the whole service process runs at
(``NORMAL`` is the shipped default for the tap's process; the playout workers
are spawned ``ABOVE_NORMAL`` and only the Python ASR *thread* is dropped to
``BELOW_NORMAL``, which the intra-op CTranslate2 pool does not inherit).

DESIGN CONSTRAINTS (all deliberate, mirroring
``civiccast.captions.tap_batch_diagnostic``):

* ALWAYS ON. ``shed_diagnostic_from_env`` returns the real collector unless
  ``CIVICAST_CAPTION_TAP_SHED_DIAGNOSTIC`` is explicitly falsy (``0``,
  ``false``, ``no``, ``off``). An operator who needs the old silence sets it.
* BOUNDED. At most one line per channel per event per
  ``min_interval_seconds`` (default 30 s -- the two events are one persistence
  window apart, so a normal episode still prints both); the last N batch
  records per channel only; at most 16 channels tracked. Nothing here grows
  without a bound, and a suppressed event is counted and named in the next
  line rather than silently lost.
* CHEAP AND SAFE. No audio is read, no I/O happens on the ASR or audio hot
  path, and the process/ffmpeg/GPU probes are coalesced behind a short cache
  so a station-wide emission never scans the process table more than once per
  couple of seconds. No new dependency: psutil and nvidia-ml-py are both
  already declared runtime dependencies, and each probe degrades to a clear
  ``unavailable`` value when its library is missing.
* FAILURE-PROOF. Every public method suppresses its own errors, and the tap
  additionally wraps every call, so a broken diagnostic is a missing log line
  -- never a broken caption tap.
* METADATA ONLY. Counts, durations, depths, ages, PIDs, process/device names
  and priority classes. No audio, no speech text, no cue text, no credentials.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from typing import Any, Final

__all__ = [
    "DEFAULT_MAX_BATCH_RECORDS",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "SHED_DIAGNOSTIC_ENV_VAR",
    "NullShedDiagnostic",
    "PhaseSampleForwarder",
    "ShedDiagnosticCollector",
    "shed_diagnostic_from_env",
]

_LOG = logging.getLogger(__name__)

#: The disable switch. Anything not in :data:`_FALSE_VALUES` -- including an
#: unset variable, the normal case -- leaves the diagnostic ON, because an
#: opt-in diagnostic is what left 63 of 87 measured sheds with no evidence.
SHED_DIAGNOSTIC_ENV_VAR: Final[str] = "CIVICAST_CAPTION_TAP_SHED_DIAGNOSTIC"

#: Minimum wall-clock spacing between two lines for the same channel AND event.
#: ``15`` persistence scans at the default 2 s poll is 30 s, so a streak start
#: and the shed it leads to are exactly this far apart and both print. The
#: bound is per (channel, event), so one channel can never write more than two
#: lines per window -- and normally writes exactly the two that matter.
DEFAULT_MIN_INTERVAL_SECONDS: Final[float] = 30.0

#: Hard bound on retained per-channel batch records, so one malformed episode
#: cannot inflate the payload.
DEFAULT_MAX_BATCH_RECORDS: Final[int] = 8

#: Hard bound on simultaneously tracked channels. A station has a handful; this
#: only stops a pathological tap-root from growing the dicts without bound.
_MAX_CHANNELS: Final[int] = 16

#: Hard bound on listed ffmpeg processes (the COUNT is still the true total).
_MAX_FFMPEG_PROCS: Final[int] = 8

#: Values that turn the diagnostic off. Everything else (including unset) is on.
_FALSE_VALUES: Final[frozenset[str]] = frozenset({"0", "false", "no", "off"})

#: The process/ffmpeg probe scan is the only expensive step; one refresh per
#: couple of seconds is plenty and keeps a 16-channel emission cheap.
_PROBE_CACHE_SECONDS: Final[float] = 2.0

#: The phase whose duration the tap cannot see from outside the pipeline.
STABILIZE_PHASE: Final[str] = "caption_stabilize"


def _round(value: object) -> float:
    try:
        return round(max(0.0, float(value)), 3)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _priority_class_name(psutil: Any, nice: object) -> str:
    """Name a Windows priority class from the value psutil reports as ``nice``."""

    names = {
        getattr(psutil, "IDLE_PRIORITY_CLASS", None): "IDLE_PRIORITY_CLASS",
        getattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS", None): "BELOW_NORMAL_PRIORITY_CLASS",
        getattr(psutil, "NORMAL_PRIORITY_CLASS", None): "NORMAL_PRIORITY_CLASS",
        getattr(psutil, "ABOVE_NORMAL_PRIORITY_CLASS", None): "ABOVE_NORMAL_PRIORITY_CLASS",
        getattr(psutil, "HIGH_PRIORITY_CLASS", None): "HIGH_PRIORITY_CLASS",
        getattr(psutil, "REALTIME_PRIORITY_CLASS", None): "REALTIME_PRIORITY_CLASS",
    }
    names.pop(None, None)
    try:
        return names.get(nice, f"unknown({nice})")
    except TypeError:  # unhashable value from an unusual platform
        return "unknown"


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


@dataclass
class ShedDiagnosticCollector:
    """Always-on, bounded shed/over-limit evidence for the live caption tap.

    One instance per tap worker, shared by every channel. The scan thread
    records gate decisions; the per-channel ASR threads record their batch
    durations and their ASR-call state, so the state is guarded by a lock --
    held only for dict/integer work, never across an ASR call or a probe, so it
    cannot serialize the path it measures.
    """

    min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS
    max_batch_records: int = DEFAULT_MAX_BATCH_RECORDS
    #: Injected clocks. ``None`` means "read the module attribute at
    #: construction", so a test can install a fake clock over
    #: ``civiccast.captions.tap_shed_diagnostic.time`` before building.
    monotonic: Callable[[], float] | None = None
    process_time: Callable[[], float] | None = None
    #: Injected probes (tests). ``None`` means "import lazily".
    psutil_module: Any | None = None
    gpu_probe: Callable[[], Mapping[str, object]] | None = None

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _batches: dict[str, deque[dict[str, object]]] = field(default_factory=dict, init=False)
    _batch_counts: dict[str, int] = field(default_factory=dict, init=False)
    _last_stabilize: dict[str, float] = field(default_factory=dict, init=False)
    _asr_started_at: dict[str, float] = field(default_factory=dict, init=False)
    _last_emitted: dict[tuple[str, str], float] = field(default_factory=dict, init=False)
    _suppressed: dict[tuple[str, str], int] = field(default_factory=dict, init=False)
    _cpu_baseline: float = field(default=0.0, init=False)
    _cpu_baseline_at: float = field(default=0.0, init=False)
    _environment: dict[str, object] | None = field(default=None, init=False)
    _environment_at: float = field(default=0.0, init=False)
    _psutil_resolved: bool = field(default=False, init=False)
    _psutil_handle: Any | None = field(default=None, init=False)
    _nvml_resolved: bool = field(default=False, init=False)
    _nvml_handle: Any | None = field(default=None, init=False)

    @property
    def enabled(self) -> bool:
        """True: the tap should spend anything at all on this diagnostic.

        The tap gates its queue-age measurement (which stats every queued
        segment) behind this, so an inert collector on the disable switch costs
        the scan path nothing. Mirrors ``BatchDiagnosticCollector.enabled``.
        """

        return True

    @property
    def samples_phases(self) -> bool:
        """True: the tap should route phase timing through a sampler for this."""

        return True

    def __post_init__(self) -> None:
        if self.monotonic is None:
            self.monotonic = time.monotonic
        if self.process_time is None:
            self.process_time = time.process_time
        self._cpu_baseline = self._cpu_now()
        self._cpu_baseline_at = self._now()

    # ------------------------------------------------------------------
    # Recording (called from the tap's scan and ASR threads).
    # ------------------------------------------------------------------
    def record_batch(
        self,
        *,
        channel: str,
        wait_seconds: float,
        feed_seconds: float,
        asr_seconds: float,
    ) -> None:
        """Keep one segment's four measured durations for the next emission."""

        with contextlib.suppress(Exception), self._lock:
            records = self._batches.get(channel)
            if records is None:
                if len(self._batches) >= _MAX_CHANNELS:
                    return
                records = deque(maxlen=max(1, int(self.max_batch_records)))
                self._batches[channel] = records
            stabilize = self._last_stabilize.pop(channel, None)
            records.append(
                {
                    "wait_s": _round(wait_seconds),
                    "feed_s": _round(feed_seconds),
                    "asr_s": _round(asr_seconds),
                    "stabilize_s": _round(stabilize) if stabilize is not None else None,
                }
            )
            self._batch_counts[channel] = self._batch_counts.get(channel, 0) + 1

    def note_stabilize(self, channel: str, seconds: float) -> None:
        """Record the stabilize phase's duration, reported by the forwarder."""

        with contextlib.suppress(Exception), self._lock:
            if channel not in self._last_stabilize and len(self._last_stabilize) >= _MAX_CHANNELS:
                return
            self._last_stabilize[channel] = float(seconds)

    def asr_started(self, *, channel: str) -> None:
        """Mark the instant this channel's transcribe thread entered the call."""

        with contextlib.suppress(Exception), self._lock:
            if channel not in self._asr_started_at and len(self._asr_started_at) >= _MAX_CHANNELS:
                return
            self._asr_started_at[channel] = self._now()

    def asr_finished(self, *, channel: str) -> None:
        """Mark the instant this channel's transcribe call returned or raised."""

        with contextlib.suppress(Exception), self._lock:
            self._asr_started_at.pop(channel, None)

    def note_streak_start(
        self,
        *,
        channel: str,
        queue_depth: int,
        oldest_queue_age_seconds: float,
        max_backlog_segments: int,
        overload_streak: int,
        persistence_scans: int,
    ) -> None:
        """Emit when a channel's over-limit streak BEGINS (first over-limit scan)."""

        with contextlib.suppress(Exception):
            self._emit(
                channel,
                "over-limit-streak-start",
                extra={
                    "queue_depth": int(queue_depth),
                    "oldest_queue_age_s": _round(oldest_queue_age_seconds),
                    "max_backlog_segments": int(max_backlog_segments),
                    "overload_streak": int(overload_streak),
                    "persistence_scans": int(persistence_scans),
                },
            )

    def note_shed(
        self,
        *,
        channel: str,
        queue_depth: int,
        oldest_queue_age_seconds: float,
        shed_count: int,
        kept: int,
        skipped_seconds: float,
        max_backlog_segments: int,
        overload_streak: int,
        persistence_scans: int,
    ) -> None:
        """Emit when a catch-up shed FIRES, after the audio is already gone."""

        with contextlib.suppress(Exception):
            self._emit(
                channel,
                "catch-up-shed",
                extra={
                    "queue_depth": int(queue_depth),
                    "oldest_queue_age_s": _round(oldest_queue_age_seconds),
                    "max_backlog_segments": int(max_backlog_segments),
                    "overload_streak": int(overload_streak),
                    "persistence_scans": int(persistence_scans),
                    "shed": {
                        "count": int(shed_count),
                        "kept": int(kept),
                        "skipped_s": _round(skipped_seconds),
                    },
                },
            )

    # ------------------------------------------------------------------
    # Emission.
    # ------------------------------------------------------------------
    def _emit(
        self,
        channel: str,
        event: str,
        *,
        extra: Mapping[str, object],
    ) -> None:
        suppressed = self._rate_limit_allows(channel, event)
        if suppressed is None:
            return
        now = self._now()
        with self._lock:
            records = list(self._batches.get(channel, ()))
            total = self._batch_counts.get(channel, 0)
            asr_started = self._asr_started_at.get(channel)
        payload: dict[str, object] = {
            "event": event,
            "channel": channel,
            "pid": os.getpid(),
            "batches": records,
            "batches_total": total,
            "batches_retained": len(records),
            "asr_in_call": asr_started is not None,
            "asr_call_s": _round(now - asr_started) if asr_started is not None else None,
            "suppressed_since_last": suppressed,
        }
        payload.update(extra)
        payload.update(self._environment_snapshot(now))
        # A broken logging handler must never propagate out of diagnostic code.
        with contextlib.suppress(Exception):
            _LOG.info("Caption tap shed diagnostic %s", json.dumps(payload))

    def _rate_limit_allows(self, channel: str, event: str) -> int | None:
        """Return the count of suppressed lines, or ``None`` to drop this one."""

        now = self._now()
        key = (channel, event)
        with self._lock:
            if len(self._last_emitted) >= _MAX_CHANNELS * 2 and key not in self._last_emitted:
                return None
            last = self._last_emitted.get(key)
            if last is not None and now - last < self.min_interval_seconds:
                self._suppressed[key] = self._suppressed.get(key, 0) + 1
                return None
            count = self._suppressed.pop(key, 0)
            self._last_emitted[key] = now
        return count

    def _environment_snapshot(self, now: float) -> dict[str, object]:
        """Process/ffmpeg/GPU state, coalesced behind a short cache.

        Every channel's line inside one scan would otherwise re-walk the process
        table and re-poll NVML; the cache makes that one refresh per couple of
        seconds for the whole station.
        """

        cached = self._environment
        if cached is not None and now - self._environment_at < _PROBE_CACHE_SECONDS:
            return cached
        snapshot: dict[str, object] = {
            "process": self._process_snapshot(now),
            "ffmpeg": self._ffmpeg_snapshot(),
            "gpu": self._gpu_snapshot(),
        }
        self._environment = snapshot
        self._environment_at = now
        return snapshot

    def _process_snapshot(self, now: float) -> dict[str, object]:
        cpu_now = self._cpu_now()
        wall = max(0.0, now - self._cpu_baseline_at)
        cpu_window = max(0.0, cpu_now - self._cpu_baseline)
        self._cpu_baseline = cpu_now
        self._cpu_baseline_at = now
        cpu_count = os.cpu_count() or 1
        cpu_pct = (cpu_window / wall * 100.0 / cpu_count) if wall > 0 else None
        threads, priority = self._process_state()
        return {
            "cpu_s_window": _round(cpu_window),
            "cpu_pct": _round(cpu_pct) if cpu_pct is not None else None,
            "wall_s": _round(wall),
            "threads": threads,
            "priority_class": priority,
        }

    def _process_state(self) -> tuple[int | None, str]:
        psutil = self._psutil()
        if psutil is None:
            return None, "unavailable"
        try:
            process = psutil.Process()
            return int(process.num_threads()), _priority_class_name(psutil, process.nice())
        except Exception:
            return None, "unavailable"

    def _ffmpeg_snapshot(self) -> dict[str, object]:
        """Every ffmpeg process on the box, not just this process's children.

        The station's conform/preparation ffmpegs are spawned by the egress and
        playout processes, so they are NOT children of the tap -- and they are
        exactly the load that competes with ASR, which is the question this
        field exists to answer.
        """

        psutil = self._psutil()
        if psutil is None:
            return {"unavailable": "psutil-not-installed"}
        try:
            total = 0
            processes: list[dict[str, object]] = []
            for process in psutil.process_iter(["name", "nice"]):
                try:
                    info = process.info
                    name = str(info.get("name") or "")
                    if not name.lower().startswith("ffmpeg"):
                        continue
                    total += 1
                    if len(processes) < _MAX_FFMPEG_PROCS:
                        processes.append(
                            {
                                "name": name,
                                "pid": int(process.pid),
                                "priority_class": _priority_class_name(psutil, info.get("nice")),
                            }
                        )
                except Exception:
                    # A process can vanish or deny access mid-census; skip it
                    # rather than lose the whole ffmpeg count.
                    _LOG.debug(
                        "Shed diagnostic: skipped one process in the ffmpeg census.", exc_info=True
                    )
                    continue
            return {"count": total, "procs": processes}
        except Exception:
            return {"unavailable": "psutil-error"}

    def _gpu_snapshot(self) -> dict[str, object]:
        if self.gpu_probe is not None:
            with contextlib.suppress(Exception):
                return dict(self.gpu_probe())
            return {"available": False, "reason": "gpu-probe-failed"}
        nvml = self._nvml()
        if nvml is None:
            return {"available": False, "reason": "pynvml-not-installed"}
        try:
            devices: list[dict[str, object]] = []
            for index in range(int(nvml.nvmlDeviceGetCount())):
                handle = nvml.nvmlDeviceGetHandleByIndex(index)
                utilization = nvml.nvmlDeviceGetUtilizationRates(handle)
                memory = nvml.nvmlDeviceGetMemoryInfo(handle)
                devices.append(
                    {
                        "name": _decode(nvml.nvmlDeviceGetName(handle)),
                        "util_pct": int(utilization.gpu),
                        "mem_used_mb": int(memory.used // (1024 * 1024)),
                        "mem_total_mb": int(memory.total // (1024 * 1024)),
                    }
                )
            return {"available": True, "devices": devices}
        except Exception as exc:
            # Initializing once and never shutting down: churning NVML init on a
            # CUDA station running ASR is the risk this avoids.
            return {"available": False, "reason": f"nvml-error:{type(exc).__name__}"}

    # ------------------------------------------------------------------
    # Lazy, guarded singletons.
    # ------------------------------------------------------------------
    def _now(self) -> float:
        clock = self.monotonic
        return clock() if clock is not None else time.monotonic()

    def _cpu_now(self) -> float:
        clock = self.process_time
        return clock() if clock is not None else time.process_time()

    def _psutil(self) -> Any | None:
        if self._psutil_resolved:
            return self._psutil_handle
        self._psutil_resolved = True
        if self.psutil_module is not None:
            self._psutil_handle = self.psutil_module
            return self._psutil_handle
        try:
            import psutil
        except Exception:
            self._psutil_handle = None
            return None
        self._psutil_handle = psutil
        return psutil

    def _nvml(self) -> Any | None:
        if self._nvml_resolved:
            return self._nvml_handle
        self._nvml_resolved = True
        try:
            import pynvml  # type: ignore[import-untyped]

            pynvml.nvmlInit()
        except Exception:
            self._nvml_handle = None
            return None
        self._nvml_handle = pynvml
        return pynvml


@dataclass
class NullShedDiagnostic:
    """Inert stand-in used only when the operator disables the diagnostic.

    Every method is a no-op and reads NO clock, so the disable switch costs the
    tap nothing and leaves production behaviour bit-for-bit unchanged.
    """

    samples_phases: bool = False
    enabled: bool = False

    def record_batch(self, **_: object) -> None:  # pragma: no cover - inert
        return None

    def note_stabilize(self, channel: str, seconds: float) -> None:  # pragma: no cover - inert
        return None

    def asr_started(self, **_: object) -> None:  # pragma: no cover - inert
        return None

    def asr_finished(self, **_: object) -> None:  # pragma: no cover - inert
        return None

    def note_streak_start(self, **_: object) -> None:  # pragma: no cover - inert
        return None

    def note_shed(self, **_: object) -> None:  # pragma: no cover - inert
        return None


class PhaseSampleForwarder:
    """Forward phase timing unchanged, and sample one phase's duration.

    The tap wires this into each per-channel :class:`LiveCaptionWorker` so the
    shed diagnostic can time ``caption_stabilize``, which happens inside the
    pipeline and is invisible from the tap. It is deliberately NOT installed as
    ``CaptionTapWorker._phase_timing``: that attribute must stay exactly the
    collector the operator configured (a test pins it to the inert one when
    ``CIVICAST_CAPTION_TAP_PHASE_TIMING`` is unset). Every call is forwarded to
    the real collector, so opting into phase timing still yields the same
    records; the only addition is the sampled duration.

    ``inner`` is duck-typed on purpose -- the same reason
    ``LiveCaptionWorker.phase_timing`` is typed ``object``: the collector is
    injected, and a test double must work here too.
    """

    def __init__(
        self,
        inner: Any,
        on_stabilize: Callable[[str, float], None],
        *,
        monotonic: Callable[[], float] | None = None,
        phase: str = STABILIZE_PHASE,
    ) -> None:
        self._inner = inner
        self._on_stabilize = on_stabilize
        self._monotonic = monotonic or time.monotonic
        self._phase_name = phase

    @contextmanager
    def phase(self, name: str, **kwargs: object) -> Iterator[None]:
        started = self._monotonic() if name == self._phase_name else None
        try:
            inner_cm: AbstractContextManager[Any] = self._inner.phase(name, **kwargs)
        except Exception:
            inner_cm = nullcontext()
        try:
            # The body's exceptions must propagate: this wraps the tap's ASR
            # call, and swallowing them here would change tap behaviour.
            with inner_cm:
                yield
        finally:
            if started is not None:
                with contextlib.suppress(Exception):
                    self._on_stabilize(
                        str(kwargs.get("channel") or ""),
                        self._monotonic() - started,
                    )

    def wait(self, phase: str, **kwargs: object) -> AbstractContextManager[Any]:
        try:
            # Annotated local: the collector seam is untyped, and the value is
            # passed straight through to the real collector's caller.
            manager: AbstractContextManager[Any] = self._inner.wait(phase, **kwargs)
        except Exception:
            return nullcontext()
        return manager

    def summarise(self, *, force: bool = False) -> dict[str, object]:
        try:
            result = self._inner.summarise(force=force)
        except Exception:
            return {}
        return result if isinstance(result, dict) else {}


def shed_diagnostic_from_env(
    *, monotonic: Callable[[], float] | None = None
) -> ShedDiagnosticCollector | NullShedDiagnostic:
    """Build the collector the environment asks for (default: the real one).

    Called once per tap worker at construction, matching how the tap reads its
    other settings. The tap passes its own clock so a fake-clock test drives
    the diagnostic's rate limit with the same hand it drives the backoff.
    """

    raw = os.environ.get(SHED_DIAGNOSTIC_ENV_VAR)
    if raw is not None and raw.strip().lower() in _FALSE_VALUES:
        return NullShedDiagnostic()
    return ShedDiagnosticCollector(monotonic=monotonic)
