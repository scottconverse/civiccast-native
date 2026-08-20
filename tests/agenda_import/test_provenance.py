# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""AgendaImportProvenanceStore round-trip (migration 0067)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from civiccast.agenda_import.provenance import AgendaImportProvenanceStore
from civiccast.db import Base


@pytest.fixture
def store() -> Iterator[AgendaImportProvenanceStore]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    assert "agenda_import_provenance" in inspect(engine).get_table_names(schema="civiccast")

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=engine) as session:
            yield session

    try:
        yield AgendaImportProvenanceStore(factory)
    finally:
        engine.dispose()


class TestProvenanceStore:
    def test_missing_row_is_none(self, store: AgendaImportProvenanceStore) -> None:
        assert store.get("ag-1") is None

    def test_record_import_round_trips(self, store: AgendaImportProvenanceStore) -> None:
        recorded = store.record_import(
            agenda_id="ag-1", source="legistar", client_code="seattle", external_id="5705"
        )
        assert recorded.agenda_id == "ag-1"

        fetched = store.get("ag-1")
        assert fetched is not None
        assert fetched.source == "legistar"
        assert fetched.client_code == "seattle"
        assert fetched.external_id == "5705"

    def test_reimport_overwrites_the_latest_row_not_a_duplicate(
        self, store: AgendaImportProvenanceStore
    ) -> None:
        store.record_import(
            agenda_id="ag-1", source="legistar", client_code="seattle", external_id="5705"
        )
        store.record_import(
            agenda_id="ag-1", source="legistar", client_code="seattle", external_id="5706"
        )

        fetched = store.get("ag-1")
        assert fetched is not None
        assert fetched.external_id == "5706"
