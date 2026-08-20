# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""3.2 LPM Lab topology contract tests."""

from __future__ import annotations

from civiccast.control_room.lpm_lab import build_lpm_lab_profiles, validate_lpm_lab_profiles


def test_lpm_lab_profiles_are_exactly_the_three_known_topologies() -> None:
    profiles = build_lpm_lab_profiles()

    assert set(profiles) == {
        "fixed-studio-livestreaming",
        "portable-field-kit",
        "digitization-obs",
    }
    assert validate_lpm_lab_profiles(profiles) == []


def test_empty_profile_map_is_not_treated_as_canonical_profiles() -> None:
    issues = validate_lpm_lab_profiles({})

    assert issues
    assert "Expected exactly" in issues[0]


def test_lpm_lab_profile_sources_are_structured_and_claim_bound() -> None:
    for profile in build_lpm_lab_profiles().values():
        assert profile.sources
        for source in profile.sources:
            assert source.source_id
            assert source.accessed_at == "2026-06-30"
            assert source.source_type in {
                "direct-lpm-doc",
                "vendor-doc",
                "civiccast-inference",
                "station-device-confirmed",
            }
            assert source.claim_ids


def test_fixed_studio_profile_preserves_decklink_inference_and_aida_contract() -> None:
    fixed = build_lpm_lab_profiles()["fixed-studio-livestreaming"]
    devices = {device.contract_id: device for device in fixed.devices}

    decklink = devices["fixed-decklink-duo-2-channels-2-3-4"]
    assert decklink.device_class == "decklink"
    assert "best-read inference" in decklink.evidence_basis
    assert "channels 2/3/4" in decklink.evidence_basis

    ptz = devices["fixed-aida-ndi-ptz"]
    assert ptz.device_class == "ptz-visca-ndi"
    assert "UDP port 52381" in ptz.integration_surface
    assert "52381" in ptz.evidence_basis
    assert "9600" in ptz.evidence_basis


def test_portable_field_kit_has_no_decklink_or_ptz_and_has_egress_targets() -> None:
    portable = build_lpm_lab_profiles()["portable-field-kit"]
    device_classes = {device.device_class for device in portable.devices}

    assert "decklink" not in device_classes
    assert not any("ptz" in device_class for device_class in device_classes)
    assert {"Castr", "LPM YouTube stream"}.issubset(portable.egress_destinations)
    assert "DeckLink card" in portable.required_absences
    assert "AIDA/PTZ target" in portable.required_absences


def test_digitization_profile_is_obs_proof_not_live_switching_claim() -> None:
    digitization = build_lpm_lab_profiles()["digitization-obs"]
    devices = {device.contract_id: device for device in digitization.devices}

    assert devices["digitization-obs-studio"].device_class == "obs"
    assert "not a live production-switching proof" in " ".join(digitization.not_claimed)


def test_lpm_lab_profiles_do_not_embed_public_default_credentials() -> None:
    body = "\n".join(
        profile.model_dump_json().lower() for profile in build_lpm_lab_profiles().values()
    )

    assert "admin/admin" not in body
    assert "password=" not in body
    assert "secret=" not in body
    assert "token=" not in body


def test_every_device_declares_required_checks() -> None:
    for profile in build_lpm_lab_profiles().values():
        for device in profile.devices:
            assert device.required_checks, f"{profile.profile_id}/{device.contract_id}"
