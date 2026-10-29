# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Portable managed originals, completed pages and confirmed database state."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from contextlib import contextmanager

import pytest
from reportlab.pdfgen import canvas
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.agenda.models import MeetingAgenda
from civiccast.agenda.store import AgendaStore
from civiccast.agenda_import import previews as preview_module
from civiccast.agenda_import.documents import DocumentStore, agenda_snapshot_lock
from civiccast.agenda_import.models import ExternalAgenda, ExternalAgendaItem
from civiccast.agenda_import.pdf_processing import process_pdf
from civiccast.agenda_import.previews import PreviewStore, agenda_fingerprint
from civiccast.db import Base
from civiccast.dr.station_backup import StationBackupService


@contextmanager
def _private_junction(link, target, private_root):
    """Create/remove only a link in this test's private tree; never recurse it."""
    import _winapi

    private_root = private_root.resolve(strict=True)
    assert link.absolute().is_relative_to(private_root)
    assert target.resolve(strict=True).is_relative_to(private_root)
    _winapi.CreateJunction(str(target), str(link))
    try:
        assert link.is_junction() and not link.is_symlink()
        yield
    finally:
        assert link.parent.resolve(strict=True).is_relative_to(private_root)
        assert link.is_junction() and link.resolve(strict=True) == target.resolve(strict=True)
        os.rmdir(link)  # noqa: PTH106 -- explicit Windows junction-only removal, never recursive.
        assert target.is_dir()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction regression")
@pytest.mark.parametrize("position", ["root", "ancestor", "descendant"])
@pytest.mark.parametrize("operation", ["backup", "restore"])
def test_managed_paths_reject_windows_junctions(tmp_path, position, operation):
    outside = tmp_path / "outside-managed-root"
    outside.mkdir()
    sentinel = outside / "original.pdf"
    sentinel.write_bytes(b"private outside original must not be copied or replaced")
    if position == "root":
        link = root = tmp_path / "agenda-import"
    elif position == "ancestor":
        link = tmp_path / "ancestor"
        root = link / "agenda-import"
        (outside / "agenda-import").mkdir()
        (outside / "agenda-import" / "original.pdf").write_bytes(sentinel.read_bytes())
    else:
        root = tmp_path / "agenda-import"
        root.mkdir()
        link = root / "versions"
    with _private_junction(link, outside, tmp_path):
        service = StationBackupService(
            database_url="sqlite://",
            destination=tmp_path / "backups",
            managed_roots={"agenda-import": root},
        )
        with pytest.raises(ValueError, match=r"reparse|symbolic|junction"):
            if operation == "backup":
                service._copy_managed_payload(tmp_path / "staging")
            else:
                relative = "versions/original.pdf" if position == "descendant" else "original.pdf"
                service._managed_restore_targets(
                    [
                        {
                            "kind": "media",
                            "managed_root": "agenda-import",
                            "source_path": "old-agenda-root",
                            "relative_path": relative,
                        }
                    ],
                    {},
                )
        assert sentinel.read_bytes() == b"private outside original must not be copied or replaced"
        assert not (tmp_path / "staging").exists()


