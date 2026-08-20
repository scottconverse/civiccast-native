# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S8-5: build_channel_automation threads the alert evaluator hook to the daemon."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import civiccast.egress.models
import civiccast.schedule.models  # noqa: F401
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.automation import build_channel_automation


@pytest.fixture
def session_factory() -> Iterator[object]:
    eng: Engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
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


def test_hook_is_threaded_to_the_daemon(session_factory, tmp_path) -> None:
    calls: list[tuple] = []

    def hook(channel_id, state, fps, bitrate) -> None:
        calls.append((channel_id, state, fps, bitrate))

    svc = build_channel_automation(session_factory, work_dir=tmp_path, alert_evaluator_hook=hook)
    assert svc._daemon._alert_evaluator_hook is hook


def test_default_hook_is_none(session_factory, tmp_path) -> None:
    svc = build_channel_automation(session_factory, work_dir=tmp_path)
    assert svc._daemon._alert_evaluator_hook is None
