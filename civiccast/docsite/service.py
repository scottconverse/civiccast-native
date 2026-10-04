# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Loads the pre-rendered in-product manual (never parses markdown/HTML at
runtime -- see civiccast/docsite/__init__.py for the full contract)."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from civiccast.docsite.models import ManualDocument
from civiccast.docsite.render import _MIME_BY_SUFFIX

_MANUAL_JSON_PATH = Path(__file__).resolve().parent / "manual.json"


def load_manual_asset(name: str) -> tuple[bytes, str]:
    """Read only content-addressed bundled images; never an arbitrary path."""
    if not re.fullmatch(r"[0-9a-f]{64}\.(?:png|jpg|jpeg|gif|svg|webp)", name):
        raise FileNotFoundError
    directory = _MANUAL_JSON_PATH.parent / "assets"
    if directory.resolve() != _MANUAL_JSON_PATH.parent.resolve() / "assets":
        raise FileNotFoundError
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise FileNotFoundError
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != name.split(".")[0]:
        raise FileNotFoundError
    return data, _MIME_BY_SUFFIX[path.suffix]


class ManualUnavailableError(RuntimeError):
    """The bundled manual cannot be loaded; safe to show to an operator."""


@lru_cache(maxsize=1)
def _load_manual_cached(mtime_ns: int) -> ManualDocument:
    """``mtime_ns`` is only a cache key: it makes ``load_manual()`` pick up a
    freshly-rendered file in a live dev server without needing a restart,
    while still avoiding a JSON parse + pydantic validation on every request.
    """

    raw = _MANUAL_JSON_PATH.read_text(encoding="utf-8")
    return ManualDocument.model_validate(json.loads(raw))


def load_manual() -> ManualDocument:
    """Return the current in-product manual document."""

    try:
        mtime_ns = _MANUAL_JSON_PATH.stat().st_mtime_ns
        return _load_manual_cached(mtime_ns)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise ManualUnavailableError(
            "The built-in manual is missing, damaged, or cannot be read. "
            "Ask your IT support person to repair the CivicCast installation."
        ) from exc
