# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Retained public originals and resumable page checkpoints.

Versioned manifests live beside originals under the managed upload directory.
No agenda row is changed by acquisition or processing. This deliberately reuses
the file-backed asset storage rather than introducing another database or worker.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filelock import FileLock


@dataclass(frozen=True)
class RetainedDocument:
    document_id: str
    path: Path
    checkpoint_path: Path
    metadata: dict[str, Any]


class DocumentStore:
    """One immutable original per provider document identity and URL.

    A per-document OS lock serializes acquisition/checkpoint updates across app
    processes. Downloads land in a disposable partial file; only complete files
    are promoted. Existing originals are hash-verified before reuse.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    def get_revision(self, document_id: str, sha256: str) -> RetainedDocument:
        """Resolve the exact previewed original, even after a newer amendment."""
        for value in (document_id, sha256):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("Invalid retained document identity.")
        folder = self.root / document_id
        version = folder / "versions" / sha256
        manifest = version / "manifest.json"
        if not manifest.is_file():
            version = folder
            manifest = folder / "legacy-manifest.json"
            if not manifest.is_file():
                manifest = folder / "manifest.json"
        if not manifest.is_file():
            raise LookupError("Retained document revision not found.")
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        identity = metadata.get("identity", {})
        identity_digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        original = version / "original.pdf"
        if (
            metadata.get("version") != 1
            or metadata.get("sha256") != sha256
            or identity_digest != document_id
            or not original.is_file()
            or _sha256(original) != sha256
        ):
            raise ValueError("Retained original is missing or changed; resume refused.")
        return RetainedDocument(document_id, original, version / "pages.json", metadata)

    @contextmanager
    def resume_revision(self, document_id: str, sha256: str) -> Iterator[RetainedDocument]:
        # Validate before using the identifier as a filesystem component.
        retained = self.get_revision(document_id, sha256)
        with FileLock(str(self.root / document_id / "document.lock"), timeout=1):
            yield retained

    @contextmanager
    def acquire(
        self,
        *,
        source: str,
        client_code: str,
        event_id: str,
        provider_document_id: str,
        url: str,
        download: Callable[[Path], None],
        refresh: bool = False,
    ) -> Iterator[RetainedDocument]:
        identity = {
            "source": source,
            "client_code": client_code,
            "event_id": event_id,
            "provider_document_id": provider_document_id,
            "url": url,
        }
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        folder = self.root / key
        folder.mkdir(parents=True, exist_ok=True)
        with FileLock(str(folder / "document.lock"), timeout=1):
            original = folder / "original.pdf"
            checkpoint = folder / "pages.json"
            manifest = folder / "manifest.json"
            previous_digest: str | None = None
            if manifest.exists():
                metadata = json.loads(manifest.read_text(encoding="utf-8"))
                if metadata.get("version") != 1 or metadata.get("identity") != identity:
                    raise ValueError("Retained document manifest identity/version mismatch.")
                if metadata.get("storage_key") is not None:
                    digest = metadata["sha256"]
                    if (
                        metadata["storage_key"] != digest
                        or len(digest) != 64
                        or any(c not in "0123456789abcdef" for c in digest)
                    ):
                        raise ValueError("Invalid retained document storage identity.")
                    original = folder / "versions" / digest / "original.pdf"
                    checkpoint = original.with_name("pages.json")
                if not original.is_file() or _sha256(original) != metadata.get("sha256"):
                    raise ValueError("Retained original is missing or changed; resume refused.")
                previous_digest = metadata["sha256"]
                # Preserve the legacy v1 manifest when a fresh revision replaces
                # the current pointer; its original/checkpoint remain untouched.
                if refresh and metadata.get("storage_key") is None:
                    _write_json(folder / "legacy-manifest.json", metadata)
            if not manifest.exists() or refresh:
                partial = folder / "download.part"
                try:
                    download(partial)
                    with partial.open("rb") as handle:
                        if b"%PDF-" not in handle.read(1024):
                            raise ValueError("The published document is not a PDF.")
                    digest = _sha256(partial)
                    metadata = {
                        "version": 1,
                        "identity": identity,
                        "sha256": digest,
                        "storage_key": digest,
                        "bytes": partial.stat().st_size,
                    }
                    version = folder / "versions" / digest
                    version.mkdir(parents=True, exist_ok=True)
                    original = version / "original.pdf"
                    previous_checkpoint = checkpoint
                    checkpoint = version / "pages.json"
                    if original.exists():
                        if _sha256(original) != digest:
                            raise ValueError(
                                "Retained revision is corrupted; refusing replacement."
                            )
                    else:
                        partial.replace(original)
                    if (
                        digest == previous_digest
                        and previous_checkpoint != checkpoint
                        and previous_checkpoint.exists()
                        and not checkpoint.exists()
                    ):
                        # Adopt only identical bytes; preserve the old checkpoint too.
                        temporary_checkpoint = checkpoint.with_suffix(".tmp")
                        shutil.copyfile(previous_checkpoint, temporary_checkpoint)
                        temporary_checkpoint.replace(checkpoint)
                    _write_json(version / "manifest.json", metadata)
                    _write_json(manifest, metadata)
                finally:
                    partial.unlink(missing_ok=True)
            yield RetainedDocument(key, original, checkpoint, metadata)


def _write_json(path: Path, metadata: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(metadata, stream)
        stream.flush()
        os.fsync(stream.fileno())
    # Windows readers (including preview polling) can briefly deny replacement.
    # Keep the old complete JSON visible and retry only those sharing/access
    # errors, for at most 310 ms. Permanent failures still surface to the caller.
    for attempt in range(6):
        try:
            temporary.replace(path)
            break
        except OSError as error:
            if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 5:
                raise
            time.sleep(0.01 * 2**attempt)


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def configured_document_store() -> DocumentStore:
    """Use managed uploads in production; an explicit local root in development."""
    override = os.environ.get("CIVICCAST_AGENDA_DOCUMENT_DIR")
    root = (
        Path(override)
        if override
        else Path(os.environ.get("CIVICCAST_UPLOAD_DIR", "uploads")) / "agenda-import"
    )
    return DocumentStore(root)
