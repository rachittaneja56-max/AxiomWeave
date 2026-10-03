"""allow global Weave creation plans

Revision ID: a41f028bc9e2
Revises: d6a2c9f7b140
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a41f028bc9e2"
down_revision: str | None = "d6a2c9f7b140"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("action_plans") as batch_op:
        batch_op.alter_column(
            "transformation_run_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.alter_column(
            "transformation_run_id",
            existing_type=sa.Integer(),
            nullable=True,
        )


def downgrade() -> None:
    connection = op.get_bind()
    global_plans = connection.scalar(
        sa.text("SELECT COUNT(*) FROM action_plans WHERE transformation_run_id IS NULL")
    )
    global_messages = connection.scalar(
        sa.text("SELECT COUNT(*) FROM chat_messages WHERE transformation_run_id IS NULL")
    )
    if global_plans or global_messages:
        raise RuntimeError("Global Weave history must be removed before this migration is reversed")
    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.alter_column(
            "transformation_run_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    with op.batch_alter_table("action_plans") as batch_op:
        batch_op.alter_column(
            "transformation_run_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
