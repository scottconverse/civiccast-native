# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Per-tier caption model registry + inventory generation (WP1 adaptive-tier).

Covers the R7-tester-surfaced defect directly: the caption pack verifier used
to hard-code large-v3's exact file inventory as THE required inventory for
the whole component, so any other tier (with its own, legitimately different
file set) structurally failed verification -- and, the scenario that
actually happened, a tier's files could be silently checked against ANOTHER
tier's hashes. See ``.agent-runs/native-windows/wp1-caption-integrity/
OWNER-DECISION-caption-adaptive-tier.md``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from civiccast.native.app_payload import (
    WHISPER_MODEL_FILES,
    WHISPER_MODEL_REPO,
    WHISPER_MODEL_REVISION,
)
from civiccast.native.caption_tiers import (
    CAPTION_TIER_REGISTRY,
    FLOOR_TIER_ID,
    LARGE_V3_TIER_ID,
    CaptionTierBindingError,
    CaptionTierSpec,
    generate_tier_inventory,
)


def test_registry_carries_at_least_the_floor_and_large_v3_tiers() -> None:
    """The owner ruling requires at least two tiers in the pack system."""

    assert {LARGE_V3_TIER_ID, FLOOR_TIER_ID} <= set(CAPTION_TIER_REGISTRY)


def test_large_v3_tier_reuses_the_existing_pinned_identity_verbatim() -> None:
    """Rule: do not change the shipped large-v3 identity."""

    spec = CAPTION_TIER_REGISTRY[LARGE_V3_TIER_ID]
    assert spec.model_repository == WHISPER_MODEL_REPO
    assert spec.model_revision == WHISPER_MODEL_REVISION
    assert spec.model_directory == "faster-whisper-large-v3"
    assert spec.files == dict(WHISPER_MODEL_FILES)
    assert spec.pending is False
    spec.require_bound()  # must not raise


def test_floor_tier_placeholder_shape_is_still_trivially_bindable() -> None:
    """Historical note: this test used to assert the REAL registry's floor
    entry was the unbound ``pending=True`` placeholder (WP1's initial
    per-tier-inventory fix landed the floor tier as a placeholder, on
    purpose, before the R7 measurement named a model). That measurement
    closed on 2026-07-30 (``OWNER-DECISION-caption-adaptive-tier.md``'s
    BINDING section: floor = ``medium``), and :data:`CAPTION_TIER_REGISTRY`'s
    real floor entry is now bound -- see
    ``test_floor_tier_is_bound_to_the_owner_ruled_medium_model`` below.

    What this test still proves, using a LOCAL synthetic spec rather than
    the module registry, is the property the binding relied on: a pending
    placeholder of this exact shape is trivially replaceable by a bound spec
    with real values, with no other code needing to change shape."""

    placeholder = CaptionTierSpec(
        tier_id=FLOOR_TIER_ID,
        model_directory="floor-tier-pending-owner-binding",
        model_repository=None,
        model_revision=None,
        files={},
        pending=True,
    )
    with pytest.raises(CaptionTierBindingError, match="floor"):
        placeholder.require_bound()

    # Binding is exactly: construct a new spec with the same shape and real
    # values -- no code elsewhere needs to change.
    bound = CaptionTierSpec(
        tier_id=placeholder.tier_id,
        model_directory="faster-whisper-medium",
        model_repository="Systran/faster-whisper-medium",
        model_revision="0" * 40,
        files={"model.bin": (123, "a" * 64)},
        pending=False,
    )
    assert bound.require_bound() is bound


def test_floor_tier_is_bound_to_the_owner_ruled_medium_model() -> None:
    """The owner's BINDING ruling (``OWNER-DECISION-caption-adaptive-tier.md``,
    2026-07-30) named ``medium`` as the floor tier: three pre-registered
    CPU-only trials on the replacement R7 (Ryzen 7 8745HS) at 18.68-18.76s
    against a 20.0s derived deadline. The real registry entry must reflect
    that binding: not pending, a non-empty inventory captured by
    ``generate_tier_inventory`` (never hand-transcribed), and an identity
    that names the medium model -- never large-v3's."""

    spec = CAPTION_TIER_REGISTRY[FLOOR_TIER_ID]
    assert spec.pending is False
    assert spec.require_bound() is spec  # must not raise

    assert spec.model_repository == "Systran/faster-whisper-medium"
    assert spec.model_directory == "faster-whisper-medium"
    assert "medium" in spec.model_repository
    assert spec.model_repository != WHISPER_MODEL_REPO
    assert spec.model_revision is not None
    assert spec.model_revision != WHISPER_MODEL_REVISION

    assert spec.files  # non-empty inventory
    assert spec.files != dict(WHISPER_MODEL_FILES)  # never large-v3's inventory
    for size, digest in spec.files.values():
        assert isinstance(size, int) and size > 0
        assert isinstance(digest, str) and len(digest) == 64


def test_generate_tier_inventory_matches_real_bytes_on_disk(tmp_path: Path) -> None:
    """The inventory is generated from actual bytes, never hand-transcribed."""

    model_dir = tmp_path / "medium-snapshot"
    (model_dir / "nested").mkdir(parents=True)
    (model_dir / "config.json").write_bytes(b"{}")
    (model_dir / "nested" / "vocabulary.json").write_bytes(b"vocab-bytes-for-medium-tier")

    inventory = generate_tier_inventory(model_dir)

    assert inventory == {
        "config.json": (2, hashlib.sha256(b"{}").hexdigest()),
        "nested/vocabulary.json": (
            27,
            hashlib.sha256(b"vocab-bytes-for-medium-tier").hexdigest(),
        ),
    }


def test_generate_tier_inventory_rejects_a_symlink(tmp_path: Path) -> None:
    model_dir = tmp_path / "snapshot"
    model_dir.mkdir()
    real = tmp_path / "real.bin"
    real.write_bytes(b"real bytes")
    link = model_dir / "linked.bin"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlink creation is not permitted in this environment")

    with pytest.raises(ValueError, match="symlink"):
        generate_tier_inventory(model_dir)


def test_generate_tier_inventory_rejects_missing_or_empty_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing"):
        generate_tier_inventory(tmp_path / "does-not-exist")

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no files"):
        generate_tier_inventory(empty)
