# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Model round-trip + persistence for live-takeover audit sessions (S5 slice 1)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.egress.models  # noqa: F401 - register takeover_audit on Base.metadata
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.models import TakeoverAuditRecordDb, TakeoverSession
from civiccast.egress.takeover_store import PostgresTakeoverAuditStore

_T0 = datetime(2026, 6, 20, 18, 0, 0, tzinfo=UTC)


def _session(
    session_id: str, *, channel_id: str = "public", took_over_at: datetime = _T0, returned_at=None
) -> TakeoverSession:  # type: ignore[no-untyped-def]
    return TakeoverSession(
        session_id=session_id,
        channel_id=channel_id,
        source_ref="live-council",
        source_label="Live: Council chamber",
        operator_id="dana",
        operator_name="Dana Operator",
        reason="Emergency council session",
        took_over_at=took_over_at,
        returned_at=returned_at,
        source_plan_json='{"channel_id":"public","segments":[]}',
        notes=None,
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


@pytest.fixture
def store(engine: Engine) -> PostgresTakeoverAuditStore:
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return PostgresTakeoverAuditStore(factory)


class TestRoundTrip:
    def test_from_session_to_session_is_identity(self) -> None:
        s = _session("tk-1", returned_at=_T0 + timedelta(minutes=20))
        assert TakeoverAuditRecordDb.from_session(s).to_session() == s

    def test_to_session_reattaches_utc_on_naive(self) -> None:
        row = TakeoverAuditRecordDb.from_session(_session("tk-1"))
        row.took_over_at = datetime(2026, 6, 20, 18, 0, 0)  # naive (SQLite round-trip)
        restored = row.to_session()
        assert restored.took_over_at.tzinfo == UTC


class TestStore:
    def test_append_then_get_active(self, store: PostgresTakeoverAuditStore) -> None:
        store.append(_session("tk-1"))
        active = store.get_active("public")
        assert active is not None
        assert active.session_id == "tk-1"
        assert active.returned_at is None

    def test_close_clears_active_and_records_return(
        self, store: PostgresTakeoverAuditStore
    ) -> None:
        store.append(_session("tk-1"))
        returned = store.close("tk-1", returned_at=_T0 + timedelta(minutes=30), notes="handed back")
        assert returned is not None
        assert returned.returned_at == _T0 + timedelta(minutes=30)
        assert returned.notes == "handed back"
        # No longer the active session for the channel.
        assert store.get_active("public") is None

    def test_close_unknown_session_returns_none(self, store: PostgresTakeoverAuditStore) -> None:
        assert store.close("nope", returned_at=_T0) is None

    def test_get_active_none_when_no_takeover(self, store: PostgresTakeoverAuditStore) -> None:
        assert store.get_active("public") is None

    def test_list_by_channel_newest_first_and_filtered(
        self, store: PostgresTakeoverAuditStore
    ) -> None:
        store.append(_session("tk-old", took_over_at=_T0))
        store.append(_session("tk-new", took_over_at=_T0 + timedelta(hours=1)))
        store.append(_session("tk-gov", channel_id="gov", took_over_at=_T0))
        rows = store.list_by_channel("public")
        assert [r.session_id for r in rows] == ["tk-new", "tk-old"]

    def test_list_limit_is_clamped(self, store: PostgresTakeoverAuditStore) -> None:
        for i in range(3):
            store.append(_session(f"tk-{i}", took_over_at=_T0 + timedelta(minutes=i)))
        assert len(store.list_by_channel("public", limit=1)) == 1
        assert len(store.list_by_channel("public", limit=0)) == 1  # clamped up to 1
        assert len(store.list_by_channel("public", limit=10_000)) == 3
