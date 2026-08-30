# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 E2/T2/Q1/W1 — the provisioning surfaces must install the adaptive summary default.

The summary default is adaptive: ``gemma4:12b`` on >=16GB boxes WITH a real GPU,
``gemma4:e4b`` everywhere else -- including every CPU-only box regardless of RAM
(field evidence 2026-08-29, candidate #17: RAM alone does not predict whether 12B
can complete a CPU-only summary; see ``detect_summary_model_default``).
Pre-fix, both provisioning surfaces (online ``download_release_models`` and the offline
``model_bundle`` / ``build_model_bundle_manifest``) shipped e4b-only, so the seeded 12B
default was never present on the majority (>=16GB) hardware class and the first summary
run raised ``OllamaRuntimeUnavailableError``. These tests assert each provisioning plan
contains the runtime tag of ``detect_summary_model_default(ram)`` for the detected box,
tying the provisioning surfaces to the SAME default-selection logic the seed uses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from civiccast.ai_models.catalog import catalog_tier
from civiccast.ai_models.models import detect_summary_model_default
from civiccast.installer import service
from civiccast.installer.model_bundle import _REQUIRED_MODELS, build_v11_model_bundle_manifest
from civiccast.installer.model_download import (
    SUMMARY_MODELS,
    download_release_models,
    summary_provisioning_tags,
)
from civiccast.installer.models import ModelBundleRequest


def _adaptive_default_tag(ram: int, *, has_gpu: bool = True) -> str:
    """The runtime tag of the adaptive summary default for ``ram`` GB.

    ``has_gpu`` defaults True here (unlike the production default) because
    this module's whole point is proving the provisioning surfaces install
    the 12B tag on the boxes that are actually eligible for it (>=16GB RAM
    AND a real GPU); the CPU-only path has its own dedicated test below.
    """
    return catalog_tier(detect_summary_model_default(ram, has_gpu=has_gpu)).model_id


@pytest.mark.parametrize("ram", [8, 16, 25])
def test_online_pull_plan_includes_the_adaptive_default_tag(ram: int) -> None:
    # The suggested gate test: for ram in {8,16,25} the provisioning plan must include
    # catalog_tier(detect_summary_model_default(ram, has_gpu=True)).model_id.
    report = download_release_models(dry_run=True, system_ram_total_gb=ram)
    planned_sources = {item.source for item in report.items}

    assert _adaptive_default_tag(ram) in planned_sources
    # The conservative e4b fallback is always present too (so an override is local-ready).
    assert "gemma4:e4b" in planned_sources
    assert "translategemma:4b" in planned_sources


def test_cpu_only_adaptive_default_is_always_e4b() -> None:
    # Field evidence 2026-08-29: a CPU-only box never gets 12B as the default,
    # regardless of RAM -- the provisioning surfaces still stage both tags
    # (asserted elsewhere in this module) so an operator CAN select 12B
    # manually, but the *default* the box would actually run is e4b.
    for ram in (8, 16, 25, 64):
        assert _adaptive_default_tag(ram, has_gpu=False) == "gemma4:e4b"


def test_online_pull_plan_default_provisions_both_summary_tags() -> None:
    # With no RAM hint, the plan provisions BOTH summary tags so the adaptive default is
    # present regardless of detected RAM (the air-gapped/unknown-hardware path).
    report = download_release_models(dry_run=True)
    planned_sources = {item.source for item in report.items}

    assert set(SUMMARY_MODELS) <= planned_sources
    assert {"gemma4:12b", "gemma4:e4b", "translategemma:4b"} <= planned_sources


@pytest.mark.parametrize("ram", [8, 16, 25])
def test_summary_provisioning_tags_include_the_adaptive_default(ram: int) -> None:
    tags = summary_provisioning_tags(ram)
    assert _adaptive_default_tag(ram) in tags
    assert "gemma4:e4b" in tags


def test_online_pull_executes_both_summary_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    # Not just the plan: a real (non-dry) pull must run `ollama pull` for both summary
    # tags + translation (whisper/floor-caption go via the huggingface downloaders).
    pulled: list[str] = []
    report = download_release_models(
        dry_run=False,
        whisper_downloader=lambda _cache: "/fake/whisper",
        floor_caption_downloader=lambda _cache: "/fake/floor-caption",
        ollama_pull=pulled.append,
    )

    assert "gemma4:12b" in pulled
    assert "gemma4:e4b" in pulled
    assert "translategemma:4b" in pulled
    assert report.status == "ok"


def test_offline_bundle_required_models_include_the_adaptive_default() -> None:
    # >=16GB default (gemma4:12b) AND the e4b fallback must both ship in the air-gap
    # bundle — there is no network fallback offline.
    required_names = {str(model["name"]) for model in _REQUIRED_MODELS}

    assert _adaptive_default_tag(16) in required_names
    assert _adaptive_default_tag(8) in required_names
    assert {"gemma4:12b", "gemma4:e4b"} <= required_names


def test_offline_bundle_manifest_ships_both_summary_tags(tmp_path: Path) -> None:
    for filename in (
        "whisper-large-v3.tar.zst",
        "gemma4-12b.tar.zst",
        "gemma4-e4b.tar.zst",
        "translategemma-4b.tar.zst",
    ):
        (tmp_path / filename).write_bytes(f"{filename} bytes".encode())

    manifest = build_v11_model_bundle_manifest(output_dir=tmp_path)
    names = {model.name for model in manifest.models}

    assert {"gemma4:12b", "gemma4:e4b"} <= names


def test_service_air_gap_manifest_ships_both_summary_tags() -> None:
    # The third provisioning surface (service.build_model_bundle_manifest) must also ship
    # both summary artifacts when summary is included.
    manifest = service.build_model_bundle_manifest(ModelBundleRequest(profile="public-meetings"))
    ids = {item.id for item in manifest.items}

    assert "gemma-4-12b-summary" in ids
    assert "gemma-4e4b-summary" in ids


def test_first_run_models_step_names_a_provisioned_default() -> None:
    # W1: the installer "models" step must name a default that is actually provisioned.
    # On a >=16GB box WITH a real GPU the named default is gemma4-12b-ollama, which
    # the plan now installs.
    default_key = detect_summary_model_default(25, has_gpu=True)
    plan = service.build_first_run_plan(
        profile="public-meetings",
        recommended_tier="tier-1",
        summary_default_key=default_key,
    )
    models_step = next(step for step in plan.steps if step.id == "models")

    assert default_key in models_step.summary
    # The named default's runtime tag is in the provisioning plan (no overpromise).
    planned = {item.source for item in download_release_models(dry_run=True).items}
    assert catalog_tier(default_key).model_id in planned
