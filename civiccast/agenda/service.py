# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S25 meeting-agenda service layer (slice 2).

Sits above :mod:`civiccast.agenda.store` and provides the operations the
router (slice 3) and the player code paths consume:

* :meth:`AgendaService.publish` / :meth:`unpublish` — the publish gate.
  Publishing refuses an empty agenda — DC-1 says a published agenda surfaces
  items + timecodes to viewers, so a zero-item agenda has no public value.
* :meth:`AgendaService.sync_from_chapters` — seeds agenda items from the
  meeting asset's operator-supplied chapter markers (``Asset.chapters_json``).
  The chapter source is injected via ``asset_chapter_provider`` so the
  service stays decoupled from :mod:`civiccast.schedule.store`. Idempotent:
  re-running skips items that already exist at the same ``order`` so
  operator edits survive a re-sync.
* :meth:`AgendaService.import_from_doc` — best-effort plain-text import of
  an operator-uploaded agenda doc. One non-blank line per item, with a
  leading numbering token (``3.a`` / ``VII`` / ``12``) split off into
  :attr:`AgendaItem.number`. PDF parsing is explicitly out of scope for
  slice 2 (the operator can paste extracted text in the meantime).
* :meth:`AgendaService.as_chapter_list` — the read path the player uses:
  returns published-and-timecoded items projected into
  :class:`civiccast.schedule.models.Chapter` shape. Draft agendas project to
  ``[]`` (DC-6 — drafts never reach the public surface).
* :meth:`AgendaService.public_view` — the read path the public endpoint
  uses: returns a :class:`PublicMeetingAgenda` only when the agenda exists
  AND is published; ``None`` otherwise (DC-6 cornerstone).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from civiccast.agenda.models import (
    AgendaItem,
    MeetingAgenda,
    PublicAgendaItem,
    PublicMeetingAgenda,
)
from civiccast.agenda.store import (
    AgendaNotFoundError,
    AgendaPublishEmptyError,
    AgendaStore,
)
from civiccast.schedule.models import Chapter

#: Provider that returns operator-supplied chapter markers for a given
#: meeting asset id. Wired in production to
#: ``PostgresAssetStore.get_staff_row(...).chapters_json`` (decoded). Kept as
#: an injection seam so the service has zero runtime dependency on the
#: schedule store.
AssetChapterProvider = Callable[[str], list[Chapter]]

# Numbering token at the start of an imported line. Examples we accept:
#   "3.a Roll call"          -> number="3.a",  title="Roll call"
#   "3.1 Roll call"          -> number="3.1",  title="Roll call"
#   "12 New business"        -> number="12",   title="New business"
#   "VII Adjourn"            -> number="VII",  title="Adjourn"
# Anything else falls through and the whole line becomes the title.
_NUMBER_PREFIX = re.compile(r"^(?P<number>(?:\d+(?:\.[a-z0-9]+)?)|(?:[IVXLCDM]+))\s+(?P<title>.+)$")

#: Pydantic caps ``AgendaItem.title`` at 400 chars. Long doc lines (paragraph-
#: as-line typos) get clipped so the import doesn't 422 on an otherwise fine
#: paste.
_TITLE_MAX = 400


class AgendaServiceError(RuntimeError):
    """Base error raised by :class:`AgendaService` operations."""


class AgendaPublishError(AgendaServiceError):
    """Publish refused — typically because the agenda has zero items."""


class AgendaImportDecodeError(AgendaServiceError):
    """Raised when the import body cannot be decoded as UTF-8.

    The router translates this to 415 so the operator gets a clean
    diagnostic ("the bytes you uploaded aren't UTF-8"), not a raw 500
    (E-3 / Q-1).
    """


