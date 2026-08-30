# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""API contract tests for the S7 media lifecycle staff router.

Mirrors ``tests/schedule/test_autoschedule_router.py``'s structure: a
minimal FastAPI app mounts the real router, sets the operator identity via
middleware (so the real ``require_any_role`` gate runs), and overrides the
store/reader dependencies with real objects backed by an in-memory SQLite
engine. Covers role-gating, CRUD round-trips, 404s, 503s (unwired store),
route-ordering safety (readiness-dashboard vs {asset_id}), and a mocked
replace-source happy path.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.schedule.ingest import FfprobeResult
from civiccast.schedule.media_lifecycle_router import (
    get_media_lifecycle_store,
    get_missing_media_reader,
    get_watch_folder_worker,
    staff_router,
)
from civiccast.schedule.media_lifecycle_store import MediaLifecycleStore
from civiccast.schedule.media_lifecycle_worker import (
    MediaLifecycleWorker,
    MediaLifecycleWorkerSettings,
    StubTranscodeExecutor,
)
from civiccast.schedule.models import Asset
from civiccast.schedule.watch_folder_worker import WatchFolderWorker, WatchFolderWorkerSettings

_VALID_FFPROBE_RESULT = FfprobeResult(
    duration_seconds=60,
    codec_video="h264",
    codec_audio="aac",
    width_px=1920,
    height_px=1080,
    bitrate_bps=5_000_000,
    format_name="mov,mp4,m4a,3gp,3g2,mj2",
)


@pytest.fixture
def factory() -> Iterator[Callable[[], Session]]:
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.connect() as conn:
        with contextlib.suppress(Exception):
            conn.exec_driver_sql("ATTACH DATABASE ':memory:' AS civiccast")
        Base.metadata.create_all(conn)
        conn.commit()

    @contextmanager
    def _factory() -> Iterator[Session]:
        sess = Session(bind=engine)
        try:
            yield sess
        finally:
            sess.close()

    try:
        yield _factory
    finally:
        engine.dispose()


def _seed_asset(factory, **overrides: object) -> None:  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = {
        "asset_id": "a1",
        "title": "Council Meeting",
        "state": "validated",
    }
    defaults.update(overrides)
    with factory() as session:
        session.add(Asset(**defaults))  # type: ignore[arg-type]
        session.commit()


def _build_app(  # type: ignore[no-untyped-def]
    factory,
    *,
    scopes=("publish", "records"),
    wire: bool = True,
    watch_folder_upload_dir: str | None = None,
):
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

    app.include_router(staff_router)
    if wire:
        store = MediaLifecycleStore(factory)
        worker = MediaLifecycleWorker(
            factory,
            settings=MediaLifecycleWorkerSettings(mode="inline", poll_seconds=1.0),
            transcode_executor=StubTranscodeExecutor(),
        )
        app.dependency_overrides[get_media_lifecycle_store] = lambda: store
        app.dependency_overrides[get_missing_media_reader] = lambda: worker
        # get_watch_folder_worker stays unwired (None -> 503) unless a test
        # explicitly asks for it, mirroring how every other DI seam in this
        # file defaults off so unrelated tests never need to care about it.
        if watch_folder_upload_dir is not None:
            watch_folder_worker = WatchFolderWorker(
                factory,
                settings=WatchFolderWorkerSettings(
                    mode="inline", upload_dir=watch_folder_upload_dir
                ),
            )
            app.dependency_overrides[get_watch_folder_worker] = lambda: watch_folder_worker
    return app


def _client(factory, **kwargs) -> TestClient:  # type: ignore[no-untyped-def]
    return TestClient(_build_app(factory, **kwargs))


class TestUnwiredStore:
    def test_dashboard_503_when_store_not_wired(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, wire=False)
        resp = client.get("/api/staff/assets/readiness-dashboard")
        assert resp.status_code == 503

    def test_missing_media_503_when_reader_not_wired(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, wire=False)
        resp = client.get("/api/staff/media-lifecycle/missing-media")
        assert resp.status_code == 503


