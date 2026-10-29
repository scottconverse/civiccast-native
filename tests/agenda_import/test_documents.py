# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Retained acquisition must survive retries without replacing its original."""

from pathlib import Path

import pytest

from civiccast.agenda_import.documents import DocumentStore


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
