# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S14 audience-report tests — packaged franchise-deliverable shape."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime

import pytest

from civiccast.analytics.audience_reports import (
    AudienceReport,
    build_audience_report,
    export_audience_csv,
    export_audience_xml,
)
from civiccast.analytics.models import (
    AnalyticsDimensionCount,
    AnalyticsReport,
    AssetViewPoint,
    LiveConcurrentPoint,
)


def _base(
    *,
    asset_views: list[AssetViewPoint] | None = None,
    concurrent: list[LiveConcurrentPoint] | None = None,
    geography: list[AnalyticsDimensionCount] | None = None,
    device: list[AnalyticsDimensionCount] | None = None,
) -> AnalyticsReport:
    return AnalyticsReport(
        generated_at=datetime.now(UTC),
        range_days=30,
        asset_views=asset_views or [],
        live_concurrent_viewers=concurrent or [],
        geography=geography or [],
        device_breakdown=device or [],
        platform_breakdown=[],
        caption_usage=[],
        audio_usage=[],
        subscription_growth=[],
        podcast_downloads=[],
        retained_fields=["event_id", "event_name", "occurred_at"],
        privacy_boundary="aggregate-only-no-session-ip-or-viewer-identity",
    )


class TestBuilder:
    def test_empty_report(self) -> None:
        out = build_audience_report(_base())
        assert isinstance(out, AudienceReport)
        assert out.total_views == 0
        assert out.total_view_seconds == 0
        assert out.channel_summaries == []
        assert out.top_assets == []
        assert out.period_kind == "monthly"

    def test_unattributed_asset_gets_bucket(self) -> None:
        base = _base(
            asset_views=[
                AssetViewPoint(
                    content_id="vod-1", day=date(2026, 6, 1), views=10, view_seconds=300
                ),
            ]
        )
        out = build_audience_report(base, period_end=date(2026, 6, 20))
        assert any(c.channel_id == "unattributed" for c in out.channel_summaries)

    def test_mapped_asset_attributed_to_channel(self) -> None:
        base = _base(
            asset_views=[
                AssetViewPoint(
                    content_id="vod-1", day=date(2026, 6, 1), views=10, view_seconds=300
                ),
                AssetViewPoint(content_id="vod-2", day=date(2026, 6, 2), views=5, view_seconds=180),
            ],
            concurrent=[
                LiveConcurrentPoint(
                    channel_id="public",
                    day=date(2026, 6, 1),
                    peak_concurrent_viewers=20,
                    average_concurrent_viewers=12.5,
                    samples=24,
                )
            ],
        )
        out = build_audience_report(
            base,
            asset_to_channel={"vod-1": "public", "vod-2": "education"},
            period_end=date(2026, 6, 20),
        )
        names = {c.channel_id for c in out.channel_summaries}
        assert {"public", "education"} == names
        public = next(c for c in out.channel_summaries if c.channel_id == "public")
        assert public.peak_concurrent_viewers == 20
        assert public.total_views == 10
        assert public.unique_assets == 1
        assert public.samples == 24
        # Sort order: public has the most views (10 > 5 + 0 concurrent for edu)
        assert out.channel_summaries[0].channel_id == "public"

    def test_top_assets_sorted_and_limited(self) -> None:
        base = _base(
            asset_views=[
                AssetViewPoint(
                    content_id=f"vod-{i}", day=date(2026, 6, 1), views=i, view_seconds=i * 10
                )
                for i in range(1, 50)
            ]
        )
        out = build_audience_report(base, top_assets_limit=5, period_end=date(2026, 6, 20))
        assert len(out.top_assets) == 5
        assert out.top_assets[0].total_views == 49
        assert out.top_assets[-1].total_views == 45

    def test_weekly_period_bounds(self) -> None:
        out = build_audience_report(_base(), kind="weekly", period_end=date(2026, 6, 18))
        assert out.period_kind == "weekly"
        assert out.period_end == date(2026, 6, 18)
        assert out.period_start == date(2026, 6, 11)

    def test_monthly_period_bounds(self) -> None:
        out = build_audience_report(_base(), kind="monthly", period_end=date(2026, 6, 18))
        assert out.period_start == date(2026, 5, 19)
        assert out.period_end == date(2026, 6, 18)

    def test_custom_period_requires_both(self) -> None:
        with pytest.raises(ValueError, match="custom period requires both"):
            build_audience_report(_base(), kind="custom", period_end=date(2026, 6, 18))

    def test_custom_period_end_before_start_rejected(self) -> None:
        with pytest.raises(ValueError, match="on or after"):
            build_audience_report(
                _base(),
                kind="custom",
                period_start=date(2026, 6, 18),
                period_end=date(2026, 6, 10),
            )

    def test_geography_passed_through(self) -> None:
        base = _base(
            geography=[
                AnalyticsDimensionCount(dimension="geography", key="US-CA", count=200),
                AnalyticsDimensionCount(dimension="geography", key="US-MI", count=50),
            ]
        )
        out = build_audience_report(base)
        assert len(out.geography) == 2
        assert all(row.dimension == "geography" for row in out.geography)

    def test_weekly_report_excludes_data_outside_the_7_day_window(self) -> None:
        """kind=weekly must only aggregate points that actually fall inside
        the resolved 7-day period — not everything the base report pulled
        from the store (range_days can be, and defaults to, a wider 30)."""
        period_end = date(2026, 6, 18)
        base = _base(
            asset_views=[
                # Inside the last 7 days (2026-06-11..2026-06-18): counted.
                AssetViewPoint(
                    content_id="recent", day=date(2026, 6, 15), views=10, view_seconds=100
                ),
                # Outside the 7-day window but inside a 30-day pull: must
                # NOT be counted in a report labeled "last 7 days".
                AssetViewPoint(
                    content_id="stale", day=date(2026, 5, 25), views=999, view_seconds=9999
                ),
            ],
            concurrent=[
                LiveConcurrentPoint(
                    channel_id="public",
                    day=date(2026, 5, 25),
                    peak_concurrent_viewers=500,
                    average_concurrent_viewers=500.0,
                    samples=1,
                ),
            ],
        )
        out = build_audience_report(base, kind="weekly", period_end=period_end)
        assert out.period_start == date(2026, 6, 11)
        assert out.period_end == period_end
        assert out.total_views == 10
        assert {a.content_id for a in out.top_assets} == {"recent"}
        # The stale/500-viewer concurrent point (outside the 7-day window)
        # must not leak into the "public" channel's peak/average.
        assert all(c.channel_id != "public" for c in out.channel_summaries)

    def test_first_seen_last_seen_aggregated(self) -> None:
        base = _base(
            asset_views=[
                AssetViewPoint(content_id="x", day=date(2026, 6, 1), views=1, view_seconds=10),
                AssetViewPoint(content_id="x", day=date(2026, 6, 18), views=2, view_seconds=30),
                AssetViewPoint(content_id="x", day=date(2026, 6, 10), views=1, view_seconds=5),
            ]
        )
        out = build_audience_report(base, period_end=date(2026, 6, 20))
        x = out.top_assets[0]
        assert x.first_seen_day == date(2026, 6, 1)
        assert x.last_seen_day == date(2026, 6, 18)
        assert x.total_views == 4
        assert x.total_view_seconds == 45


