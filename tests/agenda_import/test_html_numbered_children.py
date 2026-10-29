# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
from __future__ import annotations

import json
import re
from pathlib import Path

from civiccast.agenda_import.docparse import extract_items_from_html

_OLD_FIXTURES = Path(__file__).parent / "fixtures"
_PACKET = _OLD_FIXTURES / "longmont-3382"


def _normalize(text: str) -> str:
    text = " ".join(text.split()).replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def _parent(number: str, title: str) -> str:
    return (
        f"<tr class='section-row'><td class='number-cell-section'>{number}</td>"
        f"<td class='section-heading'><div class='item-cell'>{title}</div></td></tr>"
    )


def _child(number: str, title: str) -> str:
    return (
        f"<tr><td class='number-cell'>{number}</td><td class='item-cell'>"
        f"<div class='agenda-item'><p>{title}</p></div></td></tr>"
    )


def test_actual_saved_html_matches_all_thirty_independent_agenda_items() -> None:
    expected = json.loads((_PACKET / "expected-agenda.json").read_text(encoding="utf-8"))
    items = extract_items_from_html((_PACKET / "agenda-15245.html").read_text(encoding="utf-8"))
    assert [(item.number.rstrip("."), _normalize(item.title)) for item in items] == [
        (number, _normalize(title)) for number, title, _page in expected["items"]
    ]
    assert [item.order for item in items] == list(range(1, 31))
    assert all(item.doc_url is None for item in items)


def test_existing_parent_only_golden_fixture_preserves_numbers_titles_and_order() -> None:
    items = extract_items_from_html(
        (_OLD_FIXTURES / "primegov_longmont_meeting_3727.html").read_text(encoding="utf-8")
    )
    assert [item.number for item in items] == [f"{number}." for number in range(1, 8)]
    assert [item.order for item in items] == list(range(1, 8))
    assert [item.title for item in items] == [
        "Call to order",
        "Public invited to be heard",
        "Approve minutes from June 11 , 202 6 - regular meeting",
        "Determine 2 Tier System",
        "Housing Needs Assessment Update Engagement \u2013 Inclusionary Housing Fee-in-Lieu Update",
        "Other Business",
        "Adjournment",
    ]


def test_child_order_parent_qualification_descriptions_and_post_adjourn_appendix() -> None:
    html = (
        _child("A.", "Orphan must be ignored")
        + _parent("4.", "APPROVAL OF MINUTES")
        + "<tr><td class='item-cell'><div class='agenda-item'>Unnumbered description</div></td></tr>"
        + _child("A.", "December&nbsp;16, 2025 &ndash; Regular Session")
        + _child("B.", "Second child")
        + _parent("5.", "GENERAL BUSINESS")
        + _child("A.", "Restart at A")
        + _parent("6.", "ADJOURN")
        + _parent("", "Appendix of Informational Items")
        + _child("A.", "Must not import attachment")
    )
    items = extract_items_from_html(html)
    assert [item.number for item in items] == ["4.", "4.A", "4.B", "5.", "5.A", "6."]
    assert [item.order for item in items] == list(range(1, 7))
    assert items[1].title == "December 16, 2025 \u2013 Regular Session"
    assert items[-1].title == "ADJOURN"


def test_parent_only_single_fixture_and_no_shape_behavior_preserved() -> None:
    items = extract_items_from_html(
        (_OLD_FIXTURES / "primegov_longmont_meeting_3726.html").read_text(encoding="utf-8")
    )
    assert len(items) == 1
    assert items[0].number == "1."
    assert items[0].title == "Board Orientation and Onboarding"
    assert extract_items_from_html("<p>No supported agenda structure</p>") == []
