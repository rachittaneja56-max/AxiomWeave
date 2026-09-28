"""add artifact review state

Revision ID: 6bcd182fea10
Revises: 36f1c625bc40
Create Date: 2026-09-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6bcd182fea10"
down_revision: str | None = "36f1c625bc40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("artifact_versions") as batch_op:
        batch_op.add_column(
            sa.Column("review_status", sa.String(length=16), nullable=False, server_default="draft")
        )
        batch_op.create_check_constraint(
            "ck_artifact_versions_review_status",
            "review_status IN ('draft', 'accepted', 'rejected')",
        )


def downgrade() -> None:
    with op.batch_alter_table("artifact_versions") as batch_op:
        batch_op.drop_constraint("ck_artifact_versions_review_status", type_="check")
        batch_op.drop_column("review_status")
