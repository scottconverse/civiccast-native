# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Add honest pending-content-reload visibility fields to egress_states.

Revision ID: 0088_egress_state_reload_visibility
Revises: 0087_retention_terms
Create Date: 2026-09-06

Hostile-review redo of the pending-content-reload latch fix (2026-09-05
tester finding + follow-up review). ``updated_at`` is the row's public
"last write" timestamp and must keep meaning exactly that -- it advances on
every write, including a poll tick that rewrites an unchanged state.
``state_entered_at`` is the DIFFERENT signal ``alerting/runtime_status.py``'s
"how long has this channel been stuck" reading actually needs: it only
advances when ``state`` itself changes (see ``daemon.py``'s ``_write_state``).
Backfilled from ``updated_at`` for existing rows (the best available anchor;
an existing row's true state-entry time is not recoverable).

``pending_reload_since`` / ``pending_reload_deadline`` make a pending
content-reload that has fallen back to the terminate+restart drain path
(``daemon.py``'s ``_request_reload``) durably visible and honest instead of
a bare, unexplained ``TRANSITIONING`` row: for an ON_AIR program that path is
a graceful wait for the outgoing leg's own natural EOS, by design, not a
stuck latch to cancel. Both are nullable and default NULL (no reload
pending); a real write clears them by simply not supplying a value.

Revision numbers are repo-global -- parent on the single current head
(``alembic heads`` at authoring time: ``0087_retention_terms``, the
``civiccast.schedule`` module's most recent migration).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0088_egress_state_reload_visibility"
down_revision = "0087_retention_terms"
branch_labels = None
depends_on = None


def _use_schema() -> bool:
    return op.get_bind().dialect.name != "sqlite"


def upgrade() -> None:
    schema = "civiccast" if _use_schema() else None
    table = f"{schema}.egress_states" if schema else "egress_states"
    op.add_column(
        "egress_states",
        sa.Column("state_entered_at", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.add_column(
        "egress_states",
        sa.Column("pending_reload_since", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    op.add_column(
        "egress_states",
        sa.Column("pending_reload_deadline", sa.DateTime(timezone=True), nullable=True),
        schema=schema,
    )
    # Backfill: an existing row's true state-entry time is not recoverable,
    # so updated_at (the closest available anchor) is the honest choice.
    op.execute(
        f"UPDATE {table} SET state_entered_at = updated_at WHERE state_entered_at IS NULL"  # noqa: S608 - identifier is code-controlled, not user input  # nosec B608
    )
    # SQLite cannot ALTER COLUMN ... SET NOT NULL in place -- batch mode
    # rebuilds the table (see 0018_manifest_url_nullable_sqlite.py for the
    # same pattern). Postgres supports the plain ALTER but batch mode works
    # identically there too, so one code path covers both dialects.
    with op.batch_alter_table("egress_states", schema=schema) as batch_op:
        batch_op.alter_column(
            "state_entered_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )


def downgrade() -> None:
    schema = "civiccast" if _use_schema() else None
    op.drop_column("egress_states", "pending_reload_deadline", schema=schema)
    op.drop_column("egress_states", "pending_reload_since", schema=schema)
    op.drop_column("egress_states", "state_entered_at", schema=schema)
