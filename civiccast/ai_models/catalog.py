# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Hard-coded model catalog (S13, decision A).

CivicCast does not fetch the model list from a provider API (decision A: hard-coded).
This module is the single source of truth for the §3.1.1 ``key -> model_id (runtime
tag) -> provider`` mapping plus the cost / latency / privacy / network flags that the
operator console renders and the service enforces.

The DEFAULT for every feature is the LOCAL (zero cloud fee, on-device, private) tier.
Summary's default is adaptive (12B QAT on >=16GB, e4b on smaller boxes). The CLOUD tiers
(Ollama Cloud ``gemma4:31b-cloud`` + the OpenRouter mid-tier) ship FUNCTIONAL (D13):
they appear as real, selectable options, are priced per token, require network, and are
off until the operator selects one and accepts the cost — they are not stubs.
"""

from __future__ import annotations

from civiccast.ai_models.models import (
    AiFeature,
    FeatureModelRegistry,
    ModelTier,
    detect_summary_model_default,
)

# Every feature the catalog covers (the operator-controllable AI surfaces).
CATALOG_FEATURES: tuple[AiFeature, ...] = ("captions", "summary", "translation")

_GEMMA4_LICENSE = "https://ai.google.dev/gemma/terms"
_WHISPER_LICENSE = "https://github.com/openai/whisper/blob/main/LICENSE"
_OPENROUTER_LICENSE = "https://openrouter.ai/terms"

# The hosted Ollama Cloud tier is offered by BOTH summary and translation. It is
# defined ONCE here (single source of truth for its cost / tag / privacy flags) and
# referenced by both feature lists below, so its cost rate and runtime tag can never
# drift between the two features or bind to the "wrong" copy (prior M6). Note: the
# ``notes`` are feature-neutral because one object is shared across features.
_GEMMA4_31B_CLOUD = ModelTier(
    key="gemma4-31b-cloud",
    provider="ollama-cloud",
    model_id="gemma4:31b-cloud",
    cost_per_token_usd=1e-7,
    latency_p95_ms=1800,
    private=False,
    requires_network=True,
    min_ram_gb=8,
    license_url=_GEMMA4_LICENSE,
    notes="Ollama Cloud Gemma 4 31B — hosted, metered per token. Default OFF.",
)

# Per-feature tier lists. ``key`` is the stable registry slug the operator/API
# references; ``model_id`` is the runtime tag the adapter loads (§3.1.1).
_CATALOG: dict[AiFeature, list[ModelTier]] = {
    "summary": [
        ModelTier(
            key="gemma4-12b-ollama",
            provider="ollama",
            model_id="gemma4:12b",
            cost_per_token_usd=0.0,
            latency_p95_ms=4200,
            private=True,
            requires_network=False,
            min_ram_gb=16,
            license_url=_GEMMA4_LICENSE,
            notes="Local Gemma 4 12B QAT — long-context summary default on >=16GB boxes.",
        ),
        ModelTier(
            key="gemma4-e4b-ollama",
            provider="ollama",
            model_id="gemma4:e4b",
            cost_per_token_usd=0.0,
            latency_p95_ms=2600,
            private=True,
            requires_network=False,
            min_ram_gb=8,
            license_url=_GEMMA4_LICENSE,
            notes="Local Gemma 4 e4b — summary fallback for 8GB boxes.",
        ),
        _GEMMA4_31B_CLOUD,
        ModelTier(
            key="gemini-2.5-flash-openrouter",
            provider="openrouter",
            model_id="google/gemini-2.5-flash",
            cost_per_token_usd=3e-7,
            latency_p95_ms=1500,
            private=False,
            requires_network=True,
            min_ram_gb=8,
            license_url=_OPENROUTER_LICENSE,
            notes="OpenRouter mid-tier frontier (Gemini 2.5 Flash) — hosted, per-token. Default OFF.",
        ),
    ],
    "translation": [
        ModelTier(
            key="translategemma-4b-ollama",
            provider="ollama",
            model_id="translategemma:4b",
            cost_per_token_usd=0.0,
            latency_p95_ms=1900,
            private=True,
            requires_network=False,
            min_ram_gb=8,
            license_url=_GEMMA4_LICENSE,
            notes="Local TranslateGemma 4B — Spanish translation default (never gemma4:4b).",
        ),
        _GEMMA4_31B_CLOUD,
    ],
    "captions": [
        # BOUND 2026-07-30 per OWNER-DECISION-caption-adaptive-tier.md: the caption
        # FLOOR tier is `medium` (Systran/faster-whisper-medium, pinned in
        # civiccast.native.caption_tiers.CAPTION_TIER_REGISTRY) and is the mandatory
        # CPU-only baseline -- see `_DEFAULT_KEY["captions"]` below. large-v3 remains
        # the optional QUALITY tier, still offered here and auto-selected only when
        # measured hardware allows.
        ModelTier(
            key="whisper-medium-faster",
            provider="external",
            model_id="whisper-medium",
            cost_per_token_usd=0.0,
            latency_p95_ms=500,
            private=True,
            requires_network=False,
            min_ram_gb=4,
            license_url=_WHISPER_LICENSE,
            notes=(
                "faster-whisper medium (int8) on-box — CPU-only caption FLOOR tier "
                "(mandatory baseline), captions default."
            ),
        ),
        ModelTier(
            key="whisper-large-v3-faster",
            provider="external",
            model_id="whisper-large-v3",
            cost_per_token_usd=0.0,
            latency_p95_ms=900,
            private=True,
            requires_network=False,
            min_ram_gb=8,
            license_url=_WHISPER_LICENSE,
            notes=(
                "faster-whisper large-v3 (int8) on-box — captions QUALITY tier, "
                "auto-selected only when measured hardware allows."
            ),
        ),
    ],
}

# The local default slug per feature (summary is resolved adaptively at build time).
_DEFAULT_KEY: dict[AiFeature, str] = {
    # OWNER-DECISION-caption-adaptive-tier.md (2026-07-30, BINDING): the caption FLOOR
    # tier (medium) is the mandatory CPU-only baseline and the default here. large-v3
    # is the optional quality tier (see caption_tier_selection.select_caption_tier /
    # the native adaptive-tier packaging system for the auto-upgrade policy).
    "captions": "whisper-medium-faster",
    "summary": "gemma4-12b-ollama",  # placeholder; overridden by detect_summary_model_default
    "translation": "translategemma-4b-ollama",
}


def catalog_tiers_for(feature: AiFeature) -> list[ModelTier]:
    """Every selectable tier for ``feature`` (fresh copies; immutable to callers)."""
    return [tier.model_copy(deep=True) for tier in _CATALOG[feature]]


def catalog_tier(key: str) -> ModelTier:
    """Resolve a registry slug to its catalog :class:`ModelTier` (first match wins)."""
    for tiers in _CATALOG.values():
        for tier in tiers:
            if tier.key == key:
                return tier.model_copy(deep=True)
    raise KeyError(f"Unknown model key: {key!r}")


def catalog_tier_for_feature(feature: AiFeature, key: str) -> ModelTier | None:
    """Resolve ``key`` only within ``feature``'s tiers (None if not offered there)."""
    for tier in _CATALOG[feature]:
        if tier.key == key:
            return tier.model_copy(deep=True)
    return None


def default_key_for(feature: AiFeature, *, system_ram_total_gb: int = 8) -> str:
    """The (possibly adaptive) local default slug for ``feature``."""
    if feature == "summary":
        return detect_summary_model_default(system_ram_total_gb)
    return _DEFAULT_KEY[feature]


def build_feature_registry(
    feature: AiFeature,
    *,
    system_ram_total_gb: int = 8,
    operator_selected_key: str | None = None,
) -> FeatureModelRegistry:
    """Assemble a :class:`FeatureModelRegistry` from the catalog + an optional selection."""
    return FeatureModelRegistry(
        feature=feature,
        default_key=default_key_for(feature, system_ram_total_gb=system_ram_total_gb),
        adaptive_default=(feature == "summary"),
        available_tiers=catalog_tiers_for(feature),
        operator_selected_key=operator_selected_key,
    )


__all__ = [
    "CATALOG_FEATURES",
    "build_feature_registry",
    "catalog_tier",
    "catalog_tier_for_feature",
    "catalog_tiers_for",
    "default_key_for",
]
