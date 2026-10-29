# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Retained acquisition must survive retries without replacing its original."""

import hashlib
import json
from pathlib import Path

import pytest

from civiccast.agenda_import.documents import DocumentStore


def test_atomic_json_retries_brief_windows_reader_lock(tmp_path, monkeypatch):
    from civiccast.agenda_import import documents

    target = tmp_path / "preview.json"
    target.write_text('{"status":"reading"}')
    replace = Path.replace
    attempts = []
    delays = []

    def busy_twice(path, destination):
        attempts.append(path)
        if len(attempts) <= 2:
            assert json.loads(target.read_text())["status"] == "reading"
            error = PermissionError("reader sharing conflict")
            error.winerror = 5
            raise error
        return replace(path, destination)

    monkeypatch.setattr(Path, "replace", busy_twice)
    monkeypatch.setattr(documents.time, "sleep", delays.append)
    documents._write_json(target, {"status": "ready"})
    assert json.loads(target.read_text()) == {"status": "ready"}
    assert len(attempts) == 3 and delays == [0.01, 0.02]


def test_atomic_json_permanent_windows_failure_is_bounded_and_preserves_old(tmp_path, monkeypatch):
    from civiccast.agenda_import import documents

    target = tmp_path / "preview.json"
    target.write_text('{"status":"reading"}')
    attempts = []
    delays = []

    def denied(path, destination):
        attempts.append(path)
        error = PermissionError("persistent denial")
        error.winerror = 5
        raise error

    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr(documents.time, "sleep", delays.append)
    with pytest.raises(PermissionError):
        documents._write_json(target, {"status": "ready"})
    assert len(attempts) == 6 and sum(delays) == pytest.approx(0.31)
    assert json.loads(target.read_text()) == {"status": "reading"}


def arguments(download):
    return {
        "source": "primegov",
        "client_code": "example",
        "event_id": "42",
        "provider_document_id": "123",
        "url": "https://example.org/packet.pdf",
        "download": download,
    }


def test_resume_reuses_original_and_provider_identity(tmp_path):
    store = DocumentStore(tmp_path)
    calls = []

    def download(path: Path):
        calls.append(path)
        path.write_bytes(b"%PDF-1.7 original")

    with store.acquire(**arguments(download)) as first:
        digest = first.metadata["sha256"]
        first.checkpoint_path.write_text('{"completed":12}')
    with store.acquire(**arguments(download)) as resumed:
        assert resumed.metadata["sha256"] == digest
        assert resumed.metadata["identity"]["event_id"] == "42"
        assert resumed.checkpoint_path.read_text() == '{"completed":12}'
    assert len(calls) == 1


def test_interrupted_download_is_not_promoted(tmp_path):
    def interrupted(path):
        path.write_bytes(b"%PDF- incomplete")
        raise TimeoutError("download deadline")

    with pytest.raises(TimeoutError), DocumentStore(tmp_path).acquire(**arguments(interrupted)):
        pass
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("manifest.json"))
    assert not list(tmp_path.rglob("original.pdf"))


def test_changed_retained_original_refuses_resume(tmp_path):
    store = DocumentStore(tmp_path)

    def download(path):
        path.write_bytes(b"%PDF- original")

    with store.acquire(**arguments(download)) as retained:
        retained.path.write_bytes(b"%PDF- changed")
    with pytest.raises(ValueError, match="changed"), store.acquire(**arguments(download)):
        pass


def test_fresh_revision_preserves_old_original_and_checkpoints(tmp_path):
    store = DocumentStore(tmp_path)
    content = [b"%PDF- old"]

    def download(path):
        path.write_bytes(content[0])

    with store.acquire(**arguments(download)) as old:
        old.checkpoint_path.write_text("saved old pages")
    content[0] = b"%PDF- revised"
    with store.acquire(**arguments(download), refresh=True) as revised:
        assert revised.path != old.path
        assert revised.path.read_bytes() == content[0]
        assert not revised.checkpoint_path.exists()
        revised.checkpoint_path.write_text("saved revised pages")
    assert old.path.read_bytes() == b"%PDF- old"
    assert old.checkpoint_path.read_text() == "saved old pages"

    def no_download(path):
        raise AssertionError("Resume must use the retained original")

    with store.acquire(**arguments(no_download)) as resumed:
        assert resumed.path == revised.path
        assert resumed.checkpoint_path.read_text() == "saved revised pages"


def test_refresh_unchanged_content_keeps_completed_pages(tmp_path):
    store = DocumentStore(tmp_path)

    def download(path):
        path.write_bytes(b"%PDF- unchanged")

    with store.acquire(**arguments(download)) as original:
        original.checkpoint_path.write_text("saved pages")
    with store.acquire(**arguments(download), refresh=True) as refreshed:
        assert refreshed.path == original.path
        assert refreshed.checkpoint_path.read_text() == "saved pages"


def test_refresh_flat_manifest_carries_same_original_checkpoint_forward(tmp_path):
    store = DocumentStore(tmp_path)

    def download(path):
        path.write_bytes(b"%PDF- unchanged")

    with store.acquire(**arguments(download)) as original:
        identity = original.metadata["identity"]
        folder = tmp_path / original.document_id
    legacy = {
        "version": 1,
        "identity": identity,
        "sha256": hashlib.sha256(b"%PDF- unchanged").hexdigest(),
        "bytes": 15,
    }
    (folder / "manifest.json").write_text(json.dumps(legacy))
    (folder / "original.pdf").write_bytes(b"%PDF- unchanged")
    (folder / "pages.json").write_text('{"completed":12}')
    with store.acquire(**arguments(download), refresh=True) as refreshed:
        assert refreshed.checkpoint_path.read_text() == '{"completed":12}'
        assert (folder / "pages.json").read_text() == '{"completed":12}'
