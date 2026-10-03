# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Bounded, metadata-only shed diagnostics for the live caption tap.

Always on unless CIVICCAST_CAPTION_TAP_SHED_DIAGNOSTIC is false; the legacy
CIVICAST spelling remains a fallback. Up to eight batch samples and sixteen
channels are retained. Events are rate-limited per channel and event.

asr_s spans process_batch, not just decoding. transcribe_s measures the model
call and lazy next() operations, excluding downstream consumer pauses.
other_process_batch_s is the residual after decoding and stabilization; it
includes other process_batch work and does not identify persistence/publication
stalls. Optional invalid measurements are null, never guessed.

Ported selectively from U69/U71; no decoding or scheduling changes.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Final

from civiccast.captions.diagnostic_identity import note_executing

__all__ = [
    "DEFAULT_MAX_BATCH_RECORDS",
    "DEFAULT_MIN_INTERVAL_SECONDS",
    "LEGACY_SHED_DIAGNOSTIC_ENV_VAR",
    "SHED_DIAGNOSTIC_ENV_VAR",
    "NullShedDiagnostic",
    "PhaseSampleForwarder",
    "ShedDiagnosticCollector",
    "shed_diagnostic_from_env",
]

_LOG = logging.getLogger(__name__)

#: One-time-warning latch for the legacy/conflict messages the shared resolver
#: emits -- see ``civiccast.egress.env_vars.resolve_renamed_env``.
_RENAMED_ENV_WARNED: set[str] = set()

#: The disable switch. Anything not in :data:`_FALSE_VALUES` -- including an
#: unset variable, the normal case -- leaves the diagnostic ON, because an
#: opt-in diagnostic is what left 63 of 87 measured sheds with no evidence.
#:
#: BETA.10 U71: two C's, the spelling the station's service registry writes.
#: U69 shipped this reader with the one-C spelling as its only name, so an
#: operator setting it the station's way got a silently inert switch; the
#: one-C ``LEGACY_SHED_DIAGNOSTIC_ENV_VAR`` below is still read as a legacy
#: fallback -- see ``civiccast.egress.env_vars.resolve_renamed_env``.
SHED_DIAGNOSTIC_ENV_VAR: Final[str] = "CIVICCAST_CAPTION_TAP_SHED_DIAGNOSTIC"
LEGACY_SHED_DIAGNOSTIC_ENV_VAR: Final[str] = "CIVICAST_CAPTION_TAP_SHED_DIAGNOSTIC"

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
    return _optional_rounded(value) or 0.0


