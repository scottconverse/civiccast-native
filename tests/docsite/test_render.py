# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for the docsite HTML sanitizer, image embedder, and TOC extractor."""

from __future__ import annotations

from pathlib import Path

from civiccast.docsite.render import embed_local_images, extract_toc, sanitize_html


class TestEmbedLocalImages:
    def test_embeds_a_relative_image_as_a_data_uri(self, tmp_path: Path) -> None:
        (tmp_path / "assets").mkdir()
        image_path = tmp_path / "assets" / "diagram.png"
        # Smallest possible valid PNG byte sequence is unnecessary here --
        # embed_local_images only needs *a file it can read*, not a real
        # decodable image.
        image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")

        html = '<img src="assets/diagram.png" alt="Diagram" />'
        out = embed_local_images(html, base_dir=tmp_path)

        assert 'src="assets/diagram.png"' not in out
        assert "data:image/png;base64," in out
        assert 'alt="Diagram"' in out

    def test_leaves_an_already_absolute_or_data_src_untouched(self, tmp_path: Path) -> None:
        for src in (
            "https://example.org/x.png",
            "http://example.org/x.png",
            "data:image/png;base64,AAAA",
            "/already/absolute.png",
            "#anchor-not-an-image",
            "mailto:someone@example.org",
        ):
            html = f'<img src="{src}" alt="x" />'
            assert embed_local_images(html, base_dir=tmp_path) == html

    def test_leaves_a_missing_file_untouched(self, tmp_path: Path) -> None:
        html = '<img src="assets/does-not-exist.png" alt="Missing" />'
        assert embed_local_images(html, base_dir=tmp_path) == html

    def test_refuses_to_embed_a_path_traversal_outside_base_dir(self, tmp_path: Path) -> None:
        outside = tmp_path.parent / "outside-secret.png"
        outside.write_bytes(b"secret-bytes")
        html = '<img src="../outside-secret.png" alt="x" />'
        out = embed_local_images(html, base_dir=tmp_path)
        assert out == html
        assert "base64" not in out

    def test_leaves_an_unsupported_file_type_untouched(self, tmp_path: Path) -> None:
        (tmp_path / "readme.txt").write_text("not an image", encoding="utf-8")
        html = '<img src="readme.txt" alt="x" />'
        assert embed_local_images(html, base_dir=tmp_path) == html

    def test_embeds_multiple_images_independently(self, tmp_path: Path) -> None:
        (tmp_path / "one.png").write_bytes(b"one-bytes")
        (tmp_path / "two.png").write_bytes(b"two-bytes")
        html = '<img src="one.png" alt="One" /><p>text</p><img src="two.png" alt="Two" />'

        out = embed_local_images(html, base_dir=tmp_path)

        assert out.count("data:image/png;base64,") == 2
        assert 'alt="One"' in out
        assert 'alt="Two"' in out


