#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Stream the signed station bundle into GitHub-sized ZIP64 parts.

The input station directory is expected to have been signature-verified by the
candidate's upstream bundle/evidence path. This builder rechecks the canonical
station-index envelope and hashes every pack while archiving it against the
index's byte-count and SHA-256 claims. No full-size intermediate ZIP is made.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from civiccast.installer.native_distribution import (  # noqa: E402
    DISTRIBUTION_PRODUCT,
    STATION_REQUIRED_COMPONENTS,
    canonical_json,
)

PART_SIZE_BYTES = 1_900_000_000
ARCHIVE_NAME = "station-models.zip"
MANIFEST_NAME = "station-models.json"
INDEX_NAME = "station-index.json"
SUMS_NAME = "SHA256SUMS.txt"
_STREAM_CHUNK_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class StationBundleError(ValueError):
    """The station source set does not match its index or cannot be packaged."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(_STREAM_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _read_station_index(station_dir: Path) -> tuple[bytes, list[dict[str, object]]]:
    index_path = station_dir / INDEX_NAME
    if index_path.is_symlink() or not index_path.is_file():
        raise StationBundleError(f"missing regular {INDEX_NAME}: {index_path}")
    raw = index_path.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise StationBundleError("station index is larger than 4 MiB")
    try:
        envelope = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StationBundleError("station index is not valid JSON") from exc
    if canonical_json(envelope) != raw:
        raise StationBundleError("station index is not canonical JSON")
    if not isinstance(envelope, dict) or set(envelope) != {"manifest", "signature"}:
        raise StationBundleError("station index envelope fields are invalid")
    signature_text = envelope.get("signature")
    if not isinstance(signature_text, str):
        raise StationBundleError("station index signature is missing")
    try:
        signature = base64.b64decode(signature_text, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise StationBundleError("station index signature encoding is invalid") from exc
    if len(signature) != 64:
        raise StationBundleError("station index signature has an invalid length")

    manifest = envelope.get("manifest")
    if not isinstance(manifest, dict):
        raise StationBundleError("station index manifest is invalid")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("product") != DISTRIBUTION_PRODUCT
        or manifest.get("kind") != "station-index"
    ):
        raise StationBundleError("input manifest is not a CivicCast station index")
    packs = manifest.get("packs")
    if not isinstance(packs, list) or len(packs) != len(STATION_REQUIRED_COMPONENTS):
        raise StationBundleError("station index must name exactly six station packs")

    seen_components: set[str] = set()
    seen_filenames: set[str] = set()
    normalized: list[dict[str, object]] = []
    for item in packs:
        if not isinstance(item, dict):
            raise StationBundleError("station index pack entry is invalid")
        component = item.get("component")
        filename = item.get("filename")
        byte_count = item.get("bytes")
        digest = item.get("sha256")
        required = item.get("required")
        urls = item.get("urls")
        if not isinstance(component, str) or component not in STATION_REQUIRED_COMPONENTS:
            raise StationBundleError(f"unexpected station component: {component!r}")
        if component in seen_components:
            raise StationBundleError(f"duplicate station component: {component}")
        if (
            not isinstance(filename, str)
            or not filename.endswith(".ccpack")
            or "/" in filename
            or "\\" in filename
            or filename in {".", ".."}
        ):
            raise StationBundleError(f"unsafe pack filename for {component}: {filename!r}")
        if filename.casefold() in seen_filenames:
            raise StationBundleError(f"duplicate station pack filename: {filename}")
        if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count <= 0:
            raise StationBundleError(f"invalid byte count for {component}")
        if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise StationBundleError(f"invalid SHA-256 for {component}")
        if required is not True or urls != []:
            raise StationBundleError(f"station pack must be required and offline: {component}")
        seen_components.add(component)
        seen_filenames.add(filename.casefold())
        normalized.append(
            {"component": component, "filename": filename, "bytes": byte_count, "sha256": digest}
        )

    if seen_components != set(STATION_REQUIRED_COMPONENTS):
        raise StationBundleError(
            "station index does not contain the complete required component set"
        )
    return raw, normalized


class _SplitHashingWriter:
    """Write one logical byte stream directly into bounded, hashed part files."""

    def __init__(self, directory: Path, *, part_size_bytes: int) -> None:
        self.directory = directory
        self.part_size_bytes = part_size_bytes
        self.total_bytes = 0
        self.archive_hash = hashlib.sha256()
        self.parts: list[dict[str, object]] = []
        self._index = 0
        self._current: BinaryIO | None = None
        self._current_size = 0
        self._current_hash = hashlib.sha256()
        self._current_path: Path | None = None

    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def tell(self) -> int:
        return self.total_bytes

    def _open_part(self) -> None:
        self._index += 1
        self._current_path = self.directory / f"{ARCHIVE_NAME}.{self._index:03d}"
        self._current = self._current_path.open("xb")
        self._current_size = 0
        self._current_hash = hashlib.sha256()

    def _finish_part(self) -> None:
        if self._current is None or self._current_path is None:
            return
        self._current.flush()
        self._current.close()
        self.parts.append(
            {
                "filename": self._current_path.name,
                "size_bytes": self._current_size,
                "sha256": self._current_hash.hexdigest(),
                "path": self._current_path,
            }
        )
        self._current = None
        self._current_path = None

    def write(self, data: bytes) -> int:
        view = memoryview(data)
        total = len(view)
        offset = 0
        while offset < total:
            if self._current is None:
                self._open_part()
            assert self._current is not None
            take = min(self.part_size_bytes - self._current_size, total - offset)
            chunk = view[offset : offset + take]
            written = self._current.write(chunk)
            if written != take:
                raise OSError("short write while creating station archive part")
            self._current_hash.update(chunk)
            self.archive_hash.update(chunk)
            self._current_size += take
            self.total_bytes += take
            offset += take
            if self._current_size == self.part_size_bytes:
                self._finish_part()
        return total

    def flush(self) -> None:
        if self._current is not None:
            self._current.flush()

    def close(self) -> None:
        self._finish_part()


def _regular_member(station_dir: Path, filename: str) -> Path:
    path = station_dir / filename
    if path.is_symlink() or not path.is_file():
        raise StationBundleError(f"station bundle member is not a regular file: {filename}")
    try:
        if path.resolve(strict=True).parent != station_dir.resolve(strict=True):
            raise StationBundleError(f"station bundle member escapes its folder: {filename}")
    except OSError as exc:
        raise StationBundleError(f"could not resolve station bundle member: {filename}") from exc
    return path


def build_station_download_bundle(
    station_dir: Path,
    output_dir: Path,
    *,
    part_size_bytes: int = PART_SIZE_BYTES,
) -> list[Path]:
    """Create ZIP64 STORE parts and a manifest; return all publishable paths.

    The archive contains exactly eight files under ``station/``: the signed
    index, its checksum list, and all six packs named by the index. Pack bytes
    are verified against index metadata as they stream through the ZIP writer.
    ``part_size_bytes`` is a small-test seam and may only reduce the production
    part size.
    """
    station_dir = Path(station_dir).expanduser().resolve(strict=True)
    output_dir = Path(output_dir).expanduser().resolve()
    if not station_dir.is_dir():
        raise StationBundleError(f"station source is not a directory: {station_dir}")
    if (
        not isinstance(part_size_bytes, int)
        or isinstance(part_size_bytes, bool)
        or not (1 <= part_size_bytes <= PART_SIZE_BYTES)
    ):
        raise StationBundleError(f"part size must be in 1..{PART_SIZE_BYTES} bytes")
    if output_dir == station_dir or output_dir.is_relative_to(station_dir):
        raise StationBundleError("output directory must be outside the source station folder")

    index_bytes, pack_entries = _read_station_index(station_dir)
    expected_filenames = {
        INDEX_NAME,
        SUMS_NAME,
        *(str(entry["filename"]) for entry in pack_entries),
    }
    for entry in pack_entries:
        _regular_member(station_dir, str(entry["filename"]))
    _regular_member(station_dir, INDEX_NAME)
    _regular_member(station_dir, SUMS_NAME)
    actual_children = list(station_dir.iterdir())
    if any(child.is_symlink() or not child.is_file() for child in actual_children):
        raise StationBundleError("station folder must contain regular files only")
    if {child.name for child in actual_children} != expected_filenames:
        raise StationBundleError(
            "station folder inventory differs from its index and checksum file"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".station-models-build-", dir=output_dir
    ) as staging_name:
        staging = Path(staging_name)
        sink = _SplitHashingWriter(staging, part_size_bytes=part_size_bytes)
        unpacked_files: list[dict[str, object]] = []
        source_specs = [
            (INDEX_NAME, len(index_bytes), hashlib.sha256(index_bytes).hexdigest(), None),
            (SUMS_NAME, (station_dir / SUMS_NAME).stat().st_size, None, None),
            *[
                (str(entry["filename"]), int(entry["bytes"]), str(entry["sha256"]), entry)
                for entry in pack_entries
            ],
        ]
        try:
            with zipfile.ZipFile(
                sink,
                mode="w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                for filename, expected_size, expected_hash, entry in source_specs:
                    source_path = _regular_member(station_dir, filename)
                    info = zipfile.ZipInfo(f"station/{filename}", date_time=(1980, 1, 1, 0, 0, 0))
                    info.create_system = 0
                    info.compress_type = zipfile.ZIP_STORED
                    digest = hashlib.sha256()
                    size = 0
                    with (
                        source_path.open("rb") as source,
                        archive.open(info, mode="w", force_zip64=True) as member,
                    ):
                        while chunk := source.read(_STREAM_CHUNK_BYTES):
                            digest.update(chunk)
                            member.write(chunk)
                            size += len(chunk)
                    actual_hash = digest.hexdigest()
                    if size != expected_size:
                        label = str(entry["component"]) if entry else filename
                        raise StationBundleError(
                            f"station member byte count differs from index: {label}"
                        )
                    if expected_hash is not None and actual_hash != expected_hash:
                        label = str(entry["component"]) if entry else filename
                        raise StationBundleError(
                            f"station member SHA-256 differs from index: {label}"
                        )
                    if (
                        filename == INDEX_NAME
                        and actual_hash != hashlib.sha256(index_bytes).hexdigest()
                    ):
                        raise StationBundleError(
                            "station index changed while the archive was written"
                        )
                    unpacked_files.append(
                        {"path": f"station/{filename}", "size_bytes": size, "sha256": actual_hash}
                    )
            sink.close()
        except Exception:
            sink.close()
            raise

        part_records = [
            {key: value for key, value in part.items() if key != "path"} for part in sink.parts
        ]
        bundle_manifest = {
            "schema_version": 1,
            "archive_format": "zip",
            "archive_name": ARCHIVE_NAME,
            "parts": part_records,
            "archive_sha256": sink.archive_hash.hexdigest(),
            "station_index_sha256": hashlib.sha256(index_bytes).hexdigest(),
            "unpacked_files": unpacked_files,
        }
        staged_manifest = staging / MANIFEST_NAME
        staged_manifest.write_text(
            json.dumps(bundle_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        # Remove the old manifest first so any interrupted replacement fails
        # closed. Replace only files owned by this builder in this output dir.
        final_manifest = output_dir / MANIFEST_NAME
        final_manifest.unlink(missing_ok=True)
        final_part_paths: list[Path] = []
        for part in sink.parts:
            final_path = output_dir / str(part["filename"])
            Path(str(part["path"])).replace(final_path)
            final_part_paths.append(final_path)
        for stale in output_dir.glob(f"{ARCHIVE_NAME}.*"):
            if (
                stale not in final_part_paths
                and stale.is_file()
                and re.fullmatch(re.escape(ARCHIVE_NAME) + r"\.\d{3,}", stale.name)
            ):
                stale.unlink()
        staged_manifest.replace(final_manifest)

    return [*final_part_paths, final_manifest]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--station-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        assets = build_station_download_bundle(args.station_dir, args.output_dir)
    except (OSError, StationBundleError) as exc:
        parser.error(str(exc))
    for asset in assets:
        print(asset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
