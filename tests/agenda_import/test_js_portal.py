# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""``JsPortalSource`` -- Agenda Bridge Phase 4 adapter tests.

Fixtures under ``tests/agenda_import/fixtures/js_portal_*.md`` are
synthetic, hand-authored markdown shaped like crawl4ai's ``result.markdown``
output for CivicPlus/Granicus-family portals -- NOT captured from a live
tenant (see ``civiccast/agenda_import/js_portal.py``'s module docstring for
why). No test in this module makes a real network call or imports crawl4ai
for real (see ``crawl4ai_absent`` below); every crawl is monkeypatched at
:func:`civiccast.agenda_import.js_portal._crawl_page`, the same seam the
adapter itself uses, so the extraction heuristics and the bounding guards
(robots.txt, same-origin, not-installed posture) are each exercised
independently of whether the optional dependency is present.

**Hermetic-either-way, on purpose.** An earlier version of
``TestNotInstalledPosture`` below just called the real
``_load_crawl4ai_classes``/``describe_js_portal_runtime`` and asserted
"not installed" -- true in THIS author's dev environment, but not a
property of the code, only of that one environment. CI's "Unit tests" job
installs every other optional extra via ``--all-extras`` (captions-runtime,
cloudflare-r2, s3-cdn), and briefly did the same for ``agenda-js-import``
before ``.github/workflows/ci-test.yml`` was corrected to exclude it --
crawl4ai was genuinely importable there, so "not installed" was false, and
a real (but browser-binary-less) crawl attempt inside
``test_fetch_meetings_surfaces_the_not_installed_error`` triggered a
Playwright launch failure whose leaked asyncio resources then surfaced as
unraisable-exception noise on an unrelated, later-running test in this same
pytest session (``test_router.py::TestRoleGating::test_wrong_scope_is_403``
-- nothing there touches crawl4ai; it was collateral GC-timing damage).
``TestNotInstalledPosture`` now forces the absent-package path via
``sys.modules['crawl4ai'] = None`` (the standard, documented way to make
the next ``import crawl4ai`` raise ``ImportError`` regardless of whether the
real package is on disk), so its assertions hold in every environment, not
just one. ``TestInstalledPostureWhenCrawl4aiIsPresent`` is the mirror: it
exercises the real, unmocked "installed" branch, but skips cleanly wherever
crawl4ai is genuinely absent (CI, most local dev setups) rather than
failing or silently asserting nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

