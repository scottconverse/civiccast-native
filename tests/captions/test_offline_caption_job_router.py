# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""HTTP tests for offline caption job operator visibility (audit finding 4).

``civiccast/captions/router.py`` had zero references to the offline caption
job: state/attempts/last_error persisted in ``offline_caption_jobs`` but
nothing listed them, and the only "retry" was re-approving publish (see
docs/ops/background-workers.md). These are the contract tests for the two
staff endpoints that close that gap: a list view for operator visibility and
a direct retry for a `failed` job that does not require re-approving publish.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.app import create_app
from civiccast.captions.persistence import PostgresOfflineCaptionJobStore
from civiccast.captions.router import get_offline_caption_job_store
from civiccast.captions.vod_job import (
    OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
    OFFLINE_CAPTION_JOB_STATE_FAILED,
    OFFLINE_CAPTION_JOB_STATE_PENDING,
    InMemoryOfflineCaptionJobStore,
    OfflineCaptionJobRecord,
    OfflineCaptionJobStore,
    new_offline_caption_job_id,
)
from civiccast.db import Base

_ASSET_ID = "council-2026-08-16"
_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
_STAFF_HEADERS = {"Authorization": "Bearer operator-token-a"}


def _record(
    *,
    asset_id: str = _ASSET_ID,
    state: str = OFFLINE_CAPTION_JOB_STATE_FAILED,
    attempts: int = 4,
    last_error: str = "caption model failed to load",
    next_attempt_at: datetime | None = None,
    created_at: datetime = _NOW,
) -> OfflineCaptionJobRecord:
    return OfflineCaptionJobRecord(
        job_id=new_offline_caption_job_id(),
        asset_id=asset_id,
        source_path=r"C:\media\council-2026-08-16.mp4",
        package_dir=r"C:\media\.civiccast-packages\council-2026-08-16",
        state=state,  # type: ignore[arg-type]
        attempts=attempts,
        last_error=last_error,
        next_attempt_at=next_attempt_at,
        created_at=created_at,
        updated_at=created_at,
    )


@pytest.fixture
def job_store() -> InMemoryOfflineCaptionJobStore:
    return InMemoryOfflineCaptionJobStore()


@pytest.fixture
def client(job_store: InMemoryOfflineCaptionJobStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_offline_caption_job_store] = lambda: job_store
    with TestClient(app, headers=_STAFF_HEADERS) as test_client:
        yield test_client


class TestListOfflineCaptionJobs:
    def test_list_returns_a_failed_jobs_state_and_last_error(
        self, client: TestClient, job_store: InMemoryOfflineCaptionJobStore
    ) -> None:
        job_store.enqueue(
            _record(
                state=OFFLINE_CAPTION_JOB_STATE_FAILED,
                attempts=4,
                last_error="caption model failed to load",
            )
        )

        response = client.get("/api/staff/captions/offline-jobs")

        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["asset_id"] == _ASSET_ID
        assert rows[0]["state"] == OFFLINE_CAPTION_JOB_STATE_FAILED
        assert rows[0]["attempts"] == 4
        assert rows[0]["last_error"] == "caption model failed to load"

    def test_list_filters_by_state(
        self, client: TestClient, job_store: InMemoryOfflineCaptionJobStore
    ) -> None:
        job_store.enqueue(_record(asset_id="a", state=OFFLINE_CAPTION_JOB_STATE_FAILED))
        job_store.enqueue(
            _record(
                asset_id="b",
                state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
                next_attempt_at=_NOW,
                attempts=0,
                last_error="",
            )
        )

        response = client.get(
            "/api/staff/captions/offline-jobs", params={"state": OFFLINE_CAPTION_JOB_STATE_FAILED}
        )

        assert response.status_code == 200
        rows = response.json()
        assert [row["asset_id"] for row in rows] == ["a"]

    def test_no_caption_job_store_configured_returns_503(self) -> None:
        app = create_app()
        app.dependency_overrides[get_offline_caption_job_store] = lambda: None

        with TestClient(app, headers=_STAFF_HEADERS) as test_client:
            response = test_client.get("/api/staff/captions/offline-jobs")

        assert response.status_code == 503


