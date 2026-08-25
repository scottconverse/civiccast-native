# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Mapper contract: idempotency (the sprint's single most important test),
operator-edit survival, and hostile-URL rejection (plan §8/§9/§10)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.agenda.models import MeetingAgenda
from civiccast.agenda.store import AgendaNotFoundError, AgendaStore
from civiccast.agenda_import.mapper import import_external_agenda
from civiccast.agenda_import.models import ExternalAgenda, ExternalAgendaItem
from civiccast.db import Base


@pytest.fixture
def store() -> Iterator[AgendaStore]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    try:
        yield AgendaStore(factory)
    finally:
        engine.dispose()


def _agenda(
    agenda_id: str = "ag-legistar-1",
    *,
    source_doc_url: str | None = None,
    status: str = "draft",
) -> MeetingAgenda:
    return MeetingAgenda(
        agenda_id=agenda_id,
        station_id="civiccast-station",
        meeting_asset_id="meeting-1",
        source_doc_url=source_doc_url,
        status=status,
    )


def _external(
    *, items: list[ExternalAgendaItem] | None = None, source_doc_url=None
) -> ExternalAgenda:
    return ExternalAgenda(
        external_id="5705",
        title="City Council — 2024-01-09",
        meeting_datetime=datetime(2024, 1, 9, tzinfo=UTC),
        source_doc_url=source_doc_url,
        items=items
        if items is not None
        else [
            ExternalAgendaItem(order=1, title="CALL TO ORDER", number="A."),
            ExternalAgendaItem(order=2, title="ROLL CALL", number="B."),
        ],
    )


class TestImportRoundTrip:
    def test_writes_draft_items_with_order_title_number_doc_anchor(
        self, store: AgendaStore
    ) -> None:
        store.upsert_agenda(_agenda())
        external = _external(
            items=[
                ExternalAgendaItem(
                    order=16,
                    title="A RESOLUTION relating to participation",
                    number="1.",
                    doc_url="https://legistar2.granicus.com/seattle/attachments/x.docx",
                )
            ]
        )

        written = import_external_agenda(store, "ag-legistar-1", external)

        assert len(written) == 1
        item = written[0]
        assert item.order == 16
        assert item.number == "1."
        assert item.title == "A RESOLUTION relating to participation"
        assert item.doc_anchor == "https://legistar2.granicus.com/seattle/attachments/x.docx"
        agenda = store.get_agenda("ag-legistar-1")
        assert agenda is not None and agenda.status == "draft"

    def test_fills_agenda_source_doc_url_when_not_already_set(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda(source_doc_url=None))
        external = _external(source_doc_url="https://legistar2.granicus.com/seattle/agenda.pdf")

        import_external_agenda(store, "ag-legistar-1", external)

        agenda = store.get_agenda("ag-legistar-1")
        assert agenda is not None
        assert agenda.source_doc_url == "https://legistar2.granicus.com/seattle/agenda.pdf"

    def test_never_clobbers_an_operator_set_source_doc_url(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda(source_doc_url="https://operator.example/their-own-link.pdf"))
        external = _external(source_doc_url="https://legistar2.granicus.com/seattle/agenda.pdf")

        import_external_agenda(store, "ag-legistar-1", external)

        agenda = store.get_agenda("ag-legistar-1")
        assert agenda is not None
        assert agenda.source_doc_url == "https://operator.example/their-own-link.pdf"

    def test_missing_agenda_raises_not_found(self, store: AgendaStore) -> None:
        with pytest.raises(AgendaNotFoundError):
            import_external_agenda(store, "does-not-exist", _external())


