# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for PrimeGovSource -- fixture-based, zero live network.

The meetings-list fixture and the two HTML-agenda fixtures were captured live
from ``longmont.primegov.com`` (see ``primegov.py``'s docstring for the full
verification ledger). Meeting 3707 in the real fixture ("Callahan House
Advisory Board Meeting") genuinely has no HTML document
(``compileOutputType`` 2 only) -- used here as a real, not synthetic,
negative control for "no HTML agenda available".
"""

from __future__ import annotations

import json
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
from civiccast.agenda_import.primegov import PrimeGovSource

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name: str) -> object:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _load_text(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


_MEETINGS = _load_json("primegov_longmont_upcoming_meetings.json")
_HTML_3727 = _load_text("primegov_longmont_meeting_3727.html")
_HTML_3726 = _load_text("primegov_longmont_meeting_3726.html")


def _handler_for(*, meetings=None, html_by_template_id=None, status_code: int = 200):
    html_by_template_id = html_by_template_id or {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ListUpcomingMeetings"):
            return httpx.Response(status_code, json=meetings if status_code == 200 else None)
        if request.url.path == "/Portal/Meeting":
            template_id = request.url.params.get("meetingTemplateId")
            html = html_by_template_id.get(template_id)
            if html is None:
                return httpx.Response(404, text="not found")
            return httpx.Response(200, text=html)
        return httpx.Response(404, text="unrouted")

    return handler


class TestFetchMeetings:
    def test_maps_longmont_meetings_into_summaries(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(_handler_for(meetings=_MEETINGS)),
        )

        meetings = source.fetch_meetings("longmont")

        assert len(meetings) == 7
        by_id = {m.external_id: m for m in meetings}
        assert by_id["3727"].title == "Housing and Human Service Advisory Board"
        assert by_id["3727"].meeting_datetime is not None
        assert by_id["3727"].meeting_datetime.year == 2026

    def test_since_filters_out_earlier_meetings(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(_handler_for(meetings=_MEETINGS)),
        )

        meetings = source.fetch_meetings("longmont", since=date(2026, 7, 13))

        assert all(m.meeting_datetime.date() >= date(2026, 7, 13) for m in meetings)
        assert "3727" not in {m.external_id for m in meetings}  # 2026-07-09, filtered out

    def test_non_list_response_is_upstream_error(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"not": "a list"})),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="not a list"):
            source.fetch_meetings("longmont")

    def test_malformed_json_raises_upstream_error(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"not json at all {{{")
            ),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="malformed JSON"):
            source.fetch_meetings("longmont")

    def test_timeout_raises_upstream_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))
        with pytest.raises(AgendaSourceUpstreamError, match="timed out"):
            source.fetch_meetings("longmont")

    def test_5xx_raises_upstream_error_not_auth_required(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down")),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="503"):
            source.fetch_meetings("longmont")

    def test_403_raises_auth_required(self) -> None:
        # Defensive, not live-proven (see primegov.py docstring): no real
        # PrimeGov tenant encountered during implementation was gated.
        source = PrimeGovSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(403, text="Forbidden")),
        )
        with pytest.raises(AgendaSourceAuthRequiredError, match="longmont"):
            source.fetch_meetings("longmont")


class TestFetchAgenda:
    def test_maps_a_real_seven_item_longmont_meeting(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(
                _handler_for(meetings=_MEETINGS, html_by_template_id={"16898": _HTML_3727})
            ),
        )

        agenda = source.fetch_agenda("longmont", "3727")

        assert agenda.external_id == "3727"
        assert agenda.title == "Housing and Human Service Advisory Board"
        assert agenda.source_doc_url == (
            "https://longmont.primegov.com/Portal/Meeting?meetingTemplateId=16898"
        )
        assert [i.order for i in agenda.items] == [1, 2, 3, 4, 5, 6, 7]
        assert agenda.items[0].title == "Call to order"

    def test_prefers_html_agenda_over_html_packet_when_packet_is_listed_first(self) -> None:
        # Real documentList order for meeting 3727 already lists "HTML
        # Agenda" (templateId 16898) before "HTML Packet" (16900), so that
        # fixture alone can't distinguish "picks first in list" from "picks
        # by templateName" -- this synthetic meeting deliberately reverses
        # the order to falsify the naive "just take the first HTML doc"
        # reading of the selection logic.
        meetings = [
            {
                "id": 999,
                "title": "Synthetic packet-first meeting",
                "dateTime": "2026-07-08T09:00:00",
                "documentList": [
                    {
                        "id": 1,
                        "templateId": 16900,
                        "templateName": "HTML Packet",
                        "compileOutputType": 3,
                        "link": None,
                    },
                    {
                        "id": 2,
                        "templateId": 16898,
                        "templateName": "HTML Agenda",
                        "compileOutputType": 3,
                        "link": None,
                    },
                ],
            }
        ]
        source = PrimeGovSource(
            transport=httpx.MockTransport(
                _handler_for(
                    meetings=meetings,
                    html_by_template_id={"16898": _HTML_3727, "16900": "<html>packet</html>"},
                )
            ),
        )

        agenda = source.fetch_agenda("longmont", "999")

        assert "meetingTemplateId=16898" in agenda.source_doc_url

    def test_single_item_meeting(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(
                _handler_for(meetings=_MEETINGS, html_by_template_id={"16893": _HTML_3726})
            ),
        )

        agenda = source.fetch_agenda("longmont", "3726")

        assert len(agenda.items) == 1
        assert agenda.items[0].title == "Board Orientation and Onboarding"

    def test_meeting_not_found_raises_upstream_error(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(_handler_for(meetings=_MEETINGS)),
        )

        with pytest.raises(AgendaSourceUpstreamError, match="not found"):
            source.fetch_agenda("longmont", "999999")

    def test_meeting_with_no_html_document_raises_upstream_error(self) -> None:
        # Real fixture: meeting 3707 ("Callahan House Advisory Board
        # Meeting") has only a compileOutputType=2 document -- no HTML, no
        # populated `link`. A genuine PrimeGov limitation, not a synthetic one.
        source = PrimeGovSource(
            transport=httpx.MockTransport(_handler_for(meetings=_MEETINGS)),
        )

        with pytest.raises(AgendaSourceUpstreamError, match="no_supported_document"):
            source.fetch_agenda("longmont", "3707")

    def test_html_document_with_no_extractable_items_raises_upstream_error(self) -> None:
        # Deliberately corrupted fixture (plan §9 negative control): the
        # section-row markup is entirely absent from the "compiled" page.
        source = PrimeGovSource(
            transport=httpx.MockTransport(
                _handler_for(
                    meetings=_MEETINGS,
                    html_by_template_id={"16898": "<html><body>corrupted</body></html>"},
                )
            ),
        )

        with pytest.raises(AgendaSourceUpstreamError, match="html_no_items"):
            source.fetch_agenda("longmont", "3727")

    def test_malformed_document_list_raises_upstream_error(self) -> None:
        meetings = [
            {"id": 1, "title": "x", "dateTime": "2026-07-08T09:00:00", "documentList": "oops"}
        ]
        source = PrimeGovSource(transport=httpx.MockTransport(_handler_for(meetings=meetings)))

        with pytest.raises(AgendaSourceUpstreamError, match="malformed documentList"):
            source.fetch_agenda("longmont", "1")

    def test_fallback_document_with_hostile_link_is_rejected_before_any_fetch(self) -> None:
        # A hostile/unsupported scheme in a vendor-supplied `link` must not
        # reach httpx (which would otherwise raise a raw ValueError) -- it's
        # rejected by the adapter's own pre-fetch guard with a clean,
        # actionable AgendaSourceUpstreamError. The mapper's
        # validate_source_doc_url is still the authoritative allowlist for
        # what gets STORED (plan §10); this is a defense-in-depth guard so a
        # hostile vendor value can't crash the adapter itself.
        meetings = [
            {
                "id": 42,
                "title": "Fallback meeting",
                "dateTime": "2026-07-08T09:00:00",
                "documentList": [
                    {
                        "id": 1,
                        "templateId": 100,
                        "templateName": "Agenda",
                        "compileOutputType": 1,
                        "link": "javascript:alert(1)",
                    }
                ],
            }
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=meetings)
            pytest.fail("adapter must not attempt a network fetch of a hostile-scheme link")

        source = PrimeGovSource(transport=httpx.MockTransport(handler))

        with pytest.raises(AgendaSourceUpstreamError, match="unsupported scheme"):
            source.fetch_agenda("longmont", "42")

    def test_fallback_document_with_a_real_pdf_url_is_fetched_and_parsed(self) -> None:
        # Untested against any real PrimeGov tenant (Longmont's `link` field
        # is always null -- see primegov.py docstring); proves the fallback
        # branch works end-to-end for a hypothetical tenant that DOES
        # populate a fetchable link.
        meetings = [
            {
                "id": 42,
                "title": "Fallback meeting",
                "dateTime": "2026-07-08T09:00:00",
                "documentList": [
                    {
                        "id": 1,
                        "templateId": 100,
                        "templateName": "Agenda",
                        "compileOutputType": 1,
                        "link": "https://example-tenant.primegov.com/agenda.pdf",
                    }
                ],
            }
        ]
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(72, 750, "1. Call to order")
        pdf.drawString(72, 730, "2. Roll call")
        pdf.save()
        pdf_bytes = buffer.getvalue()

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=meetings)
            assert str(request.url) == "https://example-tenant.primegov.com/agenda.pdf"
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))

        agenda = source.fetch_agenda("longmont", "42")

        assert [i.title for i in agenda.items] == ["Call to order", "Roll call"]
        assert agenda.source_doc_url == "https://example-tenant.primegov.com/agenda.pdf"
