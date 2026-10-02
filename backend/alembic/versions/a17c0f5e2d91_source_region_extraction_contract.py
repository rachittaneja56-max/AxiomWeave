"""make source region projection optional and persist extraction coverage

Revision ID: a17c0f5e2d91
Revises: e8a62c0916df
Create Date: 2026-10-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a17c0f5e2d91"
down_revision: str | None = "e8a62c0916df"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Complete is justified only for extractor methods used by the successful legacy ingest
    # paths. Unknown methods remain inspectable but conservatively have partial coverage.
    op.add_column("source_assets", sa.Column("extraction_profile", sa.String(40), nullable=True))
    op.add_column(
        "source_assets", sa.Column("extraction_profile_version", sa.Integer(), nullable=True)
    )
    op.add_column("source_assets", sa.Column("extraction_coverage", sa.String(16), nullable=True))
    op.execute(
        sa.text(
            "UPDATE source_assets SET extraction_profile = 'text', "
            "extraction_profile_version = 1, extraction_coverage = CASE "
            "WHEN extraction_method IN ('legacy_backfill', 'pasted_text', 'manual_revision', "
            "'text', 'docx', 'pdf_native', 'pdf_native_plus_ocr', 'url_html') "
            "THEN 'complete' ELSE 'partial' END"
        )
    )
    with op.batch_alter_table("source_assets") as batch_op:
        batch_op.alter_column("extraction_profile", existing_type=sa.String(40), nullable=False)
        batch_op.alter_column(
            "extraction_profile_version", existing_type=sa.Integer(), nullable=False
        )
        batch_op.alter_column("extraction_coverage", existing_type=sa.String(16), nullable=False)
        batch_op.create_check_constraint(
            "ck_source_assets_extraction_profile_version", "extraction_profile_version > 0"
        )
        batch_op.create_check_constraint(
            "ck_source_assets_extraction_coverage",
            "extraction_coverage IN ('complete', 'partial')",
        )

    with op.batch_alter_table("source_regions") as batch_op:
        batch_op.alter_column("source_segment_id", existing_type=sa.Integer(), nullable=True)
        batch_op.alter_column("text", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    connection = op.get_bind()
    null_regions = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM source_regions WHERE source_segment_id IS NULL OR text IS NULL"
        )
    )
    if null_regions:
        raise RuntimeError("Cannot restore required legacy source-region projections")

    with op.batch_alter_table("source_regions") as batch_op:
        batch_op.alter_column("source_segment_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("text", existing_type=sa.Text(), nullable=False)

    with op.batch_alter_table("source_assets") as batch_op:
        batch_op.drop_constraint("ck_source_assets_extraction_coverage", type_="check")
        batch_op.drop_constraint("ck_source_assets_extraction_profile_version", type_="check")
        batch_op.drop_column("extraction_coverage")
        batch_op.drop_column("extraction_profile_version")
        batch_op.drop_column("extraction_profile")