class TestSanitizeHtml:
    def test_drops_script_tag_and_its_content(self) -> None:
        out = sanitize_html("<p>hello</p><script>alert(document.cookie)</script><p>world</p>")
        assert "<script" in "<p>hello</p><script>alert(document.cookie)</script><p>world</p>"
        assert "<script" not in out
        assert "alert(document.cookie)" not in out
        assert "<p>hello</p>" in out
        assert "<p>world</p>" in out

    def test_drops_style_tag_and_its_content(self) -> None:
        out = sanitize_html("<style>body{display:none}</style><p>text</p>")
        assert "<style" not in out
        assert "display:none" not in out
        assert "<p>text</p>" in out

    def test_strips_event_handler_attributes(self) -> None:
        out = sanitize_html('<img src="https://example.org/x.png" onerror="steal()" alt="x" />')
        assert "onerror" not in out
        assert "steal()" not in out
        assert 'src="https://example.org/x.png"' in out

    def test_strips_javascript_scheme_href(self) -> None:
        out = sanitize_html('<a href="javascript:alert(1)">click</a>')
        assert "javascript:" not in out
        assert "click" in out

    def test_keeps_figure_and_figcaption_and_the_image_inside_them(self) -> None:
        # Regression (PR #74 review): figure/figcaption were not on the
        # allowlist, and a disallowed tag is dropped along with everything
        # nested inside it -- so pandoc's <figure><img/><figcaption>...
        # wrapper around docs/USER-MANUAL.md's two architecture diagrams
        # silently deleted the images AND their captions from the manual.
        out = sanitize_html(
            "<figure>"
            '<img src="data:image/png;base64,AAAA" alt="CivicCast system architecture" />'
            '<figcaption aria-hidden="true">CivicCast system architecture</figcaption>'
            "</figure>"
        )
        assert "<figure>" in out
        assert "</figure>" in out
        assert "<figcaption" in out
        assert "CivicCast system architecture" in out
        assert 'src="data:image/png;base64,AAAA"' in out

    def test_keeps_relative_hash_and_https_links(self) -> None:
        out = sanitize_html(
            '<a href="#glossary">Glossary</a> <a href="https://example.org">Example</a>'
        )
        assert 'href="#glossary"' in out
        assert 'href="https://example.org"' in out

    def test_drops_data_uri_href_but_keeps_data_image_src(self) -> None:
        out = sanitize_html(
            '<a href="data:text/html,<script>1</script>">bad</a>'
            '<img src="data:image/png;base64,AAAA" alt="ok" />'
        )
        assert "href=" not in out
        assert 'src="data:image/png;base64,AAAA"' in out

    def test_handles_self_closing_disallowed_void_element_without_getting_stuck(self) -> None:
        # Regression: <col/> (pandoc table colgroup output) has no matching
        # end tag. An earlier version of this parser incremented a skip
        # counter for it that nothing ever decremented, silently truncating
        # every table (and everything after it) out of the rendered manual.
        out = sanitize_html(
            '<table><colgroup><col style="width: 33%" /><col /></colgroup>'
            "<tbody><tr><td>kept</td></tr></tbody></table><p>after</p>"
        )
        assert "kept" in out
        assert "<p>after</p>" in out
        assert "colgroup" not in out
        assert "<col" not in out

    def test_unknown_tag_with_end_tag_is_dropped_with_its_content(self) -> None:
        out = sanitize_html('<iframe src="https://evil.example">nested</iframe><p>safe</p>')
        assert "iframe" not in out
        assert "nested" not in out
        assert "<p>safe</p>" in out

    def test_escapes_data_text_as_entities(self) -> None:
        out = sanitize_html("<p>1 &lt; 2 &amp; 3 &gt; 2</p>")
        assert "1 &lt; 2 &amp; 3 &gt; 2" in out


class TestExtractToc:
    def test_collects_headings_with_ids_in_document_order(self) -> None:
        html = (
            '<h1 id="top">Title</h1>'
            "<p>intro</p>"
            '<h2 id="section-a">Section A</h2>'
            '<h3 id="sub-a1">Sub A1</h3>'
            '<h2 id="section-b">Section B</h2>'
        )
        toc = extract_toc(html)
        assert toc == [
            {"level": 1, "id": "top", "title": "Title"},
            {"level": 2, "id": "section-a", "title": "Section A"},
            {"level": 3, "id": "sub-a1", "title": "Sub A1"},
            {"level": 2, "id": "section-b", "title": "Section B"},
        ]

    def test_ignores_headings_without_an_id(self) -> None:
        html = '<h2>No id here</h2><h2 id="has-id">Has id</h2>'
        toc = extract_toc(html)
        assert toc == [{"level": 2, "id": "has-id", "title": "Has id"}]

    def test_flattens_inline_markup_inside_heading_text(self) -> None:
        html = '<h2 id="mixed">Cloudflare <code>R2</code> setup</h2>'
        toc = extract_toc(html)
        assert toc == [{"level": 2, "id": "mixed", "title": "Cloudflare R2 setup"}]
