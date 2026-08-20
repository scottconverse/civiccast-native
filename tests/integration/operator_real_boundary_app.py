# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Real-boundary app fixture for the operator portal Playwright smoke gate.

This module is imported by Uvicorn inside the Playwright worker. It starts a
real Postgres testcontainer, runs Alembic, seeds one packaged asset and one
pending summary through the production stores, issues a real DB-backed staff
token, then exposes ``app`` from the normal CivicCast app factory.
"""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.middleware.cors import CORSMiddleware
from pydantic import HttpUrl
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

from civiccast.auth.store import PostgresStaffTokenStore
from civiccast.schedule.store import PostgresAssetStore
from civiccast.summary.store import PostgresSummaryStore
from civiccast.vod.models import AssetMetadata
from tests.summary.test_summary_persistence import _summary

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_tmp_dir = Path(tempfile.mkdtemp(prefix="civiccast-real-boundary-"))
atexit.register(lambda: shutil.rmtree(_tmp_dir, ignore_errors=True))

_container = PostgresContainer("postgres:17", driver="psycopg")
_container.start()
atexit.register(_container.stop)

DATABASE_URL = _container.get_connection_url()
os.environ["DATABASE_URL"] = DATABASE_URL
os.environ["CIVICCAST_AUTH_ACK"] = "1"
os.environ["CIVICCAST_ACTIVITYPUB_MODE"] = "disabled"
os.environ["CIVICCAST_SUBSCRIBE_SECRETS_FILE"] = str(_tmp_dir / "subscribe-secrets.json")
os.environ.pop("CIVICCAST_ALLOW_EPHEMERAL_STORES", None)
os.environ.pop("CIVICCAST_ALLOW_DETERMINISTIC_STAFF_TOKEN", None)
os.environ.pop("CIVICCAST_ALLOW_DETERMINISTIC_SUBSCRIBE_SECRETS", None)

from civiccast.app import create_app  # noqa: E402

_cfg = Config(str(ALEMBIC_INI))
_cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
command.upgrade(_cfg, "head")

_engine = create_engine(DATABASE_URL, future=True)
atexit.register(_engine.dispose)


@contextmanager
def _session_factory() -> Iterator[Session]:
    with Session(bind=_engine) as session:
        yield session


_token_store = PostgresStaffTokenStore(_session_factory)
_issued = _token_store.issue_token(
    operator_id="real-boundary-operator",
    operator_display_name="Real Boundary Operator",
)

_token_path_raw = os.environ.get("CIVICCAST_REAL_BOUNDARY_TOKEN_FILE")
if _token_path_raw:
    _token_path = Path(_token_path_raw)
    _token_path.parent.mkdir(parents=True, exist_ok=True)
    _token_path.write_text(_issued.secret, encoding="utf-8")

_asset_id = f"real-boundary-{uuid4().hex[:8]}"
PostgresAssetStore(_session_factory).create(
    AssetMetadata(
        asset_id=_asset_id,
        title="Council - Real Boundary Smoke",
        description="Seeded through Postgres for the operator real-boundary smoke.",
        manifest_url=cast(HttpUrl, "https://cdn.example/real-boundary/playlist.m3u8"),
        poster_url=None,
        duration_seconds=3600,
        published_at=datetime(2026, 5, 21, 19, 0, tzinfo=UTC),
    )
)
with _session_factory() as _session:
    _session.execute(
        text("UPDATE civiccast.assets SET retention_policy = 'meeting' WHERE asset_id = :asset_id"),
        {"asset_id": _asset_id},
    )
    _session.commit()

_base_summary = _summary()
PostgresSummaryStore(_session_factory).create_summary(
    _base_summary.model_copy(
        update={
            "summary_id": "summary-real-boundary",
            "meeting_id": _asset_id,
            "narrative": "The board approved the first-mile operator smoke test.",
            "sourced_claims": [
                _base_summary.sourced_claims[0].model_copy(
                    update={
                        "claim_id": "claim-real-boundary",
                        "text": "The board approved the first-mile operator smoke test.",
                    }
                )
            ],
        }
    )
)

app = create_app()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4174", "http://127.0.0.1:4174"],
    allow_methods=["*"],
    allow_headers=["*"],
)
