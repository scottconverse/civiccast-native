#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Policy: changed files must fall inside allowed_paths and outside forbidden_paths."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from policy_utils import find_repo_root, strip_yaml_comment
except ModuleNotFoundError:  # pragma: no cover - source-tree test import
    from scripts.policy_utils import find_repo_root, strip_yaml_comment


REPO_ROOT = find_repo_root(__file__)
RUN_DIR = REPO_ROOT / ".agent-runs"


def _git_changed_files() -> list[str]:
    """Return tracked and untracked paths changed in the working tree."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    changed = [line.strip() for line in result.stdout.splitlines() if line.strip()]

    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    changed.extend(line.strip() for line in untracked.stdout.splitlines() if line.strip())
    return sorted(set(changed))


def _load_manifest_lists(manifest_path: Path) -> tuple[list[str], list[str]]:
    """Return (allowed_paths, forbidden_paths) parsed from manifest YAML."""
    if not manifest_path.exists():
        print(f"FAIL: manifest not found at {manifest_path}", file=sys.stderr)
        sys.exit(1)

    text = manifest_path.read_text(encoding="utf-8")
    allowed: list[str] = []
    forbidden: list[str] = []
    current_key: str | None = None

    for raw in text.splitlines():
        line = strip_yaml_comment(raw.rstrip())
        if not line:
            continue
        stripped = line.strip()
        if stripped.startswith("allowed_paths:"):
            current_key = "allowed"
            if "[]" in stripped:
                current_key = None
            continue
        if stripped.startswith("forbidden_paths:"):
            current_key = "forbidden"
            if "[]" in stripped:
                current_key = None
            continue
        if not raw.startswith((" ", "\t")) and stripped.endswith(":"):
            current_key = None
            continue
        if stripped.startswith("- ") and current_key is not None:
            value = stripped[2:].strip().strip("\"'")
            if current_key == "allowed":
                allowed.append(value)
            elif current_key == "forbidden":
                forbidden.append(value)
        elif current_key is not None and not stripped.startswith("- "):
            current_key = None

    return allowed, forbidden


def _is_under(path: str, prefixes: list[str]) -> bool:
    """True if path is exactly a prefix or starts with prefix + slash."""
    for prefix in prefixes:
        if not prefix:
            continue
        normalized = prefix.rstrip("/")
        if path == normalized or path.startswith(normalized + "/"):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        help="Pipeline run id (directory under .agent-runs/). Without this, the check is a no-op.",
    )
    args = parser.parse_args()

    if not args.run:
        print(
            "check_allowed_paths: no --run argument provided; skipping (no-op outside a pipeline run)."
        )
        return 0

    manifest_path = RUN_DIR / args.run / "manifest.yaml"
    allowed, forbidden = _load_manifest_lists(manifest_path)

    if not allowed and not forbidden:
        print(
            "check_allowed_paths: manifest has empty allowed_paths AND forbidden_paths - "
            "no constraints to enforce. PASS."
        )
        return 0

    changed = _git_changed_files()
    if not changed:
        print("check_allowed_paths: no changed files in working tree. PASS.")
        return 0

    violations: list[tuple[str, str]] = []
    for path in changed:
        if forbidden and _is_under(path, forbidden):
            violations.append((path, "matches forbidden_paths"))
            continue
        if allowed and not _is_under(path, allowed):
            violations.append((path, "outside allowed_paths"))

    if violations:
        print("check_allowed_paths: FAIL")
        print(f"  manifest: {manifest_path}")
        print(f"  allowed_paths: {allowed or '(none)'}")
        print(f"  forbidden_paths: {forbidden or '(none)'}")
        print("  violations:")
        for path, reason in violations:
            print(f"    {path}  ({reason})")
        return 1

    print(f"check_allowed_paths: PASS - {len(changed)} changed file(s), all within allowed_paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
