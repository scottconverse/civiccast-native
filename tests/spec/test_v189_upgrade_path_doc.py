from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "ops" / "v1.7.3-to-v1.8.9-upgrade-path.md"


def _doc_text() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_upgrade_runbook_names_supported_start_and_target_versions() -> None:
    text = _doc_text()

    assert "v1.7.3" in text
    assert "v1.8.9" in text
    assert "release-candidate" in text


def test_upgrade_runbook_uses_existing_installer_controls() -> None:
    text = _doc_text()

    for endpoint in (
        "/api/staff/installer/backup",
        "/api/staff/installer/restore/rehearsal",
        "/api/staff/installer/update-rollback/preflight",
        "/api/staff/installer/update-rollback/rollback-artifact",
        "/api/staff/installer/update-rollback/rollback-rehearsal",
        "/api/staff/installer/update-rollback/maintenance-window",
        "/api/staff/installer/update-rollback/post-update-proof",
        "/api/staff/installer/support-bundle",
        "/health",
        "/api/version",
    ):
        assert endpoint in text


def test_upgrade_runbook_covers_every_parity_surface() -> None:
    text = _doc_text()

    for surface in (
        "Native OTT and mobile app suite",
        "Gated and private video access",
        "VOD preroll messaging",
        "Full multi-zone CG bulletin board",
        "AV router control",
        "Caption appliance integration",
        "Squeezebacks and L-bar live overlays",
        "RTMP cloud ingest relay",
        "Expanded audience measurement and reporting",
        "Contributor submission portal",
    ):
        assert surface in text


def test_upgrade_runbook_preserves_public_claim_boundaries() -> None:
    text = _doc_text().lower()

    for boundary in (
        "app-store publication",
        "live router hardware behavior",
        "live caption appliance behavior",
        "hosted relay connectivity",
        "production analytics traffic",
        "legal compliance",
    ):
        assert boundary in text
