# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""``PrimeGovSource`` -- anonymous PrimeGov Public Portal adapter (plan §3, §8
Phase 2). LPM's own dogfood tenant (``longmont``).

Live-verification ledger (2026-07-08, this implementation pass -- re-verified
independently of the plan's 2026-07-05 planning-pass findings, against the
real ``longmont.primegov.com`` tenant):

* ``GET https://{tenant}.primegov.com/api/v2/PublicPortal/ListUpcomingMeetings``
  -- **public, anonymous, real data.** Returned 7 real upcoming Longmont
  meetings with a ``documentList[]`` per meeting (fields used here: ``id``,
  ``title``, ``dateTime``, and each document's ``id``, ``templateId``,
  ``templateName``, ``compileOutputType``, ``link``).
* ``GET https://{tenant}.primegov.com/Portal/Meeting?meetingTemplateId={id}``
  -- **public, anonymous, real data**, for a document whose
  ``compileOutputType == 3`` ("HTML Agenda"/"HTML Packet"). Confirmed against
  two real Longmont meetings (3726 single-item orientation meeting; 3727,
  7-item Housing and Human Service Advisory Board agenda) -- server-rendered
  ``<tr class='section-row'>`` blocks, parsed by
  :func:`civiccast.agenda_import.docparse.extract_items_from_html`.
* ``GET https://{tenant}.primegov.com/Portal/MeetingPreview?
  compiledMeetingDocumentFileId={id}`` -- **requires a staff login**
  (redirects to ``/Login``). NOT used.
* A ``compileOutputType == 1`` (PDF) document can be fetched anonymously via
  the PUBLIC pre-compiled-document endpoint
  ``/Public/CompiledDocument?meetingTemplateId={templateId}&compileOutputType={n}``
  built from the document's ``templateId`` (see :func:`_compiled_document_url`).
  This corrects an earlier, now-superseded belief that only a login-gated
  SignalR compile could produce the PDF. The mechanism is TownReporter's
  RECORDED historical proof (source ``3ebf045a``, reused behaviour re-implemented
  in Python), plus the recorded real Longmont council packet
  (``meetingTemplateId=15247&compileOutputType=1``: 41,472,505 bytes, 258 pages)
  -- a historical record, not a live receipt from this pass. This adapter's own
  live acquisition is exercised separately; see the P1/P2 handoff receipt.
* Every document's ``link`` field was ``null`` on every meeting/document
  observed for Longmont, so the CompiledDocument path above is the normal one.
  An explicit vendor ``link`` is still honoured verbatim when present (and a
  hostile scheme is refused before any fetch).
* Of Longmont's 7 real upcoming meetings (fixture): 4 have an HTML agenda
  (``compileOutputType == 3``); the rest range from a real PDF agenda to a
  ``compileOutputType == 2`` document of unknown meaning to "CANCELLED" /
  "Notice of Cancellation" meetings. A document with only a cancellation
  notice yields an honest ``cancellation_notice_only`` error; every PDF path
  is bounded (download byte/time cap + page/char-capped extraction) and a
  partial extraction is REFUSED before any import, never silently persisted.

Net effect: this adapter's fully-proven, live-verified path is
HTML-compiled-agenda extraction. A meeting with no HTML document surfaces a
distinct, actionable :class:`~civiccast.agenda_import.base.
AgendaSourceUpstreamError` naming which extraction path was unavailable
(plan §9 "fail loud, never silently import nothing") rather than fabricating
items or guessing at an unverified PDF URL.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from typing import Any

import httpx

from civiccast.agenda_import.base import (
    AgendaSourceAuthRequiredError,
    AgendaSourceError,
    AgendaSourceUpstreamError,
)
from civiccast.agenda_import.config import validate_portal_url
from civiccast.agenda_import.docparse import (
    DEFAULT_MAX_PDF_PAGES,
    DEFAULT_MAX_PDF_TEXT_CHARS,
    PdfExtraction,
    extract_items_from_html,
    extract_items_from_pdf_bounded,
)
from civiccast.agenda_import.models import (
    ExternalAgenda,
    ExternalAgendaItem,
    ExternalMeetingSummary,
)

