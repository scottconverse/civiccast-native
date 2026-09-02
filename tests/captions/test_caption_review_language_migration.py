# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration 0083_caption_review_language: upgrade/downgrade + backfill.

Recorded-Spanish captions add a ``language`` column to
``caption_review_items`` so English transcription and Spanish translation are
reviewed as two separate passes on a shared asset. This pins three contracts
the migration must honor:

1. Upgrade to 0083 adds a non-null ``language`` column.
2. A row that existed BEFORE the column (created at the 0082 head) backfills
   to ``'en'`` -- the language every prior review row implicitly was.
3. Downgrade to 0082 removes the column cleanly.

Real Alembic runner against a temp SQLite DB -- no mocks.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_PARENT = "0082_egress_graphics_overlay"
_HEAD = "0083_caption_review_language"


def _cfg(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _language_columns(database_url: str) -> list[str]:
    engine = create_engine(database_url, future=True)
    try:
        columns = [c["name"] for c in inspect(engine).get_columns("caption_review_items")]
    finally:
        engine.dispose()
    return columns


def _insert_pre_language_row(db_path: Path) -> None:
    """Insert a caption_review_items row as it looked at the 0082 head."""

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO caption_review_items (
                review_item_id, asset_id, cue_id, start_seconds, end_seconds,
                confidence, low_confidence, status, original_text, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, CURRENT_TIMESTAMP)
            """,
            ("legacy-1", "council-x", "cue-1", 1.0, 2.0, 0.9, 0, "motion carries"),
        )
        conn.commit()


def test_upgrade_adds_language_downgrade_removes_it_and_backfills_en(tmp_path: Path) -> None:
    db_path = tmp_path / "captions.db"
    url = f"sqlite:///{db_path}"
    cfg = _cfg(url)

    # Bring the DB up to the migration's PARENT, then seed a pre-language row.
    command.upgrade(cfg, _PARENT)
    assert "language" not in _language_columns(url)
    _insert_pre_language_row(db_path)

    # Upgrade one step: the column appears and the legacy row backfills to en.
    command.upgrade(cfg, _HEAD)
    assert "language" in _language_columns(url)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT language FROM caption_review_items WHERE review_item_id = 'legacy-1'"
        ).fetchone()
    assert row == ("en",)

    # Downgrade back to the parent: the column is gone, the row survives.
    command.downgrade(cfg, _PARENT)
    assert "language" not in _language_columns(url)
    with sqlite3.connect(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM caption_review_items WHERE review_item_id = 'legacy-1'"
        ).fetchone()
    assert count == (1,)


def test_new_rows_default_to_en_when_language_is_unspecified(tmp_path: Path) -> None:
    """The server_default keeps working for inserts that omit language."""

    db_path = tmp_path / "captions.db"
    url = f"sqlite:///{db_path}"
    command.upgrade(_cfg(url), _HEAD)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO caption_review_items (
                review_item_id, asset_id, cue_id, start_seconds, end_seconds,
                confidence, low_confidence, status, original_text, updated_at
            ) VALUES ('no-lang', 'council-x', 'cue-1', 1.0, 2.0, 0.9, 0,
                      'pending', 'motion carries', CURRENT_TIMESTAMP)
            """
        )
        conn.commit()
        language = conn.execute(
            "SELECT language FROM caption_review_items WHERE review_item_id = 'no-lang'"
        ).fetchone()
    assert language == ("en",)


@pytest.mark.parametrize("revision", [_PARENT, _HEAD])
def test_single_head_reachable_from_both_ends(tmp_path: Path, revision: str) -> None:
    """Sanity: upgrade to the revision then all the way to head is clean."""

    url = f"sqlite:///{tmp_path / f'{revision}.db'}"
    cfg = _cfg(url)
    command.upgrade(cfg, revision)
    command.upgrade(cfg, "head")
    assert "language" in _language_columns(url)
