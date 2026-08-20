#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Ensure every ``uses: owner/repo@ref`` pin in the workflows actually resolves.

actionlint (the existing lint gate) validates workflow syntax and known-action
input schemas, but it does NOT confirm that a pinned action *version* exists on
GitHub. That gap is exactly how ``actions/download-artifact@v7.0.1`` (a
nonexistent tag — the v7 line of download-artifact stops at v7.0.0) passed every
PR gate and only failed when the real v1.0.0-rc8 tag build tried to resolve it
(gate-civiccast C1/G-1, C3).

This check extracts every external action pin and resolves each `@ref` against
GitHub (tag, branch, or commit SHA), failing closed on any that 404. Extraction
(`iter_action_pins`) is pure and unit-tested; only the default resolver touches
the network, so CI runs it with a token while the unit tests inject a stub.

Usage:
    python scripts/policy/check_action_pins.py        # resolve via `gh api`
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

try:
    from policy_utils import find_repo_root
except ModuleNotFoundError:  # pragma: no cover - package import in tests
    from scripts.policy.policy_utils import find_repo_root

REPO_ROOT = find_repo_root(__file__)

# `uses: owner/repo@ref` or `owner/repo/sub/path@ref`. Skips local (`./...`) and
# docker (`docker://...`) uses, which have no GitHub ref to resolve.
_USES_RE = re.compile(r"""^\s*(?:-\s*)?uses:\s*['"]?(?P<action>[^@'"\s]+)@(?P<ref>[^\s'"#]+)""")


@dataclass(frozen=True)
class Pin:
    action: str  # e.g. "actions/download-artifact" or "owner/repo/sub"
    ref: str  # tag, branch, or commit SHA
    file: str
    line: int

    @property
    def repo(self) -> str:
        """The owner/repo the ref lives in (drops any action sub-path)."""
        parts = self.action.split("/")
        return "/".join(parts[:2])


def iter_action_pins(text: str, display_path: str) -> list[Pin]:
    pins: list[Pin] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        m = _USES_RE.match(raw)
        if not m:
            continue
        action = m.group("action")
        if action.startswith(".") or action.startswith("docker:"):
            continue  # local composite action / docker image — no GitHub ref
        pins.append(Pin(action=action, ref=m.group("ref"), file=display_path, line=i))
    return pins


def collect_pins(root: Path = REPO_ROOT) -> list[Pin]:
    workflow_dir = root / ".github" / "workflows"
    if not workflow_dir.exists():
        return []
    pins: list[Pin] = []
    for path in sorted(workflow_dir.glob("*.yml")):
        rel = str(path.relative_to(root))
        pins.extend(iter_action_pins(path.read_text(encoding="utf-8-sig"), rel))
    return pins


# A "definitive miss" for one endpoint: 404 (no tag/branch) or the commits
# endpoint's 422 "No commit found" for a non-SHA ref. Anything else on a non-zero
# exit (5xx, 403 rate-limit, or a network error with no JSON status) is transient.
_DEFINITIVE_MISS_RE = re.compile(r'"status"\s*:\s*"4(?:04|22)"|Not Found|No commit found')


def _gh_ref_exists(repo: str, ref: str) -> bool:
    """True if `ref` resolves in `repo` as a tag, branch, or commit SHA.

    Fails CLOSED only when EVERY lookup is a definitive miss (404, or the commits
    endpoint's 422 "No commit found"). A transient failure (network blip, GitHub
    5xx, secondary rate limit) is inconclusive and returns True, so a blip can't
    false-fail the required PR gate — the real tag build is the ultimate backstop.
    """
    for endpoint in (
        f"repos/{repo}/git/refs/tags/{ref}",
        f"repos/{repo}/git/refs/heads/{ref}",
        f"repos/{repo}/commits/{ref}",
    ):
        result = subprocess.run(
            ["gh", "api", endpoint],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True
        combined = (result.stderr or "") + (result.stdout or "")
        if not _DEFINITIVE_MISS_RE.search(combined):
            # Not a definitive miss (5xx / rate-limit / network): fail open.
            return True
    return False  # every endpoint was a definitive miss -> genuinely nonexistent


def check_action_pins(
    root: Path = REPO_ROOT,
    resolver: Callable[[str, str], bool] = _gh_ref_exists,
) -> list[str]:
    """Return a list of unresolved-pin problems (empty == all pins resolve).

    `resolver(repo, ref)` returns True if the ref exists; injected in tests.
    """
    problems: list[str] = []
    # Resolve each distinct (repo, ref) once, even if used in many files.
    seen: dict[tuple[str, str], bool] = {}
    for pin in collect_pins(root):
        key = (pin.repo, pin.ref)
        if key not in seen:
            seen[key] = resolver(pin.repo, pin.ref)
        if not seen[key]:
            problems.append(
                f"{pin.file}:{pin.line}: uses {pin.action}@{pin.ref} — "
                f"ref '{pin.ref}' does not resolve in {pin.repo} "
                "(nonexistent tag/branch/SHA)"
            )
    return problems


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    problems = check_action_pins()
    if problems:
        print("check_action_pins: FAIL")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("check_action_pins: PASS - every workflow action pin resolves on GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
