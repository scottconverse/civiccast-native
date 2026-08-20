# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Durable community bulletin store tests (cable automation CA-3).

Bulletins were contract-only mock data before CA-3; the bulletin filler can
only show REAL community content if submissions persist. State-transition
integrity (approval requires an operator id, decline requires notes) lives in
the pydantic model — the store persists what the model already validated.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import civiccast.schedule.models  # noqa: F401 -- ATTACH ':memory:' AS civiccast on SQLite connect
from civiccast.cg.bulletin_store import PostgresCgBulletinStore
from civiccast.cg.models import CgBulletinSubmission
from civiccast.db import Base, bind_engine, reset_engine

_NOW = datetime(2026, 6, 12, 9, 0, tzinfo=UTC)


@contextmanager
def _store() -> Iterator[PostgresCgBulletinStore]:
    engine = create_engine("sqlite:///:memory:", future=True)
    bind_engine(engine)
    Base.metadata.create_all(engine)
    try:

        @contextmanager
        def session_factory() -> Iterator[Session]:
            sess = Session(bind=engine)
            try:
                yield sess
            finally:
                sess.close()

        yield PostgresCgBulletinStore(session_factory)
    finally:
        reset_engine()
        engine.dispose()


def _submission(
    *,
    submission_id: str = "cgb-garden-club",
    state: str = "submitted",
    **overrides,  # type: ignore[no-untyped-def]
) -> CgBulletinSubmission:
    payload = {
        "submission_id": submission_id,
        "organization": "Pinegrove Garden Club",
        "submitter_label": "Garden Club coordinator",
        "title": "Spring plant sale",
        "message": "Saturday 9am at the community center. Proceeds support the seed library.",
        "target_zone_kind": "primary",
        "state": state,
    }
    payload.update(overrides)
    return CgBulletinSubmission(**payload)  # type: ignore[arg-type]


class TestBulletinStore:
    def test_round_trip_and_channel_scoping(self) -> None:
        with _store() as store:
            created = store.create("public", _submission())
            other = store.create("education", _submission(submission_id="cgb-school-news"))

            assert store.get("cgb-garden-club") == ("public", created)
            assert store.list(channel_id="public") == [created]
            assert store.list(channel_id="education") == [other]
            assert store.get("cgb-missing") is None

    def test_update_persists_approval_transition(self) -> None:
        with _store() as store:
            store.create("public", _submission())
            approved = _submission(state="accepted", approved_by_operator="op-hash-1")

            store.update("public", approved)

            stored = store.get("cgb-garden-club")
            assert stored is not None
            assert stored[1].state == "accepted"
            assert stored[1].approved_by_operator == "op-hash-1"

    def test_list_approved_returns_only_airable_states_in_creation_order(self) -> None:
        with _store() as store:
            store.create(
                "public",
                _submission(submission_id="cgb-1", state="accepted", approved_by_operator="op"),
            )
            store.create("public", _submission(submission_id="cgb-2", state="submitted"))
            store.create(
                "public",
                _submission(
                    submission_id="cgb-3",
                    state="declined",
                    moderation_notes="duplicate",
                ),
            )
            store.create(
                "public",
                _submission(submission_id="cgb-4", state="scheduled", approved_by_operator="op"),
            )

            approved = store.list_approved("public")

            assert [item.submission_id for item in approved] == ["cgb-1", "cgb-4"]

    def test_model_transition_rules_still_hold(self) -> None:
        # The store trusts the model; prove the model actually guards.
        with pytest.raises(ValidationError, match="approved_by_operator"):
            _submission(state="accepted")
        with pytest.raises(ValidationError, match="moderation_notes"):
            _submission(state="declined")
