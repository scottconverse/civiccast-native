# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Grade F-1 reload commits from new worker logs; this is not a full soak verdict."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_READY = re.compile(r"preroll verified \(reload_id=(\d+)\) held_streams=(\d+)")
_HELD = re.compile(r"\(0 stream\(s\) still to preroll\) \(reload_id=(\d+)\)")
_FIRE = re.compile(r"CTRL reload: firing \(reload_id=(\d+)\)")
_COMMIT = re.compile(r"CTRL reload committed \(elements=(\d+)\)")


def check_log(text: str, expected_elements: int | None = None) -> tuple[int, list[str]]:
    """Every commit consumes its own preroll proof; worker exits reset IDs.

    Held file legs additionally require the final all-stream hold line. Live
    and immediate unheld legs use the engine's all-stream first-buffer proof;
    inventing a hold for those streams would change their clock behavior.
    """
    held: set[int] = set()
    ready: set[int] = set()
    firing: int | None = None
    commits = 0
    errors: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        if "WORKER_RESULT" in line:
            held.clear()
            ready.clear()
            firing = None
        if match := _HELD.search(line):
            held.add(int(match[1]))
        if match := _READY.search(line):
            txn, streams = int(match[1]), int(match[2])
            if streams and txn not in held:
                errors.append(f"line {number}: reload {txn} has no completed preroll hold")
            else:
                ready.add(txn)
        if match := _FIRE.search(line):
            firing = int(match[1])
        if match := _COMMIT.search(line):
            commits += 1
            if firing is None or firing not in ready:
                errors.append(f"line {number}: commit has no matching current preroll proof")
            else:
                ready.remove(firing)
                held.discard(firing)
            firing = None
            if expected_elements is not None and int(match[1]) != expected_elements:
                errors.append(f"line {number}: elements={match[1]}, expected {expected_elements}")
    if not commits:
        errors.append("no reload commits found")
    return commits, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", type=Path, nargs="+")
    parser.add_argument("--expected-elements", type=int)
    args = parser.parse_args()
    failed = False
    for path in args.logs:
        count, errors = check_log(
            path.read_text(encoding="utf-8", errors="replace"), args.expected_elements
        )
        print(f"{path}: {count} commits; {'FAIL' if errors else 'PASS'}")
        for error in errors:
            print(f"  {error}")
        failed |= bool(errors)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
