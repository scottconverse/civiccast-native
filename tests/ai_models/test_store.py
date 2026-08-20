# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""S13 data layer — ORM *Db twins + AiModelStore (selection + config row) + migration 0053.

SQLite-backed; the live-Postgres full-chain head check lives in
tests/live/test_real_postgres.py. The 0053 migration's up/down reversibility is asserted
by TestAiModelConfigurationMigration via the real Alembic chain on SQLite.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from civiccast.ai_models.store import (
    AiModelStore,
    FeatureNotFoundError,
)
from civiccast.db import Base

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


@pytest.fixture
def store(tmp_path: Path) -> Iterator[AiModelStore]:
    eng = create_engine(f"sqlite:///{tmp_path / 'ai_models.sqlite'}", future=True)
    Base.metadata.create_all(eng)

    @contextmanager
    def factory() -> Iterator[Session]:
        with Session(bind=eng) as session:
            yield session

    try:
        yield AiModelStore(factory)
    finally:
        eng.dispose()


# --- selection persistence ---------------------------------------------------


def test_no_selection_returns_none(store: AiModelStore) -> None:
    assert store.get_selection("summary") is None


def test_select_persists_and_round_trips(store: AiModelStore) -> None:
    row = store.set_selection("summary", model_key="gemma4-31b-cloud", tier="cloud")
    assert row.model_key == "gemma4-31b-cloud"
    assert row.tier == "cloud"
    assert store.get_selection("summary") == "gemma4-31b-cloud"


def test_select_is_upsert_one_live_row_per_feature(store: AiModelStore) -> None:
    store.set_selection("summary", model_key="gemma4-12b-ollama", tier="local")
    store.set_selection("summary", model_key="gemma4-e4b-ollama", tier="local")
    assert store.get_selection("summary") == "gemma4-e4b-ollama"
    # Exactly one live selection row for the feature.
    assert len(store.list_selections()) == 1


def test_selections_are_independent_per_feature(store: AiModelStore) -> None:
    store.set_selection("summary", model_key="gemma4-31b-cloud", tier="cloud")
    store.set_selection("translation", model_key="translategemma-4b-ollama", tier="local")
    assert store.get_selection("summary") == "gemma4-31b-cloud"
    assert store.get_selection("translation") == "translategemma-4b-ollama"
    assert store.get_selection("captions") is None


def test_clear_selection_soft_deletes(store: AiModelStore) -> None:
    store.set_selection("summary", model_key="gemma4-31b-cloud", tier="cloud")
    store.clear_selection("summary")
    assert store.get_selection("summary") is None
    # A cleared feature can be re-selected (the partial unique only counts live rows).
    store.set_selection("summary", model_key="gemma4-12b-ollama", tier="local")
    assert store.get_selection("summary") == "gemma4-12b-ollama"


def test_clear_unknown_feature_raises(store: AiModelStore) -> None:
    with pytest.raises(FeatureNotFoundError):
        store.clear_selection("summary")


def test_returned_timestamps_are_utc_aware(store: AiModelStore) -> None:
    row = store.set_selection("summary", model_key="gemma4-12b-ollama", tier="local")
    assert row.created_at.tzinfo is not None
    assert row.updated_at.tzinfo is not None


# --- global config row -------------------------------------------------------


def test_config_row_is_created_on_demand(store: AiModelStore) -> None:
    cfg = store.get_or_create_configuration()
    assert cfg.created_at.tzinfo is not None
    assert cfg.updated_at.tzinfo is not None
    # Idempotent: a second call returns the same singleton (same created_at).
    again = store.get_or_create_configuration()
    assert again.created_at == cfg.created_at


# --- migration 0053 ----------------------------------------------------------


def _make_cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


class TestAiModelConfigurationMigration:
    """0053_ai_model_configuration creates its two tables on upgrade and drops
    exactly those on a single-step downgrade to 0052 — the rest survives.

    These upgrade to the explicit ``0053`` revision (not ``head``) because this test
    pins the 0053 migration's *own* tables; later migrations (e.g. 0054) advance the
    repo head, which is asserted separately in tests/test_schema_check.py.
    """

    _TABLES = ("ai_model_configuration", "feature_model_registry")
    _REVISION = "0053_ai_model_configuration"

    def test_revision_is_0053(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, self._REVISION)
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            from sqlalchemy import text

            with eng.connect() as conn:
                head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            assert head == "0053_ai_model_configuration"
        finally:
            eng.dispose()

    def test_upgrade_creates_the_two_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, self._REVISION)
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert insp.has_table(table), table
            idx = {ix["name"] for ix in insp.get_indexes("feature_model_registry")}
            assert "feature_model_registry_feature_unique" in idx
        finally:
            eng.dispose()

    def test_single_step_downgrade_drops_only_the_two_tables(self, tmp_path: Path) -> None:
        db_file = tmp_path / "rev.sqlite"
        cfg = _make_cfg(f"sqlite:///{db_file}")
        command.upgrade(cfg, self._REVISION)
        command.downgrade(cfg, "0052_secondary_audio")
        eng = create_engine(f"sqlite:///{db_file}", future=True)
        try:
            insp = inspect(eng)
            for table in self._TABLES:
                assert not insp.has_table(table), table
            assert insp.has_table("audio_program_tracks")  # 0052 table survives
        finally:
            eng.dispose()
