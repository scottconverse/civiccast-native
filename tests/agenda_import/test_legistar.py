# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Contract tests for LegistarSource -- fixture-based, zero live network.

Fixtures under ``fixtures/`` were captured live from ``webapi.legistar.com/
v1/seattle`` (Event 5705, City Council, 2024-01-09) during plan
implementation. The NYC 403 behavior is asserted directly (a real,
independently-confirmed live fact -- plan §3) without needing a fixture body.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from civiccast.agenda_import.base import (
    AgendaSourceAuthRequiredError,
    AgendaSourceUpstreamError,
)
from civiccast.agenda_import.legistar import LegistarSource

_FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> object:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _handler_for(*, events=None, event=None, items=None, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/EventItems"):
            return httpx.Response(status_code, json=items if status_code == 200 else None)
        if path.rstrip("/").endswith("/Events"):
            return httpx.Response(status_code, json=events if status_code == 200 else None)
        # single-event GET .../Events/{id}
        return httpx.Response(status_code, json=event if status_code == 200 else None)

    return handler


class TestFetchMeetings:
    def test_maps_seattle_events_list_into_summaries(self) -> None:
        events = _load("legistar_events_list.json")
        source = LegistarSource(
            transport=httpx.MockTransport(_handler_for(events=events)),
        )

        meetings = source.fetch_meetings("seattle")

        assert [m.external_id for m in meetings] == ["5696", "5699", "5705"]
        assert meetings[2].title == "City Council — 2024-01-09"
        assert meetings[2].meeting_datetime is not None
        assert meetings[2].meeting_datetime.year == 2024

    def test_non_list_response_is_upstream_error(self) -> None:
        source = LegistarSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"not": "a list"})),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="not a list"):
            source.fetch_meetings("seattle")

    def test_nyc_403_raises_auth_required_naming_the_client_code(self) -> None:
        # Real live fact (plan §3): webapi.legistar.com/v1/nyc/Events returns
        # 403 with no token configured -- confirmed live during this
        # implementation pass (curl, 2026-07-07).
        source = LegistarSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(403, text="Forbidden")),
        )
        with pytest.raises(AgendaSourceAuthRequiredError, match="nyc"):
            source.fetch_meetings("nyc")

    def test_5xx_raises_upstream_error_not_auth_required(self) -> None:
        source = LegistarSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down")),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="503"):
            source.fetch_meetings("seattle")

    def test_malformed_json_raises_upstream_error(self) -> None:
        source = LegistarSource(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"not json at all {{{")
            ),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="malformed JSON"):
            source.fetch_meetings("seattle")

    def test_timeout_raises_upstream_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        source = LegistarSource(transport=httpx.MockTransport(handler))
        with pytest.raises(AgendaSourceUpstreamError, match="timed out"):
            source.fetch_meetings("seattle")

    def test_token_is_sent_as_a_query_parameter_when_configured(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=[])

        source = LegistarSource(
            token="secret-token-sentinel", transport=httpx.MockTransport(handler)
        )
        source.fetch_meetings("seattle")

        assert len(seen) == 1
        assert seen[0].url.params["token"] == "secret-token-sentinel"


class TestFetchAgenda:
    def test_maps_a_real_seattle_event_into_a_normalized_agenda(self) -> None:
        event = _load("legistar_event_5705.json")
        items = _load("legistar_event_items_5705.json")
        source = LegistarSource(
            transport=httpx.MockTransport(_handler_for(event=event, items=items)),
        )

        agenda = source.fetch_agenda("seattle", "5705")

        assert agenda.external_id == "5705"
        assert agenda.title == "City Council — 2024-01-09"
        assert agenda.source_doc_url == event["EventAgendaFile"]
        # 6 raw fixture rows; one has no EventItemAgendaSequence and is
        # skipped (fail-loud-on-truly-empty is a SEPARATE guard -- 5 of 6
        # rows remain, so it does not fire here).
        assert [item.order for item in agenda.items] == [1, 2, 7, 11, 16]

    def test_blank_event_item_title_falls_back_to_matter_file(self) -> None:
        event = _load("legistar_event_5705.json")
        items = _load("legistar_event_items_5705.json")
        source = LegistarSource(
            transport=httpx.MockTransport(_handler_for(event=event, items=items)),
        )

        agenda = source.fetch_agenda("seattle", "5705")

        item_at_1 = next(i for i in agenda.items if i.order == 1)
        assert item_at_1.title  # never blank -- AgendaItem requires min_length=1
        item_at_7 = next(i for i in agenda.items if i.order == 7)
        assert item_at_7.title == "January 9, 2024"

    def test_first_matter_attachment_hyperlink_becomes_doc_url(self) -> None:
        event = _load("legistar_event_5705.json")
        items = _load("legistar_event_items_5705.json")
        source = LegistarSource(
            transport=httpx.MockTransport(_handler_for(event=event, items=items)),
        )

        agenda = source.fetch_agenda("seattle", "5705")

        item_16 = next(i for i in agenda.items if i.order == 16)
        assert item_16.doc_url == (
            "https://legistar2.granicus.com/seattle/attachments/"
            "e85c31d6-9248-45c1-8060-d61ab69311bb.docx"
        )
        assert item_16.number == "1."

    def test_item_with_no_agenda_sequence_is_skipped(self) -> None:
        event = _load("legistar_event_5705.json")
        items = _load("legistar_event_items_5705.json")
        source = LegistarSource(
            transport=httpx.MockTransport(_handler_for(event=event, items=items)),
        )

        agenda = source.fetch_agenda("seattle", "5705")

        assert 104485 not in {i.order for i in agenda.items}
        assert len(agenda.items) == 5

    def test_all_items_skipped_raises_upstream_error_never_a_silent_empty_import(self) -> None:
        event = _load("legistar_event_5705.json")
        no_sequence_items = [
            {**row, "EventItemAgendaSequence": None}
            for row in _load("legistar_event_items_5705.json")
        ]
        source = LegistarSource(
            transport=httpx.MockTransport(_handler_for(event=event, items=no_sequence_items)),
        )

        with pytest.raises(AgendaSourceUpstreamError, match="no orderable agenda items"):
            source.fetch_agenda("seattle", "5705")

    def test_hostile_matter_attachment_link_passes_through_unvalidated(self) -> None:
        # LegistarSource is a pure adapter -- it does not apply the
        # http/https allowlist. That happens once, in the mapper, at the
        # trust boundary (plan §10). This test pins that the adapter itself
        # does not silently drop or crash on a hostile link.
        event = _load("legistar_event_5705.json")
        hostile_items = _load("legistar_event_items_hostile.json")
        source = LegistarSource(
            transport=httpx.MockTransport(_handler_for(event=event, items=hostile_items)),
        )

        agenda = source.fetch_agenda("seattle", "5705")

        hostile = next(i for i in agenda.items if i.order == 2)
        assert hostile.doc_url == "javascript:alert(document.cookie)"

    def test_nyc_403_on_fetch_agenda_raises_auth_required(self) -> None:
        source = LegistarSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(403, text="Forbidden")),
        )
        with pytest.raises(AgendaSourceAuthRequiredError, match="nyc"):
            source.fetch_agenda("nyc", "1")

    def test_malformed_event_response_raises_upstream_error(self) -> None:
        source = LegistarSource(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"no": "EventId"})),
        )
        with pytest.raises(AgendaSourceUpstreamError, match="malformed"):
            source.fetch_agenda("seattle", "5705")
