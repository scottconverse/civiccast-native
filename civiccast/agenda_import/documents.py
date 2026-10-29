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
            manifest = folder / "manifest.json"
            if manifest.exists():
                metadata = json.loads(manifest.read_text(encoding="utf-8"))
                if metadata.get("version") != 1 or metadata.get("identity") != identity:
                    raise ValueError("Retained document manifest identity/version mismatch.")
                if not original.is_file() or _sha256(original) != metadata.get("sha256"):
                    raise ValueError("Retained original is missing or changed; resume refused.")
            else:
                partial = folder / "download.part"
                try:
                    download(partial)
                    with partial.open("rb") as handle:
                        if b"%PDF-" not in handle.read(1024):
                            raise ValueError("The published document is not a PDF.")
                    metadata = {
                        "version": 1,
                        "identity": identity,
                        "sha256": _sha256(partial),
                        "bytes": partial.stat().st_size,
                    }
                    partial.replace(original)
                    temporary = folder / "manifest.tmp"
                    temporary.write_text(json.dumps(metadata), encoding="utf-8")
                    temporary.replace(manifest)
                finally:
                    partial.unlink(missing_ok=True)
            yield RetainedDocument(key, original, folder / "pages.json", metadata)


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
