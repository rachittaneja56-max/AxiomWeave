"""add evidence and discrepancy tables

Revision ID: a84e72119c60
Revises: 6bcd182fea10
Create Date: 2026-09-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a84e72119c60"
down_revision: str | None = "6bcd182fea10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("artifact_version_id", sa.Integer(), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("source_version_id", sa.Integer(), nullable=False),
        sa.Column("source_segment_id", sa.Integer(), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("source_locator", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('linked', 'support_not_located')",
            name="ck_evidence_links_status",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"], ["artifact_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["source_segment_id"], ["source_segments.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_version_id"], ["source_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_links_artifact_version_id", "evidence_links", ["artifact_version_id"]
    )
    op.create_index("ix_evidence_links_source_version_id", "evidence_links", ["source_version_id"])
    op.create_index("ix_evidence_links_source_segment_id", "evidence_links", ["source_segment_id"])

    op.create_table(
        "discrepancy_findings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_version_id", sa.Integer(), nullable=False),
        sa.Column("artifact_version_a_id", sa.Integer(), nullable=False),
        sa.Column("artifact_version_b_id", sa.Integer(), nullable=False),
        sa.Column("statement_a", sa.Text(), nullable=False),
        sa.Column("statement_b", sa.Text(), nullable=False),
        sa.Column("discrepancy_type", sa.String(length=80), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "artifact_version_a_id != artifact_version_b_id",
            name="ck_discrepancy_findings_distinct_versions",
        ),
        sa.CheckConstraint(
            "review_status IN ('open', 'dismissed')",
            name="ck_discrepancy_findings_review_status",
        ),
        sa.ForeignKeyConstraint(
            ["artifact_version_a_id"], ["artifact_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["artifact_version_b_id"], ["artifact_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["source_version_id"], ["source_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_version_a_id",
            "artifact_version_b_id",
            name="uq_discrepancy_findings_version_pair",
        ),
    )
    op.create_index(
        "ix_discrepancy_findings_source_version_id", "discrepancy_findings", ["source_version_id"]
    )
    op.create_index(
        "ix_discrepancy_findings_artifact_version_a_id",
        "discrepancy_findings",
        ["artifact_version_a_id"],
    )
    op.create_index(
        "ix_discrepancy_findings_artifact_version_b_id",
        "discrepancy_findings",
        ["artifact_version_b_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discrepancy_findings_artifact_version_b_id", table_name="discrepancy_findings"
    )
    op.drop_index(
        "ix_discrepancy_findings_artifact_version_a_id", table_name="discrepancy_findings"
    )
    op.drop_index("ix_discrepancy_findings_source_version_id", table_name="discrepancy_findings")
    op.drop_table("discrepancy_findings")
    op.drop_index("ix_evidence_links_source_segment_id", table_name="evidence_links")
    op.drop_index("ix_evidence_links_source_version_id", table_name="evidence_links")
    op.drop_index("ix_evidence_links_artifact_version_id", table_name="evidence_links")
    op.drop_table("evidence_links")
