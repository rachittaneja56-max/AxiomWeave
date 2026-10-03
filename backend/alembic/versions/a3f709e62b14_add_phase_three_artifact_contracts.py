"""Add Phase 3 artifact schema and claim projection metadata.

Revision ID: a3f709e62b14
Revises: f2c6a19b5d40
"""

import sqlalchemy as sa

from alembic import op

revision = "a3f709e62b14"
down_revision = "f2c6a19b5d40"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("artifact_versions", sa.Column("artifact_schema_version", sa.String(40)))
    op.add_column("claim_scans", sa.Column("text_projection", sa.Text()))


def downgrade() -> None:
    op.drop_column("claim_scans", "text_projection")
    op.drop_column("artifact_versions", "artifact_schema_version")
