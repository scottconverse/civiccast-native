# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""USER-MANUAL Pandoc render content assertions.

The ci-docs workflow already runs the render script and uploads the artifact,
but no test asserts the rendered output's content matches expectations beyond
"the file got produced." This module fills that gap.

Skips when pandoc is not on PATH, which is common on developer Windows
machines without the document-rendering packages. CI runs pandoc
unconditionally so the gate is real on every push and PR.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import render_user_manual

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SOURCE = _REPO_ROOT / "docs" / "USER-MANUAL.md"
_PANDOC_AVAILABLE = shutil.which("pandoc") is not None
_PANDOC_SKIP = pytest.mark.skipif(
    not _PANDOC_AVAILABLE,
    reason="pandoc not on PATH; user-manual render content check skipped.",
)


_REQUIRED_FRAGMENTS = (
    "CivicCast User Manual",
    "Admin Quick Guide",
    "Meeting Operator Quick Guide",
    "Records Clerk Quick Guide",
    "Technical Operations Reference",
)


@pytest.fixture
def docx_artifact(tmp_path: Path) -> Path:
    """Render USER-MANUAL.md to DOCX into a tmp directory; yield the path."""

    out = tmp_path / "USER-MANUAL.docx"
    subprocess.run(
        ["pandoc", str(_SOURCE), "-o", str(out)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return out


@pytest.fixture
def plaintext_artifact(tmp_path: Path) -> str:
    """Render USER-MANUAL.md to plain text for binary-format-independent checks."""

    out = tmp_path / "USER-MANUAL.txt"
    subprocess.run(
        ["pandoc", str(_SOURCE), "-t", "plain", "-o", str(out)],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return out.read_text(encoding="utf-8")


class TestUserManualRenderContent:
    """Lock the printed handbook's required section headings."""

    @_PANDOC_SKIP
    def test_renders_to_docx_without_error(self, tmp_path: Path) -> None:
        out = tmp_path / "USER-MANUAL.docx"
        subprocess.run(
            ["pandoc", str(_SOURCE), "-o", str(out)],
            check=True,
            capture_output=True,
            timeout=60,
        )
        assert out.exists()
        assert out.stat().st_size > 0

    @_PANDOC_SKIP
    def test_plaintext_render_contains_required_headings(self, plaintext_artifact: str) -> None:
        for fragment in _REQUIRED_FRAGMENTS:
            assert fragment in plaintext_artifact, (
                f"USER-MANUAL.md plaintext render missing fragment: '{fragment}'. "
                "Either the heading was renamed and _REQUIRED_FRAGMENTS needs an update, "
                "or the manual is broken."
            )

    @_PANDOC_SKIP
    def test_docx_artifact_contains_document_payload(self, docx_artifact: Path) -> None:
        import zipfile

        with zipfile.ZipFile(docx_artifact) as zf:
            names = set(zf.namelist())
            assert "word/document.xml" in names
            xml = zf.read("word/document.xml").decode("utf-8")
        assert "CivicCast User Manual" in xml
        assert "Meeting Operator Quick Guide" in xml


def test_manual_source_hash_is_independent_of_checkout_line_endings(tmp_path: Path) -> None:
    lf = tmp_path / "manual-lf.md"
    crlf = tmp_path / "manual-crlf.md"
    lf.write_bytes(b"# Manual\n\nBody\n")
    crlf.write_bytes(b"# Manual\r\n\r\nBody\r\n")

    assert render_user_manual._source_sha256(lf) == render_user_manual._source_sha256(crlf)


_XELATEX_AVAILABLE = shutil.which("xelatex") is not None
_PDF_RENDER_SKIP = pytest.mark.skipif(
    not (_PANDOC_AVAILABLE and _XELATEX_AVAILABLE),
    reason="pandoc/xelatex not on PATH; PDF running-header check skipped.",
)


class TestUserManualVersionHeaderConsistency:
    """TW-A regression guard: the rendered PDF's title page and running
    header must name the same version as each other and as
    docs/USER-MANUAL.md's own subtitle. Incident: docs/assets/manual-style.tex
    hard-coded `v1.0.0-rc17` in `\\fancyhead[R]` while the title page (driven
    by the subtitle) had already moved to `v1.0.0-rc18`, and nothing checked
    the two against each other."""

    def test_source_version_token_reads_the_subtitle(self) -> None:
        text = "---\ntitle: X\nsubtitle: For ops - v1.0.0-rc18 public beta\n---\n"
        assert render_user_manual._source_version_token(text) == "v1.0.0-rc18"

    def test_source_version_token_rejects_a_subtitle_without_a_version(self) -> None:
        with pytest.raises(RuntimeError):
            render_user_manual._source_version_token(
                "---\ntitle: X\nsubtitle: no version here\n---\n"
            )

    def test_tracked_pdf_running_header_matches_manual_subtitle(self) -> None:
        """Falsifiable regression check against the artifacts as committed:
        reads docs/USER-MANUAL.md's subtitle and docs/USER-MANUAL.pdf's page-2
        running header (no re-render) and asserts they name the same version.
        FAILS on the unfixed tracked PDF (title page rc18, header rc17);
        PASSES once docs/USER-MANUAL.pdf is re-rendered from the fixed
        template that derives both from the same subtitle."""
        source_token = render_user_manual._source_version_token(
            render_user_manual.SOURCE.read_text(encoding="utf-8")
        )
        header_token = render_user_manual._rendered_header_version_token(
            render_user_manual.ROOT / "docs" / "USER-MANUAL.pdf"
        )
        assert header_token == source_token, (
            f"docs/USER-MANUAL.pdf running header says {header_token!r} but "
            f"docs/USER-MANUAL.md's subtitle says {source_token!r}"
        )

    @_PDF_RENDER_SKIP
    def test_fresh_render_running_header_matches_source_and_passes_check_current(self) -> None:
        # render_manual() reports artifact paths relative to ROOT, so the
        # output directory must live inside the repo tree (same constraint
        # the tracked docs/ render already has); clean up unconditionally.
        out_dir = render_user_manual.ROOT / ".pytest-tmp-user-manual-render"
        if out_dir.exists():
            shutil.rmtree(out_dir)
        try:
            pdf, _docx = render_user_manual.render_manual(out_dir)
            source_token = render_user_manual._source_version_token(
                render_user_manual.SOURCE.read_text(encoding="utf-8")
            )
            header_token = render_user_manual._rendered_header_version_token(pdf)
            assert header_token == source_token
            # check_current must accept its own fresh, consistent render.
            render_user_manual.check_current(out_dir)
        finally:
            shutil.rmtree(out_dir, ignore_errors=True)
