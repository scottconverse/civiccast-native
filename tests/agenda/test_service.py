# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S25 agenda service (slice 2): publish gate, sync-from-chapters, import,
chapter projection, public read view.

The fixtures mirror ``tests/agenda/test_models_and_store.py`` — sqlite-backed
:class:`AgendaStore`, then a :class:`AgendaService` wrapped around it. The
``asset_chapter_provider`` seam is fed a stub list per test.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.agenda.models import AgendaItem, MeetingAgenda
from civiccast.agenda.service import (
    AgendaPublishError,
    AgendaService,
    AgendaServiceError,
)
from civiccast.agenda.store import AgendaNotFoundError, AgendaStore
from civiccast.db import Base
from civiccast.schedule.models import Chapter

# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AgendaStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'svc.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as sess:
            yield sess

    try:
        yield AgendaStore(factory)
    finally:
        eng.dispose()


def _agenda(
    agenda_id: str = "ag-1",
    *,
    status: str = "draft",
    meeting_asset_id: str = "meeting-jan-2026",
) -> MeetingAgenda:
    return MeetingAgenda(
        agenda_id=agenda_id,
        station_id="civiccast-station",
        meeting_asset_id=meeting_asset_id,
        status=status,  # type: ignore[arg-type]
    )


def _item(
    item_id: str,
    *,
    order: int,
    agenda_id: str = "ag-1",
    title: str = "Item",
    timecode: int | None = None,
) -> AgendaItem:
    return AgendaItem(
        item_id=item_id,
        agenda_id=agenda_id,
        order=order,
        title=title,
        video_timecode_s=timecode,
    )


def _provider(chapters: list[Chapter]) -> Callable[[str], list[Chapter]]:
    return lambda _asset_id: list(chapters)


# --- publish gate -----------------------------------------------------------


