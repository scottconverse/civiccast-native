# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Migration-graph and schema-width guards (Stage B+D audit follow-up).

Locks three contracts the Stage B+D audit found violated (ENG-001/W-1,
ENG-003/W-3, ENG-012/W-8):

1. The alembic graph has exactly one head. Two heads break
   ``alembic upgrade head`` product-wide, including the installer's
   "Prepare storage" path. The reversibility tests in
   ``tests/db/test_alembic_env.py`` fail too when the graph forks, but
   this named guard makes the failure message instant.

2. Byte-size columns on ``live_finalization_jobs`` are 64-bit. Postgres
   ``INTEGER`` caps at 2,147,483,647 (~2 GiB) — a routine council-meeting
   recording size. SQLite integers are 64-bit, so only an explicit type
   assertion can catch the width mistake in every environment; the
   >2 GiB round-trip proof lives in the Docker-gated real-Postgres suite.

3. New migration revision ids sort after their ``down_revision``. The
   repo uses zero-padded numeric prefixes; an out-of-order id
   (``0011`` parented after ``0019``/``0022``) misleads readers of the
   chain and invited the W-1 mis-parenting.
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import BigInteger

from civiccast.live.models import LiveFinalizationJob

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

_NUMERIC_PREFIX = re.compile(r"^(\d+)_")


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(ALEMBIC_INI))
    return ScriptDirectory.from_config(cfg)


def test_alembic_graph_has_exactly_one_head() -> None:
    heads = _script_directory().get_heads()
    assert len(heads) == 1, (
        f"alembic graph is forked into {len(heads)} heads: {sorted(heads)}. "
        "`alembic upgrade head` (used by the installer's storage setup) fails "
        "with multiple heads; re-parent the newest migration onto the single "
        "current head before merging."
    )


def test_finalization_job_byte_columns_are_64_bit() -> None:
    for column_name in ("recording_size_bytes", "last_observed_size_bytes"):
        column_type = LiveFinalizationJob.__table__.c[column_name].type
        assert isinstance(column_type, BigInteger), (
            f"live_finalization_jobs.{column_name} must be BigInteger: Postgres "
            f"INTEGER overflows at ~2 GiB, a routine recording size. Got "
            f"{column_type!r}."
        )


def test_revision_ids_sort_after_their_down_revision() -> None:
    """Numeric-prefixed revision ids must not sort before their parents."""

    script = _script_directory()
    violations: list[str] = []
    for revision in script.walk_revisions():
        parents = revision.down_revision
        if parents is None:
            continue
        if isinstance(parents, str):
            parents = (parents,)
        child_match = _NUMERIC_PREFIX.match(revision.revision)
        if child_match is None:
            continue
        for parent in parents:
            parent_match = _NUMERIC_PREFIX.match(parent)
            if parent_match is None:
                continue
            if int(child_match.group(1)) <= int(parent_match.group(1)):
                violations.append(f"{revision.revision} revises {parent}")
    assert violations == [], (
        "Migration revision ids must sort after their down_revision so the "
        f"chain reads in order; out-of-order: {violations}"
    )
