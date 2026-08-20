# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Per-tier caption pack verification (WP1 adaptive-tier).

Exercises ``civiccast.installer.native_packs.verify_caption_pack_tiers``
directly against constructed manifest dicts -- the same lightweight
convention ``tests/installer/test_native_packs.py`` uses for
``_validate_component_contract`` -- so these tests run in milliseconds and
don't need a real 3 GB model file.

The scenario in ``test_verifier_refuses_cross_tier_file_borrowing`` is the
EXACT defect the R7 tester hit: a non-large-v3 tier's manifest entry pointed
at large-v3-hashed bytes and the old verifier could not tell, because it only
ever checked large-v3's hard-coded inventory.
"""

from __future__ import annotations

from typing import Any

import pytest

from civiccast.installer import native_packs
from civiccast.installer.native_packs import NativePackVerificationError
from civiccast.native.app_payload import WHISPER_MODEL_FILES
from civiccast.native.caption_tiers import (
    CAPTION_TIER_REGISTRY,
    FLOOR_TIER_ID,
    LARGE_V3_TIER_ID,
    CaptionTierSpec,
)

_MEDIUM_MODEL_DIRECTORY = "faster-whisper-medium"


def _bind_fake_floor_tier(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[int, str]]:
    """Bind the registry's floor placeholder to a synthetic v2-family tier
    with its OWN inventory, distinct from large-v3's -- exactly how the real
    binding will look once R7 names the floor model, without waiting on it.
    """

    medium_files = {
        "config.json": (11, "b" * 64),
        "vocabulary.json": (1_068_114 - 1, "c" * 64),  # different size from large-v3's on purpose
    }
    monkeypatch.setitem(
        CAPTION_TIER_REGISTRY,
        FLOOR_TIER_ID,
        CaptionTierSpec(
            tier_id=FLOOR_TIER_ID,
            model_directory=_MEDIUM_MODEL_DIRECTORY,
            model_repository="Systran/faster-whisper-medium",
            model_revision="1" * 40,
            files=medium_files,
            pending=False,
        ),
    )
    return medium_files


def _large_v3_file_entries() -> list[dict[str, Any]]:
    return [
        {"path": f"models/faster-whisper-large-v3/{name}", "bytes": size, "sha256": digest}
        for name, (size, digest) in WHISPER_MODEL_FILES.items()
    ]


def _medium_file_entries(medium_files: dict[str, tuple[int, str]]) -> list[dict[str, Any]]:
    return [
        {"path": f"models/{_MEDIUM_MODEL_DIRECTORY}/{name}", "bytes": size, "sha256": digest}
        for name, (size, digest) in medium_files.items()
    ]


def _manifest(*, files: list[dict[str, Any]], tier_ids: list[str]) -> dict[str, Any]:
    return {
        "component": native_packs.CAPTION_COMPONENT,
        "files": files,
        "metadata": {"caption_tiers": tier_ids},
    }


def test_verifier_accepts_a_two_tier_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    medium_files = _bind_fake_floor_tier(monkeypatch)
    manifest = _manifest(
        files=_large_v3_file_entries() + _medium_file_entries(medium_files),
        tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID],
    )

    verified = native_packs.verify_caption_pack_tiers(
        manifest, required_tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID]
    )

    assert set(verified) == {LARGE_V3_TIER_ID, FLOOR_TIER_ID}


def test_verifier_refuses_cross_tier_file_borrowing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A floor-tier file entry pointing at large-v3's bytes/hash must fail --
    each tier is checked against ITS OWN recorded inventory, never another's.
    """

    medium_files = _bind_fake_floor_tier(monkeypatch)
    borrowed_bytes, borrowed_sha256 = WHISPER_MODEL_FILES["vocabulary.json"]
    tampered_medium = [
        {
            "path": f"models/{_MEDIUM_MODEL_DIRECTORY}/config.json",
            **_entry(medium_files, "config.json"),
        },
        {
            "path": f"models/{_MEDIUM_MODEL_DIRECTORY}/vocabulary.json",
            "bytes": borrowed_bytes,
            "sha256": borrowed_sha256,
        },
    ]
    manifest = _manifest(
        files=_large_v3_file_entries() + tampered_medium,
        tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID],
    )

    with pytest.raises(NativePackVerificationError, match=r"floor.*vocabulary\.json|substituted"):
        native_packs.verify_caption_pack_tiers(
            manifest, required_tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID]
        )


