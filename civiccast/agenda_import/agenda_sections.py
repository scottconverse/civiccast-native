# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Ordered extraction for numbered agenda headings and lettered child titles.

Supported packet layout: a call-to-order opening, uppercase parent headings,
optional mixed-case descriptions, lettered children, and an adjourn boundary.
This is a structural heuristic for that layout, not a general PDF classifier.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from civiccast.agenda_import.models import ExternalAgendaItem
from civiccast.agenda_import.pdf_processing import PdfPageResult

_PARENT = re.compile(r"^(\d+)[.)]\s*(.*)$")
_CHILD = re.compile(r"^([A-Z])[.)]\s*(.*)$")
_QUALIFIED = re.compile(r"^(\d+)\.([A-Z])(?:[.)])?(?:\s+(.*)|$)")
_OPENING = re.compile(r"^(?:MEETING\s+)?(?:CALLED|CALL)\s+TO\s+ORDER$", re.I)
_CLOSING = re.compile(r"^ADJOURN(?:MENT)?$", re.I)
_DATE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}\b",
    re.I,
)
_FOOTER = re.compile(r"^Page\s+\d+(?:\s+of\s+\d+)?$", re.I)
_ATTACHMENT = re.compile(r"^(?:APPENDIX(?:\s+OF\b.*)?|ATTACHMENTS?|MINUTES)$", re.I)


@dataclass
class AgendaSectionResult:
    items: list[ExternalAgendaItem] = field(default_factory=list)
    agenda_pages: list[int] = field(default_factory=list)
    item_pages: dict[int, list[int]] = field(default_factory=dict)
    complete: bool = False
    issues: list[str] = field(default_factory=list)


@dataclass
class _Heading:
    number: str
    pages: set[int]
    child: bool
    parts: list[str] = field(default_factory=list)
    description: bool = False


def _clean(line: str) -> str:
    line = " ".join(line.split())
    return re.sub(r"\s+([,.;:!?])", r"\1", line)


def _label(line: str) -> tuple[int | None, str | None, str] | None:
    qualified = _QUALIFIED.fullmatch(line)
    if qualified:
        return int(qualified[1]), qualified[2], qualified[3] or ""
    parent = _PARENT.fullmatch(line)
    if parent:
        return int(parent[1]), None, parent[2]
    child = _CHILD.fullmatch(line)
    if child:
        return None, child[1], child[2]
    return None


def extract_agenda_section(
    pages: list[PdfPageResult],
    *,
    source_doc_url: str,
    packet: bool,
) -> AgendaSectionResult:
    """Extract supported headings, refusing uncertain packet/number boundaries.

    ``item_pages`` is keyed by the item's contiguous one-based order. A partial
    result retains recoverable items for preview; callers must require complete
    before importing. Pages after a confirmed adjourn boundary are never parsed.
    """
    result = AgendaSectionResult()
    current: _Heading | None = None
    parent_number = 0
    child_number = 0
    opened = False
    closed = False
    attachment = False
    previous_page = 0
    counts = Counter(_clean(line) for page in pages for line in page.text.splitlines())
    repeated_dates: set[str] = set()
    for page in pages:
        lines = [line for raw in page.text.splitlines() if (line := _clean(raw))]
        for index, line in enumerate(lines):
            if index and _FOOTER.fullmatch(line):
                candidate = lines[index - 1]
                if counts[candidate] > 1 and _DATE.search(candidate):
                    repeated_dates.add(candidate)

    def finish() -> bool:
        nonlocal current, opened, closed
        if current is None:
            return closed
        title = _clean(" ".join(current.parts))
        if not title or len(title) > 400:
            result.issues.append(f"Item {current.number} has an empty or unsupported long title")
        elif "\ufffd" in title:
            result.issues.append(f"Item {current.number} has unreadable glyphs")
        else:
            if packet and not current.child and not title.isupper():
                result.issues.append(
                    f"Item {current.number} has an unsupported packet heading layout"
                )
            if not result.items:
                opened = bool(_OPENING.fullmatch(title))
                if packet and not opened:
                    result.issues.append(
                        "Packet agenda does not begin with a clear call-to-order heading"
                    )
            order = len(result.items) + 1
            provenance = sorted(current.pages)
            result.items.append(
                ExternalAgendaItem(
                    order=order,
                    number=current.number,
                    title=title,
                    doc_url=f"{source_doc_url.split('#', 1)[0]}#page={provenance[0]}",
                )
            )
            result.item_pages[order] = provenance
            if not current.child and _CLOSING.fullmatch(title):
                closed = True
        current = None
        return closed

    for page in pages:
        if closed or attachment:
            break
        if page.page <= previous_page or (previous_page and page.page != previous_page + 1):
            result.issues.append("Agenda page order is missing, duplicate, or nonconsecutive")
        previous_page = page.page
        if page.status not in {"complete", "blank"} or "\ufffd" in page.text:
            result.issues.append(f"Page {page.page} was not read completely")
        for raw in page.text.splitlines():
            line = _clean(raw)
            if not line or _FOOTER.fullmatch(line) or line in repeated_dates:
                continue
            if _ATTACHMENT.fullmatch(line):
                finish()
                attachment = True
                if not closed:
                    result.issues.append("Attachment boundary reached before agenda adjournment")
                break
            marker = _label(line)
            if marker is not None:
                if finish():
                    break
                number, letter, title = marker
                if letter is None:
                    assert number is not None
                    if number != parent_number + 1:
                        result.issues.append(
                            f"Expected parent item {parent_number + 1}; found {number}"
                        )
                    parent_number, child_number = number, 0
                    current = _Heading(str(number), {page.page}, False)
                else:
                    if not parent_number or (number is not None and number != parent_number):
                        result.issues.append("Child item has no matching parent")
                    expected = chr(ord("A") + child_number)
                    if letter != expected:
                        result.issues.append(f"Expected child {expected}; found {letter}")
                    child_number = ord(letter) - ord("A") + 1
                    current = _Heading(f"{parent_number}.{letter}", {page.page}, True)
                if title:
                    current.parts.append(title)
                if page.page not in result.agenda_pages:
                    result.agenda_pages.append(page.page)
            elif current is not None:
                if (
                    current.child
                    or not current.parts
                    or (line.isupper() and not current.description)
                ):
                    current.parts.append(line)
                    current.pages.add(page.page)
                else:
                    current.description = True
            # Close at the title itself, not at the next numbered item/appendix.
            if current is not None and _CLOSING.fullmatch(_clean(" ".join(current.parts))):
                finish()
                break
            if current is not None and page.page not in result.agenda_pages:
                result.agenda_pages.append(page.page)
    finish()
    if packet and not opened:
        result.issues.append("A clear packet agenda opening was not established")
    if packet and not closed:
        result.issues.append("Packet agenda adjourn boundary was not found")
    if not result.items:
        result.issues.append("No supported ordered agenda items were found")
    result.issues = list(dict.fromkeys(result.issues))
    result.complete = bool(result.items) and not result.issues
    return result
