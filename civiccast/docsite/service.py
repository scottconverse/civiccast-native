# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Loads the pre-rendered in-product manual (never parses markdown/HTML at
runtime -- see civiccast/docsite/__init__.py for the full contract)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from civiccast.docsite.models import ManualDocument

_MANUAL_JSON_PATH = Path(__file__).resolve().parent / "manual.json"


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
