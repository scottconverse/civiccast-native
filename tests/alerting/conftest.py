# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Shared fixtures for alerting tests."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Import ORM models so Base.metadata is populated before create_all.
import civiccast.alerting.models  # noqa: F401
from civiccast.db import Base


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session with the full alerting schema."""
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
