# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CablecastAdapter: offline golden-fixture parsing + pagination + a real,
read-only, network-touching check against a live public Cablecast server.

The golden fixtures under ``tests/migrate/fixtures/cablecast_*.json`` are
TRIMMED, VERBATIM captures from a real, publicly reachable Cablecast server
(``access-sacramento.cablecast.tv/cablecastapi/v1/...``, fetched 2026-07-08,
read-only, no auth) — not hand-invented shapes. The live test at the bottom
re-verifies the adapter against that same real server over the network; it
is marked ``integration`` (deselected by default, per
``pyproject.toml``'s ``-m "not slow"`` convention for anything that reaches
outside the process) so the normal test run stays offline and fast.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from civiccast.migrate.adapters import CablecastAdapter, CablecastConnection

FIXTURES = Path(__file__).parent / "fixtures"
_BASE = "https://access-sacramento.cablecast.tv/cablecastapi/v1"

_ENDPOINT_FIXTURES = {
    "/shows": "cablecast_shows.json",
    "/scheduleitems": "cablecast_scheduleitems.json",
    "/producers": "cablecast_producers.json",
    "/categories": "cablecast_categories.json",
    "/projects": "cablecast_projects.json",
}


def _load(name: str) -> dict[str, object]:
    result: dict[str, object] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return result


def _golden_handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/cablecastapi/v1")
    fixture = _ENDPOINT_FIXTURES.get(path)
    assert fixture is not None, f"unexpected path {path!r}"
    offset = int(parse_qs(request.url.query.decode())["offset"][0])
    if offset > 0:
        # Every golden fixture's meta.count == its own single page, so a
        # second page request would be a pagination bug — fail loudly.
        raise AssertionError(f"unexpected second page request for {path!r} (offset={offset})")
    return httpx.Response(200, json=_load(fixture))


def _adapter() -> CablecastAdapter:
    transport = httpx.MockTransport(_golden_handler)
    return CablecastAdapter(CablecastConnection(base_url=_BASE), transport=transport)


def test_fetch_inventory_parses_real_cablecast_shape() -> None:
    inventory = _adapter().fetch_inventory()

    assert inventory.source_system == "cablecast"
    assert {s.source_ref for s in inventory.shows} == {"73411", "73410"}

    militaru = next(s for s in inventory.shows if s.source_ref == "73411")
    assert militaru.title == "John Militaru Ministries Internat'l"
    assert militaru.description == "Featuring bilingual messages of faith and hope."
    assert militaru.producer == "John Militaru"
    assert militaru.category == "17 - Religion"
    assert militaru.duration_seconds == 3515
    assert militaru.air_date is not None and militaru.air_date.year == 2026
    assert militaru.media_ref == f"{_BASE}/reels/75355"


def test_fetch_inventory_skips_filler_events_and_looks_up_duration() -> None:
    inventory = _adapter().fetch_inventory()

    # show == -1 (id 340402) is Cablecast's manual/filler marker — excluded.
    refs = {item.source_ref for item in inventory.schedule_items}
    assert refs == {"1087848", "1087849"}

    militaru_run = next(i for i in inventory.schedule_items if i.source_ref == "1087848")
    assert militaru_run.show_source_ref == "73411"
    assert militaru_run.channel_ref == "2"
    # scheduleitems carries no duration of its own — looked up from the
    # referenced show's totalRunTime.
    assert militaru_run.duration_seconds == 3515


def test_fetch_inventory_builds_playlists_from_projects() -> None:
    inventory = _adapter().fetch_inventory()

    militaru_project = next(p for p in inventory.playlists if p.source_ref == "170")
    assert militaru_project.name == "John Militaru Ministries"
    assert militaru_project.item_source_refs == ["73411"]


def test_fetch_inventory_paginates_by_offset() -> None:
    """A synthetic two-page server: page 1 returns 1 show + meta.count=2;
    the adapter must request offset=1 for the second page."""
    page1 = {"meta": {"offset": 0, "pageSize": 1, "count": 2}, "shows": [{"id": 1, "title": "A"}]}
    page2 = {"meta": {"offset": 1, "pageSize": 1, "count": 2}, "shows": [{"id": 2, "title": "B"}]}
    empty = {"meta": {"offset": 0, "pageSize": 50, "count": 0}}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/cablecastapi/v1")
        if path == "/shows":
            offset = int(parse_qs(request.url.query.decode())["offset"][0])
            return httpx.Response(200, json=page1 if offset == 0 else page2)
        return httpx.Response(200, json=empty)

    adapter = CablecastAdapter(
        CablecastConnection(base_url=_BASE), transport=httpx.MockTransport(handler)
    )
    inventory = adapter.fetch_inventory()
    assert {s.title for s in inventory.shows} == {"A", "B"}


def test_fetch_inventory_raises_on_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    adapter = CablecastAdapter(
        CablecastConnection(base_url=_BASE), transport=httpx.MockTransport(handler)
    )
    with pytest.raises(httpx.HTTPStatusError):
        adapter.fetch_inventory()


# ---------------------------------------------------------------------------
# Live, read-only verification against a real public Cablecast server.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_fetch_inventory_against_a_real_cablecast_server() -> None:
    """Read-only, no auth. Deselected by default (``-m "not integration"``
    is NOT wired into CI's default addopts, so this only runs when a
    developer explicitly asks for it: ``pytest -m integration``). If the
    real server is unreachable (offline dev box, server retired), fails
    honestly rather than silently no-op'ing — the roadmap's live-validation
    claim depends on this actually having run at least once (see the
    verbatim evidence recorded in the module docstring's changelog note and
    the task report)."""
    adapter = CablecastAdapter(
        CablecastConnection(base_url="https://access-sacramento.cablecast.tv/cablecastapi/v1")
    )
    inventory = adapter.fetch_inventory()
    assert inventory.shows, "expected at least one real show from the live server"