class TestRoleGating:
    def test_readiness_dashboard_requires_a_read_role(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=())
        resp = client.get("/api/staff/assets/readiness-dashboard")
        assert resp.status_code == 403

    def test_legal_hold_requires_records_clerk_or_support_admin(self, factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(factory, asset_id="a1")
        client = _client(factory, scopes=("meeting",))  # meeting_operator can't set holds
        resp = client.put("/api/staff/assets/a1/legal-hold", json={"legal_hold": True})
        assert resp.status_code == 403

    def test_watch_folder_write_requires_publish_or_setup(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("support",))
        resp = client.post(
            "/api/staff/media-lifecycle/watch-folder-configs", json={"monitor_path": "/x"}
        )
        assert resp.status_code == 403


class TestRouteOrdering:
    """The literal ``/assets/readiness-dashboard`` path must never be
    swallowed by schedule_router's ``GET /assets/{asset_id}``. This router
    is tested standalone (that other router isn't mounted here), so this
    confirms the literal path resolves to the dashboard handler, not a
    404-from-treating-it-as-an-asset-id -- the real collision-avoidance
    proof is the include_router ORDER in civiccast.app (see that module's
    wiring comment); this test guards the route's own shape.
    """

    def test_readiness_dashboard_returns_dashboard_shape_not_asset_shape(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)
        resp = client.get("/api/staff/assets/readiness-dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert "total_assets" in body
        assert "by_asset" in body


class TestReadiness:
    def test_get_readiness_unknown_asset_404s(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)
        resp = client.get("/api/staff/assets/nope/readiness")
        assert resp.status_code == 404

    def test_get_readiness_known_asset_returns_not_ready_before_worker_pass(self, factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(factory, asset_id="a1")
        client = _client(factory)
        resp = client.get("/api/staff/assets/a1/readiness")
        assert resp.status_code == 200
        assert resp.json()["readiness_state"] == "not_ready"


class TestLegalHold:
    def test_set_legal_hold_unknown_asset_404s(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("records",))
        resp = client.put("/api/staff/assets/nope/legal-hold", json={"legal_hold": True})
        assert resp.status_code == 404

    def test_set_and_read_back_legal_hold(self, factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(factory, asset_id="a1")
        client = _client(factory, scopes=("records", "support"))
        resp = client.put(
            "/api/staff/assets/a1/legal-hold", json={"legal_hold": True, "reason": "subpoena"}
        )
        assert resp.status_code == 200
        assert resp.json()["legal_hold"] is True

        resp2 = client.get("/api/staff/assets/a1/readiness")
        assert resp2.json()["legal_hold"] is True


class TestWatchFolderConfigApi:
    def test_crud_round_trip(self, factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
        dir1 = tmp_path / "incoming"
        dir1.mkdir()
        dir2 = tmp_path / "incoming2"
        dir2.mkdir()
        client = _client(factory, scopes=("publish",))
        created = client.post(
            "/api/staff/media-lifecycle/watch-folder-configs",
            json={"monitor_path": str(dir1), "settle_window_seconds": 12},
        )
        assert created.status_code == 201, created.text
        config_id = created.json()["config_id"]

        listed = client.get("/api/staff/media-lifecycle/watch-folder-configs")
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        updated = client.put(
            f"/api/staff/media-lifecycle/watch-folder-configs/{config_id}",
            json={"monitor_path": str(dir2), "settle_window_seconds": 30},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["settle_window_seconds"] == 30

        deleted = client.delete(f"/api/staff/media-lifecycle/watch-folder-configs/{config_id}")
        assert deleted.status_code == 204

        listed_after = client.get("/api/staff/media-lifecycle/watch-folder-configs")
        assert listed_after.json() == []

    def test_update_unknown_config_404s(self, factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("publish",))
        resp = client.put(
            "/api/staff/media-lifecycle/watch-folder-configs/nope",
            json={"monitor_path": str(tmp_path)},
        )
        assert resp.status_code == 404

    def test_invalid_retention_policy_default_422s(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("publish",))
        resp = client.post(
            "/api/staff/media-lifecycle/watch-folder-configs",
            json={"monitor_path": "/x", "retention_policy_default": "not-a-real-policy"},
        )
        assert resp.status_code == 422

    def test_create_rejects_a_path_that_does_not_exist(self, factory) -> None:  # type: ignore[no-untyped-def]
        # Finding 3 (candidate #17): a non-technical operator gets a plain-
        # language 422 here instead of a config silently accepted and only
        # discovered broken on the daemon's next poll.
        client = _client(factory, scopes=("publish",))
        resp = client.post(
            "/api/staff/media-lifecycle/watch-folder-configs",
            json={"monitor_path": "/definitely/does/not/exist/anywhere"},
        )
        assert resp.status_code == 422
        assert "does not exist" in resp.json()["detail"] or "cannot read" in resp.json()["detail"]

    def test_create_rejects_a_path_that_is_a_file_not_a_directory(  # type: ignore[no-untyped-def]
        self, factory, tmp_path
    ) -> None:
        a_file = tmp_path / "not-a-folder.txt"
        a_file.write_text("x")
        client = _client(factory, scopes=("publish",))
        resp = client.post(
            "/api/staff/media-lifecycle/watch-folder-configs",
            json={"monitor_path": str(a_file)},
        )
        assert resp.status_code == 422

    def test_update_rejects_an_unreadable_path_too(self, factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
        valid_dir = tmp_path / "incoming"
        valid_dir.mkdir()
        client = _client(factory, scopes=("publish",))
        created = client.post(
            "/api/staff/media-lifecycle/watch-folder-configs",
            json={"monitor_path": str(valid_dir)},
        )
        config_id = created.json()["config_id"]
        resp = client.put(
            f"/api/staff/media-lifecycle/watch-folder-configs/{config_id}",
            json={"monitor_path": "/definitely/does/not/exist/anywhere"},
        )
        assert resp.status_code == 422


class TestWatchFolderScanNowApi:
    def test_404s_for_an_unknown_config(self, factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("publish",), watch_folder_upload_dir=str(tmp_path))
        resp = client.post("/api/staff/media-lifecycle/watch-folder-configs/nope/scan-now")
        assert resp.status_code == 404

    def test_503s_when_the_daemon_is_not_wired(self, factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
        # watch_folder_upload_dir omitted -> get_watch_folder_worker resolves
        # to None, same "not wired yet" shape every other DI seam in this
        # router uses.
        watch_dir = tmp_path / "incoming"
        watch_dir.mkdir()
        client = _client(factory, scopes=("publish",))
        created = client.post(
            "/api/staff/media-lifecycle/watch-folder-configs",
            json={"monitor_path": str(watch_dir)},
        )
        config_id = created.json()["config_id"]
        resp = client.post(f"/api/staff/media-lifecycle/watch-folder-configs/{config_id}/scan-now")
        assert resp.status_code == 503

    def test_scans_immediately_and_reports_what_it_found(self, factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
        watch_dir = tmp_path / "incoming"
        watch_dir.mkdir()
        client = _client(
            factory, scopes=("publish",), watch_folder_upload_dir=str(tmp_path / "uploads")
        )
        created = client.post(
            "/api/staff/media-lifecycle/watch-folder-configs",
            # A huge poll_interval_seconds proves "Scan now" bypasses the
            # due-check rather than happening to land on a due poll.
            json={"monitor_path": str(watch_dir), "poll_interval_seconds": 3600},
        )
        config_id = created.json()["config_id"]
        assert created.json()["last_poll_at"] is None

        resp = client.post(f"/api/staff/media-lifecycle/watch-folder-configs/{config_id}/scan-now")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["healthy"] is True
        assert body["files_seen"] == 0
        # An empty folder still counts as "we checked": last_poll_at moves
        # off None immediately, unlike the pre-fix "Last poll: never" state.
        assert body["config"]["last_poll_at"] is not None
        assert body["config"]["health_status"] == "ok"


class TestBrowseFoldersApi:
    """Finding 3 (candidate #17): the non-technical "Browse..." picker's
    backend. No file-content access -- directories only."""

    def test_no_path_lists_roots(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("publish",))
        resp = client.get("/api/staff/media-lifecycle/browse-folders")
        assert resp.status_code == 200
        body = resp.json()
        assert body["current_path"] is None
        assert body["readable"] is True
        assert len(body["entries"]) >= 1

    def test_lists_subdirectories_of_a_real_path(self, factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
        (tmp_path / "b-folder").mkdir()
        (tmp_path / "a-folder").mkdir()
        (tmp_path / "a-file.txt").write_text("not a folder")
        client = _client(factory, scopes=("publish",))
        resp = client.get(
            "/api/staff/media-lifecycle/browse-folders", params={"path": str(tmp_path)}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["readable"] is True
        names = [e["name"] for e in body["entries"]]
        # Files are never listed, and entries sort case-insensitively.
        assert names == ["a-folder", "b-folder"]
        assert body["parent_path"] is not None

    def test_unreadable_path_reports_readable_false_not_a_500(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("publish",))
        resp = client.get(
            "/api/staff/media-lifecycle/browse-folders",
            params={"path": "/definitely/does/not/exist/anywhere"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["readable"] is False
        assert body["error"]

    def test_requires_a_write_role(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("support",))
        resp = client.get("/api/staff/media-lifecycle/browse-folders")
        assert resp.status_code == 403


class TestRetentionPolicyApi:
    def test_crud_round_trip(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory, scopes=("records",))
        created = client.post(
            "/api/staff/media-lifecycle/retention-policies",
            json={
                "name": "Council",
                "match_meeting_body": "City Council",
                "retention_policy": "meeting",
            },
        )
        assert created.status_code == 201
        policy_id = created.json()["policy_id"]

        listed = client.get("/api/staff/media-lifecycle/retention-policies")
        assert len(listed.json()) == 1

        deleted = client.delete(f"/api/staff/media-lifecycle/retention-policies/{policy_id}")
        assert deleted.status_code == 204

    def test_apply_endpoint_reports_changed_count(self, factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(factory, asset_id="a1", meeting_body="City Council", retention_policy="default")
        client = _client(factory, scopes=("records",))
        client.post(
            "/api/staff/media-lifecycle/retention-policies",
            json={
                "name": "Council",
                "match_meeting_body": "City Council",
                "retention_policy": "meeting",
            },
        )
        resp = client.post("/api/staff/media-lifecycle/retention-policies/apply")
        assert resp.status_code == 200
        assert resp.json()["assets_changed"] == 1


class TestStorageBudgetApi:
    def test_returns_totals(self, factory, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.delenv("CIVICCAST_MEDIA_STORAGE_BUDGET_BYTES", raising=False)
        _seed_asset(factory, asset_id="a1", file_size_bytes=1000)
        client = _client(factory)
        resp = client.get("/api/staff/media-lifecycle/storage-budget")
        assert resp.status_code == 200
        assert resp.json()["total_bytes_used"] == 1000
        assert resp.json()["budget_bytes"] is None


class TestMissingMediaApi:
    def test_returns_empty_list_when_nothing_scheduled(self, factory) -> None:  # type: ignore[no-untyped-def]
        client = _client(factory)
        resp = client.get("/api/staff/media-lifecycle/missing-media")
        assert resp.status_code == 200
        assert resp.json() == []


class TestAuditLogApi:
    def test_returns_entries_after_a_mutation(self, factory) -> None:  # type: ignore[no-untyped-def]
        _seed_asset(factory, asset_id="a1")
        client = _client(factory, scopes=("records", "support"))
        client.put("/api/staff/assets/a1/legal-hold", json={"legal_hold": True, "reason": "x"})
        resp = client.get("/api/staff/media-lifecycle/audit-log")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


class TestReplaceSourceApi:
    def test_replace_source_unknown_asset_404s(
        self,
        factory,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    ) -> None:
        monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
        client = _client(factory, scopes=("publish",))
        resp = client.put(
            "/api/staff/assets/nope/replace-source",
            files={"file": ("replacement.mp4", b"\x00" * 16, "video/mp4")},
        )
        assert resp.status_code == 404

    def test_replace_source_happy_path(
        self,
        factory,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,  # type: ignore[no-untyped-def]
    ) -> None:
        monkeypatch.setenv("CIVICCAST_UPLOAD_DIR", str(tmp_path))
        _seed_asset(factory, asset_id="a1", state="rejected", file_status="missing")
        client = _client(factory, scopes=("publish",))

        with patch(
            "civiccast.schedule.media_lifecycle_router.run_ffprobe",
            return_value=_VALID_FFPROBE_RESULT,
        ):
            resp = client.put(
                "/api/staff/assets/a1/replace-source",
                files={"file": ("replacement.mp4", b"\x00" * 16, "video/mp4")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # The asset is back to not_ready (readiness row cleared by the
        # store; the next lifecycle worker pass recomputes it) rather than
        # the stale rejected/missing_file state it had before replacement.
        assert body["readiness_state"] == "not_ready"

        with factory() as session:
            asset = session.get(Asset, "a1")
            assert asset is not None
            assert asset.state == "validated"
            assert asset.file_status == "ok"