class TestCsvExport:
    def test_header_section_present(self) -> None:
        report = build_audience_report(_base())
        csv_text = export_audience_csv(report)
        assert "section,audience-report-header" in csv_text
        assert "period_kind,monthly" in csv_text
        assert "total_views,0" in csv_text

    def test_channels_and_top_assets_sections(self) -> None:
        base = _base(
            asset_views=[
                AssetViewPoint(content_id="vod-1", day=date(2026, 6, 1), views=10, view_seconds=300)
            ]
        )
        report = build_audience_report(
            base, asset_to_channel={"vod-1": "public"}, period_end=date(2026, 6, 20)
        )
        csv_text = export_audience_csv(report)
        assert "section,channel-summaries" in csv_text
        assert "section,top-assets" in csv_text
        assert "public" in csv_text
        assert "vod-1" in csv_text

    def test_dimensions_section_included(self) -> None:
        base = _base(
            geography=[AnalyticsDimensionCount(dimension="geography", key="US-MI", count=15)]
        )
        report = build_audience_report(base)
        csv_text = export_audience_csv(report)
        assert "section,dimensions" in csv_text
        assert "geography,US-MI,15" in csv_text

    def test_formula_injection_guard_on_channel_and_content_ids(self) -> None:
        """A channel/content id starting with =, +, -, or @ must not reach the
        CSV cell verbatim — Excel/LibreOffice would execute it as a formula."""
        base = _base(
            asset_views=[
                AssetViewPoint(
                    content_id='=HYPERLINK("http://evil","x")',
                    day=date(2026, 6, 1),
                    views=1,
                    view_seconds=10,
                )
            ],
            geography=[
                AnalyticsDimensionCount(dimension="geography", key="+1;calc", count=1),
            ],
        )
        report = build_audience_report(
            base,
            asset_to_channel={'=HYPERLINK("http://evil","x")': "@evil-channel"},
            period_end=date(2026, 6, 20),
        )
        csv_text = export_audience_csv(report)
        for row in csv_text.splitlines():
            for cell in row.split(","):
                assert not cell.startswith(("=", "+", "-", "@")), (
                    f"unguarded formula-triggering cell: {cell!r}"
                )


