# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S18 slice 5b — auto-schedule preview (dry-run) + compile endpoints.

Service-level: preview returns the slots a rule would fill WITHOUT writing;
compile runs the materializer and reports what it created. Router-level
(TestClient): role gates (preview read-ok, compile write-only) and the happy
paths. A file-backed SQLite factory is used (not StaticPool) because compile
interleaves the materializer's write session with the store's stamp session.
"""

from __future__ import annotations

import random
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from civiccast.auth.models import OperatorIdentity
from civiccast.db import Base
from civiccast.schedule.autoschedule_models import AssetQuery
from civiccast.schedule.autoschedule_router import get_autoschedule_service, staff_router
from civiccast.schedule.autoschedule_service import AutoScheduleService
from civiccast.schedule.autoschedule_store import AutoScheduleStore
from civiccast.schedule.models import ASSET_STATE_VALIDATED, Asset, ScheduleItem

_NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[Callable[[], Session]]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'compile.sqlite'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    @contextmanager
    def _factory() -> Iterator[Session]:
        with Session(bind=engine) as s:
            yield s

    try:
        yield _factory
    finally:
        engine.dispose()


def _service(factory) -> AutoScheduleService:  # type: ignore[no-untyped-def]
    return AutoScheduleService(
        AutoScheduleStore(factory),
        session_factory=factory,
        clock=lambda: _NOW,
        rng=random.Random(0),
    )


def _seed_one_council_asset(factory) -> None:  # type: ignore[no-untyped-def]
    with factory() as s:
        s.add(
            Asset(
                asset_id="a1",
                title="City Council Regular Meeting",
                meeting_body="City Council",
                state=ASSET_STATE_VALIDATED,
                retention_policy="default",
                duration_seconds=1800,
                published_at=datetime(2026, 5, 30, tzinfo=UTC),
            )
        )
        s.commit()


def _make_rule(service: AutoScheduleService) -> str:
    """Create a daily 18:00-19:00 council rule over a 14-day window; return id."""
    service.create_saved_search(
        name="Council",
        description=None,
        query=AssetQuery(meeting_body="City Council", states=[ASSET_STATE_VALIDATED]),
    )
    search = service.list_saved_searches()[0]
    block = service.create_schedule_block(
        channel_id="public",
        name="Evening",
        start_minute=18 * 60,
        end_minute=19 * 60,
        days_of_week=[0, 1, 2, 3, 4, 5, 6],
        active_from=None,
        active_until=None,
        enabled=True,
    )
    rule = service.create_rule(
        name="Evening council",
        saved_search_id=search.saved_search_id,
        channel_id="public",
        schedule_block_id=block.block_id,
        pick_strategy="newest",
        rolling_window_days=14,
        repeat_prevention_days=0,
        priority=100,
        enabled=True,
    )
    return rule.rule_id


def _item_count(factory) -> int:  # type: ignore[no-untyped-def]
    with factory() as s:
        return s.scalar(select(func.count()).select_from(ScheduleItem)) or 0


# ---------------------------------------------------------------------------
# Service-level
# ---------------------------------------------------------------------------


def test_preview_returns_slots_without_writing(factory) -> None:  # type: ignore[no-untyped-def]
    _seed_one_council_asset(factory)
    service = _service(factory)
    rid = _make_rule(service)

    preview = service.preview_rule(rid)
    assert preview is not None
    assert preview.would_fill_count == 14
    assert len(preview.slots) == 14
    assert all(s.action == "fill" and s.asset_id == "a1" for s in preview.slots)
    # The dry-run created NOTHING.
    assert _item_count(factory) == 0


def test_preview_missing_rule_returns_none(factory) -> None:  # type: ignore[no-untyped-def]
    assert _service(factory).preview_rule("asr_nope") is None


def test_preview_dangling_rule_flags_missing_dependency(factory) -> None:  # type: ignore[no-untyped-def]
    service = _service(factory)
    rule = service.create_rule(
        name="Dangling",
        saved_search_id="ss_missing",
        channel_id="public",
        schedule_block_id="sb_missing",
        pick_strategy="newest",
        rolling_window_days=14,
        repeat_prevention_days=0,
        priority=100,
        enabled=True,
    )
    preview = service.preview_rule(rule.rule_id)
    assert preview is not None
    assert preview.missing_dependency is True
    assert preview.slots == []


def test_compile_writes_items_and_reports(factory) -> None:  # type: ignore[no-untyped-def]
    _seed_one_council_asset(factory)
    service = _service(factory)
    _make_rule(service)

    report = service.compile()
    assert report.items_created == 14
    assert _item_count(factory) == 14
    [result] = report.results
    assert result.items_created == 14
    assert result.slots_considered == 14


# ---------------------------------------------------------------------------
# Router-level (role gates + wiring)
# ---------------------------------------------------------------------------


def _build_app(factory, *, scopes=("publish",)):  # type: ignore[no-untyped-def]
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
    service = _service(factory)
    app.dependency_overrides[get_autoschedule_service] = lambda: service
    return app


def test_compile_is_write_gated(factory) -> None:  # type: ignore[no-untyped-def]
    # support_admin is read-only -> compile (a write) is forbidden.
    client = TestClient(_build_app(factory, scopes=("support_admin",)))
    assert client.post("/api/staff/auto-schedule/compile").status_code == 403


def test_preview_allowed_for_read_role(factory) -> None:  # type: ignore[no-untyped-def]
    _seed_one_council_asset(factory)
    # Build a rule first with a write-capable service, then preview as read-only.
    _make_rule(_service(factory))
    rid = _service(factory).list_rules()[0].rule_id
    client = TestClient(_build_app(factory, scopes=("support_admin",)))
    resp = client.post(f"/api/staff/auto-schedule/rules/{rid}/preview")
    assert resp.status_code == 200
    assert resp.json()["would_fill_count"] == 14


def test_preview_404_via_api(factory) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(_build_app(factory))
    assert client.post("/api/staff/auto-schedule/rules/asr_nope/preview").status_code == 404


def test_compile_happy_path_via_api(factory) -> None:  # type: ignore[no-untyped-def]
    _seed_one_council_asset(factory)
    _make_rule(_service(factory))
    client = TestClient(_build_app(factory, scopes=("publish",)))
    resp = client.post("/api/staff/auto-schedule/compile")
    assert resp.status_code == 200
    assert resp.json()["items_created"] == 14
    assert _item_count(factory) == 14
