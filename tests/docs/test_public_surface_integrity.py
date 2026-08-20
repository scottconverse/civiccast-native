"""Public-surface integrity guard for the beta.

These tests keep the user-facing surfaces honest and usable after signing landed:
  1. No LIVE user-facing doc may claim the software is unsigned / un-certificated /
     signed-via-SignPath (all false since Azure Trusted Signing shipped), nor promise
     an "unknown-publisher" warning (it now shows the verified publisher).
  2. The landing page (docs/index.html) must not link ABOVE its published /docs root
     (Pages publishes only /docs, so ``../`` links 404).
  3. Withdrawn packages must not be installable, while the current controlled beta
     must be linked from the release surface.

Historical/verification/audit docs are intentionally excluded — they record past state.

This is a doc-vs-reality consistency gate; it is expected to FAIL until the rc8 doc
rewrites land, then stay green.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CURRENT_RELEASE_TAG = (
    "v"
    + (
        (REPO / "civiccast" / "_version.py")
        .read_text(encoding="utf-8")
        .split('__version__ = "', 1)[1]
        .split('"', 1)[0]
    )
)
WITHDRAWN_RELEASE_TAG = "v1.0.0-rc13"

# How the current line is described to the public. A surface that offers the
# download must also name the framing, so a reader never sees a Download button
# without the scope it ships under.
CURRENT_RELEASE_FRAMING = "controlled beta"

# Live, user-facing surfaces a PEG operator or their IT actually reads.
LIVE_DOCS = [
    "README.md",
    "INSTALL-WINDOWS.md",
    "CODE_SIGNING_POLICY.md",
    "docs/tester/SMARTSCREEN-WALKTHROUGH.md",
    "docs/tester/START-HERE.md",
    "docs/install/windows-release-trust.md",
    "docs/USER-MANUAL.md",
    "docs/adoption/early-adopter-quickstart.md",
    "docs/adoption/release-policy.md",
    "docs/installer/cross-platform-installer.md",
    "docs/tester/lpm-beta-test-handoff.md",
    "docs/tester/known-limitations.md",
    "docs/tester/nontechnical-walkthrough.md",
    "docs/tester/technical-walkthrough.md",
    "docs/technical-ops-reference.md",
    "docs/spec/spec.md",
]

# Claims that are FALSE now that the Windows installer is Authenticode-signed.
STALE_SIGNING_CLAIMS = [
    r"not\s+Authenticode-signed",
    r"NOT\s+signed",
    r"installer is\s+unsigned",
    r"unsigned\s+(open-source|private)?\s*(build|beta)",
    r"we'd rather.{0,60}certificate",
    r"no\s+(purchased\s+)?(Authenticode\s+)?code-signing certificate",
    r"SignPath",
    r"unknown[- ]publisher warning",
    r"may be unsigned",
    r"installer is unsigned at",
    r"signing is D5",
    r"SmartScreen policy prevents",
]

# TE-3 (gate-civiccast): the phrase list above only catches the EXACT prior
# wording. A contributor rewording the same false claim ("ships without a code
# signature", "carries no certificate") would sail through it. This coarse
# trip-wire flags EVERY "unsigned"-family mention in a live doc; each must be in
# the allowlist below (a small set of genuinely-true, non-Windows-installer uses),
# so a NEW/reworded mention gets human eyes instead of silently passing.
UNSIGNED_FAMILY = re.compile(
    r"\b(?:unsigned|not signed|no code[- ]?sign\w*|without a (?:code )?signature)\b",
    re.IGNORECASE,
)
# Known-legitimate mentions (substring must appear on the flagged line). Adding to
# this list is a deliberate, reviewable act — that is the point.
ALLOWED_UNSIGNED_CONTEXTS = [
    'hardcoded "unsigned" literal',  # README: describes the build-metadata fix
    "unsigned software would say",  # SMARTSCREEN: contrast vs "Unknown publisher"
    "allow unsigned software",  # SMARTSCREEN: IT-policy note (none needed)
    "unsigned install manifest",  # USER-MANUAL: a tests-only env var
    "unsigned manifests",  # cross-platform-installer: a blocked state
    "builds remain unsigned",  # spec: macOS Gatekeeper (genuinely unsigned)
    "builds the unsigned installer, then",  # CODE_SIGNING_POLICY: pipeline stage before signing
]


def _unallowlisted_unsigned_lines(rel: str, text: str) -> list[str]:
    problems = []
    for i, line in enumerate(text.splitlines(), 1):
        if UNSIGNED_FAMILY.search(line):
            low = line.lower()
            if not any(allowed.lower() in low for allowed in ALLOWED_UNSIGNED_CONTEXTS):
                problems.append(f"{rel}:{i}: {line.strip()[:100]!r}")
    return problems


_EXISTING_LIVE_DOCS = [d for d in LIVE_DOCS if (REPO / d).exists()]

# Published HTML pages (Pages serves these rendered; the .md files serve raw).
HTML_DOCS = ["docs/index.html", "docs/install-windows.html"]


@pytest.mark.parametrize("rel", _EXISTING_LIVE_DOCS)
def test_no_stale_unsigned_claims_in_live_docs(rel: str) -> None:
    text = (REPO / rel).read_text(encoding="utf-8")
    hits = []
    for pat in STALE_SIGNING_CLAIMS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            line = text[: m.start()].count("\n") + 1
            hits.append(f"{rel}:{line}: {m.group(0)!r}")
    assert not hits, (
        "Live doc still asserts the software is unsigned/un-certificated:\n" + "\n".join(hits)
    )


@pytest.mark.parametrize("rel", _EXISTING_LIVE_DOCS + [d for d in HTML_DOCS if (REPO / d).exists()])
def test_no_unallowlisted_unsigned_mentions(rel: str) -> None:
    # Semantic trip-wire (TE-3): any "unsigned"-family word in a live doc must be
    # a known-legitimate use; a reworded stale claim lands here for human review.
    text = (REPO / rel).read_text(encoding="utf-8")
    problems = _unallowlisted_unsigned_lines(rel, text)
    assert not problems, (
        "Unallowlisted 'unsigned'-family mention in a live doc (reword of a stale "
        "signing claim, or a new legitimate use to allowlist):\n" + "\n".join(problems)
    )


def test_semantic_trip_wire_catches_reworded_stale_claims() -> None:
    # Mutation test: prove the trip-wire goes red on wordings the phrase list misses.
    for bad in (
        "The release build carries no code signature.",
        "The Windows installer ships unsigned for now.",
        "Windows shows this because the .exe is not signed.",
    ):
        assert _unallowlisted_unsigned_lines("x.md", bad), f"missed: {bad!r}"
    # ...and does NOT fire on an allowlisted legitimate line.
    assert not _unallowlisted_unsigned_lines("x.md", "macOS builds remain unsigned (Gatekeeper).")


@pytest.mark.parametrize("rel", [d for d in HTML_DOCS if (REPO / d).exists()])
def test_published_html_has_no_links_escaping_docroot(rel: str) -> None:
    # GitHub Pages publishes only /docs, so any ../ href escapes the docroot and
    # 404s live (this is exactly how the LEGAL-NOTICES link broke). Guard every
    # published HTML page, not just the landing page.
    html = (REPO / rel).read_text(encoding="utf-8")
    escaping = re.findall(r'href="(\.\./[^"]+)"', html)
    assert not escaping, (
        f"{rel} links escape the published /docs root (will 404 on Pages): {escaping}"
    )


def test_landing_page_has_one_coherent_current_release_posture() -> None:
    html = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    current_release_link = f"releases/tag/{CURRENT_RELEASE_TAG}"
    assert f"releases/tag/{WITHDRAWN_RELEASE_TAG}" not in html
    assert "withdrawn from beta use" in html.lower()
    assert CURRENT_RELEASE_TAG in html
    if current_release_link in html:
        assert CURRENT_RELEASE_FRAMING in html.lower()
    else:
        assert "owner-held unpublished" in html.lower()


def test_readme_has_one_coherent_current_release_posture() -> None:
    text = (REPO / "README.md").read_text(encoding="utf-8")
    assert f"releases/tag/{WITHDRAWN_RELEASE_TAG}" not in text
    assert "withdrawn from beta use" in text.lower()
    assert CURRENT_RELEASE_TAG in text
    if f"releases/tag/{CURRENT_RELEASE_TAG}" in text:
        assert CURRENT_RELEASE_FRAMING in text.lower()
    else:
        assert "owner-held unpublished" in text.lower()


def test_landing_page_docs_are_not_raw_markdown() -> None:
    for f in ("docs/index.html", "docs/install-windows.html"):
        html = (REPO / f).read_text(encoding="utf-8")
        raw = re.findall(r'href="(?!http)(?!#)(?!mailto:)[^"]+\.md"', html)
        assert not raw, f"{f} links to raw .md (serves raw markdown on Pages): {raw}"


def test_landing_page_has_no_withdrawn_release_download_cta() -> None:
    html = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
    prims = re.findall(r'class="button primary"[^>]*>([^<]+)<', html)
    assert prims, "no primary buttons found"
    assert f"Download {WITHDRAWN_RELEASE_TAG.rsplit('-', 1)[-1]}" not in prims
    assert "Do not install rc13" in html


def test_lpm_handoff_does_not_hardcode_a_stale_installer_hash() -> None:
    """The LPM beta handoff must point testers at the release's own .sidecar.json,
    not a hardcoded SHA-256 that goes stale every release (it pinned an rc7 hash that
    never matched the real signed rc7 installer, hard-stopping the named beta partner)."""
    doc = REPO / "docs" / "tester" / "lpm-beta-test-handoff.md"
    if not doc.exists():
        return
    hexes = re.findall(r"[0-9a-fA-F]{64}", doc.read_text(encoding="utf-8"))
    assert not hexes, (
        f"LPM handoff hardcodes installer hash(es) instead of pointing to the sidecar: {hexes}"
    )


@pytest.mark.parametrize("rel", [d for d in HTML_DOCS if (REPO / d).exists()])
def test_no_stale_unsigned_claims_in_html_docs(rel: str) -> None:
    """The published HTML pages must not claim the Windows installer is unsigned
    or that SmartScreen blocks 'unsigned' software (it is Authenticode-signed)."""
    text = (REPO / rel).read_text(encoding="utf-8")
    hits = []
    for pat in STALE_SIGNING_CLAIMS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            line = text.count(chr(10), 0, m.start()) + 1
            hits.append(f"{rel}:{line}: {m.group(0)!r}")
    assert not hits, "stale signing claim(s) in published HTML: " + "; ".join(hits)