class TestRetryOfflineCaptionJob:
    def test_retry_moves_a_failed_job_back_to_pending(
        self, client: TestClient, job_store: InMemoryOfflineCaptionJobStore
    ) -> None:
        failed = job_store.enqueue(
            _record(
                state=OFFLINE_CAPTION_JOB_STATE_FAILED,
                attempts=4,
                last_error="caption model failed to load",
            )
        )

        response = client.post(f"/api/staff/captions/offline-jobs/{failed.job_id}/retry")

        assert response.status_code == 200
        body = response.json()
        assert body["job_id"] == failed.job_id
        assert body["state"] == OFFLINE_CAPTION_JOB_STATE_PENDING
        assert body["attempts"] == 0
        assert body["next_attempt_at"] is not None

        persisted = job_store.get(failed.job_id)
        assert persisted is not None
        assert persisted.state == OFFLINE_CAPTION_JOB_STATE_PENDING
        assert persisted.attempts == 0

    def test_retry_on_a_non_failed_job_is_409(
        self, client: TestClient, job_store: InMemoryOfflineCaptionJobStore
    ) -> None:
        awaiting = job_store.enqueue(
            _record(
                state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
                next_attempt_at=_NOW,
                attempts=0,
                last_error="",
            )
        )

        response = client.post(f"/api/staff/captions/offline-jobs/{awaiting.job_id}/retry")

        assert response.status_code == 409

    def test_retry_on_an_unknown_job_is_404(self, client: TestClient) -> None:
        response = client.post("/api/staff/captions/offline-jobs/ocj_missing/retry")

        assert response.status_code == 404

    def test_retry_requires_records_clerk_role(
        self, job_store: InMemoryOfflineCaptionJobStore
    ) -> None:
        failed = job_store.enqueue(_record(state=OFFLINE_CAPTION_JOB_STATE_FAILED))
        app = create_app()
        app.dependency_overrides[get_offline_caption_job_store] = lambda: job_store

        with TestClient(app, headers={"Authorization": "Bearer no-role-token"}) as test_client:
            response = test_client.post(f"/api/staff/captions/offline-jobs/{failed.job_id}/retry")

        assert response.status_code in (401, 403)


def _durable_factory_for(engine: Engine):  # type: ignore[no-untyped-def]
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return factory


@pytest.fixture
def durable_engine() -> Iterator[Engine]:
    # StaticPool + check_same_thread=False: the router tests drive this
    # engine through TestClient, which dispatches the request (and this
    # store's queries) onto a worker thread -- plain sqlite:///:memory:
    # rejects cross-thread use of its single connection. Matches the
    # established pattern in tests/reporting/test_router.py.
    eng = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    eng = eng.execution_options(schema_translate_map={"civiccast": None})
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture(params=["memory", "durable"])
def conflict_job_store(
    request: pytest.FixtureRequest, durable_engine: Engine
) -> OfflineCaptionJobStore:
    """Both store implementations, mirroring the parametrized ``store``
    fixture in tests/captions/test_offline_caption_job_persistence.py's
    concurrency tests."""

    if request.param == "memory":
        return InMemoryOfflineCaptionJobStore()
    return PostgresOfflineCaptionJobStore(_durable_factory_for(durable_engine))


@pytest.fixture
def conflict_client(conflict_job_store: OfflineCaptionJobStore) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_offline_caption_job_store] = lambda: conflict_job_store
    with TestClient(app, headers=_STAFF_HEADERS) as test_client:
        yield test_client


class TestRetryOfflineCaptionJobConflict:
    """Audit finding (MAJOR): manual retry reopened the active-for-asset race.

    ``retry_offline_caption_job`` used to reset a FAILED job to PENDING via
    a bare ``store.save(...)``, without checking whether a *different* job
    was already active for the same asset. Run against both store
    implementations, same as ``TestConcurrentEnqueue`` in
    test_offline_caption_job_persistence.py.
    """

    def test_retry_conflicts_with_a_different_active_job_for_the_same_asset(
        self, conflict_client: TestClient, conflict_job_store: OfflineCaptionJobStore
    ) -> None:
        active = conflict_job_store.enqueue(
            _record(
                state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW,
                next_attempt_at=_NOW,
                attempts=0,
                last_error="",
            )
        )
        failed = conflict_job_store.enqueue(
            _record(
                state=OFFLINE_CAPTION_JOB_STATE_FAILED,
                attempts=4,
                last_error="caption model failed to load",
                next_attempt_at=None,
            )
        )

        response = conflict_client.post(f"/api/staff/captions/offline-jobs/{failed.job_id}/retry")

        assert response.status_code == 409
        # The failed job must stay failed -- not silently flipped to
        # pending -- and the asset must still have exactly one active job.
        reloaded_failed = conflict_job_store.get(failed.job_id)
        assert reloaded_failed is not None
        assert reloaded_failed.state == OFFLINE_CAPTION_JOB_STATE_FAILED
        active_rows = [
            row
            for row in conflict_job_store.list(asset_id=_ASSET_ID)
            if row.state
            in (OFFLINE_CAPTION_JOB_STATE_PENDING, OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW)
        ]
        assert [row.job_id for row in active_rows] == [active.job_id]

    def test_retry_still_succeeds_with_no_competing_active_job(
        self, conflict_client: TestClient, conflict_job_store: OfflineCaptionJobStore
    ) -> None:
        failed = conflict_job_store.enqueue(
            _record(
                state=OFFLINE_CAPTION_JOB_STATE_FAILED,
                attempts=4,
                last_error="caption model failed to load",
                next_attempt_at=None,
            )
        )

        response = conflict_client.post(f"/api/staff/captions/offline-jobs/{failed.job_id}/retry")

        assert response.status_code == 200
        assert response.json()["state"] == OFFLINE_CAPTION_JOB_STATE_PENDING
        reloaded = conflict_job_store.get(failed.job_id)
        assert reloaded is not None
        assert reloaded.state == OFFLINE_CAPTION_JOB_STATE_PENDING


