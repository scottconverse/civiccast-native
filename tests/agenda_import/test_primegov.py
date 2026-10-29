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
import time
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
from civiccast.agenda_import.docparse import PdfExtraction
from civiccast.agenda_import.models import ExternalAgendaItem
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
            if request.url.path.endswith("/ListArchivedMeetings"):
                # P3 adds an archived-list call; fail it so only the upcoming
                # list answers, then assert the hostile link is never fetched.
                return httpx.Response(404, text="no archive")
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
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(404, text="no archive")
            assert str(request.url) == "https://example-tenant.primegov.com/agenda.pdf"
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))

        agenda = source.fetch_agenda("longmont", "42")

        assert [i.title for i in agenda.items] == ["Call to order", "Roll call"]
        assert agenda.source_doc_url == "https://example-tenant.primegov.com/agenda.pdf"


def _agenda_pdf(lines: list[str]) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 750
    for line in lines:
        pdf.drawString(72, y, line)
        y -= 20
    pdf.save()
    return buffer.getvalue()


def _single_meeting(documents: list[dict]) -> list[dict]:
    return [
        {
            "id": 777,
            "title": "PDF-only meeting",
            "dateTime": "2026-07-08T09:00:00",
            "documentList": documents,
        }
    ]


class TestCompiledDocumentPdf:
    """P1: a PDF document with a null vendor link is fetched from PrimeGov's
    PUBLIC pre-compiled-document endpoint built from templateId + compileOutputType."""

    def test_retained_pipeline_reuses_original_and_recovers_items(self, tmp_path) -> None:
        from civiccast.agenda_import.documents import DocumentStore

        documents = [{"id": 1, "templateId": 555, "templateName": "Agenda", "compileOutputType": 1}]
        calls = []

        def handler(request):
            if "List" in request.url.path:
                return httpx.Response(200, json=_single_meeting(documents))
            calls.append(str(request.url))
            return httpx.Response(200, content=_agenda_pdf(["1. Call to order", "2. Roll call"]))

        source = PrimeGovSource(
            transport=httpx.MockTransport(handler), document_store=DocumentStore(tmp_path)
        )
        first = source.fetch_agenda("example", "777")
        second = source.fetch_agenda("example", "777")
        assert [item.title for item in first.items] == ["Call to order", "Roll call"]
        assert first == second
        assert len(calls) == 1
        assert source.last_processing.complete
        assert source.last_document.metadata["identity"]["event_id"] == "777"
        assert source.last_document.path.exists()
        assert source.last_document.checkpoint_path.exists()

    def test_pdf_agenda_with_null_link_builds_public_compiled_document_url(self) -> None:
        pdf_bytes = _agenda_pdf(["1. Call to order", "2. Roll call"])
        requested: list[tuple[str | None, str | None]] = []
        meetings = _single_meeting(
            [
                {
                    "id": 1,
                    "templateId": 555,
                    "templateName": "Agenda",
                    "compileOutputType": 1,
                    "link": None,
                }
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=meetings)
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(404, text="no archive")
            assert request.url.path == "/Public/CompiledDocument"
            requested.append(
                (
                    request.url.params.get("meetingTemplateId"),
                    request.url.params.get("compileOutputType"),
                )
            )
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))
        agenda = source.fetch_agenda("longmont", "777")

        assert agenda.source_doc_url == (
            "https://longmont.primegov.com/Public/CompiledDocument"
            "?meetingTemplateId=555&compileOutputType=1"
        )
        assert [i.title for i in agenda.items] == ["Call to order", "Roll call"]
        assert requested == [("555", "1")]

    def test_agenda_document_preferred_over_packet_for_pdfs(self) -> None:
        pdf_bytes = _agenda_pdf(["1. Call to order"])
        requested: list[str | None] = []
        meetings = _single_meeting(
            [
                {
                    "id": 1,
                    "templateId": 900,
                    "templateName": "Packet",
                    "compileOutputType": 1,
                    "link": None,
                },
                {
                    "id": 2,
                    "templateId": 800,
                    "templateName": "Agenda",
                    "compileOutputType": 1,
                    "link": None,
                },
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=meetings)
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(404, text="x")
            requested.append(request.url.params.get("meetingTemplateId"))
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))
        agenda = source.fetch_agenda("longmont", "777")

        assert requested == ["800"]
        assert "meetingTemplateId=800" in agenda.source_doc_url

    def test_cancellation_notice_only_is_honest_error(self) -> None:
        # Real fixture meeting 3695 has only a Notice of Cancellation document.
        source = PrimeGovSource(transport=httpx.MockTransport(_handler_for(meetings=_MEETINGS)))
        with pytest.raises(AgendaSourceUpstreamError, match="cancellation_notice_only"):
            source.fetch_agenda("longmont", "3695")


