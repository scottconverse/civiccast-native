# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 per-token cost (decision A: $USD/token + estimate).

Money is :class:`decimal.Decimal`, never float. Local tiers cost $0. Cloud tiers
are priced from the catalog ``cost_per_token_usd`` over realized prompt+completion
token counts.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from civiccast.ai_models.cloud.cost import estimate_cost_usd


def test_local_tier_is_free() -> None:
    # whisper-large-v3-faster has cost_per_token_usd == 0.0 in the catalog.
    cost = estimate_cost_usd("whisper-large-v3-faster", prompt_tokens=1000, completion_tokens=1000)
    assert cost == Decimal("0")


def test_cloud_tier_cost_is_decimal_and_positive() -> None:
    cost = estimate_cost_usd("gemma4-31b-cloud", prompt_tokens=1000, completion_tokens=500)
    assert isinstance(cost, Decimal)
    # gemma4-31b-cloud is 1e-7 USD/token over 1500 tokens -> 1.5e-4 USD.
    assert cost == Decimal("1500") * Decimal("1e-7")
    assert cost > 0


def test_openrouter_tier_cost_uses_catalog_rate() -> None:
    # gemini-2.5-flash-openrouter is 3e-7 USD/token over 200 tokens.
    cost = estimate_cost_usd("gemini-2.5-flash-openrouter", prompt_tokens=120, completion_tokens=80)
    assert cost == Decimal("200") * Decimal("3e-7")


def test_zero_tokens_is_zero_cost() -> None:
    assert estimate_cost_usd("gemma4-31b-cloud", prompt_tokens=0, completion_tokens=0) == Decimal(
        "0"
    )


def test_unknown_model_key_raises() -> None:
    with pytest.raises(KeyError):
        estimate_cost_usd("does-not-exist", prompt_tokens=1, completion_tokens=1)


def test_negative_token_count_rejected() -> None:
    with pytest.raises(ValueError, match=r"negative|token"):
        estimate_cost_usd("gemma4-31b-cloud", prompt_tokens=-1, completion_tokens=10)


def test_feature_scoped_cost_resolves_via_that_features_tier() -> None:
    # gemma4-31b-cloud is offered for BOTH summary and translation; a feature-scoped
    # estimate resolves the rate from that feature's tier (never a wrong-feature copy).
    summary_cost = estimate_cost_usd(
        "gemma4-31b-cloud", prompt_tokens=1000, completion_tokens=500, feature="summary"
    )
    translation_cost = estimate_cost_usd(
        "gemma4-31b-cloud", prompt_tokens=1000, completion_tokens=500, feature="translation"
    )
    assert summary_cost == Decimal("1500") * Decimal("1e-7")
    # Both features share the one cloud tier definition, so the rate is identical.
    assert summary_cost == translation_cost


def test_feature_scoped_cost_rejects_key_not_offered_for_that_feature() -> None:
    # The OpenRouter frontier tier is offered for summary but NOT translation; a
    # feature-scoped estimate must refuse it rather than silently fall through.
    with pytest.raises(KeyError):
        estimate_cost_usd(
            "gemini-2.5-flash-openrouter",
            prompt_tokens=10,
            completion_tokens=10,
            feature="translation",
        )
