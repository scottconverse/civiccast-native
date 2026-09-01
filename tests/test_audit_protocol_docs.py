from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
# Derived from the single source of truth (civiccast/_version.py) so this
# policy check can't drift against a version bump.
CURRENT_BETA_RELEASE_TAG = (
    "v"
    + (
        (REPO_ROOT / "civiccast" / "_version.py")
        .read_text(encoding="utf-8")
        .split('__version__ = "', 1)[1]
        .split('"', 1)[0]
    )
)


def test_mandatory_audit_protocol_is_repo_local() -> None:
    protocol = REPO_ROOT / "docs/process/CIVICCAST_AUDIT_PROTOCOL.md"
    self_audit = REPO_ROOT / "docs/process/5-lens-self-audit.md"
    claude = REPO_ROOT / "CLAUDE.md"

    assert protocol.exists()
    assert "repo-local mandatory protocol" in protocol.read_text(encoding="utf-8")

    for path in (claude, self_audit):
        text = path.read_text(encoding="utf-8")
        assert "docs/process/CIVICCAST_AUDIT_PROTOCOL.md" in text
        assert "CIVICCAST_AUDIT_PROTOCOL.md" in text
        assert "OneDrive" not in text
        assert "feedback_5_lens_self_audit_before_push.md" not in text


def test_active_public_docs_link_validated_current_candidate() -> None:
    public_release_docs = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs/index.html",
        REPO_ROOT / "docs/install-windows.html",
    )

    for path in public_release_docs:
        text = path.read_text(encoding="utf-8")
        normalized = " ".join(text.lower().split())
        assert "github.com/scottconverse/civiccast/releases/latest" not in text
        assert CURRENT_BETA_RELEASE_TAG in text
        assert "owner-held unpublished candidate" in normalized
        assert "no installer" in normalized or "no public installer" in normalized
        assert "not a public or production release" in normalized


def test_retired_adoption_docs_are_classified_as_historical() -> None:
    retired_adoption_docs = (
        REPO_ROOT / "docs/adoption/early-adopter-quickstart.md",
        REPO_ROOT / "docs/public/civiccast-org-holding-page.md",
    )

    for path in retired_adoption_docs:
        text = path.read_text(encoding="utf-8").lower()
        assert "historical" in text or "superseded" in text
        assert ("not this" in text and "repository" in text) or "do not masquerade" in text


def test_public_docs_do_not_overclaim_sdi_or_cg_proof() -> None:
    public_page = (REPO_ROOT / "docs/index.html").read_text(encoding="utf-8")

    assert "DeckLink SDI through the engine's own sink" not in public_page
    assert "Multi-zone CG designer" not in public_page
    assert "Physical DeckLink SDI capture and acceptance" in public_page
    assert "Real cable-operator headend acceptance" in public_page
    assert "Sustained production use at a real PEG station" in public_page
