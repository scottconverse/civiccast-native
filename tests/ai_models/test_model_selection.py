# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the S13 model-selection registry entities (data layer, slice 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from civiccast.ai_models.models import (
    FeatureModelRegistry,
    ModelTier,
    detect_summary_model_default,
)


def _tier(key: str = "gemma4-e4b-ollama", **overrides: object) -> ModelTier:
    fields: dict[str, object] = {
        "key": key,
        "provider": "ollama",
        "model_id": "gemma4:e4b",
        "notes": "local default",
    }
    fields.update(overrides)
    return ModelTier(**fields)  # type: ignore[arg-type]


def test_model_tier_constructs_with_model_id_field() -> None:
    # `model_id` starts with pydantic's protected "model_" namespace; this only
    # constructs cleanly (no warning-as-error) if protected_namespaces is off.
    assert _tier().model_id == "gemma4:e4b"


def test_model_tier_rejects_negative_cost() -> None:
    with pytest.raises(ValidationError):
        _tier(cost_per_token_usd=-0.01)


def test_model_tier_rejects_negative_latency() -> None:
    with pytest.raises(ValidationError):
        _tier(latency_p95_ms=-1)


def test_effective_model_key_prefers_operator_selection() -> None:
    reg = FeatureModelRegistry(
        feature="summary",
        default_key="gemma4-12b-ollama",
        available_tiers=[_tier(), _tier(key="gemma4-12b-ollama", model_id="gemma4:12b")],
        operator_selected_key="gemma4-e4b-ollama",
    )
    assert reg.effective_model_key == "gemma4-e4b-ollama"


def test_effective_model_key_falls_back_to_default() -> None:
    reg = FeatureModelRegistry(
        feature="summary",
        default_key="gemma4-12b-ollama",
        available_tiers=[_tier(key="gemma4-12b-ollama", model_id="gemma4:12b")],
    )
    assert reg.effective_model_key == "gemma4-12b-ollama"


def test_adaptive_default_uses_12b_at_16gb() -> None:
    assert detect_summary_model_default(16) == "gemma4-12b-ollama"


def test_adaptive_default_uses_e4b_below_16gb() -> None:
    assert detect_summary_model_default(8) == "gemma4-e4b-ollama"
