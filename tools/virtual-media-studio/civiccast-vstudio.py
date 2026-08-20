#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the CivicCast Virtual Media Studio CLI from a source checkout."""

from __future__ import annotations

import sys
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent
REPO_ROOT = TOOL_ROOT.parents[1]

for path in (TOOL_ROOT, REPO_ROOT):
    path_text = str(path)
    if path_text not in sys.path:
        sys.path.insert(0, path_text)


def _main() -> int:
    try:
        from vstudio.cli import main
    except ModuleNotFoundError as exc:
        missing = exc.name or str(exc)
        print(
            "ERROR: Missing Python dependency "
            f"{missing!r}. Run from the project environment, for example: "
            "`uv run python tools/virtual-media-studio/civiccast-vstudio.py ...`.",
            file=sys.stderr,
        )
        return 2
    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
