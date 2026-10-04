# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for GET /api/public/manual."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from civiccast.app import create_app
from civiccast.docsite import service as docsite_service


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as c:
        yield c


class TestManualEndpoint:
    @pytest.mark.parametrize("payload", [None, b"\xff", b"{", b"{}"])
    def test_unavailable_artifact_gives_operator_repair_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        payload: bytes | None,
    ) -> None:
        artifact = tmp_path / "manual.json"
        if payload is not None:
            artifact.write_bytes(payload)
        monkeypatch.setattr(docsite_service, "_MANUAL_JSON_PATH", artifact)
        docsite_service._load_manual_cached.cache_clear()
        try:
            with TestClient(create_app(), raise_server_exceptions=False) as client:
                response = client.get("/api/public/manual")
            assert response.status_code == 503
            assert response.json()["detail"] == (
                "The built-in manual is missing, damaged, or cannot be read. "
                "Ask your IT support person to repair the CivicCast installation."
            )
            assert str(tmp_path) not in response.text
        finally:
            docsite_service._load_manual_cached.cache_clear()

    @pytest.mark.parametrize("operation", ["stat", "read_text"])
    def test_unreadable_artifact_recovers_after_repair(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        operation: str,
    ) -> None:
        original = getattr(Path, operation)

        def denied(path: Path, *args: object, **kwargs: object) -> object:
            if path == docsite_service._MANUAL_JSON_PATH:
                raise PermissionError("private filesystem detail")
            return original(path, *args, **kwargs)

        docsite_service._load_manual_cached.cache_clear()
        try:
            with monkeypatch.context() as patch:
                patch.setattr(Path, operation, denied)
                response = client.get("/api/public/manual")
                assert response.status_code == 503
                assert "repair the CivicCast installation" in response.json()["detail"]
                assert "private filesystem detail" not in response.text
            assert client.get("/api/public/manual").status_code == 200
        finally:
            docsite_service._load_manual_cached.cache_clear()

    def test_returns_the_rendered_manual(self, client: TestClient) -> None:
        response = client.get("/api/public/manual")
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "docs/USER-MANUAL.md"
        assert len(body["source_sha256"]) == 64
        assert isinstance(body["toc"], list)
        assert len(body["toc"]) > 10
        assert "<h1" in body["html"] or "<h2" in body["html"]

    def test_toc_includes_the_provider_and_glossary_sections(self, client: TestClient) -> None:
        toc_ids = {entry["id"] for entry in client.get("/api/public/manual").json()["toc"]}
        for anchor in (
            "glossary",
            "provider-cloudflare-r2",
            "provider-internet-archive",
            "provider-youtube",
            "provider-federation",
            "where-recordings-live",
            "publish-surfaces",
            "cdn-cost-estimate",
            "report-without-github",
        ):
            assert anchor in toc_ids, f"expected manual anchor {anchor!r} in the table of contents"

    def test_html_never_carries_a_script_tag(self, client: TestClient) -> None:
        assert "<script" not in client.get("/api/public/manual").json()["html"]

    def test_architecture_diagrams_are_embedded_not_broken_relative_links(
        self, client: TestClient
    ) -> None:
        # Regression (PR #74 review): the sanitizer used to drop pandoc's
        # <figure> wrapper entirely (figure/figcaption were not
        # allowlisted), and even a surviving <img> would have pointed at an
        # unresolvable relative "assets/..." path once served from this
        # JSON endpoint with no filesystem underneath it.
        html = client.get("/api/public/manual").json()["html"]
        assert "<figure>" in html
        assert "data:image/png;base64," in html
        assert 'src="assets/' not in html

    def test_no_staff_token_required(self, client: TestClient) -> None:
        # Regression guard: this must stay reachable from the un-authenticated
        # First Setup screen, so it must never start with /api/staff/ (see
        # civiccast/auth/middleware.py's prefix-based gate) and must succeed
        # with no Authorization header at all.
        response = client.get("/api/public/manual", headers={})
        assert response.status_code == 200

    def test_returns_503_with_actionable_detail_when_artifact_is_missing(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _boom() -> None:
            raise docsite_service.ManualUnavailableError(
                "The built-in manual is missing, damaged, or cannot be read. "
                "Ask your IT support person to repair the CivicCast installation."
            )

        monkeypatch.setattr("civiccast.docsite.router.load_manual", _boom)
        response = client.get("/api/public/manual")
        assert response.status_code == 503
        assert "repair the CivicCast installation" in response.json()["detail"]
