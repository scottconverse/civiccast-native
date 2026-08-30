# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the real recording-storage probe (bug B3).

``civiccast.live.storage_probe.probe_storage_free_bytes`` is the
``StorageProbe`` implementation wired into every real station's
``PreflightEvaluator`` (``civiccast/app.py``'s
``_resolve_preflight_evaluator``). Before this module existed, the
"Recording storage" pre-flight check depended entirely on a caller
supplying ``storage_free_bytes`` -- no real caller ever did, so the check
reported ``storage.not_probed`` forever (field evidence, native beta
candidate #17).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from civiccast.live.storage_probe import build_storage_probe, probe_storage_free_bytes


def test_probe_returns_real_free_bytes(tmp_path: Path) -> None:
    free_bytes, message = probe_storage_free_bytes(path=tmp_path)
    assert message is None
    # Real, live free-space bytes fluctuate between calls; assert it is a
    # real positive number in the right ballpark rather than pinning an
    # exact byte count against a second live read.
    assert free_bytes is not None and free_bytes > 0
    assert abs(free_bytes - shutil.disk_usage(tmp_path).free) < 10 * (1024**3)


def test_probe_reports_failure_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(path: object) -> None:
        raise OSError("volume unavailable")

    monkeypatch.setattr(shutil, "disk_usage", _boom)
    free_bytes, message = probe_storage_free_bytes(path=tmp_path)
    assert free_bytes is None
    assert message is not None and "volume unavailable" in message


def test_default_path_uses_upload_dir_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
    seen_paths: list[Path] = []
    real_disk_usage = shutil.disk_usage

    def _tracking_disk_usage(path: Path):  # type: ignore[no-untyped-def]
        seen_paths.append(Path(path))
        return real_disk_usage(path)

    monkeypatch.setattr(shutil, "disk_usage", _tracking_disk_usage)
    probe_storage_free_bytes()
    assert seen_paths == [tmp_path]


def test_default_path_falls_back_to_home_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CIVICCAST_UPLOAD_DIR", raising=False)
    seen_paths: list[Path] = []
    real_disk_usage = shutil.disk_usage

    def _tracking_disk_usage(path: Path):  # type: ignore[no-untyped-def]
        seen_paths.append(Path(path))
        return real_disk_usage(path)

    monkeypatch.setattr(shutil, "disk_usage", _tracking_disk_usage)
    probe_storage_free_bytes()
    assert seen_paths == [Path.home()]


def test_build_storage_probe_binds_explicit_path(tmp_path: Path) -> None:
    probe = build_storage_probe(path=tmp_path)
    free_bytes, message = probe()
    assert message is None
    # Real, live free-space bytes fluctuate between calls (other processes on
    # the box write to the same volume); assert it is a real positive number
    # rather than pinning an exact byte count against a second live read.
    assert free_bytes is not None and free_bytes > 0
