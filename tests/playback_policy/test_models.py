# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Playback policy model tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from civiccast.playback_policy.models import (
    PlaybackPolicyConfig,
    PrerollCreative,
    PrerollSequence,
    ViewerAccount,
    utc_now,
)


def test_viewer_account_is_distinct_from_operator_or_contributor() -> None:
    viewer = ViewerAccount(account_id="viewer-one", display_name="Viewer One")

    assert viewer.tier == "viewer"

    with pytest.raises(ValidationError, match="viewer tier"):
        ViewerAccount(
            account_id="bad-viewer",
            tier="operator",
            display_name="Operator One",
        )


def test_public_record_policy_cannot_be_gated_or_authenticated_rss() -> None:
    with pytest.raises(ValidationError, match="public-record"):
        PlaybackPolicyConfig(
            subject_type="asset",
            subject_id="council-record",
            access_tier="authenticated",
            public_record_required=True,
            updated_at=utc_now(),
        )

    with pytest.raises(ValidationError, match="public-record"):
        PlaybackPolicyConfig(
            subject_type="asset",
            subject_id="archive-complete",
            authenticated_rss_enabled=True,
            public_archive_complete=True,
            updated_at=utc_now(),
        )


def test_preroll_sequence_is_playback_only_and_accessibility_ready() -> None:
    creative = PrerollCreative(
        creative_id="station-card",
        kind="graphic",
        asset_url="/media/preroll/station-card.png",
        duration_seconds=10,
        skippable_after_seconds=5,
        accessible_label="Station announcement graphic",
    )

    sequence = PrerollSequence(enabled=True, creatives=[creative])

    assert sequence.creatives[0].accessible_label == "Station announcement graphic"

    with pytest.raises(ValidationError, match="archival exports"):
        PrerollSequence(
            enabled=True,
            creatives=[creative],
            apply_to_archive_exports=True,
        )
