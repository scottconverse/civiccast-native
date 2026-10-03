# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""App-owned, nonblocking schema readiness with retained actual DB work."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from contextlib import contextmanager
from typing import Any

from civiccast.db.guarded_connect import track_bounded_work
from civiccast.schema_check import SchemaStatus

_LOG = logging.getLogger(__name__)


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
        state.schema_status = SchemaStatus(state="unknown")
        state.schema_status_checked_monotonic = None

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
        try:
            with track_bounded_work(self._work):
                self._sync_storage()
                with self._lock:
                    if self._closed:
                        return
                    epoch = self._epoch
                    source = self._source()
                    self._cached_source = source
                status = check_schema_currency(source)
                if status.state == "current" and not self._storage_ready(source):
                    status = SchemaStatus(state="unknown")
        except Exception:
            # No URL/driver exception is exported from the owner.
            _LOG.warning("Schema readiness refresh or storage activation failed.")
            status = SchemaStatus(state="unknown")
        with self._lock:
            if not self._closed and epoch == self._epoch and source == self._source():
                self._state.schema_status = status
                self._state.schema_status_checked_monotonic = self._clock()

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
