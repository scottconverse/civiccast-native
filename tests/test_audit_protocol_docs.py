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
    release_url = (
        f"https://github.com/scottconverse/civiccast/releases/tag/{CURRENT_BETA_RELEASE_TAG}"
    )
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    public_release = release_url in readme
    public_release_docs = (
        REPO_ROOT / "docs/install-windows.html",
        REPO_ROOT / "docs/adoption/early-adopter-quickstart.md",
        REPO_ROOT / "docs/public/civiccast-org-holding-page.md",
        REPO_ROOT
        / f"docs/public/github-discussions/{CURRENT_BETA_RELEASE_TAG}-community-seed-pack.md",
    )

    for path in public_release_docs:
        text = path.read_text(encoding="utf-8")
        assert "github.com/scottconverse/civiccast/releases/latest" not in text
        assert CURRENT_BETA_RELEASE_TAG in text
        if public_release:
            assert release_url in text
            assert "public" in text.lower()
            assert "passed" in text.lower() or "validated" in text.lower()
        else:
            assert release_url not in text
            assert "unpublished" in text.lower() or "not approved" in text.lower()

        if "Longmont" in text or "LPM" in text:
            assert CURRENT_BETA_RELEASE_TAG in text

        assert "Status: v1.7 early adoption candidate guidance" not in text
        assert "draft public-facing holding page for the v1.7 early adoption" not in text


def test_general_adoption_docs_are_not_stale_v17_guidance() -> None:
    active_adoption_docs = (
        REPO_ROOT / "docs/adoption/early-adopter-quickstart.md",
        REPO_ROOT / "docs/adoption/procurement-legal-brief.md",
        REPO_ROOT / "docs/adoption/release-policy.md",
        REPO_ROOT / "docs/adoption/support-intake.md",
        REPO_ROOT / "docs/public/civiccast-org-holding-page.md",
    )

    for path in active_adoption_docs:
        text = path.read_text(encoding="utf-8")
        assert "Status: v1.7 early adoption candidate guidance" not in text
        assert "current beta" in text or "beta" in text


def test_public_docs_do_not_overclaim_sdi_or_cg_proof() -> None:
    public_page = (REPO_ROOT / "docs/index.html").read_text(encoding="utf-8")

    assert "DeckLink SDI through the engine's own sink" not in public_page
    assert "Multi-zone CG designer" not in public_page
    assert "SDI/DeckLink remains config-gated and hardware proof pending" in public_page
    # Multi-zone template rendering (primary/ticker/schedule/logo zones) shipped
    # production-wired in #352 (gate finding D-5: the page previously claimed
    # it "remains contract-only until runtime proof lands", which went stale
    # the moment #352 merged). The page must say the multi-zone rendering that
    # DID ship is wired, but must NOT claim the two items that genuinely remain
    # contract-only (live-video-in-zone, per-channel board audio; spec S15 §5)
    # are done.
    assert "multi-zone template rendering" in public_page
    assert "Live video embedded in a zone" in public_page
    assert "contract-only until runtime proof lands" in public_page