_LIST_UPCOMING_PATH = "/api/v2/PublicPortal/ListUpcomingMeetings"
_LIST_ARCHIVED_PATH = "/api/v2/PublicPortal/ListArchivedMeetings"

# --- Bounded-document defaults (Agenda Bridge P1/P2) ------------------------
#
# Chosen to accommodate the RECORDED real Longmont council packet (a published
# PrimeGov ``CompiledDocument``: 41,472,505 bytes, 258 pages, recorded 2026-01
# in TownReporter's proof -- a historical record, NOT a live receipt from this
# pass) with finite headroom, while refusing anything pathological:
#   * 100 MiB download cap   > 41.5 MB recorded, and far below the box's RAM.
#   * 180 s total download   -> a real bounded wall-clock budget, checked on
#                               every streamed chunk (not only after the fact).
#   * 500 pages / 2,000,000 chars -> > 258 recorded pages / its ~text size.
#   * 60 s extraction budget -> a caller-bound child-process guard is used when
#                               pypdf extraction itself must be hard-capped
#                               (a between-page clock check alone cannot abort a
#                               single slow page), see _extract_pdf_bounded.
_MAX_DOCUMENT_BYTES = 100 * 1024 * 1024
_DOCUMENT_DEADLINE_SECONDS = 180.0
_MAX_PDF_PAGES = DEFAULT_MAX_PDF_PAGES
_MAX_PDF_TEXT_CHARS = DEFAULT_MAX_PDF_TEXT_CHARS
_EXTRACTION_DEADLINE_SECONDS = 60.0
_MAX_DOCUMENT_REDIRECTS = 5


