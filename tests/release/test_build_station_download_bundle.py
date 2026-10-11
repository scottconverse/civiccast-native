from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from civiccast.installer.native_distribution import (
    STATION_REQUIRED_COMPONENTS,
    build_distribution_index,
)
from scripts.release.build_station_download_bundle import (
    StationBundleError,
    build_station_download_bundle,
)


def _station_fixture(directory: Path) -> dict[str, Path]:
    directory.mkdir(parents=True)
    packs = {
        component: directory / f"{component}.ccpack" for component in STATION_REQUIRED_COMPONENTS
    }
    for component, path in packs.items():
        path.write_bytes((component + ":").encode() + bytes(range(256)))
    index_path = directory / "station-index.json"
    build_distribution_index(
        output=index_path,
        kind="station-index",
        channel="beta",
        product_version="1.0.0-beta.12",
        compatible_core="1.0.0-beta.12",
        packs=packs,
        urls={component: [] for component in packs},
        signing_private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))),
        signing_key_id="test-key",
        created_epoch=1_700_000_000,
    )
    (directory / "SHA256SUMS.txt").write_text("fixture\\n", encoding="utf-8")
    return packs


def test_bundle_streams_zip64_parts_and_manifest(tmp_path: Path) -> None:
    station_dir = tmp_path / "station"
    source_packs = _station_fixture(station_dir)
    output_dir = tmp_path / "release"

    assets = build_station_download_bundle(station_dir, output_dir, part_size_bytes=700)
    manifest_path = next(path for path in assets if path.name == "station-models.json")
    part_paths = [path for path in assets if path.name.startswith("station-models.zip.")]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    archive_bytes = b"".join(path.read_bytes() for path in part_paths)

    assert len(part_paths) > 1
    assert all(path.stat().st_size <= 700 for path in part_paths)
    assert manifest["archive_format"] == "zip"
    assert manifest["archive_name"] == "station-models.zip"
    assert manifest["archive_sha256"] == hashlib.sha256(archive_bytes).hexdigest()
    assert [part["filename"] for part in manifest["parts"]] == [path.name for path in part_paths]
    assert all(
        part["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        for part, path in zip(manifest["parts"], part_paths, strict=True)
    )

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "station/SHA256SUMS.txt",
            "station/station-index.json",
            *(f"station/{path.name}" for path in source_packs.values()),
        }
        assert all(item.compress_type == zipfile.ZIP_STORED for item in archive.infolist())
        for path in source_packs.values():
            entry = next(
                item
                for item in manifest["unpacked_files"]
                if item["path"] == f"station/{path.name}"
            )
            assert entry["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
            assert archive.read(entry["path"]) == path.read_bytes()


def test_bundle_rejects_station_pack_changed_after_index(tmp_path: Path) -> None:
    station_dir = tmp_path / "station"
    packs = _station_fixture(station_dir)
    pack = next(iter(packs.values()))
    original = pack.read_bytes()
    pack.write_bytes(b"X" + original[1:])
    output_dir = tmp_path / "release"

    with pytest.raises(StationBundleError, match="SHA-256 differs from index"):
        build_station_download_bundle(station_dir, output_dir, part_size_bytes=700)

    assert not list(output_dir.glob("station-models.zip.*"))
    assert not (output_dir / "station-models.json").exists()
