# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""OCR source trust and service-independent executable discovery."""

import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts import build_native_ocr as builder


def test_corrupt_cached_artifact_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "eng.traineddata"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        builder._acquire({"bytes": 7, "sha256": hashlib.sha256(b"correct").hexdigest()}, path)


def test_verified_source_reuse_preserves_time_and_refuses_tampering(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("source/file.c", "reviewed source")
    target = tmp_path / "unpacked"
    builder._extract_sources(archive, target)
    source = target / "source/file.c"
    timestamp = source.stat().st_mtime_ns
    builder._extract_sources(archive, target)
    assert source.stat().st_mtime_ns == timestamp
    source.write_text("tampered")
    with pytest.raises(ValueError, match="Modified OCR source cache"):
        builder._extract_sources(archive, target)


def test_source_traversal_is_refused(tmp_path: Path) -> None:
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.c", "untrusted")
    with pytest.raises(ValueError, match="Unsafe OCR source archive path"):
        builder._extract_sources(archive, tmp_path / "unpacked")


def test_ocr_locates_build_tools_in_selected_msvc_installation(tmp_path, monkeypatch):
    selected = tmp_path / "runner-selected-msvc"
    vcvarsall = selected / "VC/Auxiliary/Build/vcvarsall.bat"
    monkeypatch.setattr(builder, "find_vcvarsall", lambda: vcvarsall)
    monkeypatch.setattr(builder, "load_pinned_msvc_environment", lambda path: {})
    captured = []

    def stop_after_tool_selection(root, versions):
        captured.append((root, versions["cmake"], versions["ninja"]))
        raise RuntimeError("tool selection reached before source acquisition")

    monkeypatch.setattr(builder, "verify_msvc_cmake_tools", stop_after_tool_selection)
    with pytest.raises(RuntimeError, match="tool selection reached"):
        builder.stage_offline_ocr(tmp_path / "output", tmp_path / "scratch")
    assert captured == [(selected, "4.2.3-msvc3", "1.12.1")]
