# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Operator confirmation is the only writer; resume pins the reviewed revision."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.agenda.models import AgendaItem, MeetingAgenda
from civiccast.agenda.store import AgendaStore
from civiccast.agenda_import.config import AgendaImportSettings
from civiccast.agenda_import.documents import DocumentStore
from civiccast.agenda_import.models import ExternalAgenda, ExternalAgendaItem
from civiccast.agenda_import.previews import PreviewStore, agenda_fingerprint
from civiccast.db import Base


@pytest.fixture
def stores(tmp_path):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    agendas = AgendaStore(sessions)
    agendas.upsert_agenda(MeetingAgenda(agenda_id="a", station_id="s", meeting_asset_id="m"))
    yield agendas, PreviewStore(DocumentStore(tmp_path))
    engine.dispose()


class Source:
    last_listing_warning = "Archived list unavailable; upcoming meetings only."

    def fetch_agenda(self, client_code, event_id, *, archive_year=None):
        assert archive_year == 2023
        return ExternalAgenda(
            external_id=event_id,
            title="Council",
            source_doc_url="https://example.org/a.pdf",
            items=[
                ExternalAgendaItem(
                    order=1,
                    number="1",
                    title="CALL TO ORDER",
                    confidence=0.85,
                    doc_url="https://example.org/a.pdf#page=1",
                )
            ],
        )


def ready(stores):
    agendas, previews = stores
    preview = previews.create(
        "a",
        {"source": "primegov", "client_code": "example", "event_id": "42", "archive_year": 2023},
        agenda_fingerprint(agendas, "a"),
    )
    previews.run(
        preview.preview_id, AgendaImportSettings(source="primegov"), lambda *a, **k: Source()
    )
    return previews.get("a", preview.preview_id)


def test_preview_is_read_only_and_confirmation_is_idempotent(stores):
    agendas, previews = stores
    preview = ready(stores)
    assert preview.status == "ready"
    assert len(preview.warnings) == 2
    assert agendas.list_items("a") == []
    assert agendas.get_agenda("a").source_doc_url is None
    written, _ = previews.confirm("a", preview.preview_id, agendas)
    assert [(i.number, i.title, i.doc_anchor) for i in written] == [
        ("1", "CALL TO ORDER", "https://example.org/a.pdf#page=1")
    ]
    assert previews.confirm("a", preview.preview_id, agendas)[0] == []
    assert len(agendas.list_items("a")) == 1


def test_confirmation_refuses_operator_changes_and_partial_results(stores):
    agendas, previews = stores
    preview = ready(stores)
    agendas.upsert_item(
        AgendaItem(item_id="manual", agenda_id="a", order=1, title="Operator title")
    )
    with pytest.raises(ValueError, match="agenda changed"):
        previews.confirm("a", preview.preview_id, agendas)
    assert agendas.list_items("a")[0].title == "Operator title"
    record = previews._load(preview.preview_id)
    record["status"] = "partial"
    previews._save(record)
    with pytest.raises(ValueError, match="Only a complete"):
        previews.confirm("a", preview.preview_id, agendas)


def test_cancelled_queued_read_can_resume_without_writing(stores):
    agendas, previews = stores
    preview = previews.create(
        "a",
        {"source": "primegov", "client_code": "example", "event_id": "42", "archive_year": 2023},
        agenda_fingerprint(agendas, "a"),
    )
    previews.cancel("a", preview.preview_id)
    previews.run(
        preview.preview_id, AgendaImportSettings(source="primegov"), lambda *a, **k: Source()
    )
    assert previews.get("a", preview.preview_id).status == "cancelled"
    assert agendas.list_items("a") == []
    previews.queue_resume("a", preview.preview_id)
    previews.run(
        preview.preview_id, AgendaImportSettings(source="primegov"), lambda *a, **k: Source()
    )
    assert previews.get("a", preview.preview_id).status == "ready"


def test_original_remains_pinned_after_provider_amendment(stores, monkeypatch):
    from civiccast.agenda_import import primegov
    from civiccast.agenda_import.pdf_processing import PdfPageResult, PdfProcessingResult

    agendas, previews = stores
    content = [b"%PDF- original"]
    args = {
        "source": "primegov",
        "client_code": "example",
        "event_id": "42",
        "provider_document_id": "7",
        "url": "https://example.org/a.pdf",
        "download": lambda path: path.write_bytes(content[0]),
    }
    with previews.documents.acquire(**args) as old:
        old.checkpoint_path.write_text("old checkpoint")
    preview = ready(stores)
    record = previews._load(preview.preview_id)
    record.update(document_id=old.document_id, document_sha256=old.metadata["sha256"])
    previews._save(record)
    content[0] = b"%PDF- amended"
    with previews.documents.acquire(**args, refresh=True) as revised:
        assert revised.path != old.path
    assert previews.original_path("a", preview.preview_id).read_bytes() == b"%PDF- original"
    with previews.documents.resume_revision(old.document_id, old.metadata["sha256"]) as resumed:
        assert resumed.checkpoint_path.read_text() == "old checkpoint"
    record.update(status="partial", _meeting={"id": 42, "title": "Council"}, _packet=True)
    previews._save(record)
    processed = []

    def process(path, checkpoint, **kwargs):
        processed.append(path)
        return PdfProcessingResult(
            old.metadata["sha256"],
            1,
            [PdfPageResult(1, "1. CALL TO ORDER\n2. ADJOURN", "pypdf", "complete")],
            "complete",
        )

    monkeypatch.setattr(primegov, "process_pdf", process)
    source = primegov.PrimeGovSource(document_store=previews.documents)
    monkeypatch.setattr(
        source,
        "_find_meeting",
        lambda *a, **k: pytest.fail("Resume must not fetch a newer meeting/document"),
    )
    previews.queue_resume("a", preview.preview_id)
    previews.run(
        preview.preview_id, AgendaImportSettings(source="primegov"), lambda *a, **k: source
    )
    assert processed == [old.path]
    assert previews.get("a", preview.preview_id).status == "ready"
    assert previews.get("a", preview.preview_id).document_sha256 == old.metadata["sha256"]
    old.path.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="changed"):
        previews.confirm("a", preview.preview_id, agendas)
    assert agendas.list_items("a") == []


def test_interrupted_state_recovers_and_other_agenda_cannot_read_it(stores):
    _, previews = stores
    preview = ready(stores)
    record = previews._load(preview.preview_id)
    record["status"] = "reading"
    previews._save(record)
    recovered = previews.get("a", preview.preview_id)
    assert recovered.status == "partial" and recovered.resumable
    with pytest.raises(LookupError):
        previews.get("another", preview.preview_id)
    with pytest.raises(ValueError):
        previews.documents.get_revision("../escape", "0" * 64)
