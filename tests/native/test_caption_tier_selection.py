# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""The runtime tier-selection seam: fail closed, log every branch, never
auto-substitute (WP1 adaptive-tier owner ruling, anti-silent-swap clause)."""

from __future__ import annotations

import pytest

from civiccast.native.caption_tier_selection import (
    CAPTIONED_DEGRADATION_EVENT,
    TIER_SELECTED_EVENT,
    TierSelectionDecision,
    TierSelectionError,
    select_caption_tier,
)


def test_selects_the_requested_tier_when_available_and_logs_it() -> None:
    result = select_caption_tier(
        available_tier_ids={"floor", "large-v3"},
        floor_tier_id="floor",
        decision=TierSelectionDecision(
            requested_tier_id="large-v3",
            allow_floor_fallback=True,
            reason="measured capacity allows large-v3",
        ),
    )

    assert result.tier_id == "large-v3"
    assert result.fell_back_to_floor is False
    assert result.log_event == {
        "event": TIER_SELECTED_EVENT,
        "tier": "large-v3",
        "requested": "large-v3",
        "fallback": False,
        "reason": "measured capacity allows large-v3",
    }


def test_missing_floor_tier_is_refused_regardless_of_the_request() -> None:
    """The mandatory CPU baseline being absent is always a hard refusal."""

    with pytest.raises(TierSelectionError, match="floor"):
        select_caption_tier(
            available_tier_ids={"large-v3"},
            floor_tier_id="floor",
            decision=TierSelectionDecision(
                requested_tier_id="floor",
                allow_floor_fallback=True,
                reason="startup",
            ),
        )


def test_unavailable_requested_tier_without_fallback_permission_fails_loud() -> None:
    """Never auto-substitute: an unavailable tier refuses unless the policy
    explicitly allowed a floor fallback."""

    with pytest.raises(TierSelectionError, match="large-v3"):
        select_caption_tier(
            available_tier_ids={"floor"},
            floor_tier_id="floor",
            decision=TierSelectionDecision(
                requested_tier_id="large-v3",
                allow_floor_fallback=False,
                reason="corrupt pack",
            ),
        )


def test_unavailable_requested_tier_with_fallback_permission_degrades_and_logs() -> None:
    result = select_caption_tier(
        available_tier_ids={"floor"},
        floor_tier_id="floor",
        decision=TierSelectionDecision(
            requested_tier_id="large-v3",
            allow_floor_fallback=True,
            reason="large-v3 pack missing at activation",
        ),
    )

    assert result.tier_id == "floor"
    assert result.fell_back_to_floor is True
    assert result.log_event == {
        "event": CAPTIONED_DEGRADATION_EVENT,
        "tier": "floor",
        "requested": "large-v3",
        "fallback": True,
        "reason": "large-v3 pack missing at activation",
    }


def test_requested_tier_equal_to_floor_is_not_treated_as_a_fallback() -> None:
    """Requesting the floor tier directly (e.g. it IS the capacity decision)
    must not be logged as a degradation event."""

    result = select_caption_tier(
        available_tier_ids={"floor", "large-v3"},
        floor_tier_id="floor",
        decision=TierSelectionDecision(
            requested_tier_id="floor",
            allow_floor_fallback=False,
            reason="measured capacity requires the floor tier",
        ),
    )

    assert result.tier_id == "floor"
    assert result.fell_back_to_floor is False
    assert result.log_event["event"] == TIER_SELECTED_EVENT
