# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Bounded selected-code receipts, not whole-module or native-code attestation.

The executing frame and looked-up anchors are distinguished. The same-Python
offline compile oracle ignores paths/line positions, but retains code semantics.
Only hashes and fixed metadata are logged, never constants, audio or transcript.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from math import isfinite
from time import perf_counter as _caller_clock
from types import CodeType, FunctionType, MethodType

_LOG = logging.getLogger(__name__)
_LOCK = threading.Lock()
_SEEN: set[str] = set()
_THREADS: dict[str, threading.Thread] = {}
_FAILED: set[str] = set()
PROOF_ENV = "CIVICCAST_CAPTION_EXECUTABLE_PROOF"
_PROOF_ENABLED = os.environ.get(PROOF_ENV, "").strip().lower() in {"1", "true", "yes", "on"}
_NONCE = "unavailable"
with suppress(Exception):
    _NONCE = os.urandom(8).hex()
_ANCHORS = {
    "tap": ("_process_channel", "_worker_for"),
    "runtime": ("transcribe", "_transcribe_source", "_measured_segments"),
    "collector": ("_environment_snapshot", "_refresh_environment", "_emit"),
}
_MAX_BYTES = 262144


def fingerprint_code(code: CodeType) -> str:
    """Version1 canonical selected code; bounded, same interpreter/optimize only."""
    digest = hashlib.sha256(b"civiccast-selected-code-v1\0")
    remaining = [_MAX_BYTES, 4096]

    def add(value: object, depth: int = 0) -> None:
        remaining[1] -= 1
        if depth > 32 or remaining[1] < 0:
            raise ValueError("code-budget")
        if isinstance(value, CodeType):
            fields = (
                value.co_code,
                value.co_exceptiontable,
                value.co_consts,
                value.co_names,
                value.co_varnames,
                value.co_freevars,
                value.co_cellvars,
                value.co_argcount,
                value.co_posonlyargcount,
                value.co_kwonlyargcount,
                value.co_nlocals,
                value.co_stacksize,
                value.co_flags,
                value.co_name,
                value.co_qualname,
            )
            add(("code", fields), depth + 1)
            return
        if isinstance(value, (tuple, frozenset)):
            if len(value) > 4096 or (isinstance(value, frozenset) and len(value) > 256):
                raise ValueError("code-budget")
            token = b"tuple" if isinstance(value, tuple) else b"frozenset"
            values = value if isinstance(value, tuple) else sorted(value, key=_constant_sort_key)
            data = token + str(len(value)).encode() + b":"
        elif value is None or value is Ellipsis:
            data = b"none" if value is None else b"ellipsis"
        elif type(value) in (bool, int, float, complex, str, bytes):
            if type(value) is str:
                if len(value) > _MAX_BYTES:
                    raise ValueError("code-budget")
                raw = value.encode("utf-8", "surrogatepass")
            elif type(value) is bytes:
                if len(value) > _MAX_BYTES:
                    raise ValueError("code-budget")
                raw = value
            elif type(value) is float:
                raw = value.hex().encode()
            elif type(value) is complex:
                raw = (value.real.hex() + "," + value.imag.hex()).encode()
            else:
                raw = str(value).encode()
            data = type(value).__name__.encode() + str(len(raw)).encode() + b":" + raw
        else:
            raise ValueError("unsupported-constant")
        remaining[0] -= len(data)
        if remaining[0] < 0:
            raise ValueError("code-budget")
        digest.update(data)
        if isinstance(value, (tuple, frozenset)):
            for item in values:
                add(item, depth + 1)

    add(code)
    return digest.hexdigest()


def _constant_sort_key(value: object) -> str:
    # Compiler frozensets contain immutable scalar constants, not arbitrary objects.
    if type(value) not in (bool, int, float, complex, str, bytes, type(None)):
        raise ValueError("unsupported-frozenset")
    if isinstance(value, (str, bytes)) and len(value) > 1024:
        raise ValueError("code-budget")
    return type(value).__name__ + ":" + repr(value)


def compiled_anchors(code: CodeType) -> dict[str, CodeType]:
    """Offline oracle: discover code without executing candidate source/imports."""
    result: dict[str, CodeType] = {}
    pending = [code]
    visited = 0
    while pending:
        item = pending.pop()
        visited += 1
        if visited > 4096:
            raise ValueError("code-budget")
        result[item.co_qualname] = item
        for child in item.co_consts:
            if isinstance(child, CodeType):
                if visited + len(pending) >= 4096:
                    raise ValueError("code-budget")
                pending.append(child)
    return result


