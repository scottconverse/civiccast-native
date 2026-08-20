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