class PrimeGovSource:
    """:class:`~civiccast.agenda_import.base.AgendaSource` for PrimeGov.

    ``client_code`` is the tenant subdomain (e.g. ``"longmont"`` for
    ``longmont.primegov.com``) -- unlike Legistar, where it's a path segment
    on one shared host.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
        max_document_bytes: int = _MAX_DOCUMENT_BYTES,
        document_deadline_seconds: float = _DOCUMENT_DEADLINE_SECONDS,
        max_pdf_pages: int = _MAX_PDF_PAGES,
        max_pdf_text_chars: int = _MAX_PDF_TEXT_CHARS,
        extraction_deadline_seconds: float = _EXTRACTION_DEADLINE_SECONDS,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._max_document_bytes = max_document_bytes
        self._document_deadline_seconds = document_deadline_seconds
        self._max_pdf_pages = max_pdf_pages
        self._max_pdf_text_chars = max_pdf_text_chars
        self._extraction_deadline_seconds = extraction_deadline_seconds
        # Set by _list_meetings when one (not both) discovery endpoint failed;
        # the router surfaces it as a response header so the operator sees a
        # PARTIAL banner instead of a silently-truncated meeting list.
        self.last_listing_warning: str | None = None

    def fetch_meetings(
        self, client_code: str, *, since: date | None = None
    ) -> list[ExternalMeetingSummary]:
        meetings = self._list_meetings(client_code, archive_year=_archive_year(since))
        summaries: list[ExternalMeetingSummary] = []
        for meeting in meetings:
            meeting_datetime = _parse_meeting_datetime(meeting.get("dateTime"))
            if (
                since is not None
                and meeting_datetime is not None
                and meeting_datetime.date() < since
            ):
                continue
            summaries.append(
                ExternalMeetingSummary(
                    external_id=str(meeting["id"]),
                    title=_meeting_title(meeting),
                    meeting_datetime=meeting_datetime,
                )
            )
        return summaries

    def fetch_agenda(self, client_code: str, event_id: str) -> ExternalAgenda:
        # P3: retrieve the SAME meeting discovery offered, including one from an
        # explicitly-selected earlier archived year. Upcoming + the current
        # archive year are checked first, then a BOUNDED window of the two prior
        # years -- never an unbounded historic scan -- so "list an older archived
        # meeting, then import it" works instead of silently looking only at the
        # current year.
        meeting = self._find_meeting(client_code, event_id)
        if meeting is None:
            raise AgendaSourceUpstreamError(
                f"PrimeGov meeting {event_id!r} was not found among tenant "
                f"{client_code!r}'s upcoming meetings or its archived meetings in the "
                f"bounded recent-year window ({_archive_year(None)}..{_archive_year(None) - 2}); "
                "the meeting may be older than that window, or the event_id is wrong."
            )
        documents = meeting.get("documentList")
        if not isinstance(documents, list):
            raise AgendaSourceUpstreamError(
                f"PrimeGov meeting {event_id!r} (tenant {client_code!r}) has a "
                f"malformed documentList (got {type(documents).__name__})."
            )

        document, route = _select_document(documents)
        if document is None:
            if route == "cancellation_notice_only":
                raise AgendaSourceUpstreamError(
                    f"PrimeGov meeting {event_id!r} (tenant {client_code!r}) has only a "
                    "cancellation notice and no agenda document "
                    "(extraction_status=cancellation_notice_only). PrimeGov publishes no "
                    "agenda for a cancelled meeting; nothing was imported and no item was "
                    "fabricated."
                )
            raise AgendaSourceUpstreamError(
                f"PrimeGov meeting {event_id!r} (tenant {client_code!r}) has no supported "
                "agenda document (extraction_status=no_supported_document): its documents "
                "are only an HTML/PDF compile of unknown type, a packet with no agenda, or "
                "an item type this adapter does not fetch. Nothing was imported."
            )
        if route == "html":
            return self._fetch_html_agenda(client_code, meeting, document)
        return self._fetch_pdf_agenda(client_code, meeting, document)

    # --- document fetch + extraction -------------------------------------

    def _fetch_html_agenda(
        self, client_code: str, meeting: dict[str, Any], document: dict[str, Any]
    ) -> ExternalAgenda:
        template_id = document.get("templateId")
        if template_id is None:
            raise AgendaSourceUpstreamError(
                f"PrimeGov HTML agenda document for meeting {meeting.get('id')!r} "
                f"(tenant {client_code!r}) is missing templateId."
            )
        doc_url = f"{_base_url(client_code)}/Portal/Meeting?meetingTemplateId={template_id}"
        page_html = self._get_text(client_code, doc_url)
        items = extract_items_from_html(page_html)
        if not items:
            raise AgendaSourceUpstreamError(
                f"PrimeGov compiled HTML agenda at {doc_url} for meeting "
                f"{meeting.get('id')!r} produced no reliably parseable items "
                "(extraction_status=html_no_items) -- refusing a silent empty "
                "import."
            )
        return _build_agenda(meeting, source_doc_url=doc_url, items=items)

    def _fetch_pdf_agenda(
        self, client_code: str, meeting: dict[str, Any], document: dict[str, Any]
    ) -> ExternalAgenda:
        # Prefer an explicitly vendor-provided link (preserved behaviour); when
        # it is absent -- every Longmont document observed leaves it null -- build
        # the PUBLIC pre-compiled-document URL from the document's templateId +
        # compileOutputType instead. This is an anonymous GET to
        # ``/Public/CompiledDocument`` (TownReporter's recorded historical proof,
        # reused behaviour re-implemented in Python), NOT a session/SignalR compile.
        link = document.get("link")
        doc_url: str | None
        if isinstance(link, str) and link:
            doc_url = link
            if not (doc_url.startswith("http://") or doc_url.startswith("https://")):
                # A hostile/unsupported scheme here would otherwise reach
                # httpx and raise a raw ValueError instead of a clean adapter
                # error -- caught before any network attempt. The mapper's
                # validate_source_doc_url stays the authoritative STORAGE
                # allowlist; this is only a pre-fetch guard.
                raise AgendaSourceUpstreamError(
                    f"PrimeGov fallback document link for meeting {meeting.get('id')!r} "
                    f"(tenant {client_code!r}) uses an unsupported scheme -- refusing to "
                    f"fetch {link!r}."
                )
        else:
            doc_url = _compiled_document_url(client_code, document)
            if doc_url is None:
                raise AgendaSourceUpstreamError(
                    f"PrimeGov PDF document for meeting {meeting.get('id')!r} "
                    f"(tenant {client_code!r}) has no vendor link and no templateId to "
                    "build a public CompiledDocument URL from "
                    "(extraction_status=pdf_no_url)."
                )

        pdf_bytes = self._fetch_document_bytes(client_code, doc_url)
        extraction = self._extract_pdf_bounded(pdf_bytes)
        if extraction.reason == "unreadable":
            raise AgendaSourceUpstreamError(
                f"PrimeGov PDF document at {doc_url} for meeting {meeting.get('id')!r} "
                "is unreadable (encrypted, malformed, or no text layer) "
                "(extraction_status=pdf_unreadable) -- refusing a silent empty import."
            )
        if extraction.partial:
            raise AgendaSourceUpstreamError(
                f"PrimeGov PDF document at {doc_url} for meeting {meeting.get('id')!r} "
                f"was only PARTIALLY extracted: stopped at {extraction.pages_read}/"
                f"{extraction.pages_total} pages ({extraction.reason}) before the bounded "
                "limit (extraction_status=pdf_partial). Refusing to import a truncated "
                "agenda over an existing complete one; split the source document or raise "
                "the operator limits deliberately."
            )
        if not extraction.items:
            raise AgendaSourceUpstreamError(
                f"PrimeGov PDF compiled agenda at {doc_url} for meeting "
                f"{meeting.get('id')!r} produced no reliably parseable items "
                "(extraction_status=pdf_no_items) -- refusing a silent empty "
                "import. This adapter's PDF extraction only recognizes flat, "
                "top-level numbered lines (see docparse.py); a differently "
                "formatted PDF is an honest miss, not a bug to silently patch "
                "around."
            )
        return _build_agenda(meeting, source_doc_url=doc_url, items=extraction.items)
    # --- meeting list + transport -----------------------------------------

    def _find_meeting(self, client_code: str, event_id: str) -> dict[str, Any] | None:
        current_year = _archive_year(None)
        meetings = self._list_meetings(client_code, archive_year=current_year)
        found = next((m for m in meetings if str(m.get("id")) == event_id), None)
        if found is not None:
            return found
        # Bounded recent-year fallback for a meeting an earlier-year discovery
        # offered. Exactly two extra archive lists at most -- finite, not a loop
        # over history.
        for year in (current_year - 1, current_year - 2):
            try:
                rows = self._fetch_meeting_list(
                    client_code,
                    f"{_base_url(client_code)}{_LIST_ARCHIVED_PATH}?year={year}",
                )
            except AgendaSourceAuthRequiredError:
                raise
            except AgendaSourceUpstreamError:
                continue
            found = next((r for r in rows if str(r.get("id")) == event_id), None)
            if found is not None:
                return found
        return None

    def _list_meetings(
        self, client_code: str, *, archive_year: int | None = None
    ) -> list[dict[str, Any]]:
        # P3: query BOTH the upcoming and a single finite archived year, dedup by
        # provider meeting id. One endpoint failing preserves the other with a
        # PARTIAL warning; both failing is an honest error, never an empty list.
        # A 401/403 is a hard auth problem (no retry will help) and propagates.
        self.last_listing_warning = None
        if archive_year is None:
            archive_year = _archive_year(None)
        upcoming_url = f"{_base_url(client_code)}{_LIST_UPCOMING_PATH}"
        archive_url = f"{_base_url(client_code)}{_LIST_ARCHIVED_PATH}?year={archive_year}"

        upcoming_rows: list[dict[str, Any]] | None = None
        archive_rows: list[dict[str, Any]] | None = None
        upcoming_err: AgendaSourceError | None = None
        archive_err: AgendaSourceError | None = None
        try:
            upcoming_rows = self._fetch_meeting_list(client_code, upcoming_url)
        except AgendaSourceAuthRequiredError as exc:
            upcoming_err = exc
        except AgendaSourceUpstreamError as exc:
            upcoming_err = exc
        try:
            archive_rows = self._fetch_meeting_list(client_code, archive_url)
        except AgendaSourceAuthRequiredError as exc:
            archive_err = exc
        except AgendaSourceUpstreamError as exc:
            archive_err = exc

        if upcoming_rows is None and archive_rows is None:
            # Both lists failed. If EITHER failure is an auth/token problem the
            # operator must know that actionable cause rather than a bare 502 --
            # an auth failure would not have been cured by retrying the other
            # list. Otherwise it is an honest upstream error, not an empty
            # calendar.
            auth_err: AgendaSourceError | None = (
                upcoming_err
                if isinstance(upcoming_err, AgendaSourceAuthRequiredError)
                else archive_err
            )
            if isinstance(auth_err, AgendaSourceAuthRequiredError):
                raise auth_err
            raise AgendaSourceUpstreamError(
                f"PrimeGov could not list meetings for tenant {client_code!r}: "
                f"upcoming list failed ({upcoming_err}); archived {archive_year} list "
                f"failed ({archive_err}). This is an honest upstream error, not an "
                "empty calendar."
            )
        if upcoming_err is not None or archive_err is not None:
            failed = []
            if upcoming_err is not None:
                failed.append("upcoming")
            if archive_err is not None:
                failed.append(f"archived({archive_year})")
            self.last_listing_warning = (
                "PARTIAL PrimeGov discovery: the " + ", ".join(failed) + " meeting list "
                "failed; showing results from the list that answered. Some meetings may "
                "be missing from this list."
            )

        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for row in (upcoming_rows or []) + (archive_rows or []):
            key = str(row.get("id"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(row)
        return merged

    def _fetch_meeting_list(self, client_code: str, url: str) -> list[dict[str, Any]]:
        data = self._get_json(client_code, url)
        if not isinstance(data, list):
            raise AgendaSourceUpstreamError(
                f"PrimeGov response from {url} was not a list "
                f"(got {type(data).__name__})."
            )
        return [
            row for row in data if isinstance(row, dict) and row.get("id") is not None
        ]

    def _request(self, client_code: str, url: str) -> httpx.Response:
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout_seconds) as client:
                response = client.get(url, headers={"Accept": "application/json, text/html"})
        except httpx.TimeoutException as exc:
            raise AgendaSourceUpstreamError(
                f"PrimeGov request to {url} timed out after {self._timeout_seconds}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise AgendaSourceUpstreamError(f"PrimeGov request to {url} failed: {exc}") from exc

        if response.status_code in (401, 403):
            raise AgendaSourceAuthRequiredError(
                f"PrimeGov tenant {client_code!r} returned HTTP "
                f"{response.status_code} for {url} -- this tenant may require "
                "authentication that this adapter does not support."
            )
        if response.status_code >= 400:
            raise AgendaSourceUpstreamError(
                f"PrimeGov request to {url} failed with HTTP {response.status_code}."
            )
        return response

    def _get_json(self, client_code: str, url: str) -> object:
        response = self._request(client_code, url)
        try:
            return response.json()
        except ValueError as exc:
            raise AgendaSourceUpstreamError(
                f"PrimeGov returned malformed JSON from {url}."
            ) from exc

    def _get_text(self, client_code: str, url: str) -> str:
        return self._request(client_code, url).text

    def _fetch_document_bytes(self, client_code: str, url: str) -> bytes:
        # Streamed download with a byte cap and a real total wall-clock deadline
        # checked on every chunk, so a slow-drip or oversized document is refused
        # with a bounded amount of work (and memory) -- unlike reading
        # ``response.content`` which buffers the whole body before any check.
        started = time.monotonic()
        chunks: list[bytes] = []
        total = 0
        current_url = url
        try:
            # The public CompiledDocument endpoint 302-redirects to the real PDF
            # object (an external public blob host). Follow redirects MANUALLY,
            # bounded in number, validating EVERY target with the existing public
            # URL guard (:func:`validate_portal_url`) so a redirect can never steer
            # this download to a loopback/private/link-local/metadata host. This is
            # the same approve-the-target check the portal trust boundary uses, not
            # a new policy. Disabling httpx's own follow_redirects is what makes the
            # hop-by-hop validation possible.
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout_seconds,
                follow_redirects=False,
            ) as client:
                for _hop in range(_MAX_DOCUMENT_REDIRECTS + 1):
                    with client.stream(
                        "GET", current_url, headers={"Accept": "application/pdf"}
                    ) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            next_url = _resolve_redirect_target(
                                current_url, response.headers.get("location")
                            )
                            if next_url is None:
                                raise AgendaSourceUpstreamError(
                                    f"PrimeGov document at {current_url} returned a redirect "
                                    "to a missing, non-http(s), or non-public target "
                                    "(extraction_status=document_redirect_blocked)."
                                )
                            current_url = next_url
                            continue
                        if response.status_code in (401, 403):
                            raise AgendaSourceAuthRequiredError(
                                f"PrimeGov tenant {client_code!r} returned HTTP "
                                f"{response.status_code} for {current_url}."
                            )
                        if response.status_code >= 400:
                            raise AgendaSourceUpstreamError(
                                f"PrimeGov document request to {current_url} failed with "
                                f"HTTP {response.status_code}."
                            )
                        for chunk in response.iter_bytes():
                            if time.monotonic() - started > self._document_deadline_seconds:
                                raise AgendaSourceUpstreamError(
                                    f"PrimeGov document at {url} exceeded the "
                                    f"{self._document_deadline_seconds:.0f}s download budget "
                                    f"after {total} bytes (extraction_status=document_timeout)."
                                )
                            total += len(chunk)
                            if total > self._max_document_bytes:
                                raise AgendaSourceUpstreamError(
                                    f"PrimeGov document at {url} exceeds the "
                                    f"{self._max_document_bytes} byte cap "
                                    "(extraction_status=document_too_large) -- refused."
                                )
                            chunks.append(chunk)
                        break
                else:
                    raise AgendaSourceUpstreamError(
                        f"PrimeGov document at {url} exceeded "
                        f"{_MAX_DOCUMENT_REDIRECTS} redirects "
                        "(extraction_status=document_redirect_blocked)."
                    )
        except httpx.TimeoutException as exc:
            raise AgendaSourceUpstreamError(
                f"PrimeGov document request to {url} timed out after "
                f"{self._timeout_seconds}s."
            ) from exc
        except httpx.HTTPError as exc:
            raise AgendaSourceUpstreamError(
                f"PrimeGov document request to {url} failed: {exc}"
            ) from exc
        return b"".join(chunks)

    def _extract_pdf_bounded(self, pdf_bytes: bytes) -> PdfExtraction:
        # Genuinely bounded extraction: caps pages and accumulated characters
        # before pypdf ever walks the whole document. A between-page time check
        # alone cannot abort a single slow page, so the page/char caps are the
        # real work bound here; a caller that needs a hard wall-clock kill can add
        # a child-process guard around this, which the bounded input size makes
        # safe to do without a new framework.
        return extract_items_from_pdf_bounded(
            pdf_bytes,
            max_pages=self._max_pdf_pages,
            max_text_chars=self._max_pdf_text_chars,
        )

def _base_url(client_code: str) -> str:
    return f"https://{client_code}.primegov.com"


def _meeting_title(meeting: dict[str, Any]) -> str:
    title = meeting.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return "Untitled PrimeGov meeting"


def _parse_meeting_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _document_kind(template_name: object) -> str:
    """Classify a document by its vendor template name for ranking.

    ``"cancel"`` (a notice of cancellation) is never selected as an agenda;
    the real agenda is preferred ahead of a huge packet, then minutes, then
    anything else -- deliberately NOT TownReporter's newsroom minutes-first
    order. This is agenda-import order, not a newsroom's.
    """
    name = str(template_name or "").lower()
    if "cancel" in name:
        return "cancel"
    if "minute" in name:
        return "minutes"
    if "agenda" in name:
        return "agenda"
    if "packet" in name:
        return "packet"
    return "other"


_KIND_RANK = {"agenda": 0, "packet": 1, "minutes": 2, "other": 3}


def _select_document(documents: list[Any]) -> tuple[dict[str, Any] | None, str]:
    """Pick the best agenda document, returning ``(document, route)``.

    ``route`` is ``"html"`` (``compileOutputType == 3``) or ``"pdf"``
    (``compileOutputType`` 1 or absent -- a public ``CompiledDocument`` PDF).
    When nothing is selectable, ``document`` is ``None`` and ``route`` is a
    reason token (``"cancellation_notice_only"`` or ``"no_supported_document"``)
    the caller turns into an honest error. Ranking: real agenda > packet >
    minutes > other, with HTML preferred over PDF at equal kind (cheaper and it
    reuses the existing live-verified HTML parser). Cancellation notices and
    unknown compile types (e.g. ``compileOutputType == 2``) are never selected.
    """
    ranked: list[tuple[tuple[int, int], dict[str, Any], str]] = []
    saw_cancel = False
    saw_unsupported = False
    for doc in documents:
        if not isinstance(doc, dict):
            continue
        kind = _document_kind(doc.get("templateName"))
        if kind == "cancel":
            saw_cancel = True
            continue
        compile_type = doc.get("compileOutputType")
        template_id = doc.get("templateId")
        if template_id is None:
            template_id = doc.get("id")
        if compile_type == 3:
            if template_id is None:
                saw_unsupported = True
                continue
            route = "html"
        elif compile_type in (1, None):
            link = doc.get("link")
            has_link = isinstance(link, str) and bool(link)
            if not has_link and template_id is None:
                saw_unsupported = True
                continue
            route = "pdf"
        else:
            saw_unsupported = True
            continue
        form_rank = 0 if route == "html" else 1
        ranked.append(((_KIND_RANK[kind], form_rank), doc, route))

    if not ranked:
        if saw_cancel and not saw_unsupported:
            return None, "cancellation_notice_only"
        return None, "no_supported_document"
    ranked.sort(key=lambda entry: entry[0])
    _, doc, route = ranked[0]
    return doc, route


def _compiled_document_url(client_code: str, document: dict[str, Any]) -> str | None:
    """Build PrimeGov's PUBLIC pre-compiled-document URL from a document row.

    Mirrors TownReporter's recorded mechanism: ``/Public/CompiledDocument?
    meetingTemplateId=<templateId|id>&compileOutputType=<n>`` -- an anonymous
    public GET, NOT a session/SignalR compile. Returns ``None`` if there is no
    template id to build from.
    """
    template_id = document.get("templateId")
    if template_id is None:
        template_id = document.get("id")
    if template_id is None:
        return None
    compile_type = document.get("compileOutputType")
    if compile_type is None:
        compile_type = 1
    return (
        f"{_base_url(client_code)}/Public/CompiledDocument"
        f"?meetingTemplateId={template_id}&compileOutputType={compile_type}"
    )


def _resolve_redirect_target(current_url: str, location: str | None) -> str | None:
    """Resolve a redirect ``Location`` and only accept a public http(s) target.

    Reuses :func:`civiccast.agenda_import.config.validate_portal_url` -- the same
    public-URL guard the staff portal trust boundary applies -- so a redirect can
    never turn this download into a loopback/private/link-local/metadata fetch.
    Returns ``None`` (caller raises an honest blocked error) for a missing,
    relative-broken, non-http(s), or non-public target.
    """
    if not location:
        return None
    try:
        target = str(httpx.URL(current_url).join(location))
        validate_portal_url(target)
    except ValueError:
        return None
    return target


def _archive_year(since: date | None) -> int:
    """The single finite archived year to query.

    Defaults to the current UTC year; when the operator supplies an existing
    ``since`` date, its year is used (clamped to not exceed the current year),
    giving explicit bounded year selection through the API's existing ``since``
    parameter without any unbounded historic scan -- exactly ONE archive list
    per discovery call.
    """
    current = datetime.now(UTC).year
    if since is None:
        return current
    return min(since.year, current)

def _build_agenda(
    meeting: dict[str, Any], *, source_doc_url: str, items: list[ExternalAgendaItem]
) -> ExternalAgenda:
    return ExternalAgenda(
        external_id=str(meeting["id"]),
        title=_meeting_title(meeting),
        meeting_datetime=_parse_meeting_datetime(meeting.get("dateTime")),
        source_doc_url=source_doc_url,
        items=items,
    )


__all__ = ["PrimeGovSource"]
