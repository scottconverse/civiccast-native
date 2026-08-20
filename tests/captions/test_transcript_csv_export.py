# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""CSV export contract tests for committed transcript caption cues."""

from __future__ import annotations

import csv
from io import StringIO

from civiccast.captions import CaptionCue
from civiccast.summary.csv_export import render_transcript_csv


def _rows(csv_text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(StringIO(csv_text)))


class TestTranscriptCsvExport:
    def test_csv_export_uses_stable_column_order_and_escapes_text(self) -> None:
        rendered = render_transcript_csv(
            [
                CaptionCue(
                    cue_id="cue-1",
                    start_seconds=65.123,
                    end_seconds=67.988,
                    text='Motion "passes", 2-1',
                    confidence=0.96,
                    low_confidence=False,
                )
            ]
        )

        assert rendered.splitlines()[0].split(",") == [
            "cue_id",
            "start_seconds",
            "end_seconds",
            "start_timestamp",
            "end_timestamp",
            "text",
            "confidence",
            "low_confidence",
        ]
        assert _rows(rendered)[0]["start_timestamp"] == "00:01:05.123"
        assert _rows(rendered)[0]["text"] == 'Motion "passes", 2-1'

    def test_empty_transcript_exports_header_only(self) -> None:
        rendered = render_transcript_csv([])

        assert rendered.strip() == (
            "cue_id,start_seconds,end_seconds,start_timestamp,end_timestamp,"
            "text,confidence,low_confidence"
        )

    def test_low_confidence_flag_is_explicit_for_partial_review_state(self) -> None:
        rendered = render_transcript_csv(
            [
                CaptionCue(
                    cue_id="cue-low",
                    start_seconds=0.0,
                    end_seconds=3.5,
                    text="uncertain speaker",
                    confidence=0.51,
                    low_confidence=True,
                )
            ]
        )

        row = _rows(rendered)[0]
        assert row["confidence"] == "0.51"
        assert row["low_confidence"] == "true"
