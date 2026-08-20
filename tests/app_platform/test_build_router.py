# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S12 (build step 8) slice 3 — staff builds + store-submissions API.

A minimal FastAPI app mounts the real build router, sets the operator identity
via middleware (so the real require_any_role gate runs), and overrides the
self-resolving DI seams with an in-memory store + an offline fake build runner.
Covers role-gating, build + list + get + download, 422 on a non-buildable
target, 404, and store-submission upsert.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from civiccast.app_platform.build_models import AppBuildRecord
from civiccast.app_platform.build_orchestrator import BuildOrchestrationError, BuiltArtifact
from civiccast.app_platform.build_router import (
    build_staff_router,
    get_app_build_runner,
    get_app_build_store,
)
from civiccast.app_platform.build_store import AppBuildStore, AppBuildStoreError
from civiccast.app_platform.router import get_app_platform_config_store
from civiccast.app_platform.store import AppPlatformConfigStore
from civiccast.auth.models import OperatorIdentity


def _fake_runner(app_target: str, work_dir: Path) -> BuiltArtifact:
    path = work_dir / f"{app_target}.zip"
    path.write_bytes(b"PK-fake-artifact-" + app_target.encode())
    return BuiltArtifact(
        artifact_path=str(path), entry_point="index.html", manifest_json={"appTarget": app_target}
    )


