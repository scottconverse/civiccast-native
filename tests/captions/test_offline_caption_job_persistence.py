# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Durable offline caption job store tests (keystone K3).

An offline caption job spans a model pass over a whole meeting and then an
operator's review of the result -- easily hours apart, across a restart. So
the queue has to be durable, and the DB-backed store has to answer exactly
what the in-memory store answers. These tests pin both: the same contract on
both implementations, and survival across store instances.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from civiccast.captions.persistence import PostgresOfflineCaptionJobStore
from civiccast.captions.vod_job import (
    OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
    OFFLINE_CAPTION_JOB_STATE_COMPLETE,
    OFFLINE_CAPTION_JOB_STATE_FAILED,
    OFFLINE_CAPTION_JOB_STATE_PENDING,
    InMemoryOfflineCaptionJobStore,
    OfflineCaptionJobConflictError,
    OfflineCaptionJobRecord,
    OfflineCaptionJobStore,
    enqueue_offline_caption_job,
    new_offline_caption_job_id,
)
from civiccast.db import Base

_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:", future=True)
    eng = eng.execution_options(schema_translate_map={"civiccast": None})
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


def _factory_for(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


@pytest.fixture
def durable_store(engine: Engine) -> PostgresOfflineCaptionJobStore:
    return PostgresOfflineCaptionJobStore(_factory_for(engine))


@pytest.fixture(params=["memory", "durable"])
def store(
    request: pytest.FixtureRequest,
    durable_store: PostgresOfflineCaptionJobStore,
) -> OfflineCaptionJobStore:
    """Run the whole contract against both implementations."""

    if request.param == "memory":
        return InMemoryOfflineCaptionJobStore()
    return durable_store


def _record(
    *,
    asset_id: str = "council-2026-08-16",
    state: str = OFFLINE_CAPTION_JOB_STATE_PENDING,
    next_attempt_at: datetime | None = _NOW,
    created_at: datetime = _NOW,
) -> OfflineCaptionJobRecord:
    return OfflineCaptionJobRecord(
        job_id=new_offline_caption_job_id(),
        asset_id=asset_id,
        source_path=r"C:\media\council-2026-08-16.mp4",
        package_dir=r"C:\media\.civiccast-packages\council-2026-08-16",
        state=state,  # type: ignore[arg-type]
        next_attempt_at=next_attempt_at,
        created_at=created_at,
        updated_at=created_at,
    )


class TestOfflineCaptionJobStoreContract:
    def test_enqueued_job_round_trips(self, store: OfflineCaptionJobStore) -> None:
        record = store.enqueue(_record())

        fetched = store.get(record.job_id)

        assert fetched == record

    def test_unknown_job_id_is_none(self, store: OfflineCaptionJobStore) -> None:
        assert store.get("ocj_missing") is None

    def test_active_for_asset_finds_pending_and_awaiting_review(
        self, store: OfflineCaptionJobStore
    ) -> None:
        pending = store.enqueue(_record(asset_id="a"))
        awaiting = store.enqueue(
            _record(asset_id="b", state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW)
        )

        assert store.active_for_asset("a") is not None
        assert store.active_for_asset("a").job_id == pending.job_id  # type: ignore[union-attr]
        assert store.active_for_asset("b").job_id == awaiting.job_id  # type: ignore[union-attr]

    def test_a_finished_job_no_longer_blocks_a_new_one(self, store: OfflineCaptionJobStore) -> None:
        store.enqueue(_record(state=OFFLINE_CAPTION_JOB_STATE_COMPLETE, next_attempt_at=None))

        # A recording re-published after its captions completed must be able
        # to queue a fresh pass rather than silently reusing a closed job.
        assert store.active_for_asset("council-2026-08-16") is None

    def test_due_honors_the_backoff_clock(self, store: OfflineCaptionJobStore) -> None:
        soon = store.enqueue(_record(asset_id="soon", next_attempt_at=_NOW))
        store.enqueue(_record(asset_id="later", next_attempt_at=_NOW + timedelta(minutes=5)))

        due = store.due(now=_NOW)

        assert [row.job_id for row in due] == [soon.job_id]
        assert len(store.due(now=_NOW + timedelta(minutes=5))) == 2

    def test_due_skips_terminal_states(self, store: OfflineCaptionJobStore) -> None:
        store.enqueue(_record(state=OFFLINE_CAPTION_JOB_STATE_COMPLETE, next_attempt_at=None))

        assert store.due(now=_NOW + timedelta(days=1)) == []

    def test_save_persists_progress(self, store: OfflineCaptionJobStore) -> None:
        record = store.enqueue(_record())

        store.save(
            record.model_copy(
                update={
                    "state": OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
                    "cue_count": 42,
                    "attempts": 1,
                    "last_error": "",
                    "updated_at": _NOW + timedelta(minutes=1),
                }
            )
        )

        fetched = store.get(record.job_id)
        assert fetched is not None
        assert fetched.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert fetched.cue_count == 42
        assert fetched.attempts == 1

    def test_enqueue_helper_is_idempotent_per_asset(
        self, store: OfflineCaptionJobStore, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        root = tmp_path_factory.mktemp("media")
        kwargs = {
            "asset_id": "council-2026-08-16",
            "source_path": root / "council.mp4",
            "package_dir": root / "packages" / "council",
        }

        first = enqueue_offline_caption_job(store, **kwargs)  # type: ignore[arg-type]
        second = enqueue_offline_caption_job(store, **kwargs)  # type: ignore[arg-type]

        assert first.job_id == second.job_id

    def test_a_second_active_enqueue_for_the_same_asset_conflicts(
        self, store: OfflineCaptionJobStore
    ) -> None:
        """Audit finding 3: the double-enqueue race.

        ``enqueue_offline_caption_job`` normally prevents this with its
        check-then-insert, but that check has a TOCTOU window (see
        ``TestConcurrentEnqueue`` below). This test calls ``store.enqueue``
        directly, bypassing the helper's pre-check entirely, to prove the
        *store* itself -- in-memory and DB-backed alike -- refuses a second
        active row for one asset rather than silently accepting it. On the
        DB-backed store this is the partial-unique index
        (``ix_offline_caption_jobs_one_active_per_asset``,
        0075_offline_caption_jobs) firing for real and being translated out
        of a raw IntegrityError.
        """

        store.enqueue(
            _record(asset_id="council-2026-08-16", state=OFFLINE_CAPTION_JOB_STATE_PENDING)
        )

        with pytest.raises(OfflineCaptionJobConflictError):
            store.enqueue(
                _record(
                    asset_id="council-2026-08-16",
                    state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
                )
            )

    def test_a_terminal_job_does_not_conflict_with_a_new_active_one(
        self, store: OfflineCaptionJobStore
    ) -> None:
        """A finished or failed job must not block a fresh pass for the asset."""

        store.enqueue(
            _record(
                asset_id="council-2026-08-16",
                state=OFFLINE_CAPTION_JOB_STATE_FAILED,
                next_attempt_at=None,
            )
        )

        fresh = store.enqueue(
            _record(asset_id="council-2026-08-16", state=OFFLINE_CAPTION_JOB_STATE_PENDING)
        )

        assert fresh.state == OFFLINE_CAPTION_JOB_STATE_PENDING


class TestSaveConflictsWithAnActiveJobForTheSameAsset:
    """Audit finding (MAJOR): a manual retry's ``store.save(...)`` used to
    reopen the active-for-asset race that ``enqueue`` already guards.

    ``civiccast/captions/router.py``'s ``retry_offline_caption_job`` resets
    a FAILED job back to PENDING via ``store.save(...)``. Durable-store-only
    (not the parametrized ``store`` contract fixture): the in-memory store's
    ``save()`` is deliberately left a plain write -- the router's
    ``active_for_asset`` pre-check is what guards it -- so only the
    durable store needs the DB-level ``IntegrityError``-catching defense
    added here to close the TOCTOU window between that pre-check and this
    write.
    """

    def test_save_transitioning_a_job_into_conflict_with_another_active_job_raises(
        self, durable_store: PostgresOfflineCaptionJobStore
    ) -> None:
        active = durable_store.enqueue(
            _record(
                asset_id="council-2026-08-16",
                state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
            )
        )
        failed = durable_store.enqueue(
            _record(
                asset_id="council-2026-08-16",
                state=OFFLINE_CAPTION_JOB_STATE_FAILED,
                next_attempt_at=None,
            )
        )

        with pytest.raises(OfflineCaptionJobConflictError):
            durable_store.save(
                failed.model_copy(
                    update={
                        "state": OFFLINE_CAPTION_JOB_STATE_PENDING,
                        "next_attempt_at": _NOW,
                    }
                )
            )

        # The failed commit must roll back cleanly -- neither row is left
        # half-mutated by the attempt.
        reloaded_failed = durable_store.get(failed.job_id)
        assert reloaded_failed is not None
        assert reloaded_failed.state == OFFLINE_CAPTION_JOB_STATE_FAILED
        reloaded_active = durable_store.get(active.job_id)
        assert reloaded_active is not None
        assert reloaded_active.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW

    def test_save_transitioning_the_same_job_that_is_already_active_still_works(
        self, durable_store: PostgresOfflineCaptionJobStore
    ) -> None:
        """A same-job pending -> running -> failed style transition (the
        row updating *itself*, not colliding with a different row) must
        not be mistaken for a conflict."""

        awaiting = durable_store.enqueue(
            _record(
                asset_id="council-2026-08-16",
                state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
            )
        )

        saved = durable_store.save(
            awaiting.model_copy(
                update={"state": OFFLINE_CAPTION_JOB_STATE_COMPLETE, "next_attempt_at": None}
            )
        )

        assert saved.state == OFFLINE_CAPTION_JOB_STATE_COMPLETE
        assert durable_store.get(awaiting.job_id).state == OFFLINE_CAPTION_JOB_STATE_COMPLETE  # type: ignore[union-attr]


class _BlindPrecheckStore:
    """Wraps a real store but reports "no active job" for its first few
    ``active_for_asset`` calls, simulating two callers racing past the
    TOCTOU window in ``enqueue_offline_caption_job`` before either has
    inserted. Later calls (the post-conflict winner re-fetch) answer for
    real, exactly like a DB row that has since become visible.
    """

    def __init__(self, backing: OfflineCaptionJobStore, *, blind_calls: int) -> None:
        self._backing = backing
        self._blind_calls = blind_calls
        self._calls = 0

    def active_for_asset(self, asset_id: str) -> OfflineCaptionJobRecord | None:
        self._calls += 1
        if self._calls <= self._blind_calls:
            return None
        return self._backing.active_for_asset(asset_id)

    def enqueue(self, record: OfflineCaptionJobRecord) -> OfflineCaptionJobRecord:
        return self._backing.enqueue(record)

    def save(self, record: OfflineCaptionJobRecord) -> OfflineCaptionJobRecord:
        return self._backing.save(record)

    def get(self, job_id: str) -> OfflineCaptionJobRecord | None:
        return self._backing.get(job_id)

    def due(self, **kwargs: object) -> list[OfflineCaptionJobRecord]:
        return self._backing.due(**kwargs)  # type: ignore[arg-type]

    def list(self, **kwargs: object) -> list[OfflineCaptionJobRecord]:
        return self._backing.list(**kwargs)  # type: ignore[arg-type]


@pytest.fixture(params=["memory", "durable"])
def backing_store(
    request: pytest.FixtureRequest,
    durable_store: PostgresOfflineCaptionJobStore,
) -> OfflineCaptionJobStore:
    if request.param == "memory":
        return InMemoryOfflineCaptionJobStore()
    return durable_store


class TestConcurrentEnqueue:
    """Audit finding 3: two concurrent enqueues must yield exactly one job.

    ``enqueue_offline_caption_job``'s idempotency check is a plain SELECT
    with no row lock, so two callers can both see "nothing active" before
    either inserts. This simulates exactly that race and asserts the
    catch-and-return-the-winner path added for finding 3, against both
    store implementations.
    """

    def test_two_racing_enqueues_yield_exactly_one_job(
        self, backing_store: OfflineCaptionJobStore, tmp_path_factory: pytest.TempPathFactory
    ) -> None:
        root = tmp_path_factory.mktemp("media")
        racy = _BlindPrecheckStore(backing_store, blind_calls=2)
        kwargs = {
            "asset_id": "council-2026-08-16",
            "source_path": root / "council.mp4",
            "package_dir": root / "packages" / "council",
        }

        first = enqueue_offline_caption_job(racy, **kwargs)  # type: ignore[arg-type]
        second = enqueue_offline_caption_job(racy, **kwargs)  # type: ignore[arg-type]

        assert first.job_id == second.job_id
        assert (
            len(
                backing_store.list(
                    asset_id="council-2026-08-16", state=OFFLINE_CAPTION_JOB_STATE_PENDING
                )
            )
            == 1
        )


class TestDurability:
    def test_a_job_awaiting_review_survives_a_restart(self, engine: Engine) -> None:
        """The operator may not review until tomorrow -- the job must wait."""

        written = PostgresOfflineCaptionJobStore(_factory_for(engine)).enqueue(
            _record(state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW)
        )

        # A brand-new store object, as a restarted process would build.
        reopened = PostgresOfflineCaptionJobStore(_factory_for(engine))

        recovered = reopened.active_for_asset("council-2026-08-16")
        assert recovered is not None
        assert recovered.job_id == written.job_id
        assert recovered.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
        assert recovered.created_at == _NOW

    def test_naive_timestamps_come_back_utc_aware(self, engine: Engine) -> None:
        """SQLite drops tzinfo; a due-time comparison must not explode on it."""

        store = PostgresOfflineCaptionJobStore(_factory_for(engine))
        store.enqueue(_record())

        due = store.due(now=_NOW)

        assert due[0].next_attempt_at is not None
        assert due[0].next_attempt_at.tzinfo is not None
        assert due[0].created_at.tzinfo is not None