class TestXmlExport:
    def test_root_and_sections_present(self) -> None:
        base = _base(
            asset_views=[
                AssetViewPoint(
                    content_id="vod-1", day=date(2026, 6, 1), views=10, view_seconds=300
                ),
            ],
            concurrent=[
                LiveConcurrentPoint(
                    channel_id="public",
                    day=date(2026, 6, 1),
                    peak_concurrent_viewers=5,
                    average_concurrent_viewers=3.0,
                    samples=12,
                )
            ],
            geography=[AnalyticsDimensionCount(dimension="geography", key="US-MI", count=15)],
        )
        report = build_audience_report(
            base, asset_to_channel={"vod-1": "public"}, period_end=date(2026, 6, 20)
        )
        xml_text = export_audience_xml(report)
        root = ET.fromstring(xml_text)
        assert root.tag == "audience-report"
        assert root.findtext("period-kind") == "monthly"
        chans = root.find("channel-summaries")
        assert chans is not None
        assert chans.find("channel/channel-id").text == "public"  # type: ignore[union-attr]
        assert root.find("geography") is not None

    def test_empty_dimensions_section_omitted(self) -> None:
        report = build_audience_report(_base())
        xml_text = export_audience_xml(report)
        root = ET.fromstring(xml_text)
        # No data → no geography section emitted (keeps the XML small).
        assert root.find("geography") is None


