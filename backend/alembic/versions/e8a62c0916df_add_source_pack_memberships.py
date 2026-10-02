"""add immutable source pack memberships

Revision ID: e8a62c0916df
Revises: d31b8f59a202
Create Date: 2026-10-02 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e8a62c0916df"
down_revision: str | None = "d31b8f59a202"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    existing_memberships = list(
        connection.execute(
            sa.text(
                """
                SELECT pack_version.id AS pack_version_id,
                       pack_version.source_version_id,
                       pack.owner_id AS pack_owner_id,
                       source.owner_id AS source_owner_id,
                       COUNT(asset.id) AS asset_count,
                       MIN(asset.id) AS source_asset_id,
                       MIN(asset.source_pack_version_id) AS asset_pack_version_id,
                       pack_version.created_at
                FROM source_pack_versions AS pack_version
                JOIN source_packs AS pack ON pack.id = pack_version.source_pack_id
                JOIN source_versions AS source_version
                  ON source_version.id = pack_version.source_version_id
                JOIN sources AS source ON source.id = source_version.source_id
                LEFT JOIN source_assets AS asset
                  ON asset.source_pack_version_id = pack_version.id
                GROUP BY pack_version.id, pack_version.source_version_id,
                         pack.owner_id, source.owner_id, pack_version.created_at
                ORDER BY pack_version.id
                """
            )
        ).mappings()
    )
    if any(
        int(row["asset_count"]) != 1
        or int(row["asset_pack_version_id"] or -1) != int(row["pack_version_id"])
        or int(row["pack_owner_id"]) != int(row["source_owner_id"])
        for row in existing_memberships
    ):
        raise RuntimeError(
            "Existing source pack versions cannot be backfilled as one PRIMARY member"
        )

    op.create_table(
        "source_pack_memberships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_pack_version_id", sa.Integer(), nullable=False),
        sa.Column("source_version_id", sa.Integer(), nullable=False),
        sa.Column("source_asset_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('PRIMARY', 'SUPPORTING', 'STYLE', 'REFERENCE', 'OPERATOR_CONTEXT')",
            name="ck_source_pack_membership_role",
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_source_pack_membership_positive_ordinal"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_pack_version_id"], ["source_pack_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["source_version_id"], ["source_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_pack_version_id", "source_version_id", name="uq_pack_member_source_version"
        ),
        sa.UniqueConstraint(
            "source_pack_version_id", "source_asset_id", name="uq_pack_member_source_asset"
        ),
        sa.UniqueConstraint(
            "source_pack_version_id", "ordinal", name="uq_pack_member_version_ordinal"
        ),
    )
    op.create_index(
        op.f("ix_source_pack_memberships_source_pack_version_id"),
        "source_pack_memberships",
        ["source_pack_version_id"],
    )
    op.create_index(
        op.f("ix_source_pack_memberships_source_version_id"),
        "source_pack_memberships",
        ["source_version_id"],
    )
    op.create_index(
        op.f("ix_source_pack_memberships_source_asset_id"),
        "source_pack_memberships",
        ["source_asset_id"],
    )
    op.create_index(
        "uq_source_pack_membership_primary",
        "source_pack_memberships",
        ["source_pack_version_id"],
        unique=True,
        sqlite_where=sa.text("role = 'PRIMARY'"),
        postgresql_where=sa.text("role = 'PRIMARY'"),
    )

    for membership in existing_memberships:
        connection.execute(
            sa.text(
                """
                INSERT INTO source_pack_memberships (
                    source_pack_version_id, source_version_id, source_asset_id,
                    ordinal, role, created_at
                ) VALUES (
                    :pack_version_id, :source_version_id, :source_asset_id,
                    1, 'PRIMARY', :created_at
                )
                """
            ),
            {
                "pack_version_id": membership["pack_version_id"],
                "source_version_id": membership["source_version_id"],
                "source_asset_id": membership["source_asset_id"],
                "created_at": membership["created_at"],
            },
        )


def downgrade() -> None:
    op.drop_index("uq_source_pack_membership_primary", table_name="source_pack_memberships")
    op.drop_index(
        op.f("ix_source_pack_memberships_source_asset_id"), table_name="source_pack_memberships"
    )
    op.drop_index(
        op.f("ix_source_pack_memberships_source_version_id"),
        table_name="source_pack_memberships",
    )
    op.drop_index(
        op.f("ix_source_pack_memberships_source_pack_version_id"),
        table_name="source_pack_memberships",
    )
    op.drop_table("source_pack_memberships")
