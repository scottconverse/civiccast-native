# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors

"""allow_software_fallback: per-channel opt-in to permit CPU (software)
encoding when no hardware encoder is present.

Mirrors the auto_start precedent (CA-2, migration 0032_channel_automation):
a Pydantic default, a durable SQLAlchemy column, store round-trip coverage,
and a migration-shape check.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import civiccast.egress.models
import civiccast.schedule.models  # noqa: F401
from civiccast.db import Base, bind_engine, reset_engine
from civiccast.egress.models import EgressConfig, EgressSinkSpec
from civiccast.egress.store import PostgresEgressStore


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
def store(engine: Engine) -> PostgresEgressStore:
    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    return PostgresEgressStore(factory)


def _config(*, channel_id: str = "gov", **overrides: object) -> EgressConfig:
    base = {
        "channel_id": channel_id,
        "enabled": True,
        "slate_message": "CivicCast is preparing the channel.",
        "sinks": [
            EgressSinkSpec(
                kind="srt",
                label="Headend",
                uri="srt://headend.example:9000",
                secret_ref="EGRESS_SRT_PASSPHRASE",
                latency_ms=1500,
            )
        ],
    }
    base.update(overrides)
    return EgressConfig(**base)


def test_allow_software_fallback_defaults_to_false_when_omitted() -> None:
    config = _config()
    assert config.allow_software_fallback is False


def test_postgres_egress_store_round_trips_allow_software_fallback_true(
    store: PostgresEgressStore,
) -> None:
    store.upsert_config(_config(channel_id="gov-true", allow_software_fallback=True))
    loaded = store.get_config("gov-true")
    assert loaded is not None
    assert loaded.allow_software_fallback is True


def test_postgres_egress_store_round_trips_allow_software_fallback_default_false(
    store: PostgresEgressStore,
) -> None:
    store.upsert_config(_config(channel_id="gov-default"))
    loaded = store.get_config("gov-default")
    assert loaded is not None
    assert loaded.allow_software_fallback is False


def test_allow_software_fallback_migration_module_shape() -> None:
    import importlib

    module = importlib.import_module(
        "civiccast.egress.migrations.versions.0073_egress_allow_software_fallback"
    )
    assert callable(module.upgrade)
    assert callable(module.downgrade)
    # Re-chained during the 2026-08-06 rc18 reconcile so the merged history keeps
    # exactly one Alembic head: 0073 now follows main's 0072_normalize_recording_file_uris.
    assert module.down_revision == "0072_normalize_recording_file_uris"