class TestBoundedPdfHandling:
    """P2: streaming byte/time caps + bounded extraction, distinguished and
    refused before any import persistence."""

    def _handler(self, meetings: list[dict], body: bytes):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=meetings)
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(404, text="x")
            return httpx.Response(200, content=body)

        return handler

    def _meeting(self) -> list[dict]:
        return _single_meeting(
            [
                {
                    "id": 1,
                    "templateId": 555,
                    "templateName": "Agenda",
                    "compileOutputType": 1,
                    "link": None,
                }
            ]
        )

    def test_oversized_document_is_refused(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(self._handler(self._meeting(), b"%PDF-1.7" + b"0" * 500)),
            max_document_bytes=100,
        )
        with pytest.raises(AgendaSourceUpstreamError, match="document_too_large"):
            source.fetch_agenda("longmont", "777")

    def test_partial_extraction_is_refused_before_import(self) -> None:
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer)
        for index in range(5):
            pdf.drawString(72, 750, f"{index + 1}. Item {index + 1}")
            pdf.showPage()
        pdf.save()

        source = PrimeGovSource(
            transport=httpx.MockTransport(self._handler(self._meeting(), buffer.getvalue())),
            max_pdf_pages=2,
        )
        with pytest.raises(AgendaSourceUpstreamError, match="pdf_partial"):
            source.fetch_agenda("longmont", "777")

    def test_single_page_text_overrun_is_refused_not_imported(self) -> None:
        # PR277 review: the character budget must bite on a single-page document
        # too. Real subprocess extraction path, real PDF, tiny budget.
        pdf_bytes = _agenda_pdf(["1. Call to order", "2. Roll call"])

        source = PrimeGovSource(
            transport=httpx.MockTransport(self._handler(self._meeting(), pdf_bytes)),
            max_pdf_text_chars=5,
        )

        with pytest.raises(AgendaSourceUpstreamError, match="pdf_partial"):
            source.fetch_agenda("longmont", "777")

    def test_failed_page_extraction_is_refused_before_import(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # PR277 review: a page that raises while other pages yield numbered items
        # must still refuse persistence -- the recovered items are incomplete.
        # Seam-level (the subprocess child is not reachable from a monkeypatch);
        # the refusal path itself is the real `_fetch_pdf_agenda` branch, and is
        # the only thing standing between a partial extraction and the mapper.
        source = PrimeGovSource(
            transport=httpx.MockTransport(
                self._handler(self._meeting(), _agenda_pdf(["1. Call to order"]))
            )
        )
        monkeypatch.setattr(
            PrimeGovSource,
            "_extract_pdf_bounded",
            lambda self, data: PdfExtraction(
                items=[ExternalAgendaItem(order=1, title="Call to order", number="1")],
                pages_total=3,
                pages_read=2,
                pages_failed=1,
                partial=True,
                reason="page_failed",
            ),
        )

        with pytest.raises(AgendaSourceUpstreamError, match="pdf_partial") as excinfo:
            source.fetch_agenda("longmont", "777")

        assert "1 page(s) could not be read" in str(excinfo.value)

    def test_unreadable_pdf_is_distinguished_from_no_items(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(self._handler(self._meeting(), b"not a pdf at all"))
        )
        with pytest.raises(AgendaSourceUpstreamError, match="pdf_unreadable"):
            source.fetch_agenda("longmont", "777")


class TestArchivedDiscovery:
    """P3: upcoming + finite current-year archives, dedup, partial-failure."""

    def _handler(self, *, upcoming=None, archive=None, upcoming_status=200, archive_status=200):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(
                    upcoming_status, json=upcoming if upcoming_status == 200 else None
                )
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(
                    archive_status, json=archive if archive_status == 200 else None
                )
            return httpx.Response(404, text="x")

        return handler

    def test_archived_meetings_merged_and_deduped_by_id(self) -> None:
        upcoming = [{"id": 1, "title": "Up1", "dateTime": "2026-07-08T09:00:00"}]
        archive = [
            {"id": 1, "title": "Up1", "dateTime": "2026-07-08T09:00:00"},
            {"id": 2, "title": "Old", "dateTime": "2025-03-01T09:00:00"},
        ]
        source = PrimeGovSource(
            transport=httpx.MockTransport(self._handler(upcoming=upcoming, archive=archive))
        )

        meetings = source.fetch_meetings("longmont")

        assert [m.external_id for m in meetings] == ["1", "2"]
        assert source.last_listing_warning is None

    def test_one_endpoint_failure_is_partial_and_preserves_the_other(self) -> None:
        upcoming = [{"id": 1, "title": "Up1", "dateTime": "2026-07-08T09:00:00"}]
        source = PrimeGovSource(
            transport=httpx.MockTransport(self._handler(upcoming=upcoming, archive_status=500))
        )

        meetings = source.fetch_meetings("longmont")

        assert [m.external_id for m in meetings] == ["1"]
        assert source.last_listing_warning is not None
        assert "PARTIAL" in source.last_listing_warning

    def test_both_endpoints_fail_is_honest_error_not_empty(self) -> None:
        source = PrimeGovSource(
            transport=httpx.MockTransport(self._handler(upcoming_status=500, archive_status=500))
        )
        with pytest.raises(AgendaSourceUpstreamError, match="honest upstream error"):
            source.fetch_meetings("longmont")

    def test_since_year_drives_bounded_archive_query(self) -> None:
        requested: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=[])
            if request.url.path.endswith("/ListArchivedMeetings"):
                requested.append(request.url.params.get("year"))
                return httpx.Response(200, json=[])
            return httpx.Response(404, text="x")

        source = PrimeGovSource(transport=httpx.MockTransport(handler))
        source.fetch_meetings("longmont", since=date(2025, 1, 1))

        assert requested == ["2025"]

    def test_earlier_year_archived_meeting_is_importable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # fetch_agenda must retrieve a meeting that an earlier archived year
        # offered, not look only at the current year.
        from civiccast.agenda_import import primegov as primegov_module

        monkeypatch.setattr(primegov_module, "_archive_year", lambda since: 2030)
        pdf_bytes = _agenda_pdf(["1. Call to order"])
        archived = [
            {
                "id": 9,
                "title": "Old meeting",
                "dateTime": "2029-03-01T09:00:00",
                "documentList": [
                    {
                        "id": 1,
                        "templateId": 321,
                        "templateName": "Agenda",
                        "compileOutputType": 1,
                        "link": None,
                    }
                ],
            }
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=[])
            if request.url.path.endswith("/ListArchivedMeetings"):
                year = request.url.params.get("year")
                return httpx.Response(200, json=archived if year == "2029" else [])
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))
        agenda = source.fetch_agenda("longmont", "9")

        assert agenda.external_id == "9"
        assert "meetingTemplateId=321" in agenda.source_doc_url

    def test_next_year_upcoming_meeting_is_importable_without_a_year_scope(self) -> None:
        # PR278 review counterexample 1: the upcoming list is not year-filtered, so
        # it can offer a meeting dated in the NEXT calendar year. It needs no
        # archive year -- the import lookup always reads the upcoming list first --
        # so no future year is ever required to import an offered upcoming item.
        from civiccast.agenda_import import primegov as primegov_module

        next_year = primegov_module._archive_year(None) + 1
        pdf_bytes = _agenda_pdf(["1. Call to order"])
        upcoming = [
            {
                "id": 4242,
                "title": f"Upcoming {next_year} meeting",
                "dateTime": f"{next_year}-01-12T19:00:00",
                "documentList": [
                    {
                        "id": 1,
                        "templateId": 777,
                        "templateName": "Agenda",
                        "compileOutputType": 1,
                        "link": None,
                    }
                ],
            }
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=upcoming)
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(200, json=[])
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))

        discovered = source.fetch_meetings("longmont")
        assert [m.external_id for m in discovered] == ["4242"]
        assert discovered[0].meeting_datetime is not None
        assert discovered[0].meeting_datetime.year == next_year
        # The next year is not an archived-list year, so it is out of scope.
        assert primegov_module.archive_year_supported(next_year) is False

        agenda = source.fetch_agenda("longmont", "4242")

        assert agenda.external_id == "4242"
        assert "meetingTemplateId=777" in agenda.source_doc_url

    def test_archived_year_before_the_old_floor_is_offered_and_importable(self) -> None:
        # PR278 review counterexample 2: discovery's `since` has no lower bound, so
        # a year far below any arbitrary import floor must still be importable --
        # one shared year rule, no floor mismatch.
        pdf_bytes = _agenda_pdf(["1. Call to order"])
        archived = [
            {
                "id": 1985,
                "title": "Archived 1985 meeting",
                "dateTime": "1985-03-01T09:00:00",
                "documentList": [
                    {
                        "id": 1,
                        "templateId": 555,
                        "templateName": "Agenda",
                        "compileOutputType": 1,
                        "link": None,
                    }
                ],
            }
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=[])
            if request.url.path.endswith("/ListArchivedMeetings"):
                year = request.url.params.get("year")
                return httpx.Response(200, json=archived if year == "1985" else [])
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))

        discovered = source.fetch_meetings("longmont", since=date(1985, 3, 1))
        assert [m.external_id for m in discovered] == ["1985"]

        agenda = source.fetch_agenda("longmont", "1985", archive_year=1985)

        assert agenda.external_id == "1985"
        assert "meetingTemplateId=555" in agenda.source_doc_url

    def test_discovery_offered_older_archived_year_is_importable(self) -> None:
        # PR277 review: discovery can offer a meeting from ANY requested archived
        # year (`since`), so the import lookup must be able to reach that same
        # finite year -- not only the current year plus the two prior ones.
        from civiccast.agenda_import import primegov as primegov_module

        current_year = primegov_module._archive_year(None)
        older_year = current_year - 3
        pdf_bytes = _agenda_pdf(["1. Call to order"])
        archived = [
            {
                "id": 4242,
                "title": f"Archived {older_year} meeting",
                "dateTime": f"{older_year}-03-01T09:00:00",
                "documentList": [
                    {
                        "id": 1,
                        "templateId": 999,
                        "templateName": "Agenda",
                        "compileOutputType": 1,
                        "link": None,
                    }
                ],
            }
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=[])
            if request.url.path.endswith("/ListArchivedMeetings"):
                year = request.url.params.get("year")
                return httpx.Response(200, json=archived if year == str(older_year) else [])
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))

        discovered = source.fetch_meetings("longmont", since=date(older_year, 1, 1))
        assert [m.external_id for m in discovered] == ["4242"]

        # Before the correction the import lookup only read the current year and
        # the two prior ones, so this discovery-offered meeting was not found.
        with pytest.raises(AgendaSourceUpstreamError, match="was not found"):
            source.fetch_agenda("longmont", "4242")

        agenda = source.fetch_agenda("longmont", "4242", archive_year=older_year)

        assert agenda.external_id == "4242"
        assert agenda.meeting_datetime is not None
        assert agenda.meeting_datetime.year == older_year
        assert "meetingTemplateId=999" in agenda.source_doc_url


