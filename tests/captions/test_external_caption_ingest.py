# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""External caption appliance ingest tests."""

from __future__ import annotations

from civiccast.captions.external import (
    ExternalCaptionIngestRequest,
    ingest_external_caption_review_items,
    parse_external_caption_payload,
)
from civiccast.captions.review import InMemoryCaptionReviewStore


def test_webvtt_payload_becomes_reviewable_cues() -> None:
    payload = ExternalCaptionIngestRequest(
        request_id="caption hw 001",
        asset_id="meeting-1",
        appliance_id="caption-appliance-a",
        source_label="Caption appliance A",
        protocol="webvtt",
        payload="""WEBVTT

00:00:01.000 --> 00:00:03.500
Good evening.

00:00:04.000 --> 00:00:06.000
The meeting is called to order.
""",
    )

    cues = parse_external_caption_payload(payload)

    assert [cue.text for cue in cues] == [
        "Good evening.",
        "The meeting is called to order.",
    ]
    assert cues[0].cue_id == "external-caption-hw-001-000001"
    assert cues[0].start_seconds == 1.0
    assert cues[0].end_seconds == 3.5


def test_srt_payload_and_decoded_cea_payload_share_review_queue_contract() -> None:
    store = InMemoryCaptionReviewStore()
    srt_payload = ExternalCaptionIngestRequest(
        request_id="caption-hw-002",
        asset_id="meeting-2",
        appliance_id="caption-appliance-b",
        source_label="Caption appliance B",
        protocol="srt",
        default_confidence=0.79,
        payload="""1
00:00:02,000 --> 00:00:05,000
Roll call begins.
""",
    )
    cea_payload = ExternalCaptionIngestRequest(
        request_id="caption-hw-003",
        asset_id="meeting-2",
        appliance_id="caption-appliance-b",
        source_label="Caption appliance B",
        protocol="cea-608-708",
        payload="00:00:05.000 --> 00:00:07.000 | Motion carries.",
    )

    srt_result = ingest_external_caption_review_items(srt_payload, store)
    cea_result = ingest_external_caption_review_items(cea_payload, store)

    assert (
        srt_result.proof_boundary
        == "external-caption-appliance-to-review-queue-no-hardware-control"
    )
    assert srt_result.review_items[0].low_confidence is True
    assert cea_result.review_items[0].original_text == "Motion carries."
    assert [item.review_item_id for item in store.list(asset_id="meeting-2")] == [
        "external-caption-hw-002-000001-review",
        "external-caption-hw-003-000001-review",
    ]