def _entry(files: dict[str, tuple[int, str]], name: str) -> dict[str, Any]:
    size, digest = files[name]
    return {"bytes": size, "sha256": digest}


def test_verifier_refuses_a_pack_missing_the_required_floor_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_fake_floor_tier(monkeypatch)
    manifest = _manifest(files=_large_v3_file_entries(), tier_ids=[LARGE_V3_TIER_ID])

    with pytest.raises(NativePackVerificationError, match=r"missing required tier.*floor"):
        native_packs.verify_caption_pack_tiers(
            manifest, required_tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID]
        )


def test_verifier_refuses_extra_files_under_a_tiers_model_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    medium_files = _bind_fake_floor_tier(monkeypatch)
    extra = [
        *_medium_file_entries(medium_files),
        {
            "path": f"models/{_MEDIUM_MODEL_DIRECTORY}/unexpected-extra-file.bin",
            "bytes": 4,
            "sha256": "e" * 64,
        },
    ]
    manifest = _manifest(
        files=_large_v3_file_entries() + extra,
        tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID],
    )

    with pytest.raises(NativePackVerificationError, match=r"unexpected files"):
        native_packs.verify_caption_pack_tiers(
            manifest, required_tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID]
        )


def test_verifier_refuses_an_inventory_claiming_files_the_pack_lacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    medium_files = _bind_fake_floor_tier(monkeypatch)
    incomplete = [_medium_file_entries(medium_files)[0]]  # drop vocabulary.json
    manifest = _manifest(
        files=_large_v3_file_entries() + incomplete,
        tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID],
    )

    with pytest.raises(NativePackVerificationError, match=r"missing declared files"):
        native_packs.verify_caption_pack_tiers(
            manifest, required_tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID]
        )


def test_verifier_refuses_a_pending_unbound_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pending, not-yet-owner-bound tier must never verify as present.

    The floor tier itself was this exact placeholder until the owner's
    BINDING ruling (``OWNER-DECISION-caption-adaptive-tier.md``, 2026-07-30)
    named ``medium`` and :data:`CAPTION_TIER_REGISTRY`'s real floor entry was
    bound to it. This test no longer relies on the real registry carrying an
    unbound tier (it doesn't, anymore) -- it monkeypatches a synthetic
    pending placeholder of the exact shape the floor tier used to have, so
    the ``require_bound()`` refusal path this verifier depends on stays
    covered regardless of the real registry's current binding state.
    """

    monkeypatch.setitem(
        CAPTION_TIER_REGISTRY,
        FLOOR_TIER_ID,
        CaptionTierSpec(
            tier_id=FLOOR_TIER_ID,
            model_directory="floor-tier-pending-owner-binding",
            model_repository=None,
            model_revision=None,
            files={},
            pending=True,
        ),
    )
    manifest = _manifest(
        files=_large_v3_file_entries(),
        tier_ids=[LARGE_V3_TIER_ID, FLOOR_TIER_ID],
    )

    with pytest.raises(NativePackVerificationError, match=r"not yet bound|pending"):
        native_packs.verify_caption_pack_tiers(manifest, required_tier_ids=[LARGE_V3_TIER_ID])


def test_verifier_refuses_an_unknown_declared_tier() -> None:
    manifest = _manifest(files=_large_v3_file_entries(), tier_ids=[LARGE_V3_TIER_ID, "turbo-xl"])

    with pytest.raises(NativePackVerificationError, match=r"unknown tier"):
        native_packs.verify_caption_pack_tiers(manifest, required_tier_ids=[LARGE_V3_TIER_ID])


def test_verifier_requires_the_caption_tiers_metadata_declaration() -> None:
    manifest = {
        "component": native_packs.CAPTION_COMPONENT,
        "files": _large_v3_file_entries(),
        "metadata": {},
    }

    with pytest.raises(NativePackVerificationError, match=r"per-tier inventory declaration"):
        native_packs.verify_caption_pack_tiers(manifest, required_tier_ids=[LARGE_V3_TIER_ID])
