# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Bounded selected-code receipts, not whole-module or native-code attestation.

The executing frame and looked-up anchors are distinguished. The same-Python
offline compile oracle ignores paths/line positions, but retains code semantics.
Only hashes and fixed metadata are logged, never constants, audio or transcript.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
from contextlib import suppress
from types import CodeType

_LOG = logging.getLogger(__name__)
_LOCK = threading.Lock()
_SEEN: set[str] = set()
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


def note_executing(module: str, code: CodeType, owner: object) -> None:
    """One fail-open receipt per fixed module key; caller supplies its frame code."""
    with suppress(Exception):
        if module not in _ANCHORS:
            return
        with _LOCK:
            if module in _SEEN:
                return
            _SEEN.add(module)
        started = time.perf_counter()
        payload: dict[str, object] = {
            "schema": "selected-code-v1",
            "module": module,
            "pid": os.getpid(),
            "process_nonce": _NONCE,
            "python_cache_tag": sys.implementation.cache_tag,
            "python_version": list(sys.version_info[:3]),
            "optimize": sys.flags.optimize,
            "status": "unavailable",
            "origin": code.co_filename[:512],
        }

        def descriptor(anchor: CodeType) -> dict[str, str]:
            return {
                "qualname": anchor.co_qualname[:160],
                "filename": anchor.co_filename[:512],
                "sha256": fingerprint_code(anchor),
            }

        with suppress(Exception):
            payload["executing"] = descriptor(code)
            payload["selected"] = [
                descriptor(getattr(owner, name).__func__.__code__) for name in _ANCHORS[module]
            ]
            matches = any(
                anchor["sha256"] == payload["executing"]["sha256"]
                and anchor["qualname"] == payload["executing"]["qualname"]
                for anchor in payload["selected"]
            )
            payload["executing_matches_selected"] = matches
            payload["status"] = "ok" if matches else "mismatch"
        elapsed = time.perf_counter() - started
        payload["elapsed_s"] = elapsed if 0 <= elapsed < float("inf") else None
        _LOG.info("Caption diagnostic executable receipt %s", json.dumps(payload, allow_nan=False))
