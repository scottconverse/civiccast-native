"""Contracts for source-state evidence collection."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "collect_source_state",
    Path(__file__).resolve().parents[1] / "scripts" / "collect_source_state.py",
)
assert _SPEC is not None
assert _SPEC.loader is not None
collect_source_state = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = collect_source_state
_SPEC.loader.exec_module(collect_source_state)


def test_git_command_failure_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fail_run(*args, **kwargs):
        raise subprocess.CalledProcessError(128, args[0], stderr=b"not a git repository")

    monkeypatch.setattr(collect_source_state.subprocess, "run", fail_run)

    with pytest.raises(RuntimeError, match="git branch --show-current failed"):
        collect_source_state.collect_source_state(repo_root=tmp_path)
