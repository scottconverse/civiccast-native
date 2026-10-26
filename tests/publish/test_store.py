# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Publish store persistence tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import cast

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from civiccast.publish.models import (
    PublishAuditEvent,
    PublishRunRecord,
    PublishSurfaceStateValue,
    PublishSurfaceStatus,
)
from civiccast.publish.store import PostgresPublishStore


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE publish_runs ("
                "asset_id VARCHAR(160) PRIMARY KEY, "
                "operator_id VARCHAR(160) NOT NULL, "
                "operator_display_name VARCHAR(240) NOT NULL, "
                "approved_at DATETIME NOT NULL, "
                "surfaces_json TEXT NOT NULL, "
                "audit_events_json TEXT NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine):  # type: ignore[no-untyped-def]
    maker = sessionmaker(bind=engine, future=True, expire_on_commit=False, class_=Session)

    @contextmanager
    def _factory() -> Iterator[Session]:
        with maker() as session:
            yield session

    return _factory


def _record(asset_id: str, state: str = "succeeded") -> PublishRunRecord:
    at = datetime(2026, 5, 14, 12, 0, tzinfo=UTC)
    verification_hash = f"sha256:{'a' * 64}"
    surface = PublishSurfaceStatus(
        id="internet-archive",
        label="Internet Archive",
        kind="archive",
        state=cast(PublishSurfaceStateValue, state),
        approval="approved",
        required=True,
        url="https://archive.org/details/council-2026-05-08",
        verification_hash=verification_hash,
        completed_at=at,
        health="ok",
        message="Internet Archive item URL verifies hash-match.",
        next_step="No action required.",
    )
    event = PublishAuditEvent(
        event_id=f"{asset_id}:internet-archive:succeeded:1",
        asset_id=asset_id,
        surface_id="internet-archive",
        action="succeeded",
        operator_id="staff-1",
        occurred_at=at,
        message="Internet Archive item URL verifies hash-match.",
        url=surface.url,
        verification_hash=verification_hash,
    )
    return PublishRunRecord(
        asset_id=asset_id,
        operator_id="staff-1",
        operator_display_name="Avery Operator",
        approved_at=at,
        surfaces=[surface],
        audit_events=[event],
    )


def test_postgres_publish_store_round_trips_surfaces_and_audit_events(
    session_factory,
) -> None:
    store = PostgresPublishStore(session_factory)
    record = _record("council-2026-05-08")

    store.upsert_run(record)
    loaded = store.get_run("council-2026-05-08")

    assert loaded is not None
    assert loaded.asset_id == record.asset_id
    assert loaded.surfaces[0].url == "https://archive.org/details/council-2026-05-08"
    assert loaded.surfaces[0].verification_hash == f"sha256:{'a' * 64}"
    assert loaded.audit_events[0].surface_id == "internet-archive"


def test_postgres_publish_store_upsert_replaces_existing_run(session_factory) -> None:
    store = PostgresPublishStore(session_factory)
    store.upsert_run(_record("council-2026-05-08", "failed"))
    store.upsert_run(_record("council-2026-05-08", "succeeded"))

    loaded = store.get_run("council-2026-05-08")

    assert loaded is not None
    assert loaded.surfaces[0].state == "succeeded"


def test_postgres_publish_store_missing_run_returns_none(session_factory) -> None:
    store = PostgresPublishStore(session_factory)

    assert store.get_run("missing") is None


def test_async_surface_update_does_not_overwrite_concurrent_publication(session_factory):
    store = PostgresPublishStore(session_factory)
    original = _record("meeting")
    store.upsert_run(original)
    newer = original.model_copy(
        update={
            "surfaces": [
                original.surfaces[0].model_copy(update={"message": "New archive verification"})
            ]
        }
    )
    store.upsert_run(newer)
    assert not store.replace_surfaces("meeting", original.surfaces, [])
    assert store.get_run("meeting") == newer
    updated = [newer.surfaces[0].model_copy(update={"message": "Confirmed"})]
    assert store.replace_surfaces("meeting", newer.surfaces, updated)
    saved = store.get_run("meeting")
    assert saved.surfaces == updated and saved.audit_events == newer.audit_events


def test_scheduled_youtube_receipt_survives_retry_restart_and_update_failure(
    session_factory, tmp_path, monkeypatch
):
    import json
    from datetime import timedelta
    from types import SimpleNamespace
    from unittest.mock import Mock

    import httpx

    import civiccast.syndicate.live_output as module
    from civiccast.egress.router import get_egress_store
    from civiccast.platform.providers import ProviderRegistry
    from civiccast.publish.models import PublishApprovalRequest, PublishRetryRequest
    from civiccast.publish.service import approve_publish, retry_publish_surface
    from civiccast.schedule.models import StaffAssetRow
    from civiccast.syndicate.live_wiring import build_youtube_output, restore_youtube_schedules
    from civiccast.syndicate.youtube import YouTubeClient, YouTubeSettings

    now = datetime.now(UTC)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(module, "datetime", Clock)
    start, end = now + timedelta(hours=1), now + timedelta(hours=2)
    calls = []
    update_fails = False
    snippet = {
        "title": "Council",
        "description": "Retain description",
        "scheduledStartTime": start.isoformat(),
    }

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "test"})
        if request.method == "DELETE" or request.url.path.endswith("/transition"):
            return httpx.Response(204)
        if request.method == "PUT":
            if update_fails:
                return httpx.Response(503)
            snippet.update(json.loads(request.content)["snippet"])
            return httpx.Response(200, json={"id": "event"})
        if request.url.path.endswith("/liveBroadcasts"):
            return httpx.Response(
                200,
                json={
                    "id": "event",
                    "items": [{"snippet": snippet, "status": {"lifeCycleStatus": "live"}}],
                },
            )
        if request.url.path.endswith("/bind"):
            return httpx.Response(200, json={"id": "event"})
        if request.url.path.endswith("/liveStreams"):
            stream = {
                "cdn": {
                    "ingestionInfo": {
                        "rtmpsIngestionAddress": "rtmps://a.rtmps.youtube.com/live2",
                        "streamName": "private-key",
                    }
                },
                "status": {"streamStatus": "active"},
            }
            return httpx.Response(200, json={"id": "stream", **stream, "items": [stream]})
        raise AssertionError(request.url)

    store = PostgresPublishStore(session_factory)
    asset = StaffAssetRow(
        asset_id="meeting",
        title="Council",
        state="validated",
        manifest_url="https://station.example/meeting.m3u8",
        published_at=now,
        retention_policy="meeting",
        version=1,
    )
    egress = Mock()
    egress.get_config.return_value = SimpleNamespace(
        enabled=True, sinks=[SimpleNamespace(kind="hls", uri=str(tmp_path))]
    )
    (tmp_path / "playlist.m3u8").write_text("#EXTM3U")
    registry = ProviderRegistry()
    app = SimpleNamespace(
        dependency_overrides={get_egress_store: lambda: egress},
        state=SimpleNamespace(
            store_bundle=SimpleNamespace(
                publish_store=lambda: store,
                asset_store=lambda: SimpleNamespace(list_all=lambda: [asset]),
            ),
            provider_registry=registry,
        ),
    )
    registry.register(
        "youtube",
        "mock",
        lambda: YouTubeClient(
            YouTubeSettings("test", "test", "test"),
            transport=httpx.MockTransport(handler),
            live_output=app.state.youtube_live_output,
        ),
    )

    def owner():
        manager = build_youtube_output(app)
        monkeypatch.setattr(manager._supervisor, "start", lambda: None)
        process = Mock()
        process.poll.return_value = None
        monkeypatch.setattr(manager, "_launch", Mock(return_value=process))
        app.state.youtube_live_output = manager
        return manager

    manager = owner()
    approval = PublishApprovalRequest(
        operator_id="operator",
        operator_display_name="Operator",
        approved_surface_ids=["portal", "youtube-live"],
        youtube_channel_id="government",
        youtube_scheduled_start=start,
        youtube_scheduled_end=end,
    )
    approve_publish(asset=asset, request=approval, store=store, registry=registry)
    surface = next(s for s in store.get_run("meeting").surfaces if s.id == "youtube-live")
    assert surface.delivery_state == "scheduled" and surface.broadcast_id == "event"
    assert "private-key" not in surface.model_dump_json()
    manager._launch.assert_not_called()
    retry = PublishRetryRequest(operator_id="operator", operator_display_name="Operator")
    retry_publish_surface(
        asset=asset, surface_id="youtube-live", request=retry, store=store, registry=registry
    )
    manager.close()
    manager = owner()
    restore_youtube_schedules(app)
    assert manager.knows("meeting")
    manager.run_once()
    manager._launch.assert_not_called()
    update_fails = True
    failed = retry_publish_surface(
        asset=asset, surface_id="youtube-live", request=retry, store=store, registry=registry
    )
    surface = next(s for s in failed.surfaces if s.id == "youtube-live")
    assert (
        surface.state == "failed"
        and surface.broadcast_id == "event"
        and surface.stream_id == "stream"
    )
    manager.run_once()
    assert (
        next(s for s in store.get_run("meeting").surfaces if s.id == "youtube-live").delivery_state
        == "failed"
    )
    update_fails = False
    retry_publish_surface(
        asset=asset, surface_id="youtube-live", request=retry, store=store, registry=registry
    )
    now = start
    manager.run_once()
    assert (
        next(s for s in store.get_run("meeting").surfaces if s.id == "youtube-live").delivery_state
        == "live"
    )
    now = end
    manager.run_once()
    row = store.get_run("meeting")
    assert next(s for s in row.surfaces if s.id == "youtube-live").delivery_state == "stopped"
    assert next(s for s in row.surfaces if s.id == "portal").state == "succeeded"
    assert calls.count(("POST", "/youtube/v3/liveBroadcasts")) == 1
    assert calls.count(("POST", "/youtube/v3/liveStreams")) == 1
    manager.close()
