# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Unit tests for the heuristic PDF agenda-line extractor
(``civiccast/agenda/pdf_import.py``), the PDF half of the product-hole fix
for ``AgendaService.import_from_doc``.

Synthetic PDF fixtures only (via ``reportlab``, an existing repo
dependency) -- no live municipal agenda PDF is available to this test
suite, matching the disclosed-limitation convention already established in
``tests/agenda_import/test_docparse.py``.
"""

from __future__ import annotations

from io import BytesIO

from reportlab.pdfgen import canvas

from civiccast.agenda.pdf_import import extract_agenda_lines_from_pdf


def _write_pdf(lines: list[str]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 750
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 20
    pdf.save()
    return buffer.getvalue()


class TestExtractAgendaLinesFromPdf:
    def test_lettered_and_roman_numbering_recognized(self) -> None:
        pdf_bytes = _write_pdf(
            [
                "A. Consent agenda",
                "IV. Old business",
                "3.a Sub-item",
            ]
        )
        items = extract_agenda_lines_from_pdf(pdf_bytes)
        assert [i.number for i in items] == ["A", "IV", "3.a"]
        assert [i.title for i in items] == ["Consent agenda", "Old business", "Sub-item"]
        assert all(i.confidence == 0.95 for i in items)

    def test_page_furniture_is_filtered_out(self) -> None:
        pdf_bytes = _write_pdf(
            [
                "1. Real item",
                "3",
                "Page 3 of 12",
                "page 4",
            ]
        )
        items = extract_agenda_lines_from_pdf(pdf_bytes)
        assert [i.title for i in items] == ["Real item"]

    def test_lowercase_prose_line_is_not_a_heading(self) -> None:
        pdf_bytes = _write_pdf(["this is just a prose sentence with no structure"])
        items = extract_agenda_lines_from_pdf(pdf_bytes)
        assert items == []

    def test_mixed_case_heading_like_line_not_matched_as_heading(self) -> None:
        # Heading detection requires the WHOLE line to be uppercase (str.isupper());
        # a title-case line should fall through to "not recognized", not be
        # misclassified as a heading.
        pdf_bytes = _write_pdf(["Welcome And Announcements"])
        items = extract_agenda_lines_from_pdf(pdf_bytes)
        assert items == []

    def test_order_is_sequential_across_pages(self) -> None:
        # reportlab's Canvas without showPage() writes everything to one
        # page; assert ordering is still 1-based and sequential regardless.
        pdf_bytes = _write_pdf(["1. First", "2. Second", "3. Third"])
        items = extract_agenda_lines_from_pdf(pdf_bytes)
        assert [i.order for i in items] == [1, 2, 3]

    def test_corrupt_bytes_return_empty_list_not_a_crash(self) -> None:
        assert extract_agenda_lines_from_pdf(b"this is not a pdf at all") == []

    def test_empty_pdf_returns_empty_list(self) -> None:
        pdf_bytes = _write_pdf([])
        assert extract_agenda_lines_from_pdf(pdf_bytes) == []

    def test_title_is_truncated_to_max_length(self) -> None:
        long_title = "x" * 1000
        pdf_bytes = _write_pdf([f"1. {long_title}"])
        items = extract_agenda_lines_from_pdf(pdf_bytes)
        assert len(items) == 1
        assert len(items[0].title) == 400
