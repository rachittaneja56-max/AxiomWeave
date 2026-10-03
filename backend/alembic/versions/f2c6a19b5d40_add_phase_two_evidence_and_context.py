"""Add assertions, complete claim scans, immutable context manifests and retrieval substrate.

Revision ID: f2c6a19b5d40
Revises: d9a32ce14f60
"""

import sqlalchemy as sa

from alembic import op
from app.models import Vector

revision = "f2c6a19b5d40"
down_revision = "d9a32ce14f60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "knowledge_assertions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "source_pack_version_id",
            sa.Integer(),
            sa.ForeignKey("source_pack_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_region_id",
            sa.Integer(),
            sa.ForeignKey("source_regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_quote", sa.Text()),
        sa.Column("quote_start", sa.Integer()),
        sa.Column("quote_end", sa.Integer()),
        sa.Column("proposition", sa.Text(), nullable=False),
        sa.Column("normalized_hash", sa.String(64), nullable=False),
        sa.Column("subject", sa.Text()),
        sa.Column("predicate", sa.Text()),
        sa.Column("object_value", sa.Text()),
        sa.Column("date_value", sa.String(80)),
        sa.Column("unit", sa.String(80)),
        sa.Column("qualifier", sa.Text()),
        sa.Column("attribution", sa.Text()),
        sa.Column("polarity", sa.String(24)),
        sa.Column("extraction_profile", sa.String(80), nullable=False),
        sa.Column("extraction_profile_version", sa.Integer(), nullable=False),
        sa.Column("provenance_state", sa.String(16), nullable=False),
        sa.Column("review_state", sa.String(20), nullable=False, server_default="needs_review"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "provenance_state IN ('validated', 'unresolved')",
            name="ck_knowledge_assertions_provenance_state",
        ),
        sa.CheckConstraint(
            "review_state IN ('needs_review', 'reviewed')",
            name="ck_knowledge_assertions_review_state",
        ),
        sa.CheckConstraint(
            "(quote_start IS NULL AND quote_end IS NULL) OR "
            "(quote_start >= 0 AND quote_end >= quote_start)",
            name="ck_knowledge_assertions_quote_offsets",
        ),
        sa.UniqueConstraint(
            "source_region_id",
            "normalized_hash",
            "extraction_profile",
            "extraction_profile_version",
            name="uq_knowledge_assertions_exact_input",
        ),
    )
    op.create_index("ix_knowledge_assertions_owner_id", "knowledge_assertions", ["owner_id"])
    op.create_index(
        "ix_knowledge_assertions_source_pack_version_id",
        "knowledge_assertions",
        ["source_pack_version_id"],
    )
    op.create_index(
        "ix_knowledge_assertions_source_region_id", "knowledge_assertions", ["source_region_id"]
    )
    op.create_index(
        "ix_knowledge_assertions_owner_pack",
        "knowledge_assertions",
        ["owner_id", "source_pack_version_id"],
    )

    op.create_table(
        "knowledge_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "source_assertion_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "target_assertion_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("relation_kind", sa.String(80), nullable=False),
        sa.Column("extraction_profile", sa.String(80), nullable=False),
        sa.Column("extraction_profile_version", sa.Integer(), nullable=False),
        sa.Column("review_state", sa.String(20), nullable=False, server_default="needs_review"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_assertion_id != target_assertion_id", name="ck_knowledge_relations_distinct"
        ),
        sa.CheckConstraint(
            "review_state IN ('needs_review', 'reviewed')",
            name="ck_knowledge_relations_review_state",
        ),
    )
    op.create_index("ix_knowledge_relations_owner_id", "knowledge_relations", ["owner_id"])
    op.create_index(
        "ix_knowledge_relations_source_assertion_id", "knowledge_relations", ["source_assertion_id"]
    )
    op.create_index(
        "ix_knowledge_relations_target_assertion_id", "knowledge_relations", ["target_assertion_id"]
    )
    op.create_index("ix_knowledge_relations_owner", "knowledge_relations", ["owner_id"])

    op.create_table(
        "claim_scans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "artifact_version_id",
            sa.Integer(),
            sa.ForeignKey("artifact_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_version_id",
            sa.Integer(),
            sa.ForeignKey("source_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("extraction_profile", sa.String(80), nullable=False),
        sa.Column("extraction_profile_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed', 'needs_review')",
            name="ck_claim_scans_status",
        ),
        sa.UniqueConstraint("artifact_version_id", name="uq_claim_scans_artifact_version"),
    )
    op.create_index("ix_claim_scans_owner_id", "claim_scans", ["owner_id"])
    op.create_index("ix_claim_scans_source_version_id", "claim_scans", ["source_version_id"])
    op.create_index("ix_claim_scans_owner", "claim_scans", ["owner_id"])

    op.create_table(
        "claim_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "claim_scan_id",
            sa.Integer(),
            sa.ForeignKey("claim_scans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text_start", sa.Integer(), nullable=False),
        sa.Column("text_end", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("extraction_profile", sa.String(80), nullable=False),
        sa.Column("extraction_profile_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("ordinal > 0", name="ck_claim_batches_positive_ordinal"),
        sa.CheckConstraint(
            "text_start >= 0 AND text_end >= text_start", name="ck_claim_batches_text_range"
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_claim_batches_attempt_count"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed', 'needs_review')",
            name="ck_claim_batches_status",
        ),
        sa.UniqueConstraint("claim_scan_id", "ordinal", name="uq_claim_batches_scan_ordinal"),
    )
    op.create_index("ix_claim_batches_claim_scan_id", "claim_batches", ["claim_scan_id"])
    op.create_index("ix_claim_batches_scan_status", "claim_batches", ["claim_scan_id", "status"])

    op.create_table(
        "text_embedding_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_name", sa.String(100), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_name", sa.String(160), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("input_construction_version", sa.String(80), nullable=False),
        sa.Column("privacy_classification", sa.String(80), nullable=False),
        sa.Column(
            "quality_disposition", sa.String(24), nullable=False, server_default="MECHANICS_ONLY"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dimension > 0", name="ck_text_embedding_profiles_dimension"),
        sa.UniqueConstraint(
            "profile_name", "profile_version", name="uq_text_embedding_profiles_version"
        ),
    )

    op.create_table(
        "context_manifests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "source_pack_id",
            sa.Integer(),
            sa.ForeignKey("source_packs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_pack_version_id",
            sa.Integer(),
            sa.ForeignKey("source_pack_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_version_id",
            sa.Integer(),
            sa.ForeignKey("source_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("task_class", sa.String(40), nullable=False),
        sa.Column("artifact_family", sa.String(40), nullable=False),
        sa.Column("route", sa.String(40), nullable=False),
        sa.Column("context_profile", sa.String(80), nullable=False),
        sa.Column("context_profile_version", sa.Integer(), nullable=False),
        sa.Column("query_construction_version", sa.Integer(), nullable=False),
        sa.Column("query_text", sa.Text()),
        sa.Column("budget_policy_version", sa.String(40), nullable=False),
        sa.Column("estimation_method", sa.String(80), nullable=False),
        sa.Column("context_budget_units", sa.Integer(), nullable=False),
        sa.Column("available_input_budget", sa.Integer(), nullable=False),
        sa.Column("estimated_context_units", sa.Integer(), nullable=False),
        sa.Column("reserved_margin", sa.Integer(), nullable=False),
        sa.Column("extraction_coverage", sa.String(24), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("context_budget_units >= 0", name="ck_context_manifests_budget"),
        sa.CheckConstraint("estimated_context_units >= 0", name="ck_context_manifests_estimated"),
        sa.CheckConstraint("available_input_budget >= 0", name="ck_context_manifests_available"),
        sa.CheckConstraint("reserved_margin >= 0", name="ck_context_manifests_reserved"),
    )
    for column in ("owner_id", "source_pack_id", "source_pack_version_id", "source_version_id"):
        op.create_index(f"ix_context_manifests_{column}", "context_manifests", [column])
    op.create_index("ix_context_manifests_owner", "context_manifests", ["owner_id"])

    op.create_table(
        "context_manifest_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "context_manifest_id",
            sa.Integer(),
            sa.ForeignKey("context_manifests.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_region_id",
            sa.Integer(),
            sa.ForeignKey("source_regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_asset_id",
            sa.Integer(),
            sa.ForeignKey("source_assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.Integer(),
            sa.ForeignKey("source_pack_memberships.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("candidate_rank", sa.Integer()),
        sa.Column("lexical_rank", sa.Integer()),
        sa.Column("lexical_score", sa.Float()),
        sa.Column("vector_rank", sa.Integer()),
        sa.Column("vector_score", sa.Float()),
        sa.Column("fused_rank", sa.Integer()),
        sa.Column("fused_score", sa.Float()),
        sa.Column("locator", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("estimated_context_units", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("profile_metadata", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "estimated_context_units >= 0", name="ck_context_manifest_entries_estimated"
        ),
        sa.CheckConstraint(
            "candidate_rank IS NULL OR candidate_rank > 0", name="ck_context_manifest_entries_rank"
        ),
        sa.CheckConstraint(
            "lexical_rank IS NULL OR lexical_rank > 0",
            name="ck_context_manifest_entries_lexical_rank",
        ),
        sa.CheckConstraint(
            "vector_rank IS NULL OR vector_rank > 0", name="ck_context_manifest_entries_vector_rank"
        ),
        sa.CheckConstraint(
            "fused_rank IS NULL OR fused_rank > 0", name="ck_context_manifest_entries_fused_rank"
        ),
        sa.UniqueConstraint(
            "context_manifest_id", "source_region_id", name="uq_context_manifest_region"
        ),
    )
    op.create_index(
        "ix_context_manifest_entries_context_manifest_id",
        "context_manifest_entries",
        ["context_manifest_id"],
    )
    op.create_index(
        "ix_context_manifest_entries_source_region_id",
        "context_manifest_entries",
        ["source_region_id"],
    )
    if is_postgres:
        op.execute(
            """
            CREATE FUNCTION reject_context_manifest_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'Context manifests are immutable';
            END;
            $$
            """
        )
        for table in ("context_manifests", "context_manifest_entries"):
            op.execute(
                f"CREATE TRIGGER {table}_immutable "
                f"BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION reject_context_manifest_mutation()"
            )
    elif bind.dialect.name == "sqlite":
        for table in ("context_manifests", "context_manifest_entries"):
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER {table}_immutable_{action.lower()} "
                    f"BEFORE {action} ON {table} "
                    "BEGIN SELECT RAISE(ABORT, 'Context manifests are immutable'); END"
                )

    op.create_table(
        "material_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "claim_scan_id",
            sa.Integer(),
            sa.ForeignKey("claim_scans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "claim_batch_id",
            sa.Integer(),
            sa.ForeignKey("claim_batches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_assertion_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"),
        ),
        sa.Column("artifact_quote", sa.Text(), nullable=False),
        sa.Column("artifact_start", sa.Integer(), nullable=False),
        sa.Column("artifact_end", sa.Integer(), nullable=False),
        sa.Column("proposition", sa.Text(), nullable=False),
        sa.Column("normalized_hash", sa.String(64), nullable=False),
        sa.Column("claim_type", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "artifact_start >= 0 AND artifact_end >= artifact_start",
            name="ck_material_claims_offsets",
        ),
        sa.UniqueConstraint(
            "claim_batch_id",
            "artifact_start",
            "artifact_end",
            "normalized_hash",
            name="uq_material_claims_exact_span",
        ),
        sa.UniqueConstraint("knowledge_assertion_id"),
    )
    op.create_index("ix_material_claims_claim_batch_id", "material_claims", ["claim_batch_id"])
    op.create_index("ix_material_claims_scan", "material_claims", ["claim_scan_id"])

    op.create_table(
        "region_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_region_id",
            sa.Integer(),
            sa.ForeignKey("source_regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "embedding_profile_id",
            sa.Integer(),
            sa.ForeignKey("text_embedding_profiles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_region_id", "embedding_profile_id", name="uq_region_embeddings_dependency"
        ),
    )
    op.create_index(
        "ix_region_embeddings_source_region_id", "region_embeddings", ["source_region_id"]
    )
    op.create_index("ix_region_embeddings_profile", "region_embeddings", ["embedding_profile_id"])

    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("context_manifest_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_jobs_context_manifest_id_context_manifests",
            "context_manifests",
            ["context_manifest_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index("ix_jobs_context_manifest_id", "jobs", ["context_manifest_id"])
    with op.batch_alter_table("artifact_versions") as batch:
        batch.add_column(sa.Column("context_manifest_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_artifact_versions_context_manifest_id_context_manifests",
            "context_manifests",
            ["context_manifest_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_artifact_versions_context_manifest_id", "artifact_versions", ["context_manifest_id"]
    )
    with op.batch_alter_table("evidence_links") as batch:
        batch.add_column(sa.Column("material_claim_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_links_material_claim_id_material_claims",
            "material_claims",
            ["material_claim_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint("uq_evidence_links_material_claim_id", ["material_claim_id"])
        batch.add_column(sa.Column("claim_batch_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_links_claim_batch_id_claim_batches",
            "claim_batches",
            ["claim_batch_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_evidence_links_batch_claim", ["claim_batch_id", "claim_text"]
        )
        batch.add_column(sa.Column("knowledge_assertion_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_evidence_links_knowledge_assertion_id_knowledge_assertions",
            "knowledge_assertions",
            ["knowledge_assertion_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_evidence_links_knowledge_assertion_id", ["knowledge_assertion_id"]
        )
    op.create_index("ix_evidence_links_claim_batch_id", "evidence_links", ["claim_batch_id"])

    if is_postgres:
        op.create_index(
            "ix_source_regions_fts_simple",
            "source_regions",
            [sa.text("to_tsvector('simple'::regconfig, coalesce(text, ''))")],
            postgresql_using="gin",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER context_manifest_entries_immutable ON context_manifest_entries")
        op.execute("DROP TRIGGER context_manifests_immutable ON context_manifests")
        op.execute("DROP FUNCTION reject_context_manifest_mutation()")
        op.drop_index("ix_source_regions_fts_simple", table_name="source_regions")
    elif bind.dialect.name == "sqlite":
        for table in ("context_manifests", "context_manifest_entries"):
            for action in ("update", "delete"):
                op.execute(f"DROP TRIGGER {table}_immutable_{action}")
    op.drop_index("ix_evidence_links_claim_batch_id", table_name="evidence_links")
    op.drop_index("ix_artifact_versions_context_manifest_id", table_name="artifact_versions")
    op.drop_index("ix_jobs_context_manifest_id", table_name="jobs")
    with op.batch_alter_table("evidence_links") as batch:
        batch.drop_constraint("uq_evidence_links_knowledge_assertion_id", type_="unique")
        batch.drop_constraint(
            "fk_evidence_links_knowledge_assertion_id_knowledge_assertions",
            type_="foreignkey",
        )
        batch.drop_column("knowledge_assertion_id")
        batch.drop_constraint("uq_evidence_links_batch_claim", type_="unique")
        batch.drop_constraint("fk_evidence_links_claim_batch_id_claim_batches", type_="foreignkey")
        batch.drop_column("claim_batch_id")
        batch.drop_constraint("uq_evidence_links_material_claim_id", type_="unique")
        batch.drop_constraint(
            "fk_evidence_links_material_claim_id_material_claims", type_="foreignkey"
        )
        batch.drop_column("material_claim_id")
    with op.batch_alter_table("artifact_versions") as batch:
        batch.drop_constraint(
            "fk_artifact_versions_context_manifest_id_context_manifests",
            type_="foreignkey",
        )
        batch.drop_column("context_manifest_id")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_constraint("fk_jobs_context_manifest_id_context_manifests", type_="foreignkey")
        batch.drop_column("context_manifest_id")
    for table in (
        "region_embeddings",
        "material_claims",
        "context_manifest_entries",
        "context_manifests",
        "text_embedding_profiles",
        "knowledge_relations",
        "claim_batches",
        "claim_scans",
        "knowledge_assertions",
    ):
        op.drop_table(table)
