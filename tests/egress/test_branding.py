# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

import pytest

from civiccast.cg.models import CgOverlayContract
from civiccast.cg.service import build_emergency_overlay, build_overlay_contract
from civiccast.egress.branding import BRANDING_PROOF_BOUNDARY, build_branding_filter_plan
from civiccast.egress.models import CanonicalProfile


def test_branding_filter_plan_maps_real_cg_contract_to_safe_area_regions() -> None:
    plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        profile=CanonicalProfile(width=1280, height=720),
    )

    assert plan.channel_id == "gov"
    assert plan.overlay_contract_format == "json-overlay-v1"
    assert plan.overlay_contract_boundary == "approved-cg-zones-to-linear-overlay-contract"
    assert plan.proof_boundary == BRANDING_PROOF_BOUNDARY
    assert plan.safe_area_pixels == 36
    assert plan.eas_claim == "not_eas"
    assert plan.emergency_overlay_id is None
    assert plan.output_video_label == "v_cg_6"
    assert len(plan.regions) == 6
    assert plan.regions[0].region == "main"
    assert plan.regions[0].x == 36
    assert "movie='/api/public/cg/channels/gov/snapshot'" in plan.filter_complex
    assert "overlay=x=36:y=36" in plan.filter_complex


def test_branding_filter_plan_prioritizes_emergency_alert_without_eas_claim() -> None:
    plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        emergency_overlay=build_emergency_overlay(overlay_id="storm-warning"),
    )

    assert plan.operator_label == "CivicCast emergency banner"
    assert plan.emergency_overlay_id == "storm-warning"
    assert plan.eas_claim == "not_eas"
    assert plan.regions[-1].zone_kind == "alert"
    assert any("does not claim FCC EAS" in claim for claim in plan.not_claimed)


def test_branding_filter_plan_can_make_relative_snapshot_url_ffmpeg_readable() -> None:
    plan = build_branding_filter_plan(
        overlay_contract=build_overlay_contract(channel_id="gov"),
        snapshot_base_url="http://127.0.0.1:8000",
    )

    assert plan.overlay_source_url == "http://127.0.0.1:8000/api/public/cg/channels/gov/snapshot"
    assert (
        "movie='http://127.0.0.1:8000/api/public/cg/channels/gov/snapshot'" in plan.filter_complex
    )


def test_branding_filter_plan_rejects_emergency_without_alert_region() -> None:
    contract = build_overlay_contract(channel_id="gov")
    no_alert = CgOverlayContract(
        channel_id=contract.channel_id,
        snapshot_url=contract.snapshot_url,
        safe_area_percent=contract.safe_area_percent,
        regions=[region for region in contract.regions if region.zone_kind != "alert"],
        zone_count=contract.zone_count - 1,
        proof_boundary=contract.proof_boundary,
    )

    with pytest.raises(ValueError, match="alert region"):
        build_branding_filter_plan(
            overlay_contract=no_alert,
            emergency_overlay=build_emergency_overlay(),
        )
