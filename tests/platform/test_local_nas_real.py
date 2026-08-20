# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real local-NAS archive transport tests (issue #112, NAS half).

The real adapter writes two genuinely distinct copies to the station's
mounted NAS directory (local mount or UNC) and verifies each with an
independent sha256 read-back. No proof is minted unless the bytes on disk
hash-match. The deterministic mock remains the default selection.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from civiccast.archive.local_nas import (
    LocalNasArchiveClient,
    LocalNasSettings,
    LocalNasVerificationError,
)
from civiccast.archive.models import MockLocalNasArchiveClient
from civiccast.platform.providers import PROVIDER_KIND_LOCAL_NAS, default_registry


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


class TestLocalNasArchiveClient:
    def test_payload_mode_writes_two_verified_copies(self, tmp_path: Path) -> None:
        client = LocalNasArchiveClient(LocalNasSettings(archive_root=tmp_path))

        copy_proof, snapshot_proof = client.archive(asset_id="meeting-42", payload=b"payload")

        copy_path = Path(copy_proof.target_url_or_path)
        snapshot_path = Path(snapshot_proof.target_url_or_path)
        assert copy_path == tmp_path / "archive" / "meeting-42.bin"
        assert snapshot_path.parent == tmp_path / "snapshots" / "meeting-42"
        assert copy_path.read_bytes() == b"payload"
        assert snapshot_path.read_bytes() == b"payload"
        assert copy_proof.target_type == "local_nas_copy"
        assert snapshot_proof.target_type == "local_nas_snapshot_copy"
        # Hashes are of the actual stored bytes, re-read from disk.
        assert copy_proof.verification_hash == _sha256(copy_path)
        assert snapshot_proof.verification_hash == _sha256(snapshot_path)

    def test_path_mode_streams_the_media_file(self, tmp_path: Path) -> None:
        media = tmp_path / "source" / "meeting-42.mp4"
        media.parent.mkdir()
        media.write_bytes(b"media-bytes" * 4096)
        nas_root = tmp_path / "nas"
        nas_root.mkdir()
        client = LocalNasArchiveClient(LocalNasSettings(archive_root=nas_root))

        copy_proof, snapshot_proof = client.archive_path(asset_id="meeting-42", path=media)

        copy_path = Path(copy_proof.target_url_or_path)
        snapshot_path = Path(snapshot_proof.target_url_or_path)
        assert copy_path == nas_root / "archive" / "meeting-42.mp4"
        assert copy_path.read_bytes() == media.read_bytes()
        assert snapshot_path.read_bytes() == media.read_bytes()
        assert snapshot_path.name.endswith(".mp4")
        assert copy_proof.verification_hash == _sha256(media)

    def test_snapshot_copies_are_write_once_per_run(self, tmp_path: Path) -> None:
        client = LocalNasArchiveClient(LocalNasSettings(archive_root=tmp_path))

        _, first = client.archive(asset_id="meeting-42", payload=b"v1")
        _, second = client.archive(asset_id="meeting-42", payload=b"v2")

        assert first.target_url_or_path != second.target_url_or_path
        assert Path(first.target_url_or_path).read_bytes() == b"v1"
        assert Path(second.target_url_or_path).read_bytes() == b"v2"
        # The canonical archive copy is overwrite-on-republish.
        assert (tmp_path / "archive" / "meeting-42.bin").read_bytes() == b"v2"

    def test_corrupted_write_raises_instead_of_minting_a_proof(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = LocalNasArchiveClient(LocalNasSettings(archive_root=tmp_path))

        original_read_hash = LocalNasArchiveClient._read_back_hash

        def corrupted(self: LocalNasArchiveClient, path: Path) -> str:
            original_read_hash(self, path)
            return "sha256:" + "0" * 64

        monkeypatch.setattr(LocalNasArchiveClient, "_read_back_hash", corrupted)
        with pytest.raises(LocalNasVerificationError, match="hash"):
            client.archive(asset_id="meeting-42", payload=b"payload")

    def test_from_env_fails_fast_with_exact_variable_name(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CIVICCAST_NAS_ARCHIVE_PATH", raising=False)
        with pytest.raises(ValueError, match="CIVICCAST_NAS_ARCHIVE_PATH"):
            LocalNasSettings.from_env()

        missing = tmp_path / "not-mounted"
        monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", str(missing))
        with pytest.raises(ValueError, match="reachable directory"):
            LocalNasSettings.from_env()

        monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", str(tmp_path))
        assert LocalNasSettings.from_env().archive_root == tmp_path


class TestRegistrySelection:
    def test_real_resolves_with_path_and_mock_stays_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CIVICCAST_PROVIDER_LOCAL_NAS", raising=False)
        assert isinstance(
            default_registry().resolve(PROVIDER_KIND_LOCAL_NAS), MockLocalNasArchiveClient
        )

        monkeypatch.setenv("CIVICCAST_PROVIDER_LOCAL_NAS", "real")
        monkeypatch.setenv("CIVICCAST_NAS_ARCHIVE_PATH", str(tmp_path))
        assert isinstance(
            default_registry().resolve(PROVIDER_KIND_LOCAL_NAS), LocalNasArchiveClient
        )

    def test_real_without_path_fails_fast_never_falls_back_to_mock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("CIVICCAST_PROVIDER_LOCAL_NAS", "real")
        monkeypatch.delenv("CIVICCAST_NAS_ARCHIVE_PATH", raising=False)
        with pytest.raises(ValueError, match="CIVICCAST_NAS_ARCHIVE_PATH"):
            default_registry().resolve(PROVIDER_KIND_LOCAL_NAS)
