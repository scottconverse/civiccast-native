from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = REPO_ROOT / "docs" / "releases" / "evidence" / "v2.0.0-final-package-proof.md"
VM_EVIDENCE_PATH = (
    REPO_ROOT / "docs" / "releases" / "evidence" / "v2.0.0-virtualbox-clean-windows-proof.md"
)


def test_v200_package_evidence_records_manifest_and_installer_hashes() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")

    assert "civiccast-2.0.0-release-artifacts-manifest.json" in text
    assert "BB1FA59C2296F808BF5BA367D7B41FD535206E2EEE55C7C6E244B0A4EF620182" in text
    assert "civiccast-2.0.0-windows-setup.exe" in text
    assert "BA7C63BA27FA3C378254426A30BAEF10B6FA89B5ADF30E71C89185E86B573FFD" in text
    assert "E7DAEDDED64A92635331ADF05F86AA08042BD3C44F833572296E3C1B4F40B447" in text
    assert "1475FAF9B3C1FEDA25AA49507A2444D60E06F9969A42E97F3AA189F74E4CABCA" in text


def test_v200_package_evidence_records_clean_import_result() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")

    assert "Successfully installed civiccast-2.0.0" in text
    assert "2.0.0" in text


def test_v200_package_evidence_records_wsl2_fresh_user_pass() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")

    assert "wsl2-fresh-user" in text
    assert "Result: `partial`" in text
    assert "faster-whisper" in text


def test_v200_package_evidence_records_final_cleanroom_pass() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")

    assert "d4ab622908d5080e4e9ff120cf675c110e922884" in text
    assert "CivicCast cleanroom: ALL GATES GREEN" in text
    assert "1347 passed" in text


def test_v200_package_evidence_names_the_proof_boundary() -> None:
    text = EVIDENCE_PATH.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    for boundary in (
        "not an installer-to-dashboard runtime proof on a WSL2-capable clean Windows target",
        "app-store publication proof",
        "live hardware proof",
        "hosted relay proof",
        "legal certification",
        "production deployment proof",
    ):
        assert boundary in normalized


def test_v200_virtualbox_evidence_records_native_installer_execution() -> None:
    text = VM_EVIDENCE_PATH.read_text(encoding="utf-8")
    normalized = " ".join(text.split())

    assert "civiccast-v200-proof-cleanwin" in text
    assert "civiccast-2.0.0-windows-setup.exe" in text
    assert "15A10DEEF570FE25A8F2A4A86BC5B2871E0D01F6333E41D5430A847AB8530C11" in text
    assert "WSL to `2.7.3`" in normalized
    assert "does not expose virtualization for WSL2" in normalized
    assert "installer-to-dashboard runtime proof" in text
