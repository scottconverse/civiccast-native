from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = REPO_ROOT / "docs" / "releases" / "evidence" / "v1.8.9-local-rc-package-proof.md"


def test_package_evidence_records_manifest_and_wheel_hashes() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")

    assert "civiccast-1.8.9-release-artifacts-manifest.json" in text
    assert "F5BE3711AF3B59CDE094D1397D389859C228B7CA878C7E68A2A6A30B2A323081" in text
    assert "civiccast-1.8.9-py3-none-any.whl" in text
    assert "6a8ff24ec2d0283bd7f9d9c553ba8efe570cf25ca7bb27be0a1230fa98322516" in text


def test_package_evidence_records_clean_import_result() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")

    assert "Successfully installed civiccast-1.8.9" in text
    assert "1.8.9" in text


def test_package_evidence_names_the_proof_boundary() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")

    for boundary in (
        "not a Windows installer smoke proof",
        "app-store package proof",
        "live hardware proof",
        "hosted relay proof",
        "production deployment proof",
    ):
        assert boundary in text
