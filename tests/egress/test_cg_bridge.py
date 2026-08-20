# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

from __future__ import annotations

from civiccast.cg.service import build_emergency_overlay, build_overlay_contract
from civiccast.egress.cg_bridge import (
    CG_EGRESS_PROOF_BOUNDARY,
    build_cg_overlay_clear_egress_proof,
    build_cg_overlay_egress_proof,
)


def test_cg_overlay_egress_proof_uses_real_contract_without_eas_claim() -> None:
    proof = build_cg_overlay_egress_proof(
        overlay=build_emergency_overlay(overlay_id="notice-1", severity="warning"),
        overlay_contract=build_overlay_contract(channel_id="gov"),
    )

    assert proof.status == "READY"
    assert proof.channel_id == "gov"
    assert proof.overlay_id == "notice-1"
    assert proof.overlay_contract_format == "json-overlay-v1"
    assert proof.overlay_contract_boundary == "approved-cg-zones-to-linear-overlay-contract"
    assert proof.egress_proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    assert proof.operator_label == "CivicCast emergency banner"
    assert proof.eas_claim == "not_eas"
    assert proof.blocker is None
    assert any("does not claim EAS" in claim for claim in proof.not_claimed)


def test_cg_overlay_egress_proof_blocks_empty_overlay_contract() -> None:
    overlay_contract = build_overlay_contract(channel_id="gov").model_copy(update={"zone_count": 0})

    proof = build_cg_overlay_egress_proof(
        overlay=build_emergency_overlay(),
        overlay_contract=overlay_contract,
    )

    assert proof.status == "BLOCKED"
    assert proof.blocker == "EGRESS_CG_OVERLAY_CONTRACT_HAS_NO_ZONES"
    assert proof.eas_claim == "not_eas"


def test_cg_overlay_clear_proof_keeps_non_eas_boundary() -> None:
    proof = build_cg_overlay_clear_egress_proof(channel_id="gov", overlay_id="notice-1")

    assert proof.status == "CLEARED"
    assert proof.channel_id == "gov"
    assert proof.overlay_id == "notice-1"
    assert proof.egress_proof_boundary == CG_EGRESS_PROOF_BOUNDARY
    assert proof.operator_label == "CivicCast emergency banner cleared"
    assert proof.eas_claim == "not_eas"
    assert any("does not claim EAS" in claim for claim in proof.not_claimed)
