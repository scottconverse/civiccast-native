# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from civiccast._version import __version__
from civiccast.installer.models import ModelBundleRequest
from civiccast.installer.service import (
    build_first_run_plan,
    build_model_bundle_manifest,
    run_first_health_check,
)


def test_first_run_plan_covers_v010_wizard_requirements() -> None:
    plan = build_first_run_plan(profile="public-meetings", recommended_tier="tier-1-plus")

    assert plan.profile == "public-meetings"
    assert plan.recommended_tier == "tier-1-plus"
    assert plan.cloud_fallback_default == "off"
    assert plan.time_to_first_broadcast_minutes < 8 * 60

    step_ids = {step.id for step in plan.steps}
    assert {
        "profile",
        "hardware",
        "storage",
        "operator-account",
        "publish-targets",
        "models",
        "health",
    } <= step_ids
    assert any("Internet Archive" in step.summary for step in plan.steps)
    assert any("You are streaming" in step.next_step for step in plan.steps)


def test_first_run_health_check_fails_closed_for_unconfigured_publish_surfaces() -> None:
    report = run_first_health_check(profile="public-meetings")

    assert report.ready is False
    assert {check.id for check in report.checks} == {
        "mtls-local-ca",
        "portal",
        "internet-archive",
        "youtube",
        "local-nas",
        "podcast",
        "signed-transcript",
        "subscriber-notifications",
        "activitypub",
    }
    checked = {check.id: check for check in report.checks}
    assert checked["internet-archive"].state == "credential_or_secret_required"
    assert "CIVICCAST_INTERNET_ARCHIVE_ACCESS_KEY" in checked["internet-archive"].next_step
    assert checked["podcast"].state == "ok"
    assert checked["signed-transcript"].state == "ok"
    assert checked["activitypub"].state == "ok"


def test_model_bundle_manifest_includes_hash_verified_air_gap_models() -> None:
    manifest = build_model_bundle_manifest(ModelBundleRequest(profile="public-meetings"))

    assert manifest.bundle_name == f"civiccast-models-public-meetings-v{__version__}.tar"
    # Bundle ships BOTH summary tags so the adaptive 12B/e4b default is present offline
    # regardless of detected RAM (S13 E2/T2/Q1); the 12B model adds ~8GB.
    assert manifest.estimated_size_gb == 20.0
    assert {item.id for item in manifest.items} == {
        "faster-whisper-large-v3",
        "gemma-4-12b-summary",
        "gemma-4e4b-summary",
        "translate-gemma-4b",
    }
    assert all(len(item.sha256) == 64 for item in manifest.items)
    assert {item.sha256 for item in manifest.items}.isdisjoint({"1" * 64, "2" * 64, "3" * 64})


def test_model_bundle_manifest_can_omit_optional_model_groups() -> None:
    manifest = build_model_bundle_manifest(
        ModelBundleRequest(
            profile="public-meetings",
            include_translation=False,
            include_summary=False,
            include_captions=True,
        )
    )

    assert [item.id for item in manifest.items] == ["faster-whisper-large-v3"]


def test_models_step_surfaces_the_adaptive_summary_default_for_an_override() -> None:
    # S13 §5.3 / §6.1: the first-run wizard shows the computed adaptive default and an
    # override option. On a >=16GB box the models step must name gemma4-12b-ollama.
    plan = build_first_run_plan(
        profile="public-meetings",
        recommended_tier="tier-1",
        summary_default_key="gemma4-12b-ollama",
    )

    models = next(step for step in plan.steps if step.id == "models")
    assert "gemma4-12b-ollama" in models.summary
    assert "override" in models.next_step.lower()


def test_models_step_default_falls_back_to_e4b_when_no_summary_default_given() -> None:
    # back-compat: callers that do not pass a default get the conservative e4b seed
    # named, so the step never invents a 12B default the box may not support.
    plan = build_first_run_plan(profile="public-meetings", recommended_tier="tier-1")

    models = next(step for step in plan.steps if step.id == "models")
    assert "gemma4-e4b-ollama" in models.summary
