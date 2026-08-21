# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S14 export tests: rollup CSV shape + board PDF rendering."""

from __future__ import annotations

from datetime import UTC, datetime

from civiccast.analytics.exports import export_board_pdf, export_rollups_csv
from civiccast.analytics.models import AnalyticsReport, ViewershipRollupPoint


def _rollup_point(**overrides) -> ViewershipRollupPoint:
    base = {
        "stream_type": "vod",
        "bucket_kind": "day",
        "bucket_start": datetime(2026, 6, 10, tzinfo=UTC),
        "subject_id": "asset-1",
        "viewer_count": 5,
        "time_viewed_seconds": 300,
        "peak_concurrent": None,
        "avg_concurrent": None,
        "samples": 0,
    }
    base.update(overrides)
    return ViewershipRollupPoint(**base)


def _empty_report(**overrides) -> AnalyticsReport:
    base = {
        "generated_at": datetime.now(UTC),
        "range_days": 30,
        "retained_fields": ["event_id"],
        "privacy_boundary": "aggregate-only-no-session-ip-or-viewer-identity",
    }
    base.update(overrides)
    return AnalyticsReport(**base)


class TestCsvExportShape:
    def test_header_and_rows(self) -> None:
        csv_text = export_rollups_csv([_rollup_point(), _rollup_point(subject_id="asset-2", viewer_count=1)])
        lines = csv_text.strip().splitlines()
        assert lines[0] == (
            "stream_type,bucket_kind,bucket_start,subject_id,viewer_count,"
            "time_viewed_seconds,peak_concurrent,avg_concurrent,samples"
        )
        assert len(lines) == 3
        assert "asset-1" in lines[1]
        assert "asset-2" in lines[2]

    def test_empty_list_is_header_only(self) -> None:
        csv_text = export_rollups_csv([])
        assert len(csv_text.strip().splitlines()) == 1


class TestBoardPdfRenders:
    def test_starts_with_pdf_magic_bytes(self) -> None:
        report = _empty_report()
        pdf_bytes = export_board_pdf(
            report,
            station_label="Test Station",
            range_start=datetime(2026, 6, 1, tzinfo=UTC),
            range_end=datetime(2026, 6, 30, tzinfo=UTC),
        )
        assert pdf_bytes.startswith(b"%PDF")

    def test_renders_with_data_and_all_sections(self) -> None:
        report = _empty_report(
            asset_views=[
                {"content_id": "asset-1", "day": "2026-06-10", "views": 5, "view_seconds": 300}
            ],
            live_concurrent_viewers=[
                {
                    "channel_id": "public",
                    "day": "2026-06-10",
                    "peak_concurrent_viewers": 42,
                    "average_concurrent_viewers": 12.5,
                    "samples": 6,
                }
            ],
            year_over_year=[
                {"metric": "viewer_count", "current_period": 10, "prior_period": 0, "delta_pct": None},
                {"metric": "time_viewed_seconds", "current_period": 20, "prior_period": 10, "delta_pct": 100.0},
            ],
        )
        pdf_bytes = export_board_pdf(
            report,
            station_label="Test Station",
            range_start=datetime(2026, 6, 1, tzinfo=UTC),
            range_end=datetime(2026, 6, 30, tzinfo=UTC),
        )
        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 500

    def test_sections_can_be_toggled_off(self) -> None:
        report = _empty_report()
        pdf_bytes = export_board_pdf(
            report,
            station_label="Test Station",
            range_start=datetime(2026, 6, 1, tzinfo=UTC),
            range_end=datetime(2026, 6, 30, tzinfo=UTC),
            include_totals=False,
            include_top_content=False,
            include_yoy=False,
            include_live_peaks=False,
        )
        assert pdf_bytes.startswith(b"%PDF")
