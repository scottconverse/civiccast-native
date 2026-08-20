# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Cable file-package contracts for PEG/headend handoff."""

from __future__ import annotations

import json
import zipfile

import pytest

from civiccast.cable.package import CablePackageError, build_cable_file_package


def test_build_cable_file_package_copies_media_caption_manifest_and_hashes(tmp_path) -> None:
    media = tmp_path / "meeting.mp4"
    captions = tmp_path / "meeting.vtt"
    media.write_bytes(b"mp4 bytes")
    captions.write_text("WEBVTT\n\n00:00.000 --> 00:01.000\nHello.\n", encoding="utf-8")

    result = build_cable_file_package(
        asset_id="council-2026-05-08",
        title="Council - May 8, 2026",
        media_path=media,
        caption_path=captions,
        output_dir=tmp_path / "out",
        portal_url="https://portal.example/watch/council-2026-05-08",
        loudness_status="verified -16 LUFS target",
    )

    assert result.status == "ok"
    assert result.package_dir.exists()
    assert result.zip_path.exists()
    assert result.verification_hash.startswith("sha256:")
    assert (result.package_dir / "media" / "meeting.mp4").read_bytes() == b"mp4 bytes"
    assert (
        (result.package_dir / "captions" / "meeting.vtt")
        .read_text(encoding="utf-8")
        .startswith("WEBVTT")
    )
    manifest = json.loads((result.package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["asset_id"] == "council-2026-05-08"
    assert manifest["title"] == "Council - May 8, 2026"
    assert manifest["proof_boundary"] == "file-package-only"
    assert manifest["loudness_status"] == "verified -16 LUFS target"
    sums = (result.package_dir / "SHA256SUMS").read_text(encoding="utf-8")
    assert "media/meeting.mp4" in sums
    assert "captions/meeting.vtt" in sums
    assert "manifest.json" in sums
    with zipfile.ZipFile(result.zip_path) as package_zip:
        assert sorted(package_zip.namelist()) == [
            "SHA256SUMS",
            "captions/meeting.vtt",
            "manifest.json",
            "media/meeting.mp4",
        ]


def test_build_cable_file_package_fails_actionably_when_caption_missing(tmp_path) -> None:
    media = tmp_path / "meeting.mp4"
    media.write_bytes(b"mp4 bytes")

    with pytest.raises(CablePackageError, match="caption sidecar"):
        build_cable_file_package(
            asset_id="council-2026-05-08",
            title="Council - May 8, 2026",
            media_path=media,
            caption_path=tmp_path / "missing.vtt",
            output_dir=tmp_path / "out",
        )


def test_build_cable_file_package_fails_actionably_when_media_missing(tmp_path) -> None:
    captions = tmp_path / "meeting.vtt"
    captions.write_text("WEBVTT\n", encoding="utf-8")

    with pytest.raises(CablePackageError, match="source media"):
        build_cable_file_package(
            asset_id="council-2026-05-08",
            title="Council - May 8, 2026",
            media_path=tmp_path / "missing.mp4",
            caption_path=captions,
            output_dir=tmp_path / "out",
        )