class TestPublishGate:
    def test_publish_refuses_zero_item_agenda(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        svc = AgendaService(store)
        with pytest.raises(AgendaPublishError):
            svc.publish("ag-1")
        # And the status stays draft — fail-closed.
        got = store.get_agenda("ag-1")
        assert got is not None
        assert got.status == "draft"

    def test_publish_succeeds_with_at_least_one_item(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        store.upsert_item(_item("it-1", order=0, title="Call to order"))
        svc = AgendaService(store)
        out = svc.publish("ag-1")
        assert out.status == "published"

    def test_publish_unknown_agenda_raises(self, store: AgendaStore) -> None:
        svc = AgendaService(store)
        with pytest.raises(AgendaNotFoundError):
            svc.publish("no-such")

    def test_unpublish_flips_back_to_draft(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda(status="published"))
        svc = AgendaService(store)
        out = svc.unpublish("ag-1")
        assert out.status == "draft"

    def test_unpublish_unknown_agenda_raises(self, store: AgendaStore) -> None:
        svc = AgendaService(store)
        with pytest.raises(AgendaNotFoundError):
            svc.unpublish("no-such")


# --- sync_from_chapters -----------------------------------------------------


class TestSyncFromChapters:
    def test_seeds_items_from_provider(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        chapters = [
            Chapter(t=0.0, name="Call to order"),
            Chapter(t=125.4, name="Roll call"),
            Chapter(t=900.9, name="New business"),
        ]
        svc = AgendaService(store, asset_chapter_provider=_provider(chapters))
        out = svc.sync_from_chapters("ag-1")
        assert [i.title for i in out] == ["Call to order", "Roll call", "New business"]
        assert [i.order for i in out] == [0, 1, 2]
        # Timecodes coerced to int(seconds).
        assert [i.video_timecode_s for i in out] == [0, 125, 900]
        # Item IDs follow the agreed naming.
        assert [i.item_id for i in out] == ["ag-1-ch-0", "ag-1-ch-1", "ag-1-ch-2"]

    def test_preserves_operator_edits_on_resync(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        # Operator already added a custom item at order=1 (renamed it).
        store.upsert_item(
            AgendaItem(
                item_id="custom-1",
                agenda_id="ag-1",
                order=1,
                title="Operator's renamed item",
                video_timecode_s=200,
            )
        )
        chapters = [
            Chapter(t=0.0, name="Call to order"),
            Chapter(t=125.0, name="Roll call (chapter version)"),
            Chapter(t=900.0, name="New business"),
        ]
        svc = AgendaService(store, asset_chapter_provider=_provider(chapters))
        written = svc.sync_from_chapters("ag-1")
        # Only orders 0 + 2 should have been written; order=1 (operator-edited) skipped.
        assert [i.order for i in written] == [0, 2]
        # The operator's custom item survives untouched.
        survivor = store.get_item("custom-1")
        assert survivor is not None
        assert survivor.title == "Operator's renamed item"

    def test_unknown_agenda_raises(self, store: AgendaStore) -> None:
        svc = AgendaService(store, asset_chapter_provider=_provider([]))
        with pytest.raises(AgendaNotFoundError):
            svc.sync_from_chapters("no-such")

    def test_no_provider_raises(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        svc = AgendaService(store)  # no provider
        with pytest.raises(AgendaServiceError):
            svc.sync_from_chapters("ag-1")

    def test_provider_skipping_malformed_chapters_keeps_valid_ones(
        self, store: AgendaStore
    ) -> None:
        """T-3 — the production ``_chapter_provider`` skips malformed
        ``chapters_json`` rows (via ``pydantic.ValidationError`` /
        ``TypeError`` catch in ``app.py``) instead of 500ing the entire
        sync. We mirror that shape here: a provider that filters out the
        bad dicts and only returns valid ``Chapter`` objects. The
        service then seeds only the survivors — the malformed rows
        cannot kill the sync.
        """
        store.upsert_agenda(_agenda())
        raw_chapters: list[dict] = [
            {"t": 0.0, "name": "Call to order"},
            {"t": "not a number", "name": "BAD"},  # would raise ValidationError
            {"t": 300.0, "name": "Adjourn"},
            {"name": "MISSING T"},  # would raise ValidationError
        ]

        def provider(_meeting_asset_id: str) -> list[Chapter]:
            # Mirrors app.py — try each dict, skip bad ones, keep valid.
            from pydantic import ValidationError

            out: list[Chapter] = []
            for raw in raw_chapters:
                try:
                    out.append(Chapter(**raw))
                except (ValidationError, TypeError):
                    continue
            return out

        svc = AgendaService(store, asset_chapter_provider=provider)
        written = svc.sync_from_chapters("ag-1")
        # The two valid chapters land; the two malformed ones are skipped.
        assert len(written) == 2
        assert [i.title for i in written] == ["Call to order", "Adjourn"]
        # And the sync did NOT raise — that's the regression guard.

    def test_resync_is_noop_when_all_orders_taken(self, store: AgendaStore) -> None:
        """T-4 — calling ``sync_from_chapters`` twice in a row must return
        ``[]`` on the second call (every order is already taken), and no
        new items get written. Guards against a regression where the
        skip-by-order rule changes to skip-by-item-id and the second sync
        ends up colliding on the ``(agenda_id, order)`` unique constraint."""
        store.upsert_agenda(_agenda())
        chapters = [
            Chapter(t=0.0, name="Call to order"),
            Chapter(t=120.0, name="Roll call"),
            Chapter(t=300.0, name="New business"),
        ]
        svc = AgendaService(store, asset_chapter_provider=_provider(chapters))
        first = svc.sync_from_chapters("ag-1")
        assert [i.order for i in first] == [0, 1, 2]
        second = svc.sync_from_chapters("ag-1")
        assert second == []
        # All three items survive untouched.
        assert len(store.list_items("ag-1")) == 3


# --- import_from_doc --------------------------------------------------------


class TestImportFromDoc:
    def test_parses_plain_text_with_numbering(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        doc = (
            b"1 Call to order\n"
            b"2.a Roll call\n"
            b"2.b Approval of minutes\n"
            b"3.1 Old business\n"
            b"VII Adjourn\n"
        )
        svc = AgendaService(store)
        out = svc.import_from_doc("ag-1", doc_bytes=doc)
        assert [i.number for i in out] == ["1", "2.a", "2.b", "3.1", "VII"]
        assert [i.title for i in out] == [
            "Call to order",
            "Roll call",
            "Approval of minutes",
            "Old business",
            "Adjourn",
        ]
        # No timecodes — operator scrubs.
        assert all(i.video_timecode_s is None for i in out)
        # Item IDs follow the agreed naming.
        assert [i.item_id for i in out] == [
            "ag-1-imp-0",
            "ag-1-imp-1",
            "ag-1-imp-2",
            "ag-1-imp-3",
            "ag-1-imp-4",
        ]

    def test_line_without_numbering_is_whole_title(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        doc = b"Welcome and announcements\n"
        svc = AgendaService(store)
        out = svc.import_from_doc("ag-1", doc_bytes=doc)
        assert len(out) == 1
        assert out[0].number is None
        assert out[0].title == "Welcome and announcements"

    def test_blank_lines_skipped(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        doc = b"1 One\n\n   \n2 Two\n"
        svc = AgendaService(store)
        out = svc.import_from_doc("ag-1", doc_bytes=doc)
        assert [i.title for i in out] == ["One", "Two"]
        assert [i.order for i in out] == [0, 1]

    def test_long_title_is_truncated(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        long_line = "x" * 1000
        svc = AgendaService(store)
        out = svc.import_from_doc("ag-1", doc_bytes=long_line.encode("utf-8"))
        assert len(out) == 1
        # Truncation lands at the Pydantic max (400 chars), well below the
        # raw line length — proves the import doesn't 422.
        assert len(out[0].title) == 400

    def test_pdf_content_type_raises_not_implemented(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        svc = AgendaService(store)
        with pytest.raises(NotImplementedError) as exc:
            svc.import_from_doc("ag-1", doc_bytes=b"%PDF-1.4...", content_type="application/pdf")
        # Helpful message — mentions PDF + slice 2 scope so the operator/dev
        # isn't left guessing.
        msg = str(exc.value)
        assert "application/pdf" in msg
        assert "text/plain" in msg

    def test_content_type_with_charset_still_accepted(self, store: AgendaStore) -> None:
        # ``text/plain; charset=utf-8`` is the realistic header; the parser
        # should match on the bare media type, not the full string.
        store.upsert_agenda(_agenda())
        svc = AgendaService(store)
        out = svc.import_from_doc(
            "ag-1",
            doc_bytes=b"1 Call to order\n",
            content_type="text/plain; charset=utf-8",
        )
        assert len(out) == 1
        assert out[0].number == "1"

    def test_existing_order_skipped_on_reimport(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        # Operator already curated order=1.
        store.upsert_item(
            AgendaItem(
                item_id="custom-1",
                agenda_id="ag-1",
                order=1,
                title="Operator's curated item",
            )
        )
        doc = b"1 One\n2 Two\n3 Three\n"
        svc = AgendaService(store)
        written = svc.import_from_doc("ag-1", doc_bytes=doc)
        assert [i.order for i in written] == [0, 2]
        survivor = store.get_item("custom-1")
        assert survivor is not None
        assert survivor.title == "Operator's curated item"

    def test_unknown_agenda_raises(self, store: AgendaStore) -> None:
        svc = AgendaService(store)
        with pytest.raises(AgendaNotFoundError):
            svc.import_from_doc("no-such", doc_bytes=b"1 One\n")


# --- as_chapter_list --------------------------------------------------------


class TestAsChapterList:
    def test_draft_agenda_returns_empty(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())
        store.upsert_item(_item("it-1", order=0, timecode=10))
        svc = AgendaService(store)
        assert svc.as_chapter_list("ag-1") == []

    def test_unknown_agenda_returns_empty(self, store: AgendaStore) -> None:
        svc = AgendaService(store)
        assert svc.as_chapter_list("no-such") == []

    def test_published_filters_none_timecodes_and_sorts(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda(status="published"))
        # Insert deliberately out of timecode order, plus one None.
        store.upsert_item(_item("it-a", order=0, title="A", timecode=300))
        store.upsert_item(_item("it-b", order=1, title="B", timecode=None))
        store.upsert_item(_item("it-c", order=2, title="C", timecode=100))
        store.upsert_item(_item("it-d", order=3, title="D", timecode=200))
        svc = AgendaService(store)
        out = svc.as_chapter_list("ag-1")
        # None filtered out; remainder sorted by timecode asc.
        assert [c.t for c in out] == [100.0, 200.0, 300.0]
        assert [c.name for c in out] == ["C", "D", "A"]
        # Chapters carry no sub on this projection.
        assert all(c.sub is None for c in out)

    def test_published_but_all_timecodes_none_returns_empty(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda(status="published"))
        store.upsert_item(_item("it-a", order=0, title="A", timecode=None))
        store.upsert_item(_item("it-b", order=1, title="B", timecode=None))
        svc = AgendaService(store)
        assert svc.as_chapter_list("ag-1") == []


# --- public_view -----------------------------------------------------------


class TestPublicView:
    def test_missing_agenda_returns_none(self, store: AgendaStore) -> None:
        svc = AgendaService(store)
        assert svc.public_view("civiccast-station", "meeting-jan-2026") is None

    def test_draft_agenda_returns_none(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda())  # draft
        store.upsert_item(_item("it-1", order=0))
        svc = AgendaService(store)
        assert svc.public_view("civiccast-station", "meeting-jan-2026") is None

    def test_wrong_station_returns_none(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda(status="published"))
        store.upsert_item(_item("it-1", order=0))
        svc = AgendaService(store)
        assert svc.public_view("other-station", "meeting-jan-2026") is None

    def test_published_returns_public_shape_ordered_by_order(self, store: AgendaStore) -> None:
        store.upsert_agenda(_agenda(status="published"))
        # Insert out of order; expect them returned by ``order`` asc.
        store.upsert_item(_item("it-a", order=2, title="Adjourn", timecode=900))
        store.upsert_item(_item("it-b", order=0, title="Call to order", timecode=0))
        store.upsert_item(_item("it-c", order=1, title="Roll call", timecode=125))
        svc = AgendaService(store)
        pub = svc.public_view("civiccast-station", "meeting-jan-2026")
        assert pub is not None
        assert pub.agenda_id == "ag-1"
        assert pub.meeting_asset_id == "meeting-jan-2026"
        assert [i.order for i in pub.items] == [0, 1, 2]
        assert [i.title for i in pub.items] == ["Call to order", "Roll call", "Adjourn"]

    def test_public_items_omit_notes_and_timestamps(self, store: AgendaStore) -> None:
        # The public projection must NOT carry operator notes or
        # engine-internal timestamps. We assert via the model's serialized
        # key set so a future field addition can't silently leak.
        store.upsert_agenda(_agenda(status="published"))
        store.upsert_item(
            AgendaItem(
                item_id="it-1",
                agenda_id="ag-1",
                order=0,
                title="Call to order",
                notes="Operator-only scratchpad — must not leak.",
                video_timecode_s=0,
            )
        )
        svc = AgendaService(store)
        pub = svc.public_view("civiccast-station", "meeting-jan-2026")
        assert pub is not None
        assert len(pub.items) == 1
        keys = set(pub.items[0].model_dump().keys())
        assert "notes" not in keys
        assert "created_at" not in keys
        assert "updated_at" not in keys
        assert keys == {
            "item_id",
            "order",
            "number",
            "title",
            "video_timecode_s",
            "doc_anchor",
        }


# --- E-5 publish atomicity (TOCTOU race) -----------------------------------


class TestPublishAtomicity:
    """E-5 — the items-exist check and the status flip must ride one
    transaction so a concurrent ``delete_item`` between them cannot
    publish an empty agenda.

    The store's session factory is the single seam; we verify the publish
    path opens exactly ONE session via ``publish_if_nonempty`` (rather
    than three separate sessions like the previous list/check/flip
    sequence).
    """

    def test_publish_uses_atomic_store_method(self, store: AgendaStore) -> None:
        """The service should call the new atomic ``publish_if_nonempty``
        store method, not the old read-then-flip pair."""
        store.upsert_agenda(_agenda())
        store.upsert_item(_item("it-1", order=0))

        calls: list[str] = []

        class _SpyStore:
            def __init__(self, inner: AgendaStore) -> None:
                self._inner = inner

            def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
                attr = getattr(self._inner, name)
                if callable(attr):

                    def _logging(*args, **kw):  # type: ignore[no-untyped-def]
                        calls.append(name)
                        return attr(*args, **kw)

                    return _logging
                return attr

        spy = _SpyStore(store)
        svc = AgendaService(spy)  # type: ignore[arg-type]
        out = svc.publish("ag-1")
        assert out.status == "published"
        # Atomic path: one store call (publish_if_nonempty). NO separate
        # list_items / set_status pair.
        assert calls == ["publish_if_nonempty"]
        assert "list_items" not in calls
        assert "set_status" not in calls

    def test_publish_atomic_under_concurrent_delete(self, store: AgendaStore) -> None:
        """Simulate the race: a chapter delete fires between the check
        and the flip. With the old non-atomic path the publish would
        succeed on a zero-item agenda. With the atomic path the SELECT 1
        + UPDATE ride one transaction; the test exercises the no-items
        leg via a store wrapper that drops the item just before the
        atomic publish runs."""
        store.upsert_agenda(_agenda())
        store.upsert_item(_item("it-1", order=0))

        class _RacyStore:
            """Wraps the real store but deletes the lone item the moment
            ``publish_if_nonempty`` is called — simulating a concurrent
            operator. With the atomic path, the SELECT 1 inside the
            store's session still sees an empty table and raises."""

            def __init__(self, inner: AgendaStore) -> None:
                self._inner = inner

            def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
                return getattr(self._inner, name)

            def publish_if_nonempty(self, agenda_id: str):  # type: ignore[no-untyped-def]
                # The race: the row vanished between the operator clicking
                # "publish" and the transaction starting.
                self._inner.delete_item("it-1")
                return self._inner.publish_if_nonempty(agenda_id)

        racy = _RacyStore(store)
        svc = AgendaService(racy)  # type: ignore[arg-type]
        with pytest.raises(AgendaPublishError):
            svc.publish("ag-1")
        # And the agenda stays draft — the empty-item-table read inside the
        # store's transaction fail-closed.
        got = store.get_agenda("ag-1")
        assert got is not None
        assert got.status == "draft"
