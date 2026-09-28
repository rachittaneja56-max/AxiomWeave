"""add source version lineage pointer

Revision ID: f0ba32d0f7a1
Revises: a84e72119c60
Create Date: 2026-09-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0ba32d0f7a1"
down_revision: str | None = "a84e72119c60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_versions") as batch_op:
        batch_op.add_column(sa.Column("parent_source_version_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            "ix_source_versions_parent_source_version_id",
            ["parent_source_version_id"],
        )
        batch_op.create_foreign_key(
            "fk_source_versions_parent_source_version_id_source_versions",
            "source_versions",
            ["parent_source_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("source_versions") as batch_op:
        batch_op.drop_constraint(
            "fk_source_versions_parent_source_version_id_source_versions",
            type_="foreignkey",
        )
        batch_op.drop_index("ix_source_versions_parent_source_version_id")
        batch_op.drop_column("parent_source_version_id")
