# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Golden + unit tests for the shared docparse extractors (plan §8 task 4).

``TestExtractItemsFromHtml`` is the golden test: real HTML captured live from
``longmont.primegov.com`` (see fixture files + ``primegov.py``'s docstring
for the verification ledger), asserting the EXACT expected item list.

``TestExtractItemsFromPdf`` proves the PDF path against a **synthetically
generated** PDF (via ``reportlab``, already a repo dependency) -- no live
PrimeGov tenant's PDF-only compiled agenda was fetchable anonymously during
this implementation pass (see ``primegov.py`` docstring), so this is
honestly a unit test of the bounded heuristic, not a live-vendor golden test.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from civiccast.agenda_import import docparse
from civiccast.agenda_import.docparse import extract_items_from_html, extract_items_from_pdf

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_html(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


class TestExtractItemsFromHtml:
    def test_seven_item_longmont_agenda_matches_exactly(self) -> None:
        html = _load_html("primegov_longmont_meeting_3727.html")

        items = extract_items_from_html(html)

        assert [i.order for i in items] == [1, 2, 3, 4, 5, 6, 7]
        assert [i.number for i in items] == ["1.", "2.", "3.", "4.", "5.", "6.", "7."]
        assert items[0].title == "Call to order"
        assert items[1].title == "Public invited to be heard"
        assert items[2].title == "Approve minutes from June 11 , 202 6 - regular meeting"
        assert items[3].title == "Determine 2 Tier System"
        assert items[4].title == (
            "Housing Needs Assessment Update Engagement – Inclusionary Housing Fee-in-Lieu Update"  # noqa: RUF001 -- real vendor text (U+2013 EN DASH), not a lint-worthy typo
        )
        assert items[5].title == "Other Business"
        assert items[6].title == "Adjournment"
        # item.doc_url is intentionally None for HTML-parsed items -- no
        # per-item attachment link is extracted in v1 (plan §5 model: doc_url
        # is optional). Only the agenda-level source_doc_url is populated,
        # by primegov.py, not by this parser.
        assert all(i.doc_url is None for i in items)

    def test_single_item_longmont_agenda(self) -> None:
        html = _load_html("primegov_longmont_meeting_3726.html")

        items = extract_items_from_html(html)

        assert len(items) == 1
        assert items[0].order == 1
        assert items[0].number == "1."
        assert items[0].title == "Board Orientation and Onboarding"

    def test_no_section_rows_returns_empty_list_not_a_fabricated_item(self) -> None:
        # Deliberately corrupted/shape-drifted fixture (plan §9 negative
        # control): the section-row markup PrimeGov ships is entirely absent.
        items = extract_items_from_html("<html><body><p>Nothing to see here.</p></body></html>")

        assert items == []

    def test_attachment_icon_markup_in_the_number_cell_does_not_break_the_number(self) -> None:
        # Real shape (fixture item 3/4/5): an attachment-icon <span> is
        # nested inside the number cell alongside the plain "N." text.
        html = (
            "<tr class='section-row'>"
            "<td class='number-cell-section'>"
            "<span class='attachment-icon-holder'><span class='section-attachment' "
            "title='Has Attachments'></span></span>3."
            "</td>"
            "<td class='section-heading'>"
            "<div class='item-cell section-item-attachments-insert' "
            "data-sectiontemplateid='1' data-meetingid='1' data-hasattachment='1'>"
            "<b>Approve minutes</b>"
            "</div></td></tr>"
        )

        items = extract_items_from_html(html)

        assert len(items) == 1
        assert items[0].number == "3."
        assert items[0].title == "Approve minutes"


def _write_pdf(lines: list[str]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 750
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 20
    pdf.save()
    return buffer.getvalue()


class TestExtractItemsFromPdf:
    def test_flat_numbered_lines_are_extracted_in_order(self) -> None:
        pdf_bytes = _write_pdf(
            [
                "City Council Agenda -- 2026-07-08",
                "1. Call to order",
                "2. Roll call",
                "3. Approval of minutes",
            ]
        )

        items = extract_items_from_pdf(pdf_bytes)

        assert [i.title for i in items] == ["Call to order", "Roll call", "Approval of minutes"]
        assert [i.number for i in items] == ["1", "2", "3"]
        assert [i.order for i in items] == [1, 2, 3]

    def test_no_numbered_lines_returns_empty_list_not_a_fabricated_item(self) -> None:
        # Bounded heuristic (docparse.py "ceiling"): a PDF with no flat
        # top-level numbering (e.g. only prose or lettered sub-items) is an
        # honest miss, never a fabricated single-item agenda.
        pdf_bytes = _write_pdf(["Just some prose.", "a) a lettered sub-item, not recognized"])

        items = extract_items_from_pdf(pdf_bytes)

        assert items == []

    def test_malformed_pdf_bytes_returns_empty_list_not_an_exception(self) -> None:
        items = extract_items_from_pdf(b"not a pdf at all")

        assert items == []

    def test_page_extraction_raising_notimplementederror_returns_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Real-world vendor PDFs can hit pypdf error types beyond
        # (PdfReadError, ValueError) -- e.g. NotImplementedError for an
        # unsupported stream filter. A too-narrow except clause lets that
        # escape uncaught instead of the documented "honest miss" -> [].
        class _RaisingReader:
            def __init__(self, *_args: object, **_kwargs: object) -> None:
                raise NotImplementedError("Unsupported filter /ASCII85Decode")

        monkeypatch.setattr(docparse, "PdfReader", _RaisingReader)

        items = extract_items_from_pdf(b"irrelevant bytes")

        assert items == []
