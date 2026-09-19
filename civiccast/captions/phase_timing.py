# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Opt-in, bounded PHASE TIMING for the live caption tap scan pass.

Field need (beta.9 N=3 ladder, 2026-09-18, three channels ON_AIR): the tap was
measured to stall -- per-segment latency max 106.01 s with 0.00 s samples that
were the gate DISCARDING settled audio -- while VRAM sat near half free and GPU
utilisation averaged 19%. The stall was real and reproducible, but its OWNER was
not measurable from outside the process: retention sweep, ASR (process_batch),
file move/unlink, or lock WAITING could each explain it, and the external
samplers cannot divide time inside a scan pass.

This module answers exactly one question -- WHERE does a scan's time go -- and
nothing else. It is deliberately SEPARATE from the earlier startup-diagnostics
slice: it shares no state with it, so either can be removed independently.

DESIGN CONSTRAINTS (all deliberate):
* DEFAULT OFF. ``civiccast.captions.phase_timing.phase_timing_from_env`` returns
  an inert collector unless ``CIVICCAST_CAPTION_TAP_PHASE_TIMING=1``. When off,
  NO clock is read and NO counter is kept, so production timing is unchanged.
* BOUNDED. A hard event cap and a wall-clock window measured from collector
  construction. Once either is exhausted the collector stops recording; the
  scan path is never made to fail or block because of timing.
* METADATA ONLY. Phases, durations, counts, channel/generation/index and the
  PID/thread that observed them. No audio, no speech text, no filesystem paths,
  no credentials, and no exception messages.
* FAILURE-PROOF. Every public method is written so that a broken handler or a
  bad value cannot change scan behaviour; recording is best effort.
* LOCK-WAIT IS SEPARATE FROM WORK. ``wait_session_lock`` and ``wait_retention_
  lock`` record time spent ACQUIRING a lock, distinct from the work done while
  holding it, because "the thread is blocked on a lock" and "the thread is busy
  transcribing" demand completely different fixes.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "DEFAULT_SUMMARY_INTERVAL_SECONDS",
    "PHASE_TIMING_ENV_VAR",
    "NullPhaseTimingCollector",
    "PhaseTimingCollector",
    "phase_timing_from_env",
]

_LOG = logging.getLogger(__name__)

#: Explicit opt-in switch. Absent or anything that is not "1"/"true"/"yes"/"on"
#: leaves the tap on the inert collector.
PHASE_TIMING_ENV_VAR: Final[str] = "CIVICCAST_CAPTION_TAP_PHASE_TIMING"

#: Hard bound on recorded events (begin/end pairs and waits both count).
_MAX_EVENTS: Final[int] = 4000
#: Hard bound on the recording window, measured from collector construction.
_MAX_SECONDS: Final[float] = 600.0
#: How often a running collector re-emits its cumulative summary.  A one-shot
#: summary was too coarse for the beta.9 stall investigation: a 30-minute run
#: produced a single data point, so a stall landing between emissions would be
#: invisible.  Emitting every 30 s keeps the samples dense enough to catch one
#: while staying bounded by the same event cap and window.
DEFAULT_SUMMARY_INTERVAL_SECONDS: Final[float] = 30.0

_TRUE_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "on"})


@dataclass
class _PhaseAggregate:
    count: int = 0
    total_ns: int = 0
    max_ns: int = 0


