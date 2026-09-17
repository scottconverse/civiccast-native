# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Preserve generator return values in the pinned mutmut baseline wrapper.

mutmut 3.6.0 delegates yields but loses StopIteration.value, so its unmutated
baseline changes daemon reload success into failure. Fix instrumentation, not
product behavior or assertions. Refuse an unreviewed version/template change.
"""

from __future__ import annotations

from importlib.metadata import distribution
from pathlib import Path

_ORIGINAL = "yield from trampoline(*args, **kwargs)  # type: ignore"
_FIXED = "return (yield from trampoline(*args, **kwargs))  # type: ignore"


def patched_source(source: str, *, version: str) -> str:
    if version != "3.6.0":
        raise ValueError(f"Expected mutmut 3.6.0, got {version}; review the workaround")
    original_count, fixed_count = source.count(_ORIGINAL), source.count(_FIXED)
    if original_count == 0 and fixed_count == 1:
        return source
    if original_count != 1 or fixed_count != 0:
        raise ValueError("Unexpected mutmut generator template; refusing to patch")
    updated = source.replace(_ORIGINAL, _FIXED, 1)
    compile(updated, "mutmut/mutation/trampoline.py", "exec")
    return updated


def main() -> None:
    package = distribution("mutmut")
    target = Path(package.locate_file("mutmut/mutation/trampoline.py"))
    source = target.read_text(encoding="utf-8")
    updated = patched_source(source, version=package.version)
    if updated != source:
        target.write_text(updated, encoding="utf-8")
    print("mutmut 3.6.0 generator-return compatibility patch verified")


if __name__ == "__main__":
    main()
