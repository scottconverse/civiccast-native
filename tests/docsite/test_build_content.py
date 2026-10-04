# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Exercise real Pandoc and the shipping sanitizer without changing artifacts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from civiccast.docsite.render import embed_local_images, sanitize_html
from scripts import render_docsite_manual as renderer


def test_definition_terms_and_descriptions_survive() -> None:
    result = sanitize_html("<dl><dt>Channel</dt><dd>A scheduled output.</dd></dl>")
    assert result == "<dl><dt>Channel</dt><dd>A scheduled output.</dd></dl>"


@pytest.mark.parametrize("source", ["missing.png", "../private.png", "notes.txt"])
def test_unembeddable_local_image_stops_build(tmp_path: Path, source: str) -> None:
    with pytest.raises(ValueError, match="manual image"):
        embed_local_images(f'<img src="{source}" alt="Illustration" />', tmp_path)


def test_actual_build_keeps_placeholders_checklists_and_late_headings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "USER-MANUAL.md"
    source.write_text(
        "# Manual\n\nEnter <your-name> at <time>.\n\n"
        "Channel\n:   A scheduled output.\n\n"
        "- [ ] Check the output before broadcasting.\n\n"
        "## Recovery\n\nThe recovery instructions must remain visible.\n\n"
        "###### Final detail\n\nEnd of manual.\n",
        encoding="utf-8",
    )
    output = tmp_path / "civiccast" / "docsite"
    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SOURCE", source)
    monkeypatch.setattr(renderer, "OUT_DIR", output)
    monkeypatch.setattr(renderer, "MANUAL_JSON", output / "manual.json")
    document = json.loads(renderer.render_docsite_manual().read_text(encoding="utf-8"))
    assert "&lt;your-name&gt;" in document["html"]
    assert "&lt;time&gt;" in document["html"]
    assert "<dt>Channel</dt>" in document["html"]
    assert "A scheduled output." in document["html"]
    assert "Check the output before broadcasting." in document["html"]
    assert "The recovery instructions must remain visible." in document["html"]
    assert "End of manual." in document["html"]
    assert [entry["level"] for entry in document["toc"]] == [1, 2, 6]
    renderer.check_current()


@pytest.mark.parametrize("reference", ["notes.txt", "clip.mp4", "sound.ogg", "document.pdf"])
def test_actual_unsupported_media_preserves_both_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reference: str
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "USER-MANUAL.md"
    source.write_text(f"# Manual\n\n![Illustration]({reference})\n\n## After\n", encoding="utf-8")
    (docs / reference).write_bytes(b"synthetic unsupported media")
    output = tmp_path / "civiccast" / "docsite"
    output.mkdir(parents=True)
    manual = output / "manual.json"
    manifest = output / renderer.MANIFEST_NAME
    manual.write_bytes(b"old manual sentinel")
    manifest.write_bytes(b"old manifest sentinel")
    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SOURCE", source)
    monkeypatch.setattr(renderer, "OUT_DIR", output)
    monkeypatch.setattr(renderer, "MANUAL_JSON", manual)
    try:
        with pytest.raises(ValueError, match=r"manual image.*unsupported"):
            renderer.render_docsite_manual()
    finally:
        assert (manual.read_bytes(), manifest.read_bytes()) == (
            b"old manual sentinel",
            b"old manifest sentinel",
        )


def test_actual_png_still_embeds_and_passes_drift_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64

    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "USER-MANUAL.md"
    source.write_text(
        "# Manual\n\n1. First step.\n2. Second step.\n\n"
        "![Diagram](diagram.png)\n\n3. Third step.\n4. Fourth step.\n\n## After\n",
        encoding="utf-8",
    )
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jH1sAAAAASUVORK5CYII="
    )
    (docs / "diagram.png").write_bytes(png)
    output = tmp_path / "civiccast" / "docsite"
    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SOURCE", source)
    monkeypatch.setattr(renderer, "OUT_DIR", output)
    monkeypatch.setattr(renderer, "MANUAL_JSON", output / "manual.json")
    document = json.loads(renderer.render_docsite_manual().read_text(encoding="utf-8"))
    assert "data:image/png;base64," + base64.b64encode(png).decode("ascii") in document["html"]
    assert "Diagram" in document["html"]
    assert '<ol start="3">' in document["html"]
    assert "Third step." in document["html"]
    assert "Fourth step." in document["html"]
    assert [entry["title"] for entry in document["toc"]] == ["Manual", "After"]
    renderer.check_current()
