"""ensure one artifact run per selected output

Revision ID: 36f1c625bc40
Revises: 0b2d23cf6e29
Create Date: 2026-09-29 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "36f1c625bc40"
down_revision: str | None = "0b2d23cf6e29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("artifact_runs") as batch_op:
        batch_op.create_unique_constraint(
            "uq_artifact_runs_transformation_output",
            ["transformation_run_id", "output_type"],
        )


def downgrade() -> None:
    with op.batch_alter_table("artifact_runs") as batch_op:
        batch_op.drop_constraint("uq_artifact_runs_transformation_output", type_="unique")
