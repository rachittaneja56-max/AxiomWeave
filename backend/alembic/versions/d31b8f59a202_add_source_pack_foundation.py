"""add source pack foundation

Revision ID: d31b8f59a202
Revises: c2a7e18f4d91
Create Date: 2026-10-02 00:00:00.000000
"""

import re
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d31b8f59a202"
down_revision: str | None = "c2a7e18f4d91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    existing_versions = list(
        connection.execute(
            sa.text(
                "SELECT id, source_id, parent_source_version_id FROM source_versions ORDER BY id"
            )
        ).mappings()
    )
    source_by_version_id = {int(row["id"]): int(row["source_id"]) for row in existing_versions}
    for version in existing_versions:
        parent_id = version["parent_source_version_id"]
        if parent_id is not None and source_by_version_id.get(int(parent_id)) != int(
            version["source_id"]
        ):
            raise RuntimeError("Source version parent lineage cannot be backfilled safely")

    op.create_table(
        "source_packs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", name="uq_source_packs_source"),
    )
    op.create_index(op.f("ix_source_packs_owner_id"), "source_packs", ["owner_id"])
    op.create_table(
        "source_pack_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_pack_id", sa.Integer(), nullable=False),
        sa.Column("source_version_id", sa.Integer(), nullable=False),
        sa.Column("parent_source_pack_version_id", sa.Integer(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version_number > 0", name="ck_source_pack_versions_positive_number"),
        sa.ForeignKeyConstraint(
            ["parent_source_pack_version_id"], ["source_pack_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["source_pack_id"], ["source_packs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_version_id"], ["source_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_pack_id", "version_number", name="uq_source_pack_versions_number"
        ),
        sa.UniqueConstraint("source_version_id", name="uq_source_pack_versions_source_version"),
    )
    op.create_index(
        op.f("ix_source_pack_versions_source_pack_id"), "source_pack_versions", ["source_pack_id"]
    )
    op.create_index(
        op.f("ix_source_pack_versions_parent_source_pack_version_id"),
        "source_pack_versions",
        ["parent_source_pack_version_id"],
    )
    op.create_table(
        "source_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_pack_version_id", sa.Integer(), nullable=False),
        sa.Column("authority_role", sa.String(length=24), nullable=False),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("media_type", sa.String(length=127), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=True),
        sa.Column("provenance_url", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "authority_role IN ('authoritative', 'supporting')",
            name="ck_source_assets_authority_role",
        ),
        sa.CheckConstraint("byte_size >= 0", name="ck_source_assets_nonnegative_byte_size"),
        sa.CheckConstraint(
            "source_kind IN ('text', 'file', 'url')", name="ck_source_assets_source_kind"
        ),
        sa.ForeignKeyConstraint(
            ["source_pack_version_id"], ["source_pack_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_source_assets_storage_key"),
    )
    op.create_index(
        op.f("ix_source_assets_source_pack_version_id"), "source_assets", ["source_pack_version_id"]
    )
    op.create_table(
        "source_regions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_asset_id", sa.Integer(), nullable=False),
        sa.Column("source_segment_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("locator", sa.String(length=255), nullable=False),
        sa.Column("region_type", sa.String(length=32), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint("ordinal > 0", name="ck_source_regions_positive_ordinal"),
        sa.CheckConstraint(
            "page_number IS NULL OR page_number > 0", name="ck_source_regions_positive_page"
        ),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_segment_id"], ["source_segments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_asset_id", "locator", name="uq_source_regions_asset_locator"),
        sa.UniqueConstraint("source_asset_id", "ordinal", name="uq_source_regions_asset_ordinal"),
        sa.UniqueConstraint("source_segment_id", name="uq_source_regions_source_segment"),
    )
    op.create_index(
        op.f("ix_source_regions_source_asset_id"), "source_regions", ["source_asset_id"]
    )

    source_table = sa.table(
        "sources",
        sa.column("id", sa.Integer),
        sa.column("owner_id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    version_table = sa.table(
        "source_versions",
        sa.column("id", sa.Integer),
        sa.column("source_id", sa.Integer),
        sa.column("parent_source_version_id", sa.Integer),
        sa.column("version_number", sa.Integer),
        sa.column("source_text", sa.Text),
        sa.column("content_hash", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    segment_table = sa.table(
        "source_segments",
        sa.column("id", sa.Integer),
        sa.column("source_version_id", sa.Integer),
        sa.column("ordinal", sa.Integer),
        sa.column("locator", sa.String),
        sa.column("segment_text", sa.Text),
    )
    pack_table = sa.table(
        "source_packs",
        sa.column("id", sa.Integer),
        sa.column("source_id", sa.Integer),
        sa.column("owner_id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    pack_version_table = sa.table(
        "source_pack_versions",
        sa.column("id", sa.Integer),
        sa.column("source_pack_id", sa.Integer),
        sa.column("source_version_id", sa.Integer),
        sa.column("parent_source_pack_version_id", sa.Integer),
        sa.column("version_number", sa.Integer),
        sa.column("content_hash", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    asset_table = sa.table(
        "source_assets",
        sa.column("id", sa.Integer),
        sa.column("source_pack_version_id", sa.Integer),
        sa.column("authority_role", sa.String),
        sa.column("source_kind", sa.String),
        sa.column("media_type", sa.String),
        sa.column("original_filename", sa.String),
        sa.column("byte_size", sa.Integer),
        sa.column("content_hash", sa.String),
        sa.column("storage_key", sa.String),
        sa.column("provenance_url", sa.Text),
        sa.column("extraction_method", sa.String),
        sa.column("created_at", sa.DateTime),
    )
    region_table = sa.table(
        "source_regions",
        sa.column("source_asset_id", sa.Integer),
        sa.column("source_segment_id", sa.Integer),
        sa.column("ordinal", sa.Integer),
        sa.column("locator", sa.String),
        sa.column("region_type", sa.String),
        sa.column("page_number", sa.Integer),
        sa.column("text", sa.Text),
    )

    source_to_pack: dict[int, int] = {}
    for source in connection.execute(
        sa.select(source_table).order_by(source_table.c.id)
    ).mappings():
        result = connection.execute(
            sa.insert(pack_table)
            .values(
                source_id=source["id"],
                owner_id=source["owner_id"],
                title=source["title"],
                created_at=source["created_at"],
            )
            .returning(pack_table.c.id)
        )
        source_to_pack[int(source["id"])] = int(result.scalar_one())

    source_version_to_pack_version: dict[int, int] = {}
    source_versions = list(
        connection.execute(
            sa.select(version_table).order_by(
                version_table.c.source_id, version_table.c.version_number
            )
        ).mappings()
    )
    pack_versions_needing_parents: list[tuple[int, int | None, int]] = []
    source_version_by_id = {int(row["id"]): row for row in source_versions}
    for version in source_versions:
        pack_id = source_to_pack[int(version["source_id"])]
        result = connection.execute(
            sa.insert(pack_version_table)
            .values(
                source_pack_id=pack_id,
                source_version_id=version["id"],
                parent_source_pack_version_id=None,
                version_number=version["version_number"],
                content_hash=version["content_hash"],
                created_at=version["created_at"],
            )
            .returning(pack_version_table.c.id)
        )
        pack_version_id = int(result.scalar_one())
        source_version_id = int(version["id"])
        source_version_to_pack_version[source_version_id] = pack_version_id
        pack_versions_needing_parents.append(
            (pack_version_id, version["parent_source_version_id"], int(version["source_id"]))
        )

    for pack_version_id, parent_source_version_id, source_id in pack_versions_needing_parents:
        if parent_source_version_id is None:
            continue
        parent = source_version_by_id.get(int(parent_source_version_id))
        if parent is None or int(parent["source_id"]) != source_id:
            raise RuntimeError("Source version parent lineage cannot be backfilled safely")
        connection.execute(
            pack_version_table.update()
            .where(pack_version_table.c.id == pack_version_id)
            .values(
                parent_source_pack_version_id=source_version_to_pack_version[
                    int(parent_source_version_id)
                ]
            )
        )

    version_to_asset: dict[int, int] = {}
    for version in source_versions:
        source_text = str(version["source_text"])
        result = connection.execute(
            sa.insert(asset_table)
            .values(
                source_pack_version_id=source_version_to_pack_version[int(version["id"])],
                authority_role="authoritative",
                source_kind="text",
                media_type="text/plain",
                original_filename=None,
                byte_size=len(source_text.encode("utf-8")),
                content_hash=version["content_hash"],
                storage_key=None,
                provenance_url=None,
                extraction_method="legacy_backfill",
                created_at=version["created_at"],
            )
            .returning(asset_table.c.id)
        )
        version_to_asset[int(version["id"])] = int(result.scalar_one())

    for segment in connection.execute(
        sa.select(segment_table).order_by(
            segment_table.c.source_version_id, segment_table.c.ordinal
        )
    ).mappings():
        locator = str(segment["locator"])
        prefix = locator.partition(":")[0]
        page_match = re.fullmatch(r"page:(\d+)", locator)
        connection.execute(
            sa.insert(region_table).values(
                source_asset_id=version_to_asset[int(segment["source_version_id"])],
                source_segment_id=segment["id"],
                ordinal=segment["ordinal"],
                locator=locator,
                region_type=prefix[:32],
                page_number=int(page_match.group(1)) if page_match else None,
                text=segment["segment_text"],
            )
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_source_regions_source_asset_id"), table_name="source_regions")
    op.drop_table("source_regions")
    op.drop_index(op.f("ix_source_assets_source_pack_version_id"), table_name="source_assets")
    op.drop_table("source_assets")
    op.drop_index(
        op.f("ix_source_pack_versions_parent_source_pack_version_id"),
        table_name="source_pack_versions",
    )
    op.drop_index(op.f("ix_source_pack_versions_source_pack_id"), table_name="source_pack_versions")
    op.drop_table("source_pack_versions")
    op.drop_index(op.f("ix_source_packs_owner_id"), table_name="source_packs")
    op.drop_table("source_packs")
