# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""App-owned, nonblocking schema readiness with retained actual DB work."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from typing import Any

from civiccast.db.guarded_connect import track_bounded_work
from civiccast.schema_check import SchemaStatus, observe_schema_phases

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RefreshDiagnostic:
    attempt: int
    epoch: int
    phase: str
    scheduled: float
    started: float | None
    phase_started: float
    state: str = "unknown"
    retained_work: int = 0
    completed: float | None = None
    previous_phase: str = "queued"
    previous_elapsed_ms: float = 0.0


class HealthSchemaOwner:
    """One refresh/activation attempt per app; HTTP never waits for its work.

    A timed-out bounded read retains its slot until the actual Future finishes.
    No stale/old-source verdict can attest readiness. Close retains unfinished
    work references: an uncancellable driver is not a gracefully stopped worker.
    """

    def __init__(
        self,
        state: Any,
        *,
        sync_storage: Callable[[], None],
        source: Callable[[], str | None],
        ttl_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._state = state
        self._sync_storage = sync_storage
        self._source = source
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._work: list[Future[Any]] = []
        self._epoch = 0
        self._closed = False
        self._operations: dict[threading.Thread, int] = {}
        self._owned_threads: list[threading.Thread] = []
        self._cached_source = source()
        from civiccast import health_provenance

        self._diagnostics_enabled = health_provenance.ENABLED
        self._diagnostic: _RefreshDiagnostic | None = None
        self._attempt = 0
        state.schema_status = SchemaStatus(state="unknown")
        state.schema_status_checked_monotonic = None

    def diagnostic_snapshot(self) -> dict[str, str | int | float]:
        """Constant-size detached diagnostic; never a readiness attestation.

        Immutable publication does not wait for the owner's locks or DB work.
        Queued delay is known only after the existing worker starts. No source,
        credentials, revision, exception, frame, or work object is exported.
        """
        snapshot = self._diagnostic
        if snapshot is None:
            return {}
        now = self._clock()
        return {
            "schema": "health-schema-refresh-v1",
            "pid": os.getpid(),
            "attempt": snapshot.attempt,
            "epoch": snapshot.epoch,
            "phase": snapshot.phase,
            "state": snapshot.state,
            "elapsed_ms": max(
                0.0,
                (
                    (snapshot.completed if snapshot.completed is not None else now)
                    - snapshot.scheduled
                )
                * 1000,
            ),
            "phase_elapsed_ms": max(0.0, (now - snapshot.phase_started) * 1000),
            "queued_ms": max(
                0.0,
                ((snapshot.started if snapshot.started is not None else now) - snapshot.scheduled)
                * 1000,
            ),
            "retained_work": snapshot.retained_work,
            "previous_phase": snapshot.previous_phase,
            "previous_elapsed_ms": snapshot.previous_elapsed_ms,
        }

    def _diagnostic_phase(self, phase: str, *, state: str = "unknown") -> None:
        # Instrumentation must never control actual refresh work or publication.
        with suppress(Exception):
            self._update_diagnostic_phase(phase, state=state)

    def _update_diagnostic_phase(self, phase: str, *, state: str = "unknown") -> None:
        if phase not in {
            "started",
            "sync_storage",
            "head",
            "read",
            "graph",
            "complete",
            "retained_work",
            "closed",
        }:
            return
        snapshot = self._diagnostic
        if snapshot is None:
            return
        now = self._clock()
        self._diagnostic = replace(
            snapshot,
            phase=phase,
            phase_started=now,
            started=now if phase == "started" else snapshot.started,
            completed=now if phase in {"complete", "retained_work", "closed"} else None,
            previous_phase=snapshot.phase,
            previous_elapsed_ms=max(0.0, (now - snapshot.phase_started) * 1000),
            state=state
            if state in {"unknown", "current", "behind", "ahead", "not-configured"}
            else "unknown",
        )
        # Only the existing refresh worker emits; HTTP performs no logging IO.
        with suppress(Exception):
            from civiccast import health_provenance

            payload = json.dumps(self.diagnostic_snapshot(), allow_nan=False, separators=(",", ":"))
            if len(payload.encode("utf-8")) > 1024:
                return
            health_provenance._LOG.info("Health schema refresh phase %s", payload)
            if phase in {"complete", "retained_work", "closed"} and now - snapshot.scheduled >= 5:
                health_provenance._LOG.info("Health schema refresh slow completion %s", payload)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def _busy(self) -> bool:
        # The attempt must finish before reading its now-immutable work list.
        return (
            bool(self._operations)
            or bool(self._thread and self._thread.is_alive())
            or any(not future.done() for future in self._work)
        )

    def _invalidate(self) -> None:
        self._epoch += 1
        self._state.schema_status = SchemaStatus(state="unknown")
        self._state.schema_status_checked_monotonic = None

    def invalidate(self) -> None:
        """Invalidate without starting work (also safe during construction)."""
        with self._lock:
            self._invalidate()

    @contextmanager
    def operation(self) -> Iterator[bool]:
        """Account for arbitrary preparation without holding the snapshot lock."""
        thread = threading.current_thread()
        with self._lock:
            allowed = not self._closed
            if allowed:
                self._operations[thread] = self._operations.get(thread, 0) + 1
        try:
            yield allowed
        finally:
            if allowed:
                with self._lock:
                    count = self._operations[thread] - 1
                    if count:
                        self._operations[thread] = count
                    else:
                        del self._operations[thread]

    @contextmanager
    def admission(self) -> Iterator[bool]:
        """Short terminal fence for controlled thread creation, never callbacks."""
        with self._lock:
            yield (
                not self._closed
                and bool(self._state.lifespan_started)
                and bool(self._state.durable_storage_active)
            )

    def publish_storage(self, source: str) -> bool:
        """Commit only state assignments atomically with terminal close."""
        with self._lock:
            if self._closed:
                return False
            self._state.durable_storage_error = None
            self._state.durable_storage_url = source
            self._state.managed_storage_pending = False
            self._state.durable_storage_active = True
            return True

    def start_hook(self, thread: threading.Thread) -> bool:
        with self.admission() as allowed:
            if not allowed:
                return False
            self._owned_threads = [t for t in self._owned_threads if t.is_alive()]
            self._owned_threads.append(thread)
            thread.start()
            return True

    def _storage_ready(self, source: str | None) -> bool:
        return bool(self._state.durable_storage_active) and (
            getattr(self._state, "durable_storage_url", None) == source
        )

    def request(self, *, invalidate: bool = False) -> SchemaStatus:
        """Read a fresh snapshot or request one attempt and return unknown."""
        with self._lock:
            if self._closed:
                return SchemaStatus(state="unknown")
            current_source = self._source()
            if invalidate or current_source != self._cached_source:
                self._cached_source = current_source
                self._invalidate()
            last = self._state.schema_status_checked_monotonic
            status: SchemaStatus = self._state.schema_status
            if last is not None and self._clock() - last < self._ttl:
                if status.state == "current" and not self._storage_ready(current_source):
                    return SchemaStatus(state="unknown")
                return status
            if not self._busy():
                self._work = []
                if self._diagnostics_enabled:
                    self._diagnostic = None
                    with suppress(Exception):
                        self._attempt += 1
                        now = self._clock()
                        self._diagnostic = _RefreshDiagnostic(
                            self._attempt, self._epoch, "queued", now, None, now
                        )
                self._thread = threading.Thread(
                    target=self._run, name="civiccast-health-schema", daemon=True
                )
                try:
                    self._thread.start()
                except Exception:
                    self._thread = None
                    self._state.schema_status = SchemaStatus(state="unknown")
                    self._state.schema_status_checked_monotonic = self._clock()
                    _LOG.warning("Could not start schema readiness refresh.")
            return SchemaStatus(state="unknown")

    def _run(self) -> None:
        from civiccast.schema_check import check_schema_currency

        with self._lock:
            epoch = self._epoch
            source = self._source()
        with suppress(Exception):
            if self._diagnostic is not None:
                self._diagnostic = replace(self._diagnostic, epoch=epoch)
        self._diagnostic_phase("started")
        try:
            with (
                track_bounded_work(self._work),
                observe_schema_phases(
                    self._diagnostic_phase if self._diagnostics_enabled else None
                ),
            ):
                self._diagnostic_phase("sync_storage")
                self._sync_storage()
                with self._lock:
                    closed = self._closed
                    if not closed:
                        epoch = self._epoch
                        source = self._source()
                        self._cached_source = source
                if closed:
                    self._diagnostic_phase("closed")
                    return
                # Storage activation may legitimately invalidate the queued epoch.
                # Correlate subsequent phases with the actual check's fence.
                with suppress(Exception):
                    if self._diagnostic is not None:
                        self._diagnostic = replace(self._diagnostic, epoch=epoch)
                status = check_schema_currency(source)
                if status.state == "current" and not self._storage_ready(source):
                    status = SchemaStatus(state="unknown")
        except Exception:
            # No URL/driver exception is exported from the owner.
            _LOG.warning("Schema readiness refresh or storage activation failed.")
            status = SchemaStatus(state="unknown")
        with self._lock:
            published = False
            if not self._closed and epoch == self._epoch and source == self._source():
                self._state.schema_status = status
                self._state.schema_status_checked_monotonic = self._clock()
                published = True
        with suppress(Exception):
            if self._diagnostic is not None:
                retained = sum(not future.done() for future in self._work)
                self._diagnostic = replace(self._diagnostic, retained_work=retained)
                self._diagnostic_phase(
                    "retained_work" if retained else "complete",
                    state=status.state if published else "unknown",
                )

    def close(self, timeout: float = 1.0) -> bool:
        """Forbid late publication/new work, then finitely join the owner."""
        with self._lock:
            self._closed = True
            self._state.durable_storage_active = False
            self._invalidate()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
        with self._lock:
            stopped = not self._busy() and not any(t.is_alive() for t in self._owned_threads)
        if not stopped:
            _LOG.warning("Schema readiness work remains owned during shutdown.")
        return stopped
