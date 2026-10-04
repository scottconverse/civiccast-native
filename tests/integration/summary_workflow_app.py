# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Isolated summary browser fixture: real routes/auth/stores, no station app."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from civiccast.auth.middleware import staff_auth_middleware
from civiccast.auth.router import staff_router as auth_router
from civiccast.captions import CaptionCue
from civiccast.records.router import get_record_store
from civiccast.records.router import staff_router as records_router
from civiccast.records.store import InMemoryRecordStore
from civiccast.summary.job import SummaryGenerationJobRecord
from civiccast.summary.persistence import PostgresSummaryGenerationJobStore
from civiccast.summary.router import get_summary_job_store, get_summary_store
from civiccast.summary.router import staff_router as summary_router
from civiccast.summary.store import PostgresSummaryStore
from tests.summary.test_summary_persistence import _summary

state_root = Path(os.environ["SUMMARY_WORKFLOW_STATE"])
state_root.mkdir(parents=True, exist_ok=True)
sqlite3.register_adapter(datetime, lambda value: value.isoformat())
engine = create_engine(f"sqlite:///{state_root / 'summaries.sqlite3'}")
with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
    import_module("civiccast.summary.migrations.versions.0011_summary_v06").upgrade()
    import_module("civiccast.summary.migrations.versions.0081_summary_generation_jobs").upgrade()


@contextmanager
def sessions():
    with Session(engine) as session:
        yield session


store = PostgresSummaryStore(sessions)
store.create_summary(_summary())
jobs = PostgresSummaryGenerationJobStore(sessions)
for job_id, meeting_id, summary_id, text in (
    (
        "original-generation",
        "meeting-1",
        "summary-1",
        "The original caption says: two voted yes and one voted no.",
    ),
    (
        "newer-other-summary",
        "meeting-1",
        "different-summary",
        "Different generation words must not appear.",
    ),
    ("other-meeting", "another-meeting", "summary-1", "Wrong meeting words must not appear."),
):
    jobs.enqueue(
        SummaryGenerationJobRecord(
            job_id=job_id,
            meeting_id=meeting_id,
            summary_id=summary_id,
            state="complete",
            cues=[
                CaptionCue(
                    cue_id="cue-1", start_seconds=18, end_seconds=24, text=text, confidence=1
                )
            ],
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    )
records = InMemoryRecordStore()
app = FastAPI()
app.middleware("http")(staff_auth_middleware)
app.include_router(auth_router)
app.include_router(summary_router)
app.include_router(records_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:18188"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
app.dependency_overrides[get_summary_store] = lambda: store
app.dependency_overrides[get_summary_job_store] = lambda: jobs
app.dependency_overrides[get_record_store] = lambda: records


@app.get("/__test__/approval")
def persisted_approval(summary_id: str = "summary-1"):
    return store.get_approval(summary_id)


@app.post("/__test__/orphan")
def create_orphan():
    draft = _summary().model_copy(update={"summary_id": "orphan-approved", "status": "approved"})
    draft.sourced_claims = [draft.sourced_claims[0].model_copy(update={"claim_id": "orphan-claim"})]
    store.create_summary(draft)
    return {"summary_id": draft.summary_id}
