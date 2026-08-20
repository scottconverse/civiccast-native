# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Playback policy store tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.playback_policy.models import (
    PlaybackPolicyEvaluationRequest,
    PlaybackPolicyUpdate,
    ViewerAccount,
)
from civiccast.playback_policy.store import PlaybackPolicyStore


def test_public_policy_allows_and_audits_without_viewer() -> None:
    store = PlaybackPolicyStore()

    result = store.evaluate(
        PlaybackPolicyEvaluationRequest(asset_id="agenda", channel_id="government")
    )
    audit = store.audit_log()

    assert result.allowed is True
    assert result.policy.access_tier == "public"
    assert audit.events[0].decision == "allowed"


def test_authenticated_and_invite_only_policy_require_viewer_entitlement() -> None:
    store = PlaybackPolicyStore()
    store.upsert_policy(
        "channel",
        "education",
        PlaybackPolicyUpdate(access_tier="authenticated"),
    )
    anonymous = store.evaluate(
        PlaybackPolicyEvaluationRequest(asset_id="workshop", channel_id="education")
    )
    signed_in = store.evaluate(
        PlaybackPolicyEvaluationRequest(
            asset_id="workshop",
            channel_id="education",
            viewer=ViewerAccount(account_id="viewer-one", display_name="Viewer One"),
        )
    )

    assert anonymous.allowed is False
    assert signed_in.allowed is True

    store.upsert_policy(
        "asset",
        "invited-workshop",
        PlaybackPolicyUpdate(access_tier="invite_only", invite_group_id="board-training"),
    )
    blocked = store.evaluate(
        PlaybackPolicyEvaluationRequest(
            asset_id="invited-workshop",
            channel_id="education",
            viewer=ViewerAccount(account_id="viewer-two", display_name="Viewer Two"),
        )
    )
    allowed = store.evaluate(
        PlaybackPolicyEvaluationRequest(
            asset_id="invited-workshop",
            channel_id="education",
            viewer=ViewerAccount(
                account_id="viewer-three",
                display_name="Viewer Three",
                invite_groups=["board-training"],
            ),
        )
    )

    assert blocked.allowed is False
    assert allowed.allowed is True
    assert store.audit_log().events[-1].access_tier == "invite_only"


def test_public_record_guardrail_rejects_gating_at_store_boundary() -> None:
    store = PlaybackPolicyStore()

    with pytest.raises(ValueError, match="public-record"):
        store.upsert_policy(
            "asset",
            "council-record",
            PlaybackPolicyUpdate(
                access_tier="invite_only",
                invite_group_id="private",
                public_record_required=True,
            ),
        )


def test_playback_policy_store_persists_policy_and_audit(tmp_path: Path) -> None:
    state_path = tmp_path / "playback-policy-state.json"
    store = PlaybackPolicyStore(state_path)

    store.upsert_policy(
        "channel",
        "education",
        PlaybackPolicyUpdate(access_tier="authenticated"),
    )
    store.evaluate(
        PlaybackPolicyEvaluationRequest(
            asset_id="workshop",
            channel_id="education",
            viewer=ViewerAccount(account_id="viewer-one", display_name="Viewer One"),
        )
    )

    restored = PlaybackPolicyStore(state_path)
    policy = restored.get_policy("channel", "education")
    audit = restored.audit_log()

    assert policy.access_tier == "authenticated"
    assert audit.events[-1].asset_id == "workshop"