def _build_app(*, scopes=("setup",), runner=_fake_runner):  # type: ignore[no-untyped-def]
    app = FastAPI()

    @app.middleware("http")
    async def _set_identity(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if scopes is not None:
            request.state.operator_identity = OperatorIdentity(
                operator_id="dana", operator_display_name="Dana", scopes=scopes
            )
        return await call_next(request)

    app.include_router(build_staff_router)
    store = AppBuildStore()
    app.dependency_overrides[get_app_build_store] = lambda: store
    app.dependency_overrides[get_app_platform_config_store] = lambda: AppPlatformConfigStore()
    app.dependency_overrides[get_app_build_runner] = lambda: runner
    return app, store


def _client(**kwargs) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(_build_app(**kwargs)[0])


@pytest.fixture(autouse=True)
def _artifacts_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIVICCAST_APP_BUILD_ARTIFACTS_DIR", str(tmp_path / "artifacts"))


class TestRoleGate:
    def test_build_queue_requires_setup_admin(self) -> None:
        # publish_operator may read but not queue a build (queue = setup_admin).
        assert (
            _client(scopes=("publish",))
            .post("/api/staff/app/builds", json={"app_target": "roku"})
            .status_code
            == 403
        )

    def test_reads_forbidden_for_meeting_operator(self) -> None:
        assert _client(scopes=("meeting",)).get("/api/staff/app/builds").status_code == 403


class TestBuildLifecycle:
    def test_build_list_get_download(self) -> None:
        client = _client(scopes=("setup",))
        created = client.post("/api/staff/app/builds", json={"app_target": "roku"})
        assert created.status_code == 201
        record = created.json()
        assert record["app_target"] == "roku"
        assert record["built_by"] == "dana"
        assert record["proof_boundary"] == "local-build-artifact-sha256-verified"
        assert len(record["artifact_sha256"]) == 64

        listed = client.get("/api/staff/app/builds")
        assert listed.status_code == 200 and [r["record_id"] for r in listed.json()] == [
            record["record_id"]
        ]
        assert client.get(f"/api/staff/app/builds/{record['record_id']}").status_code == 200

        download = client.get(f"/api/staff/app/builds/{record['record_id']}/download")
        assert download.status_code == 200
        assert download.content.startswith(b"PK-fake-artifact")

    def test_non_buildable_target_is_422(self) -> None:
        resp = _client(scopes=("setup",)).post("/api/staff/app/builds", json={"app_target": "cg"})
        assert resp.status_code == 422

    def test_unknown_build_is_404(self) -> None:
        client = _client(scopes=("setup",))
        assert client.get("/api/staff/app/builds/nope").status_code == 404
        assert client.get("/api/staff/app/builds/nope/download").status_code == 404


class TestStoreSubmissions:
    def test_patch_upsert_and_list(self) -> None:
        client = _client(scopes=("publish",))
        resp = client.patch(
            "/api/staff/app/store-submissions/roku",
            json={"submission_status": "pending_review", "package_id": "tv.civiccast.roku"},
        )
        assert resp.status_code == 200
        assert resp.json()["submission_status"] == "pending_review"
        assert resp.json()["package_id"] == "tv.civiccast.roku"
        # A second patch merges onto the stored row.
        resp2 = client.patch(
            "/api/staff/app/store-submissions/roku", json={"published_url": "https://channelstore"}
        )
        assert resp2.json()["package_id"] == "tv.civiccast.roku"  # preserved
        assert resp2.json()["published_url"] == "https://channelstore"
        listed = client.get("/api/staff/app/store-submissions")
        assert [s["app_target"] for s in listed.json()] == ["roku"]

    def test_patch_records_updated_by_and_at(self) -> None:
        client = _client(scopes=("publish",))
        body = client.patch(
            "/api/staff/app/store-submissions/roku", json={"submission_status": "approved"}
        ).json()
        assert body["updated_by"] == "dana"
        assert body["updated_at"] is not None


class TestDownloadGuards:
    def test_missing_artifact_file_is_404(self) -> None:
        client = _client(scopes=("setup",))
        record = client.post("/api/staff/app/builds", json={"app_target": "roku"}).json()
        Path(record["artifact_path"]).unlink()
        resp = client.get(f"/api/staff/app/builds/{record['record_id']}/download")
        assert resp.status_code == 404
        assert "no longer present" in resp.json()["detail"]

    def test_artifact_outside_managed_dir_is_403(self, tmp_path: Path) -> None:
        # A tampered store record pointing outside the managed artifacts dir must
        # be refused (path-traversal defence-in-depth), not served.
        app, store = _build_app(scopes=("setup",))
        client = TestClient(app)
        real = AppBuildRecord.model_validate(
            client.post("/api/staff/app/builds", json={"app_target": "roku"}).json()
        )
        outside = tmp_path / "outside" / "evil.zip"
        outside.parent.mkdir(parents=True, exist_ok=True)
        outside.write_bytes(b"PK-evil")
        store.add_build(
            real.model_copy(update={"record_id": "rec_evil", "artifact_path": str(outside)})
        )
        resp = client.get("/api/staff/app/builds/rec_evil/download")
        assert resp.status_code == 403
        assert "outside the managed" in resp.json()["detail"]


class TestBuildFailureHandling:
    def test_store_write_failure_is_503(self) -> None:
        class _FailingStore(AppBuildStore):
            def add_build(self, record: AppBuildRecord) -> AppBuildRecord:
                raise AppBuildStoreError("disk full")

        app, _ = _build_app(scopes=("setup",))
        app.dependency_overrides[get_app_build_store] = lambda: _FailingStore()
        resp = TestClient(app).post("/api/staff/app/builds", json={"app_target": "roku"})
        assert resp.status_code == 503
        assert "could not be recorded" in resp.json()["detail"]

    def test_non_buildable_422_does_not_leak_path(self) -> None:
        resp = _client(scopes=("setup",)).post("/api/staff/app/builds", json={"app_target": "cg"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, str) and "not buildable" in detail
        assert "/" not in detail and "\\" not in detail

    def test_missing_build_tool_is_controlled_422(self) -> None:
        def missing_tool(_app_target: str, _work_dir: Path) -> BuiltArtifact:
            raise FileNotFoundError("node")

        resp = _client(scopes=("setup",), runner=missing_tool).post(
            "/api/staff/app/builds", json={"app_target": "roku"}
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, str) and "App build tooling is not configured" in detail
        assert "Meeting capture and scheduled recording are unaffected" in detail
        assert "/" not in detail and "\\" not in detail

    def test_wrapped_missing_node_is_operator_readable_422(self) -> None:
        def missing_node(_app_target: str, _work_dir: Path) -> BuiltArtifact:
            raise BuildOrchestrationError("required app build tool 'node' is not available in PATH")

        resp = _client(scopes=("setup",), runner=missing_node).post(
            "/api/staff/app/builds", json={"app_target": "roku"}
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert isinstance(detail, str) and "App build tooling is not configured" in detail
        assert "app-shell builds are optional" in detail
        assert "/" not in detail and "\\" not in detail
