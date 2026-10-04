from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
# Derived from docs/releases/release-truth.yaml's authored `current` field --
# the sole authored source for which tag is the published, validated
# release -- NOT from civiccast/_version.py. The two diverge on purpose
# during a release-prep bump: civiccast/_version.py moves to the next
# owner-held candidate (a `staging` entry with no verification record yet)
# while `current` stays on the published tag whose verification record the
# public front doors must keep linking. check_v17_adoption_gate.py keeps
# the same distinction.
CURRENT_BETA_RELEASE_TAG = yaml.safe_load(
    (REPO_ROOT / "docs" / "releases" / "release-truth.yaml").read_text(encoding="utf-8")
)["current"]


def test_active_public_docs_link_validated_current_candidate() -> None:
    """Every public front door must name the current release tag and link
    its validated verification record (docs/releases/v<version>-verification.md)
    -- not a floating "latest" link, and not stale "unpublished candidate"
    language once the tag is actually published (see
    docs/releases/release-truth.yaml for which is true right now)."""

    public_release_docs = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs/index.html",
        REPO_ROOT / "docs/install-windows.html",
    )
    verification_doc_name = f"{CURRENT_BETA_RELEASE_TAG}-verification.md"

    for path in public_release_docs:
        text = path.read_text(encoding="utf-8")
        normalized = " ".join(text.lower().split())
        assert "github.com/scottconverse/civiccast/releases/latest" not in text
        assert CURRENT_BETA_RELEASE_TAG in text
        assert verification_doc_name.lower() in normalized, (
            f"{path.name} does not link the validated candidate's verification "
            f"record ({verification_doc_name})."
        )


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
    # Keep the limitations, not the retired landing page's exact phrasing.
    plain = " ".join(re.sub(r"<[^>]+>", " ", public_page).split())
    assert "Real cable-operator acceptance and SDI capture cards have not been tested." in plain
    assert "Cable headend and SDI cards are unproven." in plain
    assert "Not run at a real station. No human field tester has signed off." in plain


@pytest.mark.parametrize(
    "limitation",
    [
        "Real cable-operator acceptance and SDI capture cards have not been tested.",
        "are unproven.",
        "No human field tester has signed off.",
    ],
)
def test_public_limitations_cannot_be_removed(
    monkeypatch: pytest.MonkeyPatch, limitation: str
) -> None:
    read_text = Path.read_text

    def omitted(path: Path, *args: object, **kwargs: object) -> str:
        text = read_text(path, *args, **kwargs)
        if path == REPO_ROOT / "docs/index.html":
            assert limitation in text
            return text.replace(limitation, "")
        return text

    monkeypatch.setattr(Path, "read_text", omitted)
    with pytest.raises(AssertionError):
        test_public_docs_do_not_overclaim_sdi_or_cg_proof()
