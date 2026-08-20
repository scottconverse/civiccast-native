# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for CivicClerkSource -- fixture-based, zero live network.

The events-window fixture and the agenda PDF fixture were captured live from
a real, currently-live CivicClerk tenant (``portagemi.api.civicclerk.com`` --
City of Portage, MI) during this implementation pass; see ``civicclerk.py``'s
module docstring for the full verification ledger.

``TestFetchAgenda.test_maps_the_real_portage_city_council_meeting`` is the
golden/prize test: it runs the real captured PDF through Phase 2's
:func:`~civiccast.agenda_import.docparse.extract_items_from_pdf` unchanged --
the first proof of that extractor against a real vendor PDF (Phase 2 could
only prove it against a synthetic ``reportlab`` fixture).
"""

from __future__ import annotations

import json
import re
from datetime import date
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from reportlab.pdfgen import canvas

from civiccast.agenda_import.base import (
    AgendaSourceAuthRequiredError,
    AgendaSourceUpstreamError,
)
from civiccast.agenda_import.civicclerk import CivicClerkSource

_FIXTURES = Path(__file__).parent / "fixtures"
_FILE_ID_RE = re.compile(r"fileId=(\d+)")

_EVENTS = json.loads(
    (_FIXTURES / "civicclerk_portagemi_events_window.json").read_text(encoding="utf-8")
)["value"]
_REAL_AGENDA_PDF = (_FIXTURES / "civicclerk_portagemi_agenda_7187.pdf").read_bytes()


def _write_pdf(lines: list[str]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 750
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 20
    pdf.save()
    return buffer.getvalue()


def _handler_for(*, events=None, pdf_by_file_id=None, html_by_url=None, status_code: int = 200):
    events = events if events is not None else _EVENTS
    pdf_by_file_id = pdf_by_file_id or {}
    html_by_url = html_by_url or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/Events":
            if status_code != 200:
                return httpx.Response(status_code, text="error")
            odata_filter = request.url.params.get("$filter", "")
            id_match = re.match(r"id eq (\d+)", odata_filter)
            if id_match:
                matched = [e for e in events if str(e.get("id")) == id_match.group(1)]
                return httpx.Response(200, json={"value": matched})
            return httpx.Response(200, json={"value": events, "_filter": odata_filter})
        if request.url.path.startswith("/v1/Meetings/GetMeetingFileStream"):
            match = _FILE_ID_RE.search(request.url.path)
            file_id = match.group(1) if match else None
            pdf_bytes = pdf_by_file_id.get(file_id)
            if pdf_bytes is not None:
                return httpx.Response(200, content=pdf_bytes)
            return httpx.Response(404, text="not found")
        if str(request.url) in html_by_url:
            return httpx.Response(200, text=html_by_url[str(request.url)])
        return httpx.Response(404, text="unrouted")

    return handler


class TestFetchMeetings:
    def test_maps_real_portage_events_into_summaries(self) -> None:
        source = CivicClerkSource(transport=httpx.MockTransport(_handler_for()))

        meetings = source.fetch_meetings("portagemi", since=date(2026, 6, 1))

        assert len(meetings) == len(_EVENTS)
        by_id = {m.external_id: m for m in meetings}
        assert by_id["2230"].title == "City Council Meeting"
        assert by_id["2230"].meeting_datetime is not None
        assert by_id["2230"].meeting_datetime.year == 2026

    def test_since_is_forwarded_as_an_odata_filter(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["filter"] = request.url.params.get("$filter", "")
            return httpx.Response(200, json={"value": _EVENTS})

        source = CivicClerkSource(transport=httpx.MockTransport(handler))
        source.fetch_meetings("portagemi", since=date(2026, 6, 15))

        assert "2026-06-15" in captured["filter"]

    def test_unpublished_events_are_excluded(self) -> None:
        events = [
            {
                "id": 1,
                "eventName": "Draft meeting",
                "eventDate": "2026-07-08T00:00:00Z",
                "isPublished": "Draft",
            },
            {
                "id": 2,
                "eventName": "Real meeting",
                "eventDate": "2026-07-08T00:00:00Z",
                "isPublished": "Published",
            },
        ]
        source = CivicClerkSource(transport=httpx.MockTransport(_handler_for(events=events)))

        meetings = source.fetch_meetings("portagemi")

        assert [m.external_id for m in meetings] == ["2"]

    def test_malformed_events_response_raises_upstream_error(self) -> None:
        source = CivicClerkSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=["not", "a", "dict"])),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="malformed"):
            source.fetch_meetings("portagemi")

    def test_malformed_json_raises_upstream_error(self) -> None:
        source = CivicClerkSource(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"not json at all {{{")
            ),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="malformed JSON"):
            source.fetch_meetings("portagemi")

    def test_timeout_raises_upstream_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        source = CivicClerkSource(transport=httpx.MockTransport(handler))
        with pytest.raises(AgendaSourceUpstreamError, match="timed out"):
            source.fetch_meetings("portagemi")

    def test_5xx_raises_upstream_error_not_auth_required(self) -> None:
        source = CivicClerkSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down")),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="503"):
            source.fetch_meetings("portagemi")

    def test_404_unknown_tenant_raises_upstream_error(self) -> None:
        # Real finding (see civicclerk.py docstring): a nonexistent tenant
        # subdomain returns a bare 404, not a connection failure.
        source = CivicClerkSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(404, text="not found")),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="404"):
            source.fetch_meetings("no-such-tenant")

    def test_403_raises_auth_required(self) -> None:
        # Defensive, not live-proven (see civicclerk.py docstring): no real
        # CivicClerk tenant encountered during implementation was gated.
        source = CivicClerkSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(403, text="Forbidden")),
        )
        with pytest.raises(AgendaSourceAuthRequiredError, match="403"):
            source.fetch_meetings("portagemi")


class TestFetchAgenda:
    def test_maps_the_real_portage_city_council_meeting(self) -> None:
        """THE PRIZE: real vendor PDF -> real docparse.extract_items_from_pdf
        output, first live-vendor proof of the Phase 2 PDF extractor."""
        source = CivicClerkSource(
            transport=httpx.MockTransport(_handler_for(pdf_by_file_id={"7187": _REAL_AGENDA_PDF})),
        )

        agenda = source.fetch_agenda("portagemi", "2230")

        assert agenda.external_id == "2230"
        assert agenda.title == "City Council Meeting"
        assert agenda.source_doc_url == (
            "https://portagemi.api.civicclerk.com/v1/Meetings/"
            "GetMeetingFileStream(fileId=7187,plainText=false)"
        )
        # Honest, disclosed extraction: the real agenda nests digit-numbered
        # items under lettered top-level sections (A. Consent Agenda, ...);
        # the bounded extractor flattens every digit-numbered line across
        # the whole document, in document order, exactly as documented.
        assert [i.order for i in agenda.items] == list(range(1, 9))
        assert agenda.items[0].title == "National Day of Summer Learning"
        assert agenda.items[1].title == "Approve the City Council Meeting Minutes of the:"
        assert agenda.items[6].title == "Calendar of Meetings:"
        assert agenda.items[7].title.startswith("Adopt the proposed ordinance amending Chapter 50")
        assert all(i.doc_url is None for i in agenda.items)

    def test_prefers_agenda_over_agenda_packet_and_minutes(self) -> None:
        # Real event 2227 has Agenda(7156) + Agenda Packet(7158) + Minutes(7175).
        pdf_bytes = _write_pdf(["1. Call to order", "2. Roll call"])
        source = CivicClerkSource(
            transport=httpx.MockTransport(_handler_for(pdf_by_file_id={"7156": pdf_bytes})),
        )

        agenda = source.fetch_agenda("portagemi", "2227")

        assert "fileId=7156" in agenda.source_doc_url
        assert [i.title for i in agenda.items] == ["Call to order", "Roll call"]

    def test_event_not_found_raises_upstream_error(self) -> None:
        source = CivicClerkSource(transport=httpx.MockTransport(_handler_for()))
        with pytest.raises(AgendaSourceUpstreamError, match="not found"):
            source.fetch_agenda("portagemi", "9999999")

    def test_event_with_no_published_files_raises_upstream_error(self) -> None:
        # Real fixture: event 2270 ("One Time Event") has zero publishedFiles
        # despite existing -- a genuine CivicClerk limitation, not synthetic.
        source = CivicClerkSource(transport=httpx.MockTransport(_handler_for()))
        with pytest.raises(AgendaSourceUpstreamError, match="no_supported_document"):
            source.fetch_agenda("portagemi", "2270")

    def test_malformed_published_files_raises_upstream_error(self) -> None:
        events = [
            {
                "id": 1,
                "eventName": "x",
                "eventDate": "2026-07-08T00:00:00Z",
                "isPublished": "Published",
                "publishedFiles": "oops",
            }
        ]
        source = CivicClerkSource(transport=httpx.MockTransport(_handler_for(events=events)))
        with pytest.raises(AgendaSourceUpstreamError, match="malformed publishedFiles"):
            source.fetch_agenda("portagemi", "1")

    def test_pdf_with_no_extractable_items_raises_upstream_error(self) -> None:
        events = [
            {
                "id": 1,
                "eventName": "x",
                "eventDate": "2026-07-08T00:00:00Z",
                "isPublished": "Published",
                "publishedFiles": [
                    {"fileId": 42, "type": "Agenda", "sort": 1, "url": "stream/x/y.pdf"}
                ],
            }
        ]
        garbage_pdf = _write_pdf(["Just some prose.", "a) a lettered sub-item, not recognized"])
        source = CivicClerkSource(
            transport=httpx.MockTransport(
                _handler_for(events=events, pdf_by_file_id={"42": garbage_pdf})
            ),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="pdf_no_items"):
            source.fetch_agenda("portagemi", "1")

    def test_html_document_dispatches_to_html_extractor(self) -> None:
        # Untested against any real CivicClerk tenant (every real document
        # observed was PDF -- see civicclerk.py docstring); proves the
        # dispatch-by-extension logic against docparse's real HTML shape.
        html_url = "https://portagemi.api.civicclerk.com/agenda.html"
        events = [
            {
                "id": 1,
                "eventName": "x",
                "eventDate": "2026-07-08T00:00:00Z",
                "isPublished": "Published",
                "publishedFiles": [{"type": "Agenda", "sort": 1, "url": html_url}],
            }
        ]
        html = (
            "<tr class='section-row'>"
            "<td class='number-cell-section'>1.</td>"
            "<td class='section-heading'>"
            "<div class='item-cell'><b>Call to order</b></div></td></tr>"
        )
        source = CivicClerkSource(
            transport=httpx.MockTransport(
                _handler_for(events=events, html_by_url={html_url: html})
            ),
        )

        agenda = source.fetch_agenda("portagemi", "1")

        assert agenda.source_doc_url == html_url
        assert [i.title for i in agenda.items] == ["Call to order"]

    def test_missing_file_id_with_hostile_url_scheme_is_rejected_before_any_fetch(self) -> None:
        # Falsification: a hostile scheme in a vendor-supplied fallback `url`
        # must never reach httpx (Phase 2's scheme-guard pattern, reused).
        events = [
            {
                "id": 1,
                "eventName": "x",
                "eventDate": "2026-07-08T00:00:00Z",
                "isPublished": "Published",
                "publishedFiles": [{"type": "Agenda", "sort": 1, "url": "javascript:alert(1)"}],
            }
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/Events":
                return httpx.Response(200, json={"value": events})
            pytest.fail("adapter must not attempt a network fetch of a hostile-scheme url")

        source = CivicClerkSource(transport=httpx.MockTransport(handler))

        with pytest.raises(AgendaSourceUpstreamError, match="unsupported scheme"):
            source.fetch_agenda("portagemi", "1")

    def test_missing_file_id_with_a_real_absolute_url_fallback_is_fetched(self) -> None:
        # Untested against any real CivicClerk tenant (every real `url` seen
        # is an internal relative storage key -- see module docstring);
        # proves the fallback branch end-to-end for a hypothetical tenant
        # that does populate a fetchable absolute url.
        fallback_url = "https://example-tenant.example.com/agenda.pdf"
        events = [
            {
                "id": 1,
                "eventName": "x",
                "eventDate": "2026-07-08T00:00:00Z",
                "isPublished": "Published",
                "publishedFiles": [{"type": "Agenda", "sort": 1, "url": fallback_url}],
            }
        ]
        pdf_bytes = _write_pdf(["1. Call to order"])

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/Events":
                return httpx.Response(200, json={"value": events})
            assert str(request.url) == fallback_url
            return httpx.Response(200, content=pdf_bytes)

        source = CivicClerkSource(transport=httpx.MockTransport(handler))

        agenda = source.fetch_agenda("portagemi", "1")

        assert agenda.source_doc_url == fallback_url
        assert [i.title for i in agenda.items] == ["Call to order"]