class TestIdempotency:
    """The single most important test in the sprint (plan §8)."""

    def test_reimporting_the_same_event_does_not_duplicate_items(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        external = _external()

        first = import_external_agenda(store, "ag-legistar-1", external)
        second = import_external_agenda(store, "ag-legistar-1", external)

        assert len(first) == 2
        assert second == []  # nothing new to write -- every order already taken
        assert len(store.list_items("ag-legistar-1")) == 2

    def test_reimport_does_not_clobber_an_operator_edited_item(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        import_external_agenda(store, "ag-legistar-1", _external())

        # Operator edits item at order=1 by hand (e.g. renames it, adds a
        # timecode) through the existing agenda editor surface.
        edited = store.get_item("ag-legistar-1-ext-1")
        assert edited is not None
        store.upsert_item(
            edited.model_copy(update={"title": "Operator's own title", "video_timecode_s": 42})
        )

        import_external_agenda(store, "ag-legistar-1", _external())

        survivor = store.get_item("ag-legistar-1-ext-1")
        assert survivor is not None
        assert survivor.title == "Operator's own title"
        assert survivor.video_timecode_s == 42

    def test_reimport_with_a_new_higher_order_item_only_adds_the_new_one(
        self, store: AgendaStore
    ) -> None:
        store.upsert_agenda(_agenda())
        import_external_agenda(store, "ag-legistar-1", _external())

        grown = _external(
            items=[
                ExternalAgendaItem(order=1, title="CALL TO ORDER", number="A."),
                ExternalAgendaItem(order=2, title="ROLL CALL", number="B."),
                ExternalAgendaItem(order=3, title="NEW BUSINESS", number="C."),
            ]
        )
        added = import_external_agenda(store, "ag-legistar-1", grown)

        assert len(added) == 1
        assert added[0].order == 3
        assert len(store.list_items("ag-legistar-1")) == 3


class TestDocAnchorLengthLimit:
    def test_a_doc_url_longer_than_the_storage_limit_is_dropped_not_truncated(
        self, store: AgendaStore
    ) -> None:
        # A signed cloud-storage attachment link legitimately carries an auth
        # token in the query string and can exceed 200 chars. Truncating it
        # produces a dead link with no error; dropping to None is honest.
        long_url = "https://example-storage.test/attachments/agenda.pdf?token=" + "a" * 160
        assert len(long_url) > 200
        store.upsert_agenda(_agenda())
        external = _external(
            items=[ExternalAgendaItem(order=1, title="Long link item", doc_url=long_url)]
        )

        written = import_external_agenda(store, "ag-legistar-1", external)

        assert written[0].doc_anchor is None

    def test_a_doc_url_within_the_storage_limit_is_kept_verbatim(self, store: AgendaStore) -> None:
        short_url = "https://legistar2.granicus.com/seattle/attachments/x.docx"
        store.upsert_agenda(_agenda())
        external = _external(
            items=[ExternalAgendaItem(order=1, title="Short link item", doc_url=short_url)]
        )

        written = import_external_agenda(store, "ag-legistar-1", external)

        assert written[0].doc_anchor == short_url


class TestHostileUrlRejection:
    def test_hostile_item_doc_url_is_rejected_and_nothing_is_written(
        self, store: AgendaStore
    ) -> None:
        store.upsert_agenda(_agenda())
        external = _external(
            items=[
                ExternalAgendaItem(order=1, title="Safe item", number="A."),
                ExternalAgendaItem(
                    order=2,
                    title="Hostile item",
                    number="B.",
                    doc_url="javascript:alert(document.cookie)",
                ),
            ]
        )

        with pytest.raises(ValueError, match="http or https"):
            import_external_agenda(store, "ag-legistar-1", external)

        # Nothing was written -- not even the safe item before the hostile
        # one in iteration order (validate-before-write, plan §10).
        assert store.list_items("ag-legistar-1") == []

    def test_hostile_agenda_level_source_doc_url_is_rejected(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        external = _external(source_doc_url="javascript:alert(1)")

        with pytest.raises(ValueError, match="http or https"):
            import_external_agenda(store, "ag-legistar-1", external)
        assert store.list_items("ag-legistar-1") == []


class TestDraftOnlyGuarantee:
    """AI/agenda non-negotiables Spec §4.2: an external import must never
    leave unreviewed content live on a published agenda. Mirrors
    civiccast.agenda.service.AgendaService.import_from_doc's identical
    reopen-to-draft behavior for the PDF-import path -- applied here to
    EVERY agenda_import vendor (not just js_portal), since the underlying
    principle is "this content did not come from the operator's own typing",
    which is equally true of a Legistar/PrimeGov/CivicClerk fetch."""

    def test_importing_into_a_published_agenda_reopens_it_to_draft(
        self, store: AgendaStore
    ) -> None:
        store.upsert_agenda(_agenda(status="published"))
        external = _external()

        import_external_agenda(store, "ag-legistar-1", external)

        agenda = store.get_agenda("ag-legistar-1")
        assert agenda is not None
        assert agenda.status == "draft"

    def test_a_no_op_reimport_does_not_disturb_a_published_agenda(self, store: AgendaStore) -> None:
        # Every order already taken -> written == [] -> nothing to review ->
        # a published agenda must NOT be reopened for zero new content.
        store.upsert_agenda(_agenda())
        import_external_agenda(store, "ag-legistar-1", _external())
        store.set_status("ag-legistar-1", "published")

        written = import_external_agenda(store, "ag-legistar-1", _external())

        assert written == []
        agenda = store.get_agenda("ag-legistar-1")
        assert agenda is not None
        assert agenda.status == "published"

    def test_importing_into_a_draft_agenda_stays_draft(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda(status="draft"))

        import_external_agenda(store, "ag-legistar-1", _external())

        agenda = store.get_agenda("ag-legistar-1")
        assert agenda is not None
        assert agenda.status == "draft"

    def test_never_sets_status_to_published(self, store: AgendaStore) -> None:
        # Static proof the function contains no path that writes "published"
        # -- the only status literal it can ever pass to store.set_status is
        # "draft" (see mapper.py's own source, not re-derived here).
        import inspect

        import civiccast.agenda_import.mapper as mapper_module

        source = inspect.getsource(mapper_module)
        assert 'set_status(agenda_id, "published")' not in source
        assert 'set_status(agenda_id, "draft")' in source
