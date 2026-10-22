# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Preserve generator return values and trim trampoline-hit overhead in mutmut.

mutmut 3.6.0 delegates yields but loses StopIteration.value, so its unmutated
baseline changes daemon reload success into failure. Additionally, 3.6.0's
``record_trampoline_hit`` eagerly resolves every source path on every hit even
when stack-depth tracking is disabled (``max_stack_depth == -1``), adding
filesystem I/O to the hot path. Fix instrumentation, not product behavior or
assertions; refuse any unreviewed version/template change.
"""

from __future__ import annotations

from collections.abc import Callable
from importlib.metadata import distribution
from pathlib import Path

_PINNED_VERSION = "3.6.0"

_GENERATOR_ORIGINAL = "yield from trampoline(*args, **kwargs)  # type: ignore"
_GENERATOR_FIXED = "return (yield from trampoline(*args, **kwargs))  # type: ignore"

_HIT_ORIGINAL = (
    "    source_paths = [p.resolve(strict=True) for p in Config.get().source_paths]\n"
    "\n"
    "    if Config.get().max_stack_depth != -1:\n"
    "        f = inspect.currentframe()\n"
)
_HIT_FIXED = (
    "    if Config.get().max_stack_depth != -1:\n"
    "        source_paths = [p.resolve(strict=True) for p in Config.get().source_paths]\n"
    "        f = inspect.currentframe()\n"
)


def _require_pinned(version: str) -> None:
    if version != _PINNED_VERSION:
        raise ValueError(f"Expected mutmut {_PINNED_VERSION}, got {version}; review the workaround")


def patched_source(source: str, *, version: str) -> str:
    _require_pinned(version)
    original_count, fixed_count = source.count(_GENERATOR_ORIGINAL), source.count(_GENERATOR_FIXED)
    if original_count == 0 and fixed_count == 1:
        return source
    if original_count != 1 or fixed_count != 0:
        raise ValueError("Unexpected mutmut generator template; refusing to patch")
    updated = source.replace(_GENERATOR_ORIGINAL, _GENERATOR_FIXED, 1)
    compile(updated, "mutmut/mutation/trampoline.py", "exec")
    return updated


def patched_record_trampoline_hit(source: str, *, version: str) -> str:
    _require_pinned(version)
    original_count, fixed_count = source.count(_HIT_ORIGINAL), source.count(_HIT_FIXED)
    if original_count == 0 and fixed_count == 1:
        return source
    if original_count != 1 or fixed_count != 0:
        raise ValueError("Unexpected mutmut record_trampoline_hit template; refusing to patch")
    updated = source.replace(_HIT_ORIGINAL, _HIT_FIXED, 1)
    compile(updated, "mutmut/__main__.py", "exec")
    return updated


def _apply(
    target: Path,
    patcher: Callable[..., str],
    *,
    version: str,
) -> None:
    source = target.read_text(encoding="utf-8")
    updated = patcher(source, version=version)
    if updated != source:
        target.write_text(updated, encoding="utf-8")


def main() -> None:
    package = distribution("mutmut")
    _apply(
        Path(package.locate_file("mutmut/mutation/trampoline.py")),
        patched_source,
        version=package.version,
    )
    print("mutmut 3.6.0 generator-return compatibility patch verified")
    _apply(
        Path(package.locate_file("mutmut/__main__.py")),
        patched_record_trampoline_hit,
        version=package.version,
    )
    print("mutmut 3.6.0 trampoline-hit path-resolution patch verified")


if __name__ == "__main__":
    main()
