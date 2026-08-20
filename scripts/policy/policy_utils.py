#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Shared helpers for Agent Pipeline policy scripts."""

from __future__ import annotations

import subprocess
from pathlib import Path


def find_repo_root(script_file: str) -> Path:
    """Resolve the repo root for source and installed policy layouts."""
    script_dir = Path(script_file).resolve().parent
    if script_dir.name == "policy" and script_dir.parent.name == "scripts":
        return script_dir.parents[1]
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=script_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return script_dir.parent


def strip_yaml_comment(line: str) -> str:
    """Strip YAML comments without treating # inside quotes as a comment."""
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_double:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if (
            char == "#"
            and not in_single
            and not in_double
            and (index == 0 or line[index - 1].isspace())
        ):
            return line[:index].rstrip()
    return line
