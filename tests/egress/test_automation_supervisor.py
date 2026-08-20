# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""build_channel_automation wires the PlayoutSupervisor as the engine (S5 integration).

Proves the production automation engine is now the takeover-capable supervisor
(with the takeover audit store wired) AND that scheduled source selection is
unchanged — lookahead=None makes the supervisor a single-plan passthrough of the
schedule resolver, behaviorally identical to the base daemon. The live 24h
takeover soak is the tester/WSL lane, not here.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.egress.models
import civiccast.schedule.models  # noqa: F401
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.automation import build_channel_automation
from civiccast.egress.supervisor import PlayoutSupervisor


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[object]:  # type: ignore[type-arg]
    eng: Engine = create_engine("sqlite:///:memory:", future=True)
    bind_engine(eng)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield factory
    finally:
        reset_engine()
        eng.dispose()


def test_production_engine_is_the_takeover_capable_supervisor(session_factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
    service = build_channel_automation(session_factory, work_dir=tmp_path / "egress")
    daemon = service._daemon
    assert isinstance(daemon, PlayoutSupervisor)
    # The takeover audit store is wired, so a "takeover" command can read the
    # open session it must put live.
    assert daemon._takeover_audit_store is not None


def test_scheduled_source_selection_unchanged_on_empty_schedule(session_factory, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # lookahead=None → the supervisor passes the schedule resolver straight
    # through; with no scheduled items the resolved plan is None (slate),
    # exactly as the base daemon behaved.
    service = build_channel_automation(session_factory, work_dir=tmp_path / "egress")
    daemon = service._daemon
    assert isinstance(daemon, PlayoutSupervisor)
    assert daemon._next_source_plan("public") is None