class TestDocumentRedirectSafety:
    """P1/P2: the CompiledDocument download follows vendor redirects to external
    public storage, but a redirect to a non-public target is refused."""

    def _meeting(self) -> list[dict]:
        return _single_meeting(
            [
                {
                    "id": 1,
                    "templateId": 555,
                    "templateName": "Agenda",
                    "compileOutputType": 1,
                    "link": None,
                }
            ]
        )

    def test_redirect_to_a_private_or_link_local_target_is_blocked(self) -> None:
        hosts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=self._meeting())
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(404, text="x")
            hosts.append(request.url.host)
            if request.url.host == "longmont.primegov.com":
                return httpx.Response(
                    302, headers={"location": "http://169.254.169.254/latest/meta-data/"}
                )
            pytest.fail(f"redirect to a non-public host must not be followed: {request.url}")

        source = PrimeGovSource(transport=httpx.MockTransport(handler))
        with pytest.raises(AgendaSourceUpstreamError, match="document_redirect_blocked"):
            source.fetch_agenda("longmont", "777")
        assert hosts == ["longmont.primegov.com"]  # the metadata host was never requested

    def test_redirect_to_public_external_storage_is_followed(self) -> None:
        pdf_bytes = _agenda_pdf(["1. Call to order"])

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=self._meeting())
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(404, text="x")
            if request.url.host == "longmont.primegov.com":
                return httpx.Response(
                    302, headers={"location": "https://pgwest.blob.core.windows.net/longmont/x.pdf"}
                )
            assert request.url.host == "pgwest.blob.core.windows.net"
            return httpx.Response(200, content=pdf_bytes)

        source = PrimeGovSource(transport=httpx.MockTransport(handler))
        agenda = source.fetch_agenda("longmont", "777")

        assert [i.title for i in agenda.items] == ["Call to order"]