class _BlindPrecheckJobStore:
    """Wraps a real (durable) store but reports "no active job" once,
    simulating the TOCTOU window between ``retry_offline_caption_job``'s
    ``active_for_asset`` pre-check and its ``store.save()`` call -- the same
    race ``_BlindPrecheckStore`` in test_offline_caption_job_persistence.py
    simulates for concurrent enqueues. Proves the router's ``save()``
    catch (item 3 of the fix) is what turns the race into a 409, not just
    the pre-check (item 1).
    """

    def __init__(self, backing: OfflineCaptionJobStore) -> None:
        self._backing = backing
        self._active_for_asset_calls = 0

    def get(self, job_id: str) -> OfflineCaptionJobRecord | None:
        return self._backing.get(job_id)

    def active_for_asset(self, asset_id: str) -> OfflineCaptionJobRecord | None:
        self._active_for_asset_calls += 1
        if self._active_for_asset_calls == 1:
            return None
        return self._backing.active_for_asset(asset_id)

    def save(self, record: OfflineCaptionJobRecord) -> OfflineCaptionJobRecord:
        return self._backing.save(record)

    def enqueue(self, record: OfflineCaptionJobRecord) -> OfflineCaptionJobRecord:
        return self._backing.enqueue(record)

    def due(self, **kwargs: object) -> list[OfflineCaptionJobRecord]:
        return self._backing.due(**kwargs)  # type: ignore[arg-type]

    def list(self, **kwargs: object) -> list[OfflineCaptionJobRecord]:
        return self._backing.list(**kwargs)  # type: ignore[arg-type]


class TestRetryOfflineCaptionJobConflictClosesTheToctouWindow:
    def test_retry_is_409_not_500_when_the_precheck_loses_the_race(
        self, durable_engine: Engine
    ) -> None:
        """Before the fix (persistence.py item 2), this scenario raised a
        raw, unhandled ``IntegrityError`` -- a 500, not a 409 -- because
        ``PostgresOfflineCaptionJobStore.save`` did not catch it the way
        ``enqueue`` already did."""

        backing = PostgresOfflineCaptionJobStore(_durable_factory_for(durable_engine))
        active = backing.enqueue(
            _record(state=OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW, next_attempt_at=_NOW)
        )
        failed = backing.enqueue(
            _record(
                state=OFFLINE_CAPTION_JOB_STATE_FAILED,
                attempts=4,
                last_error="caption model failed to load",
                next_attempt_at=None,
            )
        )
        racy_store = _BlindPrecheckJobStore(backing)

        app = create_app()
        app.dependency_overrides[get_offline_caption_job_store] = lambda: racy_store

        with TestClient(app, headers=_STAFF_HEADERS) as test_client:
            response = test_client.post(f"/api/staff/captions/offline-jobs/{failed.job_id}/retry")

        assert response.status_code == 409
        reloaded_failed = backing.get(failed.job_id)
        assert reloaded_failed is not None
        assert reloaded_failed.state == OFFLINE_CAPTION_JOB_STATE_FAILED
        reloaded_active = backing.get(active.job_id)
        assert reloaded_active is not None
        assert reloaded_active.state == OFFLINE_CAPTION_JOB_STATE_AWAITING_REVIEW
