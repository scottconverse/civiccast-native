# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
from __future__ import annotations

import json
from pathlib import Path

import pytest

from civiccast.agenda_import.agenda_sections import extract_agenda_section
from civiccast.agenda_import.pdf_processing import PdfPageResult


def _page(number: int, text: str) -> PdfPageResult:
    return PdfPageResult(page=number, text=text, method="pypdf", status="complete")


def test_manually_verified_public_packet_all_thirty_items() -> None:
    directory = Path(__file__).parent / "fixtures" / "longmont-3382"
    expected = json.loads((directory / "expected-agenda.json").read_text(encoding="utf-8"))
    pages = [
        _page(number, (directory / f"page-{number}.txt").read_text(encoding="utf-8"))
        for number in range(1, 8)
    ]
    result = extract_agenda_section(
        pages, source_doc_url="https://example.org/packet.pdf", packet=True
    )
    assert result.complete, result.issues
    assert result.agenda_pages == expected["agenda_pages"]
    assert [
        (item.number, item.title, result.item_pages[item.order][0]) for item in result.items
    ] == [tuple(item) for item in expected["items"]]
    assert [item.order for item in result.items] == list(range(1, 31))
    assert all(
        item.doc_url == f"https://example.org/packet.pdf#page={result.item_pages[item.order][0]}"
        for item in result.items
    )


def test_split_labels_wrapped_parent_child_and_page_provenance() -> None:
    result = extract_agenda_section(
        [
            _page(1, "AGENDA\n1.\nCALL TO ORDER\nDescription excluded.\n2.\nPUBLIC HEARINGS AND\n"),
            _page(
                2,
                "GENERAL BUSINESS\nA.\nWater rate\nhearing continuation\nB. Second child\n3. ADJOURN\n1. Attachment",
            ),
        ],
        source_doc_url="https://example.org/p.pdf#old",
        packet=True,
    )
    assert result.complete, result.issues
    assert [(item.number, item.title) for item in result.items] == [
        ("1", "CALL TO ORDER"),
        ("2", "PUBLIC HEARINGS AND GENERAL BUSINESS"),
        ("2.A", "Water rate hearing continuation"),
        ("2.B", "Second child"),
        ("3", "ADJOURN"),
    ]
    assert result.item_pages[2] == [1, 2]
    assert result.items[1].doc_url == "https://example.org/p.pdf#page=1"


def test_standalone_flat_agenda_does_not_require_adjourn() -> None:
    result = extract_agenda_section(
        [_page(1, "1. Public comment\n2. Water rates")],
        source_doc_url="https://example.org/a.pdf",
        packet=False,
    )
    assert result.complete
    assert [item.title for item in result.items] == ["Public comment", "Water rates"]


def test_repeated_date_child_title_is_not_a_footer() -> None:
    result = extract_agenda_section(
        [
            _page(1, "1. CALL TO ORDER\n2. APPROVAL OF MINUTES\nA. January 1, 2026\n3. ADJOURN"),
            _page(2, "MINUTES\nJanuary 1, 2026"),
        ],
        source_doc_url="https://example.org/p.pdf",
        packet=True,
    )
    assert result.complete, result.issues
    assert result.items[2].title == "January 1, 2026"


def test_stop_at_adjourn_before_appendix_and_prior_minutes() -> None:
    result = extract_agenda_section(
        [
            _page(1, "PACKET\n1. CALL TO ORDER\n2. ADJOURN\nAppendix\n1. Misleading attachment"),
            _page(2, "MINUTES\n1. Another meeting\n2. Another item"),
        ],
        source_doc_url="https://example.org/p.pdf",
        packet=True,
    )
    assert result.complete
    assert result.agenda_pages == [1]
    assert len(result.items) == 2


@pytest.mark.parametrize(
    "text",
    [
        "1. CALL TO ORDER\n2. Water rates",
        "1. Unknown opening\n2. ADJOURN",
        "1. CALL TO ORDER\n3. ADJOURN",
        "1. CALL TO ORDER\nA. First\nC. Gap\n2. ADJOURN",
        "1. CALL TO ORDER\nAppendix\n1. Numbered attachment",
        "1. CALL TO ORDER\n2. Mixed case parent\nUnknown continuation\n3. ADJOURN",
    ],
)
def test_missing_boundaries_and_numbering_gaps_refused(text: str) -> None:
    result = extract_agenda_section(
        [_page(1, text)], source_doc_url="https://example.org/p.pdf", packet=True
    )
    assert not result.complete
    assert result.issues
