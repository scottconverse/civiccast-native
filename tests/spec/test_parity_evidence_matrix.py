from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "docs" / "spec" / "2.0" / "parity-evidence-matrix.json"
FORBIDDEN_PUBLIC_NAMES = (
    "cable" + "cast",
    "cable" + " cast",
    "cable" + "cast.tv",
)
EXPECTED_GAPS = {
    "native-ott-mobile-app-suite",
    "gated-private-video-access",
    "vod-preroll-messaging",
    "multi-zone-cg-bulletin-board",
    "av-router-control",
    "caption-appliance-integration",
    "squeezebacks-and-lbar-live-overlays",
    "rtmp-cloud-ingest-relay",
    "expanded-audience-measurement-reporting",
    "contributor-submission-portal",
}


def _load_matrix() -> dict[str, object]:
    return json.loads(MATRIX_PATH.read_text(encoding="utf-8"))


def test_parity_matrix_covers_every_planned_gap() -> None:
    matrix = _load_matrix()

    gaps = matrix["gaps"]
    assert isinstance(gaps, list)
    assert {gap["id"] for gap in gaps} == EXPECTED_GAPS
    assert len(gaps) == 10


def test_parity_matrix_uses_release_gate_statuses() -> None:
    matrix = _load_matrix()
    allowed = set(matrix["allowed_statuses"])
    assert allowed == {"complete", "complete_with_external_dependency", "human_blocked"}

    for gap in matrix["gaps"]:
        status = gap["status"]
        assert status in allowed
        if status == "complete":
            assert gap["external_dependency"] is None
        if status == "complete_with_external_dependency":
            assert gap["external_dependency"]


def test_parity_matrix_evidence_paths_exist() -> None:
    matrix = _load_matrix()

    for gap in matrix["gaps"]:
        evidence = gap["evidence"]
        assert evidence, gap["id"]
        for evidence_path in evidence:
            path = REPO_ROOT / evidence_path
            assert path.exists(), f"{gap['id']} evidence path is missing: {evidence_path}"


def test_parity_matrix_public_language_avoids_direct_competitor_names() -> None:
    text = MATRIX_PATH.read_text(encoding="utf-8")
    lowered = text.lower()

    for forbidden in FORBIDDEN_PUBLIC_NAMES:
        assert forbidden not in lowered


def test_parity_matrix_claim_boundary_blocks_overclaiming() -> None:
    matrix = _load_matrix()
    boundary = str(matrix["public_claim_boundary"]).lower()

    for required_phrase in (
        "app-store publication",
        "hardware certification",
        "legal certification",
        "managed-service operation",
        "live-device validation",
    ):
        assert required_phrase in boundary