def _optional_rounded(value: object) -> float | None:
    """Finite non-negative scalar or null; diagnostic coercion never raises."""

    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
        return round(number, 3) if isfinite(number) and number >= 0 else None
    except Exception:
        return None


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
    _probe_thread: threading.Thread | None = field(default=None, init=False)
    _probe_started: float | None = field(default=None, init=False)
    _probe_elapsed: float | None = field(default=None, init=False)
    _probe_status: str = field(default="pending", init=False)
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
        with contextlib.suppress(Exception):
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
        transcribe_seconds: float | None = None,
        duration_after_vad_seconds: float | None = None,
        max_segment_temperature: float | None = None,
    ) -> None:
        """Keep one segment batch's measured costs for the next emission.

        ``wait_s``/``feed_s``/``asr_s``/``stabilize_s`` are unchanged. U71 adds
        the decode's own split, which the tap cannot see from outside the
        pipeline (the runtime times it -- see
        ``FasterWhisperRuntime.last_decode_metrics``):

        * ``transcribe_s`` -- time inside the model ``transcribe()`` and the
          consumption of its lazy segment generator, i.e. the ASR decode
          proper, as distinct from everything else ``asr_s`` covers;
        * ``other_process_batch_s`` -- DERIVED here as ``asr_s - transcribe_s -
          stabilize_s``: the share of ``asr_s`` that was neither decode nor
          stabilization. It includes other process_batch work; it cannot identify
          a persistence or publication stall. It
          stays ``None`` when either term is unknown, because a residual with a
          missing term is a wrong number, not a smaller one;
        * ``duration_after_vad`` -- the audio that survived the VAD, the honest
          denominator for comparing decode cost to retained audio; a long
          ``transcribe_s`` over little retained audio warrants investigation,
          but alone does not prove a stall;
        * ``max_segment_temperature`` -- the highest per-segment decode
          temperature; a positive value is a diagnostic signal, not alone
          proof that a fallback list was walked.

        A caller that has none of the new numbers (another runtime or a test
        fake) omits them and gets JSON ``null``: the record shape is stable and
        the field is never simply absent.
        """

        with contextlib.suppress(Exception), self._lock:
            records = self._batches.get(channel)
            if records is None:
                if len(self._batches) >= _MAX_CHANNELS:
                    return
                records = deque(
                    maxlen=min(DEFAULT_MAX_BATCH_RECORDS, max(1, int(self.max_batch_records)))
                )
                self._batches[channel] = records
            stabilize = self._last_stabilize.pop(channel, None)
            asr_valid = _optional_rounded(asr_seconds)
            asr_rounded = _round(asr_seconds)
            transcribe_rounded = _optional_rounded(transcribe_seconds)
            other_rounded: float | None = None
            stabilize = _optional_rounded(stabilize)
            if asr_valid is not None and transcribe_rounded is not None and stabilize is not None:
                other_rounded = _optional_rounded(asr_valid - transcribe_rounded - stabilize)
            records.append(
                {
                    "wait_s": _round(wait_seconds),
                    "feed_s": _round(feed_seconds),
                    "asr_s": asr_rounded,
                    "stabilize_s": _round(stabilize) if stabilize is not None else None,
                    "transcribe_s": transcribe_rounded,
                    "other_process_batch_s": other_rounded,
                    "duration_after_vad": _optional_rounded(duration_after_vad_seconds),
                    "max_segment_temperature": _optional_rounded(max_segment_temperature),
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
            _LOG.info("Caption tap shed diagnostic %s", json.dumps(payload, allow_nan=False))

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
        """Event-triggered single-flight refresh; caller never waits for probes.

        A stuck daemon keeps its slot forever: no cancellation or replacement.
        Cached results can be stale; explicit ages never imply a fresh sample.
        """
        started = time.perf_counter()
        dispatch = False
        with self._lock:
            age = _optional_rounded(now - self._environment_at) if self._environment else None
            fresh = age is not None and age < _PROBE_CACHE_SECONDS
            if not fresh and self._probe_started is None:
                self._probe_started = now
                self._probe_status = "pending"
                dispatch = True
        # Thread start (and every native call) must be outside the state lock.
        if dispatch:
            try:
                worker = threading.Thread(
                    target=self._refresh_environment, daemon=True, name="caption-diagnostic-probe"
                )
                with self._lock:
                    self._probe_thread = worker
                worker.start()
            except Exception:
                with self._lock:
                    self._probe_status = "unavailable"
                    # Retain the slot: no unbounded start/retry storm.
        with self._lock:
            age = _optional_rounded(now - self._environment_at) if self._environment else None
            result = dict(
                self._environment
                or {
                    "process": {"unavailable": "probe-pending"},
                    "ffmpeg": {"unavailable": "probe-pending"},
                    "gpu": {"available": False, "reason": "probe-pending"},
                }
            )
            result.update(
                {
                    "probe_status": (
                        "fresh" if age is not None and age < _PROBE_CACHE_SECONDS else "stale"
                    )
                    if self._environment
                    else self._probe_status,
                    "probe_refresh_s": self._probe_elapsed,
                    "probe_inflight_s": _optional_rounded(now - self._probe_started)
                    if self._probe_started is not None and self._probe_status == "pending"
                    else None,
                    "probe_cache_age_s": age,
                }
            )
        result["sampling_elapsed_s"] = _optional_rounded(time.perf_counter() - started)
        return result

    def _refresh_environment(self) -> None:
        with contextlib.suppress(Exception):
            note_executing("collector", sys._getframe().f_code, self)
        snapshot = None
        completed = None
        elapsed = None
        try:
            started = self._now()
            snapshot = {
                "process": self._process_snapshot(started),
                "ffmpeg": self._ffmpeg_snapshot(),
                "gpu": self._gpu_snapshot(),
            }
            completed = self._now()
            elapsed = _optional_rounded(completed - started)
        except Exception:
            snapshot = None
        finally:
            with self._lock:
                if snapshot is not None and completed is not None and elapsed is not None:
                    self._environment = snapshot
                    self._environment_at = completed
                self._probe_elapsed = elapsed
                self._probe_status = "unavailable" if elapsed is None else "fresh"
                self._probe_started = None

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
                                "name": name[:160],
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
                supplied = self.gpu_probe()
                result: dict[str, object] = {"available": supplied.get("available") is True}
                if "reason" in supplied:
                    result["reason"] = str(supplied["reason"])[:160]
                devices = supplied.get("devices")
                if isinstance(devices, (tuple, list)):
                    result["devices"] = [
                        {
                            "name": str(device.get("name", ""))[:160],
                            "util_pct": _optional_rounded(device.get("util_pct")),
                            "mem_used_mb": _optional_rounded(device.get("mem_used_mb")),
                            "mem_total_mb": _optional_rounded(device.get("mem_total_mb")),
                        }
                        for device in devices[:8]
                        if isinstance(device, Mapping)
                    ]
                return result
            return {"available": False, "reason": "gpu-probe-failed"}
        nvml = self._nvml()
        if nvml is None:
            return {"available": False, "reason": "pynvml-not-installed"}
        try:
            devices: list[dict[str, object]] = []
            for index in range(min(8, max(0, int(nvml.nvmlDeviceGetCount())))):
                handle = nvml.nvmlDeviceGetHandleByIndex(index)
                utilization = nvml.nvmlDeviceGetUtilizationRates(handle)
                memory = nvml.nvmlDeviceGetMemoryInfo(handle)
                devices.append(
                    {
                        "name": _decode(nvml.nvmlDeviceGetName(handle))[:160],
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
        value = float(clock() if clock is not None else time.monotonic())
        if not isfinite(value) or value < 0:
            raise ValueError("invalid-diagnostic-clock")
        return value

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

    Every collector hook is a no-op and reads no clock. Disabling skips record
    sampling, event probes and queue-age stats, but the tap/runtime timing
    calls remain; this is not a zero-overhead or bit-for-bit timing claim.
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
    ``CIVICCAST_CAPTION_TAP_PHASE_TIMING`` is unset). Every call is forwarded to
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
        started = None
        if name == self._phase_name:
            with contextlib.suppress(Exception):
                started = self._monotonic()
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

    BETA.10 U71: reads ``SHED_DIAGNOSTIC_ENV_VAR`` (two C's, the spelling the
    station's service registry writes), falling back to the legacy one-C
    ``LEGACY_SHED_DIAGNOSTIC_ENV_VAR`` that U69 shipped as the only name. The
    resolver is imported lazily here: importing ``civiccast.egress.env_vars``
    executes the whole ``civiccast.egress`` package, and this module is on that
    package's own import path.
    """

    from civiccast.egress.env_vars import resolve_renamed_env

    resolved = resolve_renamed_env(
        name=SHED_DIAGNOSTIC_ENV_VAR,
        legacy_name=LEGACY_SHED_DIAGNOSTIC_ENV_VAR,
        logger=_LOG,
        warned=_RENAMED_ENV_WARNED,
    )
    if resolved is None:
        return ShedDiagnosticCollector(monotonic=monotonic)
    _, raw = resolved
    if raw.lower() in _FALSE_VALUES:
        return NullShedDiagnostic()
    return ShedDiagnosticCollector(monotonic=monotonic)
