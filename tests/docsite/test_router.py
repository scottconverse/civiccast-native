# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Tests for GET /api/public/manual."""

from __future__ import annotations

import hashlib
import json
import subprocess
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

    def test_bundled_manual_contains_current_product_destinations(self, client: TestClient) -> None:
        # This checks the real bundled artifact. Keep it separate from the
        # source-render test: callers must not ship ahead of their destination.
        response = client.get("/api/public/manual")
        assert response.status_code == 200
        body = response.json()
        required = {
            "app-glossary",
            "cdn-and-provider-options",
            "publishing-providers",
            "federation-activitypub",
            "configuration-storage",
            "the-publishing-steps-surfaces",
            "report-a-beta-issue",
            "ch-before-meeting",
            "live-captions-what-the-settings-change",
        }
        toc_ids = {entry["id"] for entry in body["toc"]}
        assert not required - toc_ids, (
            f"bundled manual missing destinations: {sorted(required - toc_ids)}"
        )
        for anchor in required:
            assert f'id="{anchor}"' in body["html"]

    def test_current_source_artifact_includes_product_destinations(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        from civiccast.docsite.render import extract_toc, sanitize_html

        source = Path(__file__).resolve().parents[2] / "docs/USER-MANUAL.md"
        # Isolated heading/navigation artifact from exact source; screenshot
        # embedding is deliberately outside this anchor test, not bypassed in shipping.
        html = sanitize_html(
            subprocess.run(
                ["pandoc", str(source), "-f", "markdown-raw_html-task_lists", "-t", "html5"],
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
        )
        source_hash = hashlib.sha256(source.read_text(encoding="utf-8").encode()).hexdigest()
        artifact = tmp_path / "current-manual.json"
        artifact.write_text(
            json.dumps(
                {
                    "source": "docs/USER-MANUAL.md",
                    "source_sha256": source_hash,
                    "generated_at": "2026-10-03T00:00:00Z",
                    "toc": extract_toc(html),
                    "html": html,
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(docsite_service, "_MANUAL_JSON_PATH", artifact)
        request.addfinalizer(docsite_service._load_manual_cached.cache_clear)
        docsite_service._load_manual_cached.cache_clear()
        response = client.get("/api/public/manual")
        assert response.status_code == 200
        body = response.json()
        assert body["source_sha256"] == source_hash
        toc_ids = {entry["id"] for entry in body["toc"]}
        for anchor in (
            "app-glossary",
            "cdn-and-provider-options",
            "publishing-providers",
            "federation-activitypub",
            "configuration-storage",
            "the-publishing-steps-surfaces",
            "report-a-beta-issue",
            "ch-before-meeting",
            "live-captions-what-the-settings-change",
        ):
            assert anchor in toc_ids, f"expected manual anchor {anchor!r} in the table of contents"
            assert f'id="{anchor}"' in body["html"]
        docsite_service._load_manual_cached.cache_clear()

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
        assert "/api/public/manual/assets/" in html
        assert 'src="assets/' not in html

    def test_all_bundled_images_load_without_auth(self, client: TestClient) -> None:
        import re

        html = client.get("/api/public/manual").json()["html"]
        paths = set(re.findall(r'src="(/api/public/manual/assets/[^"]+)"', html))
        assert paths
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("image/")
            assert response.headers["x-content-type-options"] == "nosniff"
            assert (
                hashlib.sha256(response.content).hexdigest() == path.rsplit("/", 1)[1].split(".")[0]
            )

    @pytest.mark.parametrize(
        "name", ["manual.json", "..%2Fmanual.json", "a" * 64 + ".html", "a" * 64 + ".png"]
    )
    def test_asset_lookup_never_serves_arbitrary_paths(self, client: TestClient, name: str) -> None:
        response = client.get(f"/api/public/manual/assets/{name}")
        assert response.status_code == 404

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