from civiccast.agenda_import.base import (
    AgendaSourceDependencyMissingError,
    AgendaSourceUpstreamError,
)
from civiccast.agenda_import.js_portal import (
    JsPortalRuntimeUnavailableError,
    JsPortalSource,
    _classify_markdown_line,
    _extract_agenda_items,
    _extract_meeting_links,
    _hash_id,
    _load_crawl4ai_classes,
    _require_robots_allowed,
    _require_same_origin,
    describe_js_portal_runtime,
)
from civiccast.agenda_import.models import ExternalAgendaItem

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_text(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def crawl4ai_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``from crawl4ai import ...`` to raise ``ImportError`` for the
    duration of one test, regardless of whether the real package is
    actually installed in this environment.

    A ``None`` entry in ``sys.modules`` is CPython's own documented signal
    that a name is known to be unimportable -- the import system checks
    ``sys.modules`` before ever touching the filesystem, so this is
    equivalent to genuine absence from crawl4ai's own caller's point of
    view, not a fragile guess about import internals.
    """
    monkeypatch.setitem(sys.modules, "crawl4ai", None)


# --- not-installed posture ---------------------------------------------------


class TestNotInstalledPosture:
    """Hermetic: every test forces the "not installed" path via
    ``crawl4ai_absent`` rather than relying on the real environment. See
    the module docstring for why that distinction matters."""

    def test_load_crawl4ai_classes_raises_a_clean_actionable_error(
        self, crawl4ai_absent: None
    ) -> None:
        with pytest.raises(JsPortalRuntimeUnavailableError, match="agenda-js-import"):
            _load_crawl4ai_classes()

    def test_the_error_is_a_dependency_missing_error(self) -> None:
        # base.py's taxonomy: the router maps this specific subclass to 503,
        # distinct from a generic upstream failure. Pure class-hierarchy
        # check -- no import attempted, so no fixture needed.
        assert issubclass(JsPortalRuntimeUnavailableError, AgendaSourceDependencyMissingError)

    def test_describe_js_portal_runtime_reports_not_installed_without_raising(
        self, crawl4ai_absent: None
    ) -> None:
        status = describe_js_portal_runtime()
        assert status.installed is False
        assert "agenda-js-import" in status.detail

    def test_fetch_meetings_surfaces_the_not_installed_error(
        self, crawl4ai_absent: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # fetch_meetings crawls immediately (no lazy short-circuit before the
        # first page fetch), so calling it with crawl4ai absent raises the
        # same dependency-missing error the router maps to 503. robots.txt
        # is stubbed too (not just crawl4ai) so this test makes zero real
        # network calls, matching the module docstring's claim exactly --
        # the fake "fairview.example.gov" host was previously reached for
        # real (its DNS failure happened to be caught as "permissive" by
        # _require_robots_allowed's own error handling, but that's an
        # accident of that function's design, not something this test
        # should depend on).
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._require_robots_allowed", lambda *a, **kw: None
        )
        source = JsPortalSource(portal_url="https://fairview.example.gov/AgendaCenter")
        with pytest.raises(JsPortalRuntimeUnavailableError):
            source.fetch_meetings("fairview")


class TestInstalledPostureWhenCrawl4aiIsPresent:
    """Mirror of :class:`TestNotInstalledPosture` for the genuinely-
    installed case. Skips cleanly (not a failure, not a silent no-op) when
    crawl4ai is not actually importable here -- the default in CI (which
    deliberately excludes the ``agenda-js-import`` extra, see
    ``.github/workflows/ci-test.yml``) and in most local dev environments.
    Run this class for real by installing the extra:
    ``pip install civiccast[agenda-js-import]``.
    """

    def test_load_crawl4ai_classes_returns_the_real_classes(self) -> None:
        pytest.importorskip("crawl4ai", reason="agenda-js-import extra not installed here")
        crawler_cls, browser_config_cls, run_config_cls, cache_mode_cls = _load_crawl4ai_classes()
        assert crawler_cls.__name__ == "AsyncWebCrawler"
        assert browser_config_cls.__name__ == "BrowserConfig"
        assert run_config_cls.__name__ == "CrawlerRunConfig"
        assert cache_mode_cls.__name__ == "CacheMode"

    def test_describe_js_portal_runtime_reports_installed_without_raising(self) -> None:
        pytest.importorskip("crawl4ai", reason="agenda-js-import extra not installed here")
        status = describe_js_portal_runtime()
        assert status.installed is True
        assert "not yet confirm the Playwright Chromium binary" in status.detail


# --- robots.txt ---------------------------------------------------------------


def _robots_transport(robots_body: str | None, *, status_code: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if robots_body is None:
            return httpx.Response(404)
        return httpx.Response(status_code, text=robots_body)

    return httpx.MockTransport(handler)


class TestRobotsTxt:
    def test_no_robots_txt_is_permissive(self) -> None:
        _require_robots_allowed(
            "https://fairview.example.gov/AgendaCenter",
            timeout_seconds=5.0,
            transport=_robots_transport(None),
        )  # does not raise

    def test_disallowed_path_raises(self) -> None:
        robots = "User-agent: *\nDisallow: /AgendaCenter\n"
        with pytest.raises(AgendaSourceUpstreamError, match=r"robots\.txt"):
            _require_robots_allowed(
                "https://fairview.example.gov/AgendaCenter",
                timeout_seconds=5.0,
                transport=_robots_transport(robots),
            )

    def test_allowed_path_does_not_raise(self) -> None:
        robots = "User-agent: *\nAllow: /\n"
        _require_robots_allowed(
            "https://fairview.example.gov/AgendaCenter",
            timeout_seconds=5.0,
            transport=_robots_transport(robots),
        )

    def test_disallow_scoped_to_a_different_path_does_not_block_this_one(self) -> None:
        robots = "User-agent: *\nDisallow: /staff-only\n"
        _require_robots_allowed(
            "https://fairview.example.gov/AgendaCenter",
            timeout_seconds=5.0,
            transport=_robots_transport(robots),
        )

    def test_unreachable_robots_txt_is_permissive(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        _require_robots_allowed(
            "https://fairview.example.gov/AgendaCenter",
            timeout_seconds=5.0,
            transport=httpx.MockTransport(handler),
        )  # does not raise -- absent robots.txt is "allow", not "deny"


# --- same-origin --------------------------------------------------------------


class TestSameOrigin:
    def test_same_origin_is_allowed(self) -> None:
        _require_same_origin(
            "https://fairview.example.gov/AgendaCenter",
            "https://fairview.example.gov/AgendaCenter/ViewFile/Agenda/_1",
        )  # does not raise

    @pytest.mark.parametrize(
        "candidate",
        [
            "https://evil.example.com/AgendaCenter/ViewFile/Agenda/_1",  # different host
            "http://fairview.example.gov/AgendaCenter/ViewFile/Agenda/_1",  # different scheme
            "https://fairview.example.gov:8443/AgendaCenter/ViewFile/Agenda/_1",  # different port
        ],
    )
    def test_off_origin_is_rejected(self, candidate: str) -> None:
        with pytest.raises(AgendaSourceUpstreamError, match="off-origin"):
            _require_same_origin("https://fairview.example.gov/AgendaCenter", candidate)


# --- listing-page extraction ---------------------------------------------------


class TestExtractMeetingLinks:
    def test_civicplus_listing_yields_real_meetings_only(self) -> None:
        markdown = _load_text("js_portal_civicplus_listing.md")
        candidates = _extract_meeting_links(
            markdown, base_url="https://fairview.example.gov/AgendaCenter", vendor_hint="civicplus"
        )
        titles = [title for _url, title, _when in candidates]
        assert "City Council - August 24, 2026 - Agenda Minutes" in titles
        assert "Planning Commission - August 27, 2026 - Agenda" in titles
        assert "Parks & Recreation Board - September 3, 2026 - Agenda" in titles
        # Nav/footer chrome (Home, Government, Contact Us, Email
        # Notifications, ADA, Privacy) never mentions agenda/meeting/minutes
        # and must not appear.
        assert not any("Privacy" in t or "Contact" in t or "Email" in t for t in titles)

    def test_civicplus_cancellation_notice_is_a_real_disclosed_result(self) -> None:
        # A cancelled meeting only has a "Notice" document, no compiled
        # agenda -- it legitimately appears in discovery (same honest
        # posture as primegov.py's handling of a CANCELLED meeting) and
        # fetch_agenda is expected to fail loud on it (see
        # TestJsPortalSourceFetchAgenda.test_no_parseable_items_fails_loud).
        markdown = _load_text("js_portal_civicplus_listing.md")
        candidates = _extract_meeting_links(
            markdown, base_url="https://fairview.example.gov/AgendaCenter", vendor_hint="civicplus"
        )
        assert any("Cancellation" in title for _url, title, _when in candidates)

    def test_off_origin_links_are_filtered_not_erroring(self) -> None:
        markdown = (
            "* [City Council Agenda](https://fairview.example.gov/AgendaCenter/1)\n"
            "* [Other City's Agenda](https://other-city.example.gov/AgendaCenter/2)\n"
        )
        candidates = _extract_meeting_links(
            markdown, base_url="https://fairview.example.gov/AgendaCenter", vendor_hint="generic"
        )
        urls = [url for url, _title, _when in candidates]
        assert urls == ["https://fairview.example.gov/AgendaCenter/1"]

    def test_granicus_table_listing_prefers_agenda_link_over_video_link(self) -> None:
        markdown = _load_text("js_portal_granicus_listing.md")
        candidates = _extract_meeting_links(
            markdown, base_url="https://meetings.riverbend.example.gov/", vendor_hint="granicus"
        )
        urls = [url for url, _title, _when in candidates]
        assert "https://meetings.riverbend.example.gov/GeneratedAgenda.php?id=9002" in urls
        assert (
            "https://meetings.riverbend.example.gov/ViewPublisher.php?view_id=3&clip_id=9002"
            not in urls
        )

    def test_parses_meeting_dates_from_the_row(self) -> None:
        markdown = _load_text("js_portal_granicus_listing.md")
        candidates = _extract_meeting_links(
            markdown, base_url="https://meetings.riverbend.example.gov/", vendor_hint="granicus"
        )
        by_title = {title: when for _url, title, when in candidates}
        matched = [
            when
            for title, when in by_title.items()
            if "Board of Supervisors" in title and "Special" not in title
        ]
        assert matched and matched[0] is not None and matched[0].month == 9 and matched[0].day == 2

    def test_a_link_with_no_recognizable_date_still_becomes_a_candidate(self) -> None:
        markdown = "* [City Council Agenda](https://fairview.example.gov/AgendaCenter/1)\n"
        candidates = _extract_meeting_links(
            markdown, base_url="https://fairview.example.gov/AgendaCenter", vendor_hint="generic"
        )
        assert len(candidates) == 1
        assert candidates[0][2] is None  # meeting_datetime -- no date, not dropped

    def test_generic_vendor_hint_still_matches_generic_keywords(self) -> None:
        markdown = "* [Meeting Agenda](https://portal.example.gov/docs/1)\n"
        candidates = _extract_meeting_links(
            markdown, base_url="https://portal.example.gov", vendor_hint="generic"
        )
        assert len(candidates) == 1

    def test_unknown_vendor_hint_falls_back_to_generic(self) -> None:
        source = JsPortalSource(
            portal_url="https://portal.example.gov", vendor_hint="not-a-real-vendor"
        )
        assert source._vendor_hint == "generic"


# --- detail-page extraction ----------------------------------------------------


class TestExtractAgendaItems:
    def test_civicplus_detail_extracts_numbered_items_in_order(self) -> None:
        markdown = _load_text("js_portal_civicplus_detail.md")
        items = _extract_agenda_items(markdown)
        numbered_titles = [i.title for i in items if i.number and i.number.isdigit()]
        assert "Call to Order" in numbered_titles
        assert "Roll Call" in numbered_titles
        assert "Adjourn" in numbered_titles
        # Order strictly increases and matches document position.
        assert [i.order for i in items] == list(range(1, len(items) + 1))

    def test_civicplus_detail_extracts_compound_sub_items(self) -> None:
        markdown = _load_text("js_portal_civicplus_detail.md")
        items = _extract_agenda_items(markdown)
        by_number = {i.number: i.title for i in items}
        assert by_number["9.a"] == "Award of Contract for Streetscape Design Services"
        assert by_number["9.b"] == "Authorization of Change Order No. 3"

    def test_numbered_items_carry_high_confidence(self) -> None:
        markdown = _load_text("js_portal_granicus_detail.md")
        items = _extract_agenda_items(markdown)
        numbered = [i for i in items if i.number is not None]
        assert numbered
        assert all(i.confidence is not None and i.confidence >= 0.8 for i in numbered)

    def test_a_numbered_item_with_a_clock_time_scores_higher_than_a_plain_one(self) -> None:
        markdown = _load_text("js_portal_granicus_detail.md")
        items = {i.number: i.confidence for i in _extract_agenda_items(markdown) if i.number}
        assert items["6"] > items["7"]  # "6." carries "9:15 AM"; "7." does not

    def test_heading_only_lines_carry_lower_confidence_than_numbered_items(self) -> None:
        markdown = _load_text("js_portal_civicplus_detail.md")
        items = _extract_agenda_items(markdown)
        numbered_conf = [i.confidence for i in items if i.number is not None]
        heading_conf = [i.confidence for i in items if i.number is None]
        assert heading_conf  # the synthetic H1/H3 headings are real, disclosed noise
        assert min(numbered_conf) > max(heading_conf)

    def test_confidence_is_always_within_bounds(self) -> None:
        for name in ("js_portal_civicplus_detail.md", "js_portal_granicus_detail.md"):
            for item in _extract_agenda_items(_load_text(name)):
                assert item.confidence is not None
                assert 0.0 <= item.confidence <= 1.0

    def test_blank_markdown_yields_no_items(self) -> None:
        assert _extract_agenda_items("\n\n   \n") == []

    def test_prose_with_no_structure_yields_no_items(self) -> None:
        markdown = "This portal has no meetings scheduled at this time.\nCheck back later.\n"
        assert _extract_agenda_items(markdown) == []


class TestClassifyMarkdownLine:
    def test_markdown_heading_is_medium_confidence(self) -> None:
        result = _classify_markdown_line("## Consent Agenda")
        assert result == (None, "Consent Agenda", pytest.approx(0.5))

    def test_bullet_numbered_item_strips_the_bullet_marker(self) -> None:
        number, title, confidence = _classify_markdown_line("- 1. Call to Order")
        assert number == "1"
        assert title == "Call to Order"
        assert confidence == pytest.approx(0.85)

    def test_bold_numbered_item_strips_bold_markers(self) -> None:
        number, title, _confidence = _classify_markdown_line("**1. Call to Order**")
        assert number == "1"
        assert title == "Call to Order"

    def test_all_caps_line_is_a_heading_fallback(self) -> None:
        result = _classify_markdown_line("CONSENT AGENDA")
        assert result == (None, "CONSENT AGENDA", pytest.approx(0.45))

    def test_time_only_line_is_the_lowest_confidence_tier(self) -> None:
        result = _classify_markdown_line("Public comment - 7:15 PM")
        assert result is not None
        assert result[2] == pytest.approx(0.3)

    def test_ordinary_prose_is_not_classified(self) -> None:
        assert _classify_markdown_line("The meeting will be held in the council chambers.") is None


# --- JsPortalSource end-to-end (crawl mocked at the adapter's own seam) --------


class TestJsPortalSourceFetchMeetings:
    def test_returns_summaries_from_the_configured_listing_page(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        markdown = _load_text("js_portal_civicplus_listing.md")
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._crawl_page", lambda url, **_kw: markdown
        )
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._require_robots_allowed", lambda *a, **kw: None
        )
        source = JsPortalSource(
            portal_url="https://fairview.example.gov/AgendaCenter", vendor_hint="civicplus"
        )

        summaries = source.fetch_meetings("fairview")

        assert len(summaries) == 4
        assert any("City Council" in s.title for s in summaries)

    def test_since_filters_out_earlier_meetings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from datetime import date

        markdown = _load_text("js_portal_civicplus_listing.md")
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._crawl_page", lambda url, **_kw: markdown
        )
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._require_robots_allowed", lambda *a, **kw: None
        )
        source = JsPortalSource(
            portal_url="https://fairview.example.gov/AgendaCenter", vendor_hint="civicplus"
        )

        summaries = source.fetch_meetings("fairview", since=date(2026, 8, 26))

        titles = [s.title for s in summaries]
        assert not any("August 24" in t for t in titles)
        assert any("August 27" in t for t in titles)

    def test_empty_listing_is_a_valid_zero_result_not_an_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Unlike fetch_agenda's items (below), zero upcoming meetings is a
        # legitimate real state (nothing scheduled), not a "fail loud" case
        # -- mirrors primegov.py's fetch_meetings, which has no empty-list
        # guard either.
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._crawl_page",
            lambda url, **_kw: "# No meetings\n\nNothing is currently scheduled.\n",
        )
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._require_robots_allowed", lambda *a, **kw: None
        )
        source = JsPortalSource(portal_url="https://fairview.example.gov/AgendaCenter")

        assert source.fetch_meetings("fairview") == []

    def test_robots_disallow_blocks_the_crawl_before_any_page_fetch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        crawled: list[str] = []
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._crawl_page",
            lambda url, **_kw: crawled.append(url) or "unused",
        )

        def _deny(*_a: object, **_kw: object) -> None:
            raise AgendaSourceUpstreamError("robots.txt disallows this")

        monkeypatch.setattr("civiccast.agenda_import.js_portal._require_robots_allowed", _deny)
        source = JsPortalSource(portal_url="https://fairview.example.gov/AgendaCenter")

        with pytest.raises(AgendaSourceUpstreamError, match=r"robots\.txt"):
            source.fetch_meetings("fairview")
        assert crawled == []  # never reached the crawl


class TestJsPortalSourceFetchAgenda:
    def test_returns_items_with_confidence_and_provenance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        listing = _load_text("js_portal_civicplus_listing.md")
        detail = _load_text("js_portal_civicplus_detail.md")
        pages = {
            "https://fairview.example.gov/AgendaCenter": listing,
            "https://fairview.example.gov/AgendaCenter/ViewFile/Agenda/_08242026-101": detail,
        }
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._crawl_page", lambda url, **_kw: pages[url]
        )
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._require_robots_allowed", lambda *a, **kw: None
        )
        source = JsPortalSource(
            portal_url="https://fairview.example.gov/AgendaCenter", vendor_hint="civicplus"
        )
        event_id = _hash_id(
            "https://fairview.example.gov/AgendaCenter/ViewFile/Agenda/_08242026-101"
        )

        agenda = source.fetch_agenda("fairview", event_id)

        assert agenda.external_id == event_id
        assert (
            agenda.source_doc_url
            == "https://fairview.example.gov/AgendaCenter/ViewFile/Agenda/_08242026-101"
        )
        assert len(agenda.items) > 0
        assert all(item.confidence is not None for item in agenda.items)

    def test_unknown_event_id_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        listing = _load_text("js_portal_civicplus_listing.md")
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._crawl_page", lambda url, **_kw: listing
        )
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._require_robots_allowed", lambda *a, **kw: None
        )
        source = JsPortalSource(portal_url="https://fairview.example.gov/AgendaCenter")

        with pytest.raises(AgendaSourceUpstreamError, match="not found"):
            source.fetch_agenda("fairview", "not-a-real-hash")

    def test_no_parseable_items_fails_loud(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The cancellation-notice meeting from the listing fixture has no
        # compiled agenda -- its "detail" page is prose only.
        listing = _load_text("js_portal_civicplus_listing.md")
        cancellation_url = (
            "https://fairview.example.gov/AgendaCenter/ViewFile/Cancellation/_08312026-104"
        )
        pages = {
            "https://fairview.example.gov/AgendaCenter": listing,
            cancellation_url: "This meeting has been cancelled. No agenda was prepared.\n",
        }
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._crawl_page", lambda url, **_kw: pages[url]
        )
        monkeypatch.setattr(
            "civiccast.agenda_import.js_portal._require_robots_allowed", lambda *a, **kw: None
        )
        source = JsPortalSource(
            portal_url="https://fairview.example.gov/AgendaCenter", vendor_hint="civicplus"
        )
        event_id = _hash_id(cancellation_url)

        with pytest.raises(AgendaSourceUpstreamError, match="js_portal_no_items"):
            source.fetch_agenda("fairview", event_id)

    def test_re_deriving_the_same_url_yields_the_same_event_id(self) -> None:
        # Idempotency precondition: fetch_meetings and a later fetch_agenda
        # both independently hash the same detail URL, so an operator who
        # discovers a meeting today and imports it tomorrow (after a fresh
        # crawl of the listing) resolves to the SAME event_id, which is what
        # lets civiccast.agenda_import.mapper's (agenda_id, order) skip rule
        # make re-importing idempotent end to end.
        url = "https://fairview.example.gov/AgendaCenter/ViewFile/Agenda/_08242026-101"
        assert _hash_id(url) == _hash_id(url)


# --- confidence flows all the way to the shared model + mapper -----------------


class TestConfidenceIntegration:
    def test_external_agenda_item_accepts_confidence(self) -> None:
        item = ExternalAgendaItem(order=1, title="Call to Order", confidence=0.85)
        assert item.confidence == 0.85

    def test_confidence_out_of_bounds_is_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ExternalAgendaItem(order=1, title="x", confidence=1.5)