class TestHardExtractionTimeout:
    """P2: extraction runs in a killable child process; a hung parse is killed
    at the hard wall-clock budget and a partial result is REFUSED, not persisted."""

    def test_hung_extraction_is_killed_and_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from civiccast.agenda_import import primegov as primegov_module

        # Replace the child script with one that hangs, so the PARENT's
        # subprocess hard timeout (not a between-pages clock) is what stops it.
        monkeypatch.setattr(primegov_module, "_EXTRACTOR_SCRIPT", "import time; time.sleep(30)")
        meetings = _single_meeting(
            [
                {
                    "id": 1,
                    "templateId": 555,
                    "templateName": "Agenda",
                    "compileOutputType": 1,
                    "link": None,
                }
            ]
        )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/ListUpcomingMeetings"):
                return httpx.Response(200, json=meetings)
            if request.url.path.endswith("/ListArchivedMeetings"):
                return httpx.Response(404, text="x")
            return httpx.Response(200, content=_agenda_pdf(["1. Call to order"]))

        source = PrimeGovSource(
            transport=httpx.MockTransport(handler), extraction_deadline_seconds=0.5
        )
        started = time.monotonic()
        with pytest.raises(AgendaSourceUpstreamError, match="pdf_partial"):
            source.fetch_agenda("longmont", "777")
        # Real hard kill, not a graceful 30 s sleep.
        assert time.monotonic() - started < 15
