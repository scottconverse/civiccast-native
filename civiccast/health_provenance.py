# SPDX-License-Identifier: Apache-2.0
"""Optional, selected loaded health code receipts; not whole-module attestation."""

from __future__ import annotations

import inspect
import json
import logging
import os
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from types import CodeType, FunctionType, MethodType
from typing import Any

ENABLED = os.environ.get("CIVICCAST_CAPTION_EXECUTABLE_PROOF", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
_LOG = logging.getLogger(__name__)
_LOCK = threading.Lock()
_CLAIMED = False
_THREAD: threading.Thread | None = None
_NONCE = "unavailable"
if ENABLED:
    with suppress(Exception):
        _NONCE = os.urandom(8).hex()
# Explicit selected behavior/support anchors, not imported whole-module hashes.
ANCHORS = {
    "civiccast.app": (
        "create_app.<locals>.health",
        "_app_lifespan",
        "_sync_health_storage",
        "_perform_durable_store_wiring",
        "_wire_live_caption_tap",
        "_maybe_start_finalization_worker",
        "_start_background_supervisors",
    ),
    "civiccast.auth.middleware": ("staff_auth_middleware",),
    "civiccast.health_schema": (
        "HealthSchemaOwner.request",
        "HealthSchemaOwner._run",
        "HealthSchemaOwner.publish_storage",
        "HealthSchemaOwner.close",
        "HealthSchemaOwner.diagnostic_snapshot",
        "HealthSchemaOwner._diagnostic_phase",
        "HealthSchemaOwner._update_diagnostic_phase",
    ),
    "civiccast.db.guarded_connect": ("run_bounded", "track_bounded_work"),
    "civiccast.schema_check": (
        "check_schema_currency",
        "read_db_revision",
        "observe_schema_phases",
        "_note_phase",
    ),
    "civiccast.platform.worker_runtime": ("ThreadSupervisor.start",),
    "civiccast.live.finalization_worker": ("FinalizationWorkerSupervisor.start",),
    "civiccast.egress.automation": ("ChannelAutomationService.prepare_storage",),
    "civiccast.reporting.asrun_outbox": (
        "AsRunOutbox.initialize",
        "AsRunOutbox._connection",
        "AsRunOutbox._open_connection",
        "AsRunOutbox.close",
    ),
    "civiccast.health_provenance": ("note_health", "_capture_codes", "_emit"),
    "civiccast.captions.diagnostic_identity": ("fingerprint_code",),
}
if ENABLED:
    # Import/nonce work happens at module startup, never in the health caller.
    from civiccast.captions.diagnostic_identity import fingerprint_code


@dataclass(frozen=True)
class _Snapshot:
    executing: CodeType
    selected: tuple[tuple[str, CodeType], ...]
    pid: int
    executable: str
    cache_tag: str
    version: tuple[int, int, int]
    optimize: int
    nonce: str
    capture_ok: bool


def _code(value: object, expected: str) -> CodeType:
    if type(value) is MethodType:
        value = value.__func__
    for _ in range(3):
        if type(value) is not FunctionType:
            raise ValueError("unsupported-selected-callable")
        if value.__code__.co_qualname == expected:
            return value.__code__
        value = value.__dict__.get("__wrapped__")
    raise ValueError("selected-qualname-mismatch")


def _capture_codes(app: Any) -> tuple[tuple[str, CodeType], ...]:
    # Bounded route/middleware metadata scans; no request, DB or disk state.
    routes = tuple(app.routes)
    middleware = tuple(app.user_middleware)
    if len(routes) > 512 or len(middleware) > 32:
        raise ValueError("metadata-budget")
    health = [r.endpoint for r in routes if getattr(r, "path", None) == "/health"]
    auth = [
        m.kwargs.get("dispatch")
        for m in middleware
        if type(m.kwargs.get("dispatch")) is FunctionType
        and m.kwargs["dispatch"].__qualname__ == "staff_auth_middleware"
    ]
    if len(health) != 1 or len(auth) != 1:
        raise ValueError("registered-callable-set")
    owner = app.state.health_schema_owner
    result = []
    for module_name, names in ANCHORS.items():
        namespace = vars(sys.modules[module_name])
        for name in names:
            if name == "create_app.<locals>.health":
                value = health[0]
            elif name == "staff_auth_middleware":
                value = auth[0]
            elif module_name == "civiccast.health_schema":
                value = inspect.getattr_static(owner, name.split(".")[1])
            else:
                parts = name.split(".")
                value = namespace[parts[0]]
                if len(parts) == 2:
                    value = inspect.getattr_static(value, parts[1])
            result.append((module_name, _code(value, name)))
    return tuple(result)


def _emit(snapshot: _Snapshot, done: threading.Event, timing: list[float | None]) -> None:
    with suppress(Exception):
        if not done.wait(2):
            return
        start = time.perf_counter()
        payload = {
            "schema": "health-selected-code-v1",
            "status": "unavailable",
            "pid": snapshot.pid,
            "python_executable": snapshot.executable,
            "python_cache_tag": snapshot.cache_tag,
            "python_version": list(snapshot.version),
            "optimize": snapshot.optimize,
            "process_nonce": snapshot.nonce,
            "caller_capture_dispatch_elapsed_s": timing[0],
            "timing_scope": "background-fingerprint",
        }
        with suppress(Exception):

            def descriptor(code: CodeType) -> dict[str, str]:
                return {
                    "qualname": code.co_qualname,
                    "filename": code.co_filename,
                    "sha256": fingerprint_code(code),
                }

            payload["executing"] = descriptor(snapshot.executing)
            payload["selected"] = [
                {"module": name, **descriptor(code)} for name, code in snapshot.selected
            ]
            payload["executing_matches_selected"] = any(
                code is snapshot.executing for _, code in snapshot.selected
            )
            if snapshot.capture_ok:
                payload["status"] = "ok" if payload["executing_matches_selected"] else "mismatch"
        payload["background_fingerprint_elapsed_s"] = time.perf_counter() - start
        encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= 16384:
            _LOG.info("Health diagnostic executable receipt %s", encoded)


def note_health(executing: CodeType, app: Any) -> None:
    """At most one process-owned worker; caller retains no frame or owner."""
    global _CLAIMED, _THREAD
    if not ENABLED:
        return
    with suppress(Exception):
        start = time.perf_counter()
        if not _LOCK.acquire(blocking=False):
            return
        try:
            if _CLAIMED:
                return
            _CLAIMED = True
        finally:
            _LOCK.release()
        selected: tuple[tuple[str, CodeType], ...] = ()
        captured = False
        with suppress(Exception):
            selected = _capture_codes(app)
            captured = True
        snapshot = _Snapshot(
            executing,
            selected,
            os.getpid(),
            sys.executable,
            sys.implementation.cache_tag,
            (sys.version_info.major, sys.version_info.minor, sys.version_info.micro),
            sys.flags.optimize,
            _NONCE,
            captured,
        )
        done = threading.Event()
        timing: list[float | None] = [None]
        try:
            worker = threading.Thread(
                target=_emit,
                args=(snapshot, done, timing),
                daemon=True,
                name="health-executable-proof",
            )
            _THREAD = worker
            worker.start()
        finally:
            timing[0] = time.perf_counter() - start
            done.set()
