# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Durable operator previews. Processing is read-only; confirmation is the writer."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from uuid import uuid4

from filelock import FileLock, Timeout
from pydantic import BaseModel, ConfigDict, Field

from civiccast.agenda.models import AgendaItem, validate_source_doc_url
from civiccast.agenda.store import AgendaStore
from civiccast.agenda_import.config import AgendaImportSettings
from civiccast.agenda_import.documents import DocumentStore, _write_json, configured_document_store
from civiccast.agenda_import.mapper import import_external_agenda
from civiccast.agenda_import.models import ExternalAgenda, ExternalAgendaItem
from civiccast.agenda_import.pdf_processing import PdfProcessingResult
from civiccast.agenda_import.primegov import PrimeGovSource
from civiccast.agenda_import.registry import build_source


class AgendaImportPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str
    agenda_id: str
    status: Literal["queued", "reading", "ready", "partial", "failed", "cancelled", "confirmed"]
    title: str | None = None
    source_doc_url: str | None = None
    items: list[ExternalAgendaItem] = Field(default_factory=list)
    agenda_pages: list[int] = Field(default_factory=list)
    item_pages: dict[int, list[int]] = Field(default_factory=dict)
    pages_read: int = 0
    pages_total: int | None = None
    warnings: list[str] = Field(default_factory=list)
    resumable: bool = False
    document_id: str | None = None
    document_sha256: str | None = None
    source_document_url: str | None = None
    cancel_requested: bool = False


def agenda_fingerprint(store: AgendaStore, agenda_id: str) -> str:
    agenda = store.get_agenda(agenda_id)
    if agenda is None:
        raise LookupError("Meeting agenda not found.")
    content = {
        "agenda": agenda.model_dump(mode="json"),
        "items": [
            item.model_dump(mode="json") for item in store.list_items(agenda_id, order_by="order")
        ],
    }
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


