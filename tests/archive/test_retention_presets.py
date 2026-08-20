# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the v1.0 retention preset subset."""

from __future__ import annotations

import pytest

from civiccast.archive.retention_presets import (
    V1_0_RETENTION_PRESETS,
    get_retention_preset,
    list_retention_presets,
)


def test_v1_0_subset_covers_top_ten_release_states() -> None:
    assert set(V1_0_RETENTION_PRESETS) == {
        "CA",
        "TX",
        "FL",
        "NY",
        "PA",
        "IL",
        "OH",
        "GA",
        "NC",
        "MI",
    }


def test_presets_are_operator_reviewable() -> None:
    for preset in V1_0_RETENTION_PRESETS.values():
        assert preset.recording_minimum_days > 0
        assert preset.source_url.startswith("https://")
        assert preset.disposition_trigger
        assert "review" in preset.review_note.lower() or "confirm" in preset.review_note.lower()


def test_lookup_is_case_insensitive() -> None:
    assert get_retention_preset("ca").state_name == "California"


def test_unknown_state_is_not_silent() -> None:
    with pytest.raises(KeyError, match=r"unsupported v1\.0 retention preset state"):
        get_retention_preset("WA")


def test_list_order_is_stable() -> None:
    assert [preset.state_code for preset in list_retention_presets()] == sorted(
        V1_0_RETENTION_PRESETS
    )