def _agendas(database):
    engine = create_engine(f"sqlite:///{database.as_posix()}").execution_options(
        schema_translate_map={"civiccast": None}
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    return AgendaStore(sessions), engine


def _ready(previews, agendas):
    preview = previews.create("a", {"source": "primegov"}, agenda_fingerprint(agendas, "a"))
    external = ExternalAgenda(
        external_id="42",
        title="Council",
        source_doc_url="https://example.org/agenda.pdf",
        items=[ExternalAgendaItem(order=1, number="1", title="Call to order")],
    )
    record = previews._load(preview.preview_id)
    record.update(status="ready", _external=external.model_dump(mode="json"))
    previews._save(record)
    return preview.preview_id


def test_agenda_roundtrip(tmp_path):
    database = tmp_path / "source.db"
    agendas, engine = _agendas(database)
    agendas.upsert_agenda(MeetingAgenda(agenda_id="a", station_id="s", meeting_asset_id="m"))
    documents = DocumentStore(tmp_path / "old")
    previews = PreviewStore(documents)
    confirmed_id = _ready(previews, agendas)
    previews.confirm("a", confirmed_id, agendas)
    pdf = tmp_path / "published.pdf"
    document = canvas.Canvas(str(pdf))
    for page in range(2):
        document.drawString(72, 700, f"Council agenda page {page + 1}")
        document.showPage()
    document.save()
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    with documents.acquire(
        source="primegov",
        client_code="example",
        event_id="42",
        provider_document_id="1",
        url="https://example.org/agenda.pdf",
        download=lambda target: shutil.copyfile(pdf, target),
    ) as retained:
        partial = process_pdf(retained.path, retained.checkpoint_path, max_pages=1)
        assert partial.pages_read == 1
        checkpoint = json.loads(retained.checkpoint_path.read_text())
        checkpoint["pages"][0]["text"] = "Previously completed page is reused"
        retained.checkpoint_path.write_text(json.dumps(checkpoint))
    partial_preview = previews.create("a", {}, agenda_fingerprint(agendas, "a"))
    record = previews._load(partial_preview.preview_id)
    record.update(
        status="partial",
        resumable=True,
        pages_read=1,
        pages_total=2,
        document_id=retained.document_id,
        document_sha256=digest,
    )
    previews._save(record)
    previews._path(partial_preview.preview_id).with_suffix(".cancel").touch()
    (documents.root / "download.part").write_bytes(b"unfinished")
    (documents.root / "manifest.tmp").write_bytes(b"unfinished")
    service = StationBackupService(
        database_url=f"sqlite:///{database.as_posix()}",
        destination=tmp_path / "backups",
        managed_roots={"agenda-import": documents.root},
        snapshot_guard=lambda: agenda_snapshot_lock(documents.root),
    )
    assert service.status()["schedule"]["selected_media_roots"] == []
    artifact = service.create_backup("agenda recovery passphrase")
    assert service.verify_backup(artifact.path, "agenda recovery passphrase").valid
    replacement = tmp_path / "new"
    replacement.mkdir()
    (replacement / "stale-preview.json").write_text('{"status":"confirmed"}')
    replacement_db = tmp_path / "replacement.db"
    replacement_service = StationBackupService(
        database_url=f"sqlite:///{replacement_db.as_posix()}",
        destination=tmp_path / "backups-new",
        managed_roots={"agenda-import": replacement},
    )
    replacement_service.restore_backup(
        artifact.path,
        "agenda recovery passphrase",
        target_database_url=f"sqlite:///{replacement_db.as_posix()}",
        writers_stopped=True,
    )
    restored_documents = DocumentStore(replacement)
    restored_previews = PreviewStore(restored_documents)
    restored_agendas, restored_engine = _agendas(replacement_db)
    try:
        assert not (replacement / "stale-preview.json").exists()
        rollback = list(tmp_path.glob("new.pre-restore-*"))
        assert len(rollback) == 1 and (rollback[0] / "stale-preview.json").exists()
        assert restored_previews.get("a", confirmed_id).status == "confirmed"
        assert len(restored_agendas.list_items("a")) == 1
        assert restored_previews.confirm("a", confirmed_id, restored_agendas)[0] == []
        assert restored_previews.get("a", partial_preview.preview_id).pages_read == 1
        assert restored_previews.get("a", partial_preview.preview_id).cancel_requested
        restored_previews.queue_resume("a", partial_preview.preview_id)
        assert not restored_previews.get("a", partial_preview.preview_id).cancel_requested
        with restored_documents.resume_revision(retained.document_id, digest) as revision:
            assert hashlib.sha256(revision.path.read_bytes()).hexdigest() == digest
            resumed = process_pdf(revision.path, revision.checkpoint_path)
        assert resumed.complete and resumed.pages_read == 2
        assert resumed.pages[0].text == "Previously completed page is reused"
        assert not (replacement / "download.part").exists()
        assert not (replacement / "manifest.tmp").exists()
        with pytest.raises(ValueError, match="replacement station"):
            replacement_service.restore_backup(
                artifact.path,
                "agenda recovery passphrase",
                target_database_url=f"sqlite:///{replacement_db.as_posix()}",
                writers_stopped=True,
                target_paths={str(documents.root): tmp_path / "arbitrary"},
            )
    finally:
        restored_engine.dispose()
        engine.dispose()


def test_confirmation_holds_snapshot_gate_until_database_and_preview_agree(tmp_path, monkeypatch):
    agendas, engine = _agendas(tmp_path / "station.db")
    agendas.upsert_agenda(MeetingAgenda(agenda_id="a", station_id="s", meeting_asset_id="m"))
    previews = PreviewStore(DocumentStore(tmp_path / "agenda-import"))
    preview_id = _ready(previews, agendas)
    database_written = threading.Event()
    finish_confirmation = threading.Event()
    backup_entered = threading.Event()
    errors = []
    import_agenda = preview_module.import_external_agenda

    def paused_import(*args):
        result = import_agenda(*args)
        database_written.set()
        assert finish_confirmation.wait(5)
        return result

    def confirm():
        try:
            previews.confirm("a", preview_id, agendas)
        except Exception as error:
            errors.append(error)

    def snapshot():
        with agenda_snapshot_lock(previews.documents.root):
            assert len(agendas.list_items("a")) == 1
            assert previews.get("a", preview_id).status == "confirmed"
            backup_entered.set()

    monkeypatch.setattr(preview_module, "import_external_agenda", paused_import)
    confirmer = threading.Thread(target=confirm)
    reader = threading.Thread(target=snapshot)
    try:
        confirmer.start()
        assert database_written.wait(5)
        reader.start()
        assert not backup_entered.wait(0.1)
        finish_confirmation.set()
        confirmer.join(5)
        reader.join(5)
        assert not confirmer.is_alive() and not reader.is_alive()
        assert not errors and backup_entered.is_set()
    finally:
        finish_confirmation.set()
        confirmer.join(5)
        if reader.ident:
            reader.join(5)
        engine.dispose()