class PreviewStore:
    def __init__(self, documents: DocumentStore) -> None:
        self.documents = documents
        self.root = documents.root / "previews"

    def _path(self, preview_id: str) -> Path:
        if len(preview_id) != 32 or any(c not in "0123456789abcdef" for c in preview_id):
            raise LookupError("Import preview not found.")
        return self.root / f"{preview_id}.json"

    def _load(self, preview_id: str, agenda_id: str | None = None) -> dict[str, Any]:
        path = self._path(preview_id)
        if not path.is_file():
            raise LookupError("Import preview not found.")
        record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if agenda_id is not None and record["agenda_id"] != agenda_id:
            raise LookupError("Import preview not found for this agenda.")
        return record

    def _save(self, record: dict[str, Any]) -> None:
        _write_json(self._path(record["preview_id"]), record)

    def _public(self, record: dict[str, Any]) -> AgendaImportPreview:
        public = {k: v for k, v in record.items() if not k.startswith("_")}
        public["cancel_requested"] = (
            self._path(record["preview_id"]).with_suffix(".cancel").exists()
        )
        return AgendaImportPreview.model_validate(public)

    def create(self, agenda_id: str, request: dict[str, Any], baseline: str) -> AgendaImportPreview:
        self.root.mkdir(parents=True, exist_ok=True)
        result = AgendaImportPreview(preview_id=uuid4().hex, agenda_id=agenda_id, status="queued")
        record = result.model_dump(mode="json")
        record.update({"_request": request, "_baseline": baseline, "_queued_at": time.time()})
        self._save(record)
        return result

    def get(self, agenda_id: str, preview_id: str) -> AgendaImportPreview:
        record = self._load(preview_id, agenda_id)
        if record["status"] == "reading" or (
            record["status"] == "queued" and time.time() - record.get("_queued_at", 0) > 10
        ):
            # A process exit releases this OS lock. Keep its checkpoints useful
            # after an app restart instead of displaying "reading" forever.
            try:
                with FileLock(str(self._path(preview_id).with_suffix(".lock")), timeout=0):
                    record = self._load(preview_id, agenda_id)
                    if record["status"] in {"queued", "reading"}:
                        record.update(
                            status="partial",
                            resumable=True,
                            warnings=["Reading was interrupted. Resume the retained document."],
                        )
                        self._save(record)
            except Timeout:
                pass
        return self._public(record)

    def queue_resume(self, agenda_id: str, preview_id: str) -> AgendaImportPreview:
        with FileLock(str(self._path(preview_id).with_suffix(".lock")), timeout=0):
            record = self._load(preview_id, agenda_id)
            if record["status"] in {"ready", "confirmed"}:
                raise ValueError("This preview is already complete.")
            self._path(preview_id).with_suffix(".cancel").unlink(missing_ok=True)
            record.update(status="queued", warnings=[], resumable=False, _queued_at=time.time())
            self._save(record)
            return self._public(record)

    def cancel(self, agenda_id: str, preview_id: str) -> AgendaImportPreview:
        record = self._load(preview_id, agenda_id)
        if record["status"] in {"queued", "reading"}:
            self._path(preview_id).with_suffix(".cancel").touch()
        return self._public(record)

    def run(
        self,
        preview_id: str,
        settings: AgendaImportSettings,
        source_builder: Callable[..., Any] | None = None,
    ) -> None:
        """FastAPI runs this bounded sync task after returning the queued response."""
        path = self._path(preview_id)
        try:
            with FileLock(str(path.with_suffix(".lock")), timeout=0):
                record = self._load(preview_id)
                if record["status"] != "queued":
                    return
                try:
                    # Reuse ordinary OS locks, not another job framework. One
                    # document read per station bounds aggregate CPU/memory.
                    with FileLock(str(self.root / "processing.lock"), timeout=0):
                        self._run_locked(record, settings, source_builder or build_source)
                except Timeout:
                    record.update(
                        status="failed",
                        resumable=True,
                        warnings=["Another document is processing. Resume when it finishes."],
                    )
                    self._save(record)
        except Timeout:
            return

    def _run_locked(
        self,
        record: dict[str, Any],
        settings: AgendaImportSettings,
        source_builder: Callable[..., Any],
    ) -> None:
        request = record["_request"]
        cancel_path = self._path(record["preview_id"]).with_suffix(".cancel")
        source: Any = None
        record.update(status="reading", warnings=[], resumable=False)
        self._save(record)

        def progress(result: PdfProcessingResult) -> None:
            record.update(pages_read=result.pages_read, pages_total=result.pages_total)
            capture_source()
            self._save(record)

        def capture_source() -> None:
            if isinstance(source, PrimeGovSource) and source.last_document is not None:
                document = source.last_document
                record.update(
                    document_id=document.document_id,
                    document_sha256=document.metadata["sha256"],
                    source_doc_url=document.metadata["identity"]["url"],
                    source_document_url=f"/api/staff/agenda/{quote(record['agenda_id'], safe='')}/import-previews/{record['preview_id']}/document",
                )
                record["_meeting"] = source.last_meeting
                record["_packet"] = source.last_document_is_packet
                if source.last_meeting is not None:
                    record["title"] = source.last_meeting.get("title")

        try:
            if cancel_path.exists():
                record.update(status="cancelled", resumable=True)
                return
            source = source_builder(
                request["source"],
                timeout_seconds=settings.timeout_seconds,
                token=settings.token,
                portal_url=request.get("portal_url"),
                portal_vendor_hint=request.get("portal_vendor_hint"),
            )
            if isinstance(source, PrimeGovSource):
                source.configure_processing(cancelled=cancel_path.exists, on_checkpoint=progress)
                if record.get("document_id") and record.get("document_sha256"):
                    external = source.resume_retained_agenda(
                        self.documents,
                        record["document_id"],
                        record["document_sha256"],
                        record["_meeting"],
                        packet=record.get("_packet", False),
                    )
                else:
                    external = source.fetch_agenda(
                        request["client_code"],
                        request["event_id"],
                        archive_year=request.get("archive_year"),
                        document_kind=request.get("document_kind", "automatic"),
                    )
                capture_source()
                if source.last_section is not None:
                    record.update(
                        agenda_pages=source.last_section.agenda_pages,
                        item_pages=source.last_section.item_pages,
                    )
            else:
                external = source.fetch_agenda(
                    request["client_code"],
                    request["event_id"],
                    archive_year=request.get("archive_year"),
                )
            if cancel_path.exists():
                record.update(status="cancelled", resumable=True)
                return
            validate_source_doc_url(external.source_doc_url)
            for item in external.items:
                validate_source_doc_url(item.doc_url)
            record.update(
                status="ready",
                title=external.title,
                source_doc_url=external.source_doc_url,
                items=[item.model_dump(mode="json") for item in external.items],
                resumable=False,
            )
            record["_external"] = external.model_dump(mode="json")
            if any(
                item.confidence is not None and item.confidence < 0.9 for item in external.items
            ):
                record["warnings"].append(
                    "Review the extracted titles and source pages before confirming."
                )
            warning = getattr(source, "last_listing_warning", None)
            if isinstance(warning, str) and warning:
                record["warnings"].append(warning)
        except Exception as error:
            capture_source()
            processing = source.last_processing if isinstance(source, PrimeGovSource) else None
            if processing is not None:
                record.update(pages_read=processing.pages_read, pages_total=processing.pages_total)
            record.update(
                status="cancelled"
                if cancel_path.exists()
                else "partial"
                if processing is not None
                else "failed",
                warnings=[str(error)[:2000]],
                resumable=processing is None or not processing.complete,
            )
        finally:
            self._save(record)

    def original_path(self, agenda_id: str, preview_id: str) -> Path:
        record = self._load(preview_id, agenda_id)
        if not record.get("document_id") or not record.get("document_sha256"):
            raise LookupError("No retained original is available yet.")
        return self.documents.get_revision(record["document_id"], record["document_sha256"]).path

    def confirm(
        self, agenda_id: str, preview_id: str, agendas: AgendaStore
    ) -> tuple[list[AgendaItem], dict[str, Any]]:
        with FileLock(str(self._path(preview_id).with_suffix(".lock")), timeout=0):
            record = self._load(preview_id, agenda_id)
            if record["status"] == "confirmed":
                return [], record["_request"]
            if record["status"] != "ready" or "_external" not in record:
                raise ValueError("Only a complete, reviewed preview can be confirmed.")
            if agenda_fingerprint(agendas, agenda_id) != record["_baseline"]:
                raise ValueError(
                    "The agenda changed after this preview. Create a new preview before confirming."
                )
            if record.get("document_id"):
                self.original_path(agenda_id, preview_id)  # verifies original hash before writes
            external = ExternalAgenda.model_validate(record["_external"])
            incoming = {item.order: item for item in external.items}
            for existing in agendas.list_items(agenda_id, order_by="order"):
                proposed = incoming.get(existing.order)
                if proposed is None or (
                    (existing.number or "").strip().rstrip(".)").upper()
                    != (proposed.number or "").strip().rstrip(".)").upper()
                ):
                    raise ValueError(
                        "Existing agenda numbering/order differs from this preview. "
                        "Create a new empty agenda or reconcile existing items manually; "
                        "no items were imported and operator edits were preserved."
                    )
            written = import_external_agenda(agendas, agenda_id, external)
            record["status"] = "confirmed"
            self._save(record)
            return written, record["_request"]


def configured_preview_store() -> PreviewStore:
    return PreviewStore(configured_document_store())
