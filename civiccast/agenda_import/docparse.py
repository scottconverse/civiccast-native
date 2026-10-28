# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared agenda-document item extraction (plan §5 ``docparse.py``).

Built in Phase 2 for PrimeGov, reused unchanged by Phase 3 (CivicClerk) --
neither adapter is the ONE place that decides what to do with an empty
result; both extractors here just return ``[]`` when nothing reliable is
found, and it's the calling :class:`~civiccast.agenda_import.base.AgendaSource`
adapter's job to treat that as "fail loud" per plan §9/§10.

Two extractors:

* :func:`extract_items_from_html` -- PrimeGov's real, **live-verified**
  compiled-agenda HTML shape (``longmont.primegov.com/Portal/Meeting?
  meetingTemplateId=...``, captured 2026-07-08): a flat sequence of
  ``<tr class='section-row'>`` blocks, each with a ``.number-cell-section``
  order label and a ``.section-heading .item-cell`` title (itself a run of
  ``<b>`` fragments). Regex-based, not a DOM parser -- the repo has no
  HTML-parsing dependency (`bs4`/`lxml` are not declared; stdlib ``re`` +
  ``html.unescape`` is the ladder-rung-3 answer) and this shape is regular
  enough that a non-greedy scan over real captured fixtures round-trips
  exactly (golden test: ``tests/agenda_import/test_docparse.py``).

* :func:`extract_items_from_pdf` -- a bounded, honest PDF-text extractor
  (``pypdf``) for the vendor-family case where a compiled agenda ships only
  as a PDF. **Ceiling, stated up front:** it recognizes flat, top-level
  numbered lines only (``"1. Call to order"``) -- the same numbering
  convention :func:`civiccast.agenda.service._split_number_and_title` already
  accepts for operator-pasted text. Lettered/roman-numeral sub-items,
  multi-line wrapped titles, and scanned-image PDFs (no extractable text
  layer) are NOT recognized; such a PDF yields ``[]``, and the caller must
  treat that as "no reliable items" (an honest miss), never fabricate a
  best-guess item list. Upgrade path if a PDF-heavy tenant needs more:
  layout-aware extraction (column/font-size heuristics) is real, scoped
  future work, not silently bolted on here.

  This extractor was proven against a **synthetically generated** PDF (via
  ``reportlab``, an existing repo dependency) in
  ``tests/agenda_import/test_docparse.py::TestExtractItemsFromPdf`` --
  **no live PrimeGov tenant's PDF-only compiled agenda was fetchable
  anonymously during this implementation pass** (every guessed download URL
  for a ``compileOutputType: 1`` document returned PrimeGov's own
  "Document Not Found" page; the real download path is a client-side
  SignalR compile-then-download flow gated behind an anti-forgery token, not
  a plain GET). See ``primegov.py`` module docstring for the live-verification
  ledger. This is a known, disclosed gap, not a silent one.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from io import BytesIO

from pypdf import PdfReader

from civiccast.agenda_import.models import ExternalAgendaItem

_ITEM_TITLE_MAX = 400

# One ``<tr class='section-row'>`` block: an order label cell followed by a
# title cell. Non-greedy across the whole block so nested markup (an
# attachment-icon <span> in the number cell; multiple <b> runs in the title)
# is captured as raw HTML and cleaned by ``_clean_text`` below, rather than
# needing a full DOM walk.
_SECTION_ROW_RE = re.compile(
    r"class=['\"]section-row['\"]>.*?"
    r"class=['\"]number-cell-section['\"]>(?P<number>.*?)</td>.*?"
    r"class=['\"]section-heading['\"]>.*?"
    r"class=['\"]item-cell[^'\"]*['\"][^>]*>(?P<title>.*?)</div>",
    re.DOTALL,
)

# Bounded PDF heuristic (module docstring "ceiling"): a line that begins with
# a plain integer + separator, mirroring the existing operator-paste
# convention in civiccast/agenda/service.py's _NUMBER_PREFIX -- restricted to
# the digit-only form here (no roman numerals / letter-suffixed sub-items)
# because that's the form actually seen in PrimeGov's HTML output (see
# module docstring); widening it is future work, not assumed here.
_PDF_NUMBERED_LINE_RE = re.compile(r"^\s*(?P<number>\d+)[.)]\s+(?P<title>\S.*)$")