class TestRouterIntegration:
    """End-to-end: the route returns the report in 3 formats with the right
    headers + status codes."""

    def _client(self, monkeypatch: pytest.MonkeyPatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from civiccast.analytics.router import get_analytics_store, staff_router
        from civiccast.analytics.store import AnalyticsStore
        from civiccast.auth.middleware import staff_auth_middleware

        monkeypatch.setenv(
            "CIVICCAST_STAFF_TOKENS", "operator-token-a:operator-a:Operator A:operator"
        )
        app = FastAPI()
        app.middleware("http")(staff_auth_middleware)
        app.include_router(staff_router)
        store = AnalyticsStore()
        # Override the DI seam directly — we don't need the full store_bundle
        # machinery for the router unit test.
        app.dependency_overrides[get_analytics_store] = lambda: store
        return TestClient(app, headers={"Authorization": "Bearer operator-token-a"})

    def test_json_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._client(monkeypatch)
        resp = client.get("/api/staff/analytics/reports/audience")
        assert resp.status_code == 200
        body = resp.json()
        assert body["period_kind"] == "monthly"
        assert body["total_views"] == 0

    def test_csv_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._client(monkeypatch)
        resp = client.get("/api/staff/analytics/reports/audience?format=csv&kind=weekly")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers["content-disposition"]
        assert "audience-report-" in resp.headers["content-disposition"]
        # BOM + header section
        assert resp.text.startswith("﻿")
        assert "audience-report-header" in resp.text

    def test_xml_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._client(monkeypatch)
        resp = client.get("/api/staff/analytics/reports/audience?format=xml")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        root = ET.fromstring(resp.text)
        assert root.tag == "audience-report"

    def test_custom_period_missing_bounds_returns_422(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._client(monkeypatch)
        resp = client.get("/api/staff/analytics/reports/audience?kind=custom")
        assert resp.status_code == 422

    def test_invalid_range_days_returns_422(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = self._client(monkeypatch)
        resp = client.get("/api/staff/analytics/reports/audience?range_days=400")
        assert resp.status_code == 422

    def test_custom_historical_period_pulls_a_wide_enough_store_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A custom period reaching further back than the default
        range_days=30 must still be able to see its own data — the store
        pull window has to cover the resolved period, not just the raw
        range_days query param."""
        from datetime import UTC, datetime, timedelta

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from civiccast.analytics.router import get_analytics_store, staff_router
        from civiccast.analytics.store import AnalyticsStore
        from civiccast.app_platform.models import AnalyticsEvent
        from civiccast.auth.middleware import staff_auth_middleware

        monkeypatch.setenv(
            "CIVICCAST_STAFF_TOKENS", "operator-token-a:operator-a:Operator A:operator"
        )
        app = FastAPI()
        app.middleware("http")(staff_auth_middleware)
        app.include_router(staff_router)
        store = AnalyticsStore()
        app.dependency_overrides[get_analytics_store] = lambda: store
        client = TestClient(app, headers={"Authorization": "Bearer operator-token-a"})

        now = datetime.now(UTC)
        store.record_event(
            AnalyticsEvent(
                event_id="old-view",
                event_name="playback_start",
                occurred_at=now - timedelta(days=40),
                app_target="web_pwa",
                content_id="vod-old",
            )
        )
        period_start = (now - timedelta(days=45)).date()
        period_end = (now - timedelta(days=35)).date()
        resp = client.get(
            "/api/staff/analytics/reports/audience"
            f"?kind=custom&period_start={period_start}&period_end={period_end}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_views"] == 1
        assert any(a["content_id"] == "vod-old" for a in body["top_assets"])


class TestAverageViewSeconds:
    """Honest proxy metric — mean view length, NOT a duration distribution
    (see the module docstring's HONEST GAP note: no per-event granularity
    is available from AnalyticsStore.report() to build a real histogram)."""

    def test_channel_average_view_seconds(self) -> None:
        base = _base(
            asset_views=[
                AssetViewPoint(
                    content_id="vod-1", day=date(2026, 6, 1), views=10, view_seconds=300
                ),
                AssetViewPoint(content_id="vod-2", day=date(2026, 6, 2), views=5, view_seconds=100),
            ]
        )
        out = build_audience_report(
            base,
            asset_to_channel={"vod-1": "public", "vod-2": "public"},
            period_end=date(2026, 6, 20),
        )
        public = next(c for c in out.channel_summaries if c.channel_id == "public")
        assert public.total_views == 15
        assert public.total_view_seconds == 400
        assert public.average_view_seconds == pytest.approx(400 / 15)

    def test_channel_average_view_seconds_zero_views_is_zero(self) -> None:
        out = build_audience_report(_base())
        # No channels at all when there's no data — nothing to divide by zero on.
        assert out.channel_summaries == []

    def test_asset_average_view_seconds(self) -> None:
        base = _base(
            asset_views=[
                AssetViewPoint(content_id="x", day=date(2026, 6, 1), views=4, view_seconds=200),
            ]
        )
        out = build_audience_report(base, period_end=date(2026, 6, 20))
        assert out.top_assets[0].average_view_seconds == pytest.approx(50.0)

    def test_channel_average_concurrent_viewers_weighted_by_samples(self) -> None:
        """A channel with ~50 average concurrent viewers/day over 2 days at
        288 samples/day (5-min polling) must report ~50, not the
        mean-of-means-over-total-samples bug (~0.17)."""
        base = _base(
            concurrent=[
                LiveConcurrentPoint(
                    channel_id="public",
                    day=date(2026, 6, 1),
                    peak_concurrent_viewers=60,
                    average_concurrent_viewers=50.0,
                    samples=288,
                ),
                LiveConcurrentPoint(
                    channel_id="public",
                    day=date(2026, 6, 2),
                    peak_concurrent_viewers=60,
                    average_concurrent_viewers=50.0,
                    samples=288,
                ),
            ]
        )
        out = build_audience_report(base, period_end=date(2026, 6, 20))
        public = next(c for c in out.channel_summaries if c.channel_id == "public")
        assert public.samples == 576
        assert public.average_concurrent_viewers == pytest.approx(50.0)
