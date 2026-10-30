# SPDX-License-Identifier: Apache-2.0
# Copyright (c) The CivicCast Authors
"""Persist per-channel repeat intent separately from automatic startup."""

import sqlalchemy as sa
from alembic import op

revision = "0098_channel_repeat_schedule"
down_revision = "0097_agenda_minutes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    schema = "civiccast" if op.get_bind().dialect.name != "sqlite" else None
    op.add_column(
        "egress_configs", sa.Column("repeat_schedule", sa.Boolean(), nullable=True), schema=schema
    )


def downgrade() -> None:
    schema = "civiccast" if op.get_bind().dialect.name != "sqlite" else None
    with op.batch_alter_table("egress_configs", schema=schema) as batch:
        batch.drop_column("repeat_schedule")