def _clean_text(fragment: str) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    no_tags = re.sub(r"<[^>]+>", " ", fragment)
    unescaped = html.unescape(no_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def extract_items_from_html(compiled_html: str) -> list[ExternalAgendaItem]:
    """Extract ordered items from a PrimeGov compiled-agenda HTML page.

    Order is the item's position in the document (1-based) -- the vendor
    doesn't ship a separate machine-readable sequence field the way Legistar
    does, but the HTML is itself already in display order, so position IS
    the order. The ``number`` label ("1.", "2.") is kept verbatim as
    display metadata, same convention as Legistar's ``EventItemAgendaNumber``.

    Returns ``[]`` if no ``section-row`` blocks are found (corrupted/
    shape-drifted HTML) -- the caller (``PrimeGovSource.fetch_agenda``)
    decides whether that's fatal, per the shared "fail loud, never a silent
    empty import" rule (plan §9/§10).
    """
    items: list[ExternalAgendaItem] = []
    for idx, match in enumerate(_SECTION_ROW_RE.finditer(compiled_html), start=1):
        number = _clean_text(match.group("number")) or None
        title = _clean_text(match.group("title"))
        if not title:
            title = f"Agenda item {idx}"
        items.append(ExternalAgendaItem(order=idx, title=title[:_ITEM_TITLE_MAX], number=number))
    return items


def extract_items_from_pdf(pdf_bytes: bytes) -> list[ExternalAgendaItem]:
    """Extract ordered items from a compiled-agenda PDF's text layer.

    Bounded on purpose -- see the module docstring's "ceiling" note. Returns
    ``[]`` (never raises) on a malformed/unreadable PDF or a PDF with no text
    lines matching the recognized numbering convention; the caller decides
    whether an empty result is fatal.
    """
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception:
        # pypdf raises many undocumented error types beyond PdfReadError/
        # ValueError (NotImplementedError, KeyError, AttributeError, ...) for
        # real-world malformed/unusual vendor PDFs; extraction failure is
        # already an "honest miss" -> [] for every caller, so widening the
        # catch doesn't change behavior, it just makes that contract
        # actually hold instead of leaking a raw crash.
        return []

    items: list[ExternalAgendaItem] = []
    order = 0
    for page_text in pages_text:
        for raw_line in page_text.splitlines():
            match = _PDF_NUMBERED_LINE_RE.match(raw_line)
            if match is None:
                continue
            order += 1
            title = match.group("title").strip()
            if not title:
                continue
            items.append(
                ExternalAgendaItem(
                    order=order, title=title[:_ITEM_TITLE_MAX], number=match.group("number")
                )
            )
    return items


# --- Bounded PDF extraction (Agenda Bridge P2) ------------------------------
#
# ``extract_items_from_pdf`` above reads every page with no ceiling, which is
# fine for a small operator-uploaded agenda but unsafe for a vendor ``Packet``
# that can run to hundreds of pages / tens of MB. ``extract_items_from_pdf_bounded``
# is the finite-work variant the PrimeGov ``CompiledDocument`` path uses: it
# caps how many pages it will touch and how much text it will accumulate, and
# reports honestly whether it finished the WHOLE document or only part of it,
# so a caller can refuse a truncated import rather than silently persist a
# partial agenda (Agenda Bridge P2 "no silent partial replacement"). The
# original ``extract_items_from_pdf`` is left untouched for the providers that
# already relied on its exact behaviour.

#: Defaults chosen to comfortably accommodate the recorded real Longmont
#: 41,472,505-byte / 258-page council packet (a real, published PrimeGov
#: document) with headroom, while staying finite: 500 pages > 258, 2,000,000
#: extracted characters is >4x the recorded packet's selectable text. Overridable
#: per-call so tests (and a future differently-sized tenant) can exercise the
#: bounds cheaply without editing this constant.
DEFAULT_MAX_PDF_PAGES = 500
DEFAULT_MAX_PDF_TEXT_CHARS = 2_000_000


@dataclass(frozen=True)
class PdfExtraction:
    """Outcome of a bounded PDF extraction.

    ``partial`` is ``True`` whenever the extractor did NOT cover the whole
    document: the page cap was hit with more pages remaining, the text budget
    was exhausted, or at least one page raised during text extraction. ``reason``
    names the cause for an operator-facing message: ``"unreadable"``
    (malformed/encrypted PDF, no usable text layer path, or EVERY page failed to
    yield text), ``"page_limit"`` / ``"text_limit"`` (bounded stop),
    ``"page_failed"`` (some -- not all -- pages raised, so the recovered items are
    incomplete and must not be persisted as a complete import), or ``None`` when
    the whole document was read without hitting a bound or losing a page.

    ``pages_failed`` counts pages whose text extraction raised. A non-zero count
    means the result is incomplete even when numbered items were recovered from
    the pages that did read; ``pages_read`` counts only pages that yielded text.
    """

    items: list[ExternalAgendaItem] = field(default_factory=list)
    pages_total: int = 0
    pages_read: int = 0
    pages_failed: int = 0
    partial: bool = False
    reason: str | None = None


def extract_items_from_pdf_bounded(
    pdf_bytes: bytes,
    *,
    max_pages: int = DEFAULT_MAX_PDF_PAGES,
    max_text_chars: int = DEFAULT_MAX_PDF_TEXT_CHARS,
    deadline_seconds: float | None = None,
) -> PdfExtraction:
    """Bounded variant of :func:`extract_items_from_pdf`.

    Never raises for a malformed/unreadable PDF -- returns a ``PdfExtraction``
    with ``reason="unreadable"`` instead, so the caller can distinguish
    "unreadable" from "read fine but no numbered items". Stops after at most
    ``max_pages`` pages or ``max_text_chars`` accumulated characters and marks
    ``partial=True`` when it did not cover the whole document. ``deadline_seconds``,
    when set, additionally stops (``partial=True``, ``reason="time_limit"``) once
    the wall-clock budget is spent *between* page extractions, bounding a
    pathologically slow -- but not infinite -- page.
    """
    import time

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        # An empty-password attempt covers the common "owner-password only"
        # vendor PDF; anything still encrypted afterwards has no anonymous text
        # path and is reported as unreadable, not a silent empty result.
        if reader.is_encrypted and reader.decrypt("") == 0:
            return PdfExtraction(reason="unreadable")
        pages = reader.pages
        pages_total = len(pages)
    except Exception:
        return PdfExtraction(reason="unreadable")

    items: list[ExternalAgendaItem] = []
    order = 0
    text_used = 0
    started = time.monotonic()
    pages_read = 0
    pages_failed = 0
    reason: str | None = None
    for index, page in enumerate(pages):
        if index >= max_pages:
            reason = "page_limit"
            break
        if deadline_seconds is not None and time.monotonic() - started > deadline_seconds:
            reason = "time_limit"
            break
        try:
            page_text = page.extract_text() or ""
        except Exception:
            # A single malformed page must not abort a mostly-readable document,
            # but it MUST be recorded: the items recovered from the other pages
            # are then an incomplete agenda, not a complete one.
            pages_failed += 1
            continue
        # The text budget is checked BEFORE this page's text is parsed or
        # appended, and on EVERY page -- single-page, final-page and intermediate
        # alike. There is deliberately no "another page remains" condition: a
        # document that would exceed the budget is a bounded overrun
        # (``partial=True`` / ``text_limit``) whether the excess is on the first,
        # a middle, or the last page, so an over-limit document can never be
        # reported complete or imported. Exactly-at-limit text is accepted: the
        # cap is an inclusive maximum, so a document totalling exactly
        # ``max_text_chars`` is complete when every page was covered.
        if text_used + len(page_text) > max_text_chars:
            reason = "text_limit"
            break
        pages_read += 1
        text_used += len(page_text)
        for raw_line in page_text.splitlines():
            match = _PDF_NUMBERED_LINE_RE.match(raw_line)
            if match is None:
                continue
            order += 1
            title = match.group("title").strip()
            if not title:
                continue
            items.append(
                ExternalAgendaItem(
                    order=order, title=title[:_ITEM_TITLE_MAX], number=match.group("number")
                )
            )

    if reason is None and pages_failed:
        # Differentiate the two page-failure outcomes the result can express:
        # EVERY page unreadable is the same operator-facing situation as an
        # unreadable document (nothing usable to import), while SOME pages lost
        # is a partial extraction that must be refused rather than persisted.
        reason = "unreadable" if pages_read == 0 and pages_failed == pages_total else "page_failed"

    return PdfExtraction(
        items=items,
        pages_total=pages_total,
        pages_read=pages_read,
        pages_failed=pages_failed,
        partial=reason is not None,
        reason=reason,
    )


__all__ = [
    "DEFAULT_MAX_PDF_PAGES",
    "DEFAULT_MAX_PDF_TEXT_CHARS",
    "PdfExtraction",
    "extract_items_from_html",
    "extract_items_from_pdf",
    "extract_items_from_pdf_bounded",
]
