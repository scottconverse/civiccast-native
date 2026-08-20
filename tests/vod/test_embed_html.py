# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for civiccast.vod.embed.build_embed_html."""

from __future__ import annotations

from civiccast.vod.embed import build_embed_html


class TestBuildEmbedHtml:
    def test_returns_iframe_tag(self) -> None:
        html = build_embed_html("https://example.org/v/abc", "Council Meeting")
        assert html.startswith("<iframe")
        assert html.endswith("></iframe>")

    def test_includes_src_and_title(self) -> None:
        html = build_embed_html("https://example.org/v/abc", "Council Meeting")
        assert 'src="https://example.org/v/abc"' in html
        assert 'title="Council Meeting"' in html

    def test_default_dimensions_are_640x360(self) -> None:
        html = build_embed_html("https://x.example/v/a", "T")
        assert 'width="640"' in html
        assert 'height="360"' in html

    def test_custom_dimensions_propagate(self) -> None:
        html = build_embed_html("https://x.example/v/a", "T", width=1280, height=720)
        assert 'width="1280"' in html
        assert 'height="720"' in html

    def test_lazy_loading_is_set(self) -> None:
        html = build_embed_html("https://x.example/v/a", "T")
        assert 'loading="lazy"' in html

    def test_allow_attributes_present(self) -> None:
        html = build_embed_html("https://x.example/v/a", "T")
        assert 'allow="autoplay; fullscreen; picture-in-picture"' in html
        assert "allowfullscreen" in html

    def test_xss_in_url_is_escaped(self) -> None:
        # If a malicious actor controlled the URL, this must not break out
        # of the src attribute.
        html = build_embed_html('"><script>alert(1)</script>', "Title")
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_xss_in_title_is_escaped(self) -> None:
        html = build_embed_html("https://x.example/v/a", '"><img src=x onerror=alert(1)>')
        assert "<img" not in html
        assert "&lt;img" in html

    def test_quote_in_title_is_escaped(self) -> None:
        html = build_embed_html("https://x.example/v/a", 'a"b')
        assert 'title="a&quot;b"' in html
