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


def test_shipping_manual_fits_blob_limit_and_packages_images() -> None:
    artifact = renderer.MANUAL_JSON
    assert artifact.stat().st_size < 5 * 1024 * 1024
    document = json.loads(artifact.read_text(encoding="utf-8"))
    assert 'src="/api/public/manual/assets/' in document["html"]
    assert "data:image/" not in document["html"]


def test_build_refuses_redirected_asset_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "USER-MANUAL.md"
    source.write_text("# Manual\n", encoding="utf-8")
    output = tmp_path / "civiccast" / "docsite"
    original_resolve = Path.resolve

    def redirected(path: Path, *args: object, **kwargs: object) -> Path:
        if path == output / "assets":
            return tmp_path / "outside"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(renderer, "ROOT", tmp_path)
    monkeypatch.setattr(renderer, "SOURCE", source)
    monkeypatch.setattr(renderer, "OUT_DIR", output)
    monkeypatch.setattr(renderer, "MANUAL_JSON", output / "manual.json")
    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(RuntimeError, match="directory escapes"):
        renderer.render_docsite_manual()
    assert not (output / "manual.json").exists()


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
    import hashlib

    name = hashlib.sha256(png).hexdigest() + ".png"
    assert f"/api/public/manual/assets/{name}" in document["html"]
    assert (output / "assets" / name).read_bytes() == png
    assert "Diagram" in document["html"]
    assert '<ol start="3">' in document["html"]
    assert "Third step." in document["html"]
    assert "Fourth step." in document["html"]
    assert [entry["title"] for entry in document["toc"]] == ["Manual", "After"]
    renderer.check_current()
    manifest_path = output / renderer.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing_asset = dict(manifest, assets={})
    manifest_path.write_text(json.dumps(missing_asset), encoding="utf-8")
    with pytest.raises(RuntimeError, match="image references"):
        renderer.check_current()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (output / "assets" / name).write_bytes(b"damaged")
    with pytest.raises(RuntimeError, match="asset missing or changed"):
        renderer.check_current()
    (output / "assets" / name).write_bytes(png)
    (docs / "diagram.png").write_bytes(b"changed source")
    with pytest.raises(RuntimeError, match="image source missing or changed"):
        renderer.check_current()
    source.write_text("# Manual\n\n## After\n", encoding="utf-8")
    renderer.render_docsite_manual()
    assert list((output / "assets").iterdir()) == []
    renderer.check_current()
