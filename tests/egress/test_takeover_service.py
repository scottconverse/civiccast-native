# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""TakeoverService orchestration tests (S5 slice 2)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.egress.models  # noqa: F401 - register takeover_audit
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.store import InMemoryEgressStore
from civiccast.egress.takeover_service import (
    AlreadyLiveError,
    NotInTakeoverError,
    TakeoverNotReadyError,
    TakeoverService,
)
from civiccast.egress.takeover_store import PostgresTakeoverAuditStore
from civiccast.live.models import LiveSourceResponse
from civiccast.live.relay import build_ingest_plan

_NOW = datetime(2026, 6, 20, 18, 0, 0, tzinfo=UTC)


def _ready_source(channel_id: str) -> LiveSourceResponse:
    """A configured LiveSource, standing in for what an operator would add
    via Run Meeting. Bug B5: build_ingest_plan's local_default no longer
    claims ready for an address nothing serves, so takeover tests need a
    real configured source in the plan the same way production does."""
    return LiveSourceResponse(
        live_source_id=f"{channel_id}-encoder",
        channel_id=channel_id,
        name="Council Room Encoder",
        source_type="srt",
        endpoint_url="srt://0.0.0.0:9000?mode=listener",
        credentials_handle=None,
        created_at=_NOW,
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        reset_engine()
        eng.dispose()


def _factory(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


def _build(
    engine: Engine,
) -> tuple[TakeoverService, InMemoryEgressStore, PostgresTakeoverAuditStore]:
    factory = _factory(engine)
    audit = PostgresTakeoverAuditStore(factory)
    egress = InMemoryEgressStore()
    # A real ready ingest plan: one configured LiveSource makes
    # build_ingest_plan yield a READY path (bug B5 -- the legacy
    # local_default no longer claims ready with nothing configured), so no
    # relay configs are needed for the happy path.
    service = TakeoverService(
        audit,
        egress,
        lambda channel_id: build_ingest_plan(
            channel_id, [], live_sources=[_ready_source(channel_id)]
        ),
        clock=lambda: _NOW,
        id_factory=lambda: "tok",
    )
    return service, egress, audit


class TestTake:
    def test_take_records_session_and_queues_command(self, engine: Engine) -> None:
        service, egress, audit = _build(engine)
        session = service.take(
            channel_id="public", operator_id="dana", operator_name="Dana", reason="Emergency"
        )
        assert session.session_id == "takeover-tok"
        assert session.returned_at is None
        assert session.operator_id == "dana"
        assert session.reason == "Emergency"
        # Durable session exists and the engine got a takeover command.
        assert audit.get_active("public") is not None
        pending = egress.pop_pending_commands("public")
        assert len(pending) == 1
        assert pending[0].action == "takeover"

    def test_take_when_already_live_raises(self, engine: Engine) -> None:
        service, _egress, _audit = _build(engine)
        service.take(channel_id="public", operator_id="dana")
        with pytest.raises(AlreadyLiveError):
            service.take(channel_id="public", operator_id="erin")

    def test_take_with_unknown_path_is_not_ready(self, engine: Engine) -> None:
        service, _egress, _audit = _build(engine)
        with pytest.raises(TakeoverNotReadyError):
            service.take(channel_id="public", operator_id="dana", path_id="does-not-exist")


class TestHandback:
    def test_handback_closes_session_and_queues_command(self, engine: Engine) -> None:
        service, egress, _audit = _build(engine)
        service.take(channel_id="public", operator_id="dana")
        egress.pop_pending_commands("public")  # clear the takeover command
        closed = service.handback(channel_id="public", operator_id="dana", notes="done")
        assert closed.returned_at == _NOW
        assert closed.notes == "done"
        pending = egress.pop_pending_commands("public")
        assert len(pending) == 1
        assert pending[0].action == "handback"
        # No longer active.
        assert service.state("public").can_return is False

    def test_handback_when_not_live_raises(self, engine: Engine) -> None:
        service, _egress, _audit = _build(engine)
        with pytest.raises(NotInTakeoverError):
            service.handback(channel_id="public", operator_id="dana")


class TestStateAndAudit:
    def test_state_ready_idle_then_live(self, engine: Engine) -> None:
        service, _egress, _audit = _build(engine)
        idle = service.state("public")
        assert idle.can_takeover is True  # ready local source, not live
        assert idle.can_return is False
        assert idle.active_session is None

        service.take(channel_id="public", operator_id="dana")
        live = service.state("public")
        assert live.can_takeover is False  # already live
        assert live.can_return is True
        assert live.active_session is not None

    def test_audit_lists_history(self, engine: Engine) -> None:
        service, _egress, _audit = _build(engine)
        service.take(channel_id="public", operator_id="dana")
        history = service.audit("public")
        assert len(history) == 1
        assert history[0].session_id == "takeover-tok"