class AgendaService:
    """Publish gating + sync-from-chapters + import + chapter projection."""

    def __init__(
        self,
        store: AgendaStore,
        *,
        asset_chapter_provider: AssetChapterProvider | None = None,
    ) -> None:
        self._store = store
        self._chapter_provider = asset_chapter_provider

    # --- publish gate ---------------------------------------------------

    def publish(self, agenda_id: str) -> MeetingAgenda:
        """Flip the agenda to ``published``. Refuses if it has zero items.

        DC-1 says a published agenda exposes items + timecodes to viewers,
        so a zero-item publish has no public value and is almost certainly
        an operator slip. DC-6 — the public endpoint trusts ``status`` — so
        we fail closed here rather than serve an empty list.

        Atomicity (E-5): the items-exist check + status flip ride a single
        transaction inside :meth:`AgendaStore.publish_if_nonempty`, so a
        concurrent ``delete_item`` between them cannot publish an empty
        agenda. The router never sees a non-atomic race here.
        """
        try:
            return self._store.publish_if_nonempty(agenda_id)
        except AgendaPublishEmptyError as exc:
            raise AgendaPublishError(
                f"Cannot publish agenda {agenda_id!r}: it has zero items. "
                "Add at least one item (DC-1) before publishing."
            ) from exc

    def unpublish(self, agenda_id: str) -> MeetingAgenda:
        """Flip the agenda back to ``draft``. No item-count check."""
        agenda = self._store.get_agenda(agenda_id)
        if agenda is None:
            raise AgendaNotFoundError(f"Meeting agenda {agenda_id!r} not found.")
        return self._store.set_status(agenda_id, "draft")

    # --- sync from chapters --------------------------------------------

    def sync_from_chapters(self, agenda_id: str) -> list[AgendaItem]:
        """Seed items from the meeting asset's ``chapters_json``.

        Each chapter becomes a draft item:
        ``item_id = f"{agenda_id}-ch-{idx}"``, ``order=idx``,
        ``title=Chapter.name``, ``video_timecode_s=int(Chapter.t)``.

        Idempotent: an existing item at the same ``(agenda_id, order)`` is
        SKIPPED — the operator may have edited it, and we don't blast their
        work on a re-sync. Returns ONLY the items the service wrote on this
        call (skipped items are not in the return list).
        """
        if self._chapter_provider is None:
            raise AgendaServiceError(
                "sync_from_chapters requires an asset_chapter_provider; "
                "the service was constructed without one."
            )
        agenda = self._store.get_agenda(agenda_id)
        if agenda is None:
            raise AgendaNotFoundError(f"Meeting agenda {agenda_id!r} not found.")
        existing = self._store.list_items(agenda_id, order_by="order")
        taken_orders = {item.order for item in existing}
        chapters = self._chapter_provider(agenda.meeting_asset_id)
        written: list[AgendaItem] = []
        for idx, chapter in enumerate(chapters):
            if idx in taken_orders:
                continue
            item = AgendaItem(
                item_id=f"{agenda_id}-ch-{idx}",
                agenda_id=agenda_id,
                order=idx,
                title=chapter.name,
                video_timecode_s=int(chapter.t),
            )
            written.append(self._store.upsert_item(item))
        return written

    # --- import from operator-uploaded doc ------------------------------

    def import_from_doc(
        self,
        agenda_id: str,
        *,
        doc_bytes: bytes,
        content_type: str = "text/plain",
    ) -> list[AgendaItem]:
        """Best-effort parse of a plain-text agenda doc.

        Each non-blank line becomes a draft item. A leading numbering token
        (``3.a`` / ``3.1`` / ``12`` / Roman ``VII``) is split off into
        :attr:`AgendaItem.number`. ``video_timecode_s`` stays None — the
        operator scrubs each item to its in-video moment afterwards.

        PDF (and any non-text/plain content type) raises
        :class:`NotImplementedError`. A robust PDF agenda parser is a
        follow-up; in the meantime the operator copy/pastes the agenda's
        text into the import form.

        Idempotent on re-run via the same ``(agenda_id, order)`` skip rule
        :meth:`sync_from_chapters` uses.
        """
        normalized = content_type.split(";", 1)[0].strip().lower()
        if normalized != "text/plain":
            raise NotImplementedError(
                f"import_from_doc: content_type {content_type!r} is not supported "
                "in slice 2. Only 'text/plain' is parsed; PDF / DOCX parsing is a "
                "follow-up. Paste the doc's extracted text in the meantime."
            )
        agenda = self._store.get_agenda(agenda_id)
        if agenda is None:
            raise AgendaNotFoundError(f"Meeting agenda {agenda_id!r} not found.")
        existing = self._store.list_items(agenda_id, order_by="order")
        taken_orders = {item.order for item in existing}

        try:
            text = doc_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            # The router maps this to 415 so the operator sees "your bytes
            # weren't UTF-8" rather than a raw 500 (E-3 / Q-1). The byte
            # position lands in the message so the dev can trace it.
            raise AgendaImportDecodeError(
                f"Body could not be decoded as UTF-8 (invalid byte at position {exc.start})."
            ) from exc
        lines = [line.strip() for line in text.splitlines()]
        lines = [line for line in lines if line]

        written: list[AgendaItem] = []
        for idx, line in enumerate(lines):
            if idx in taken_orders:
                continue
            number, title = _split_number_and_title(line)
            item = AgendaItem(
                item_id=f"{agenda_id}-imp-{idx}",
                agenda_id=agenda_id,
                order=idx,
                number=number,
                title=title[:_TITLE_MAX],
            )
            written.append(self._store.upsert_item(item))
        return written

    # --- read projections ----------------------------------------------

    def as_chapter_list(self, agenda_id: str) -> list[Chapter]:
        """Project the agenda's published-and-timecoded items as Chapters.

        Used by the player's chapter list when an agenda exists for the
        meeting asset. Returns ``[]`` for a draft agenda (DC-6 — drafts
        never surface to viewers) OR for a published agenda whose items
        all lack timecodes (nothing to seek to).
        """
        agenda = self._store.get_agenda(agenda_id)
        if agenda is None or agenda.status != "published":
            return []
        items = self._store.list_items(agenda_id, order_by="timecode")
        chapters: list[Chapter] = []
        for item in items:
            if item.video_timecode_s is None:
                continue
            chapters.append(
                Chapter(
                    t=float(item.video_timecode_s),
                    name=item.title,
                    sub=None,
                )
            )
        return chapters

    def public_view(
        self,
        station_id: str,
        meeting_asset_id: str,
    ) -> PublicMeetingAgenda | None:
        """Return the public projection if and only if a published agenda
        exists for ``(station_id, meeting_asset_id)``. ``None`` otherwise.

        DC-6 cornerstone: draft agendas (and missing agendas) MUST surface
        as 404 on the public endpoint — the router translates this ``None``.
        """
        agenda = self._store.get_agenda_by_asset(station_id, meeting_asset_id)
        if agenda is None or agenda.status != "published":
            return None
        items = self._store.list_items(agenda.agenda_id, order_by="order")
        return PublicMeetingAgenda(
            agenda_id=agenda.agenda_id,
            meeting_asset_id=agenda.meeting_asset_id,
            source_doc_url=agenda.source_doc_url,
            items=[
                PublicAgendaItem(
                    item_id=item.item_id,
                    order=item.order,
                    number=item.number,
                    title=item.title,
                    video_timecode_s=item.video_timecode_s,
                    doc_anchor=item.doc_anchor,
                )
                for item in items
            ],
        )


def _split_number_and_title(line: str) -> tuple[str | None, str]:
    """Split ``"3.a Roll call"`` into ``("3.a", "Roll call")``.

    Returns ``(None, line)`` when the line has no recognizable leading
    numbering token. The regex is intentionally narrow: a stray sentence
    starting with a digit shouldn't get a phantom ``number``.
    """
    match = _NUMBER_PREFIX.match(line)
    if match is None:
        return None, line
    return match.group("number"), match.group("title").strip()


__all__ = [
    "AgendaImportDecodeError",
    "AgendaPublishError",
    "AgendaService",
    "AgendaServiceError",
    "AssetChapterProvider",
]