@dataclass
class PhaseTimingCollector:
    """Bounded per-phase timing with a cumulative summary.

    Not thread-safe by accident: the tap scan thread and the per-channel ASR
    pool threads can both record, so ``_record`` takes a lock. The lock is held
    only for arithmetic on integers, never across scan work, so it cannot
    serialise the scan pass it is measuring.
    """

    window_seconds: float = _MAX_SECONDS
    max_events: int = _MAX_EVENTS
    summary_interval_seconds: float = DEFAULT_SUMMARY_INTERVAL_SECONDS
    _start_ns: int = field(default=0, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _events: int = field(default=0, init=False)
    _aggregates: dict[str, _PhaseAggregate] = field(default_factory=dict, init=False)
    _summarised: bool = field(default=False, init=False)
    _last_summary_ns: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # Resolve the clock through the module attribute at CONSTRUCTION time
        # (not via a default_factory bound at class-definition time) so the
        # collector reads exactly the clock the rest of its methods read, and
        # so a test can install a fake clock before building it.
        self._start_ns = time.monotonic_ns()
        self._last_summary_ns = self._start_ns

    def _exhausted_locked(self) -> bool:
        return self._events >= self.max_events or (
            time.monotonic_ns() - self._start_ns >= int(self.window_seconds * 1_000_000_000)
        )

    def _record(self, phase: str, duration_ns: int) -> None:
        # Timing is best effort: a bad value or a broken lock must never change
        # scan behaviour.
        with contextlib.suppress(Exception):
            if duration_ns < 0:
                return
            with self._lock:
                if self._exhausted_locked():
                    return
                self._events += 1
                agg = self._aggregates.get(phase)
                if agg is None:
                    agg = _PhaseAggregate()
                    self._aggregates[phase] = agg
                agg.count += 1
                agg.total_ns += duration_ns
                if duration_ns > agg.max_ns:
                    agg.max_ns = duration_ns

    @contextmanager
    def phase(
        self,
        phase: str,
        *,
        channel: str | None = None,
        generation: int | None = None,
        index: int | None = None,
    ) -> Iterator[None]:
        """Time one unit of WORK (retention, backlog gate, ASR, file move...)."""

        started = time.monotonic_ns()
        try:
            yield
        finally:
            self._record(phase, time.monotonic_ns() - started)

    @contextmanager
    def wait(self, phase: str, *, channel: str | None = None) -> Iterator[None]:
        """Time WAITING to acquire a lock, kept distinct from held-lock work."""

        started = time.monotonic_ns()
        try:
            yield
        finally:
            self._record(phase, time.monotonic_ns() - started)

    def summarise(self, *, force: bool = False) -> dict[str, dict[str, float]]:
        """Return (and log) the per-phase cumulative summary.

        PERIODIC, not one-shot: at most one emission per
        ``summary_interval_seconds`` so a long run yields a dense-enough series
        to catch a stall, while the event cap and wall-clock window still bound
        the whole recording. ``force=True`` (used at shutdown) emits regardless
        of the interval.

        Durations are reported in milliseconds: count, total_ms, max_ms.
        """

        now_ns = time.monotonic_ns()
        with self._lock:
            if not force and now_ns - self._last_summary_ns < int(
                self.summary_interval_seconds * 1_000_000_000
            ):
                return {}
            if self._summarised and not self._aggregates:
                return {}
            self._last_summary_ns = now_ns
            snapshot = {
                name: {
                    "count": agg.count,
                    "total_ms": round(agg.total_ns / 1_000_000, 3),
                    "max_ms": round(agg.max_ns / 1_000_000, 3),
                }
                for name, agg in sorted(self._aggregates.items())
            }
            events = self._events
        # A broken logging handler must never propagate out of timing code.
        with contextlib.suppress(Exception):
            _LOG.info(
                "Caption tap phase timing summary %s",
                json.dumps(
                    {
                        "events": events,
                        "pid": os.getpid(),
                        "window_s": self.window_seconds,
                        "phases": snapshot,
                    }
                ),
            )
        return snapshot


@dataclass
class NullPhaseTimingCollector:
    """Inert collector used whenever the switch is off.

    Every method is a no-op and reads NO clock, so an operator who never opts in
    pays nothing and production timing is bit-for-bit unchanged.
    """

    def _record(self, phase: str, duration_ns: int) -> None:  # pragma: no cover - inert
        return None

    @contextmanager
    def phase(self, phase: str, **_: object) -> Iterator[None]:  # pragma: no cover
        yield

    @contextmanager
    def wait(self, phase: str, **_: object) -> Iterator[None]:  # pragma: no cover
        yield

    def summarise(self) -> dict[str, dict[str, float]]:
        return {}


def _env_truthy(raw: str) -> bool:
    return raw.strip().lower() in _TRUE_VALUES


def phase_timing_from_env() -> PhaseTimingCollector | NullPhaseTimingCollector:
    """Build the collector the environment asks for (default: inert).

    Called once per tap worker at construction, matching how the tap reads its
    other settings, so the switch is evaluated at the same point as the rest of
    the worker configuration.
    """

    raw = os.environ.get(PHASE_TIMING_ENV_VAR, "")
    if not _env_truthy(raw):
        return NullPhaseTimingCollector()
    return PhaseTimingCollector()
