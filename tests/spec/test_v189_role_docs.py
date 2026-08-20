from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_MAP = REPO_ROOT / "docs" / "spec" / "2.0" / "v1.8.9-role-documentation-map.md"
ROLE_GUIDES = {
    "Station admins": REPO_ROOT / "docs" / "ops" / "v2.0-station-admin-guide.md",
    "Operators": REPO_ROOT / "docs" / "ops" / "v2.0-operator-guide.md",
    "Viewers": REPO_ROOT / "docs" / "public" / "v2.0-viewer-guide.md",
    "Contributors": REPO_ROOT / "docs" / "public" / "v2.0-contributor-guide.md",
    "Integrators": REPO_ROOT / "docs" / "ops" / "v2.0-integrator-guide.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_role_documentation_map_links_existing_files() -> None:
    text = _read(DOC_MAP)
    paths = re.findall(r"`([^`]+)`", text)

    assert paths
    for path in paths:
        assert (REPO_ROOT / path).exists(), path


def test_role_documentation_map_names_every_role() -> None:
    text = _read(DOC_MAP)

    for role, guide in ROLE_GUIDES.items():
        assert role in text
        assert str(guide.relative_to(REPO_ROOT)).replace("\\", "/") in text


def test_role_guides_have_claim_boundary_language() -> None:
    required_boundaries = (
        "app-store",
        "hardware",
        "legal",
        "managed-service",
    )

    combined = "\n".join(_read(path).lower() for path in ROLE_GUIDES.values())
    for boundary in required_boundaries:
        assert boundary in combined


def test_operator_and_integrator_guides_cover_facility_and_overlay_workflows() -> None:
    combined = (_read(ROLE_GUIDES["Operators"]) + "\n" + _read(ROLE_GUIDES["Integrators"])).lower()

    for term in ("router", "caption", "overlay", "l-bar", "squeezeback", "relay"):
        assert term in combined