def _selected_code(owner: object, name: str) -> CodeType:
    """Capture plain callable code without executing arbitrary owner descriptors."""
    selected = inspect.getattr_static(owner, name)
    if type(selected) is MethodType:
        return selected.__func__.__code__
    if type(selected) is FunctionType:
        return selected.__code__
    function = inspect.getattr_static(selected, "__func__")
    code = inspect.getattr_static(function, "__code__")
    if not isinstance(code, CodeType):
        raise ValueError("unsupported-anchor")
    return code


@dataclass(frozen=True)
class _Captured:
    module: str
    executing: CodeType
    selected: tuple[CodeType, ...]
    capture_ok: bool
    pid: int
    nonce: str
    cache_tag: str
    version: tuple[int, int, int]
    optimize: int


def _finite_elapsed(start: float | None, end: float | None) -> float | None:
    with suppress(Exception):
        value = end - start
        if isfinite(value) and value >= 0:
            return value
    return None


def _caller_now() -> float | None:
    with suppress(Exception):
        value = _caller_clock()
        if isfinite(value) and value >= 0:
            return value
    return None


def _emit_captured(snapshot: _Captured, done: threading.Event, timing: list[float | None]) -> None:
    """Worker-only callback work; immutable codes/scalars, never owner or frame."""
    with suppress(Exception):
        if not done.wait(2):
            return
        started = time.perf_counter()
        payload: dict[str, object] = {
            "schema": "selected-code-v1",
            "module": snapshot.module,
            "pid": snapshot.pid,
            "process_nonce": snapshot.nonce,
            "python_cache_tag": snapshot.cache_tag,
            "python_version": list(snapshot.version),
            "optimize": snapshot.optimize,
            "status": "unavailable",
            "origin": snapshot.executing.co_filename[:512],
            "caller_capture_dispatch_elapsed_s": timing[0],
            "timing_scope": "background-fingerprint",
        }

        def descriptor(anchor: CodeType) -> dict[str, str]:
            return {
                "qualname": anchor.co_qualname[:160],
                "filename": anchor.co_filename[:512],
                "sha256": fingerprint_code(anchor),
            }

        with suppress(Exception):
            payload["executing"] = descriptor(snapshot.executing)
            payload["selected"] = [descriptor(anchor) for anchor in snapshot.selected]
            matches = any(
                anchor["sha256"] == payload["executing"]["sha256"]
                and anchor["qualname"] == payload["executing"]["qualname"]
                for anchor in payload["selected"]
            )
            payload["executing_matches_selected"] = matches
            if snapshot.capture_ok:
                payload["status"] = "ok" if matches else "mismatch"
        payload["background_fingerprint_elapsed_s"] = _finite_elapsed(started, time.perf_counter())
        _LOG.info("Caption diagnostic executable receipt %s", json.dumps(payload, allow_nan=False))


def note_executing(module: str, code: CodeType, owner: object) -> None:
    """Proof-only, at most three one-shot workers; caller never joins callbacks."""
    with suppress(Exception):
        if module not in _ANCHORS or not _PROOF_ENABLED:
            return
        started = _caller_now()
        if not _LOCK.acquire(blocking=False):
            return
        try:
            if module in _SEEN:
                return
            _SEEN.add(module)
        finally:
            _LOCK.release()
        selected: tuple[CodeType, ...] = ()
        capture_ok = False
        with suppress(Exception):
            selected = tuple(_selected_code(owner, name) for name in _ANCHORS[module])
            capture_ok = True
        snapshot = _Captured(
            module,
            code,
            selected,
            capture_ok,
            os.getpid(),
            _NONCE,
            sys.implementation.cache_tag,
            tuple(sys.version_info[:3]),
            sys.flags.optimize,
        )
        done = threading.Event()
        timing: list[float | None] = [None]
        try:
            worker = threading.Thread(
                target=_emit_captured,
                args=(snapshot, done, timing),
                name="caption-proof-" + module,
                daemon=True,
            )
            _THREADS[module] = worker
            worker.start()
        except Exception:
            _FAILED.add(module)
        finally:
            timing[0] = _finite_elapsed(started, _caller_now())
            done.set()
