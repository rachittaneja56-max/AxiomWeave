"""Add Phase 4 blocks, evidence assessments, lineage and deterministic alignment.

Revision ID: c4a91b0d7e22
Revises: a3f709e62b14
"""

import sqlalchemy as sa

from alembic import op

revision = "c4a91b0d7e22"
down_revision = "a3f709e62b14"
branch_labels = None
depends_on = None


def _create_immutability_triggers() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER artifact_versions_immutable_update "
            "BEFORE UPDATE ON artifact_versions "
            "WHEN NEW.artifact_run_id IS NOT OLD.artifact_run_id "
            "OR NEW.version_number IS NOT OLD.version_number "
            "OR NEW.source_version_id IS NOT OLD.source_version_id "
            "OR NEW.context_manifest_id IS NOT OLD.context_manifest_id "
            "OR NEW.content IS NOT OLD.content "
            "OR NEW.provider IS NOT OLD.provider "
            "OR NEW.model IS NOT OLD.model "
            "OR NEW.prompt_version IS NOT OLD.prompt_version "
            "OR NEW.prompt_hash IS NOT OLD.prompt_hash "
            "OR NEW.artifact_schema_version IS NOT OLD.artifact_schema_version "
            "OR NEW.origin IS NOT OLD.origin "
            "OR NEW.created_at IS NOT OLD.created_at "
            "BEGIN SELECT RAISE(ABORT, 'artifact version snapshot is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER artifact_versions_immutable_delete BEFORE DELETE ON artifact_versions "
            "BEGIN SELECT RAISE(ABORT, 'artifact version snapshot is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER artifact_blocks_immutable_update BEFORE UPDATE ON artifact_blocks "
            "BEGIN SELECT RAISE(ABORT, 'artifact block snapshot is immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER artifact_blocks_immutable_delete BEFORE DELETE ON artifact_blocks "
            "BEGIN SELECT RAISE(ABORT, 'artifact block snapshot is immutable'); END"
        )
    elif bind.dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION prevent_artifact_snapshot_mutation() RETURNS trigger AS $$ "
            "BEGIN IF TG_OP = 'DELETE' THEN "
            "RAISE EXCEPTION 'artifact snapshot is immutable'; END IF; "
            "IF TG_TABLE_NAME = 'artifact_versions' THEN "
            "IF ROW(NEW.artifact_run_id, NEW.version_number, NEW.source_version_id, "
            "NEW.context_manifest_id, NEW.content, NEW.provider, NEW.model, NEW.prompt_version, "
            "NEW.prompt_hash, NEW.artifact_schema_version, NEW.origin, NEW.created_at) "
            "IS DISTINCT FROM "
            "ROW(OLD.artifact_run_id, OLD.version_number, OLD.source_version_id, "
            "OLD.context_manifest_id, OLD.content, OLD.provider, OLD.model, OLD.prompt_version, "
            "OLD.prompt_hash, OLD.artifact_schema_version, OLD.origin, OLD.created_at) THEN "
            "RAISE EXCEPTION 'artifact version snapshot is immutable'; END IF; "
            "ELSE RAISE EXCEPTION 'artifact snapshot is immutable'; END IF; "
            "RETURN NEW; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER artifact_versions_immutable BEFORE UPDATE OR DELETE "
            "ON artifact_versions "
            "FOR EACH ROW EXECUTE FUNCTION prevent_artifact_snapshot_mutation()"
        )
        op.execute(
            "CREATE TRIGGER artifact_blocks_immutable BEFORE UPDATE OR DELETE ON artifact_blocks "
            "FOR EACH ROW EXECUTE FUNCTION prevent_artifact_snapshot_mutation()"
        )


def upgrade() -> None:
    op.add_column("artifact_versions", sa.Column("origin", sa.String(32), nullable=True))
    op.add_column("jobs", sa.Column("targeted_block_keys", sa.JSON(), nullable=True))
    with op.batch_alter_table("material_claims") as batch:
        batch.add_column(sa.Column("block_mapping_state", sa.String(16), nullable=True))
        batch.create_check_constraint(
            "ck_material_claims_block_mapping_state",
            "block_mapping_state IS NULL OR block_mapping_state IN "
            "('validated', 'ambiguous', 'unmapped')",
        )
    with op.batch_alter_table("discrepancy_findings") as batch:
        batch.add_column(sa.Column("material_claim_a_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("material_claim_b_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_discrepancy_claim_a",
            "material_claims",
            ["material_claim_a_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_discrepancy_claim_b",
            "material_claims",
            ["material_claim_b_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_discrepancy_findings_material_claim_a_id",
        "discrepancy_findings",
        ["material_claim_a_id"],
    )
    op.create_index(
        "ix_discrepancy_findings_material_claim_b_id",
        "discrepancy_findings",
        ["material_claim_b_id"],
    )

    op.create_table(
        "artifact_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artifact_version_id",
            sa.Integer(),
            sa.ForeignKey("artifact_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("block_key", sa.String(255), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(40), nullable=False),
        sa.Column("visible_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("structural_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "artifact_version_id", "block_key", name="uq_artifact_blocks_version_key"
        ),
        sa.UniqueConstraint(
            "artifact_version_id", "ordinal", name="uq_artifact_blocks_version_ordinal"
        ),
        sa.CheckConstraint("ordinal > 0", name="ck_artifact_blocks_positive_ordinal"),
    )
    op.create_index(
        "ix_artifact_blocks_artifact_version_id", "artifact_blocks", ["artifact_version_id"]
    )

    op.create_table(
        "material_claim_blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "material_claim_id",
            sa.Integer(),
            sa.ForeignKey("material_claims.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "artifact_block_id",
            sa.Integer(),
            sa.ForeignKey("artifact_blocks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("mapping_state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("material_claim_id", "artifact_block_id", name="uq_claim_block_link"),
        sa.CheckConstraint(
            "mapping_state IN ('validated', 'ambiguous')", name="ck_claim_block_state"
        ),
    )
    op.create_index(
        "ix_material_claim_blocks_material_claim_id", "material_claim_blocks", ["material_claim_id"]
    )
    op.create_index(
        "ix_material_claim_blocks_artifact_block_id", "material_claim_blocks", ["artifact_block_id"]
    )

    op.create_table(
        "lineage_proposals",
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
            "artifact_block_id",
            sa.Integer(),
            sa.ForeignKey("artifact_blocks.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "material_claim_id",
            sa.Integer(),
            sa.ForeignKey("material_claims.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("proposed_block_key", sa.String(255), nullable=False),
        sa.Column("proposed_claim", sa.Text(), nullable=False),
        sa.Column("proposed_source_region_id", sa.Integer(), nullable=True),
        sa.Column("proposed_assertion_id", sa.Integer(), nullable=True),
        sa.Column("proposed_quote", sa.Text(), nullable=False),
        sa.Column("proposed_quote_start", sa.Integer(), nullable=True),
        sa.Column("proposed_quote_end", sa.Integer(), nullable=True),
        sa.Column("validated_quote_start", sa.Integer(), nullable=True),
        sa.Column("validated_quote_end", sa.Integer(), nullable=True),
        sa.Column("validation_state", sa.String(24), nullable=False),
        sa.Column("rejection_reason", sa.String(80), nullable=True),
        sa.Column("proposal_profile", sa.String(80), nullable=False),
        sa.Column("proposal_profile_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "validation_state IN ('validated', 'invalid_scope', 'invalid_region', "
            "'invalid_assertion', 'invalid_span', 'ambiguous', 'unresolved')",
            name="ck_lineage_proposals_validation_state",
        ),
        sa.CheckConstraint(
            "(proposed_quote_start IS NULL AND proposed_quote_end IS NULL) OR "
            "(proposed_quote_start >= 0 AND proposed_quote_end >= proposed_quote_start)",
            name="ck_lineage_proposals_quote_offsets",
        ),
        sa.CheckConstraint(
            "(validated_quote_start IS NULL AND validated_quote_end IS NULL) OR "
            "(validated_quote_start >= 0 AND validated_quote_end > validated_quote_start)",
            name="ck_lineage_proposals_validated_quote_offsets",
        ),
    )
    for table in ("owner_id", "artifact_version_id"):
        op.create_index(f"ix_lineage_proposals_{table}", "lineage_proposals", [table])
    op.create_index(
        "ix_lineage_proposals_artifact_block_id", "lineage_proposals", ["artifact_block_id"]
    )
    op.create_index(
        "ix_lineage_proposals_material_claim_id", "lineage_proposals", ["material_claim_id"]
    )

    op.create_table(
        "claim_evidence_assessments",
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
            "material_claim_id",
            sa.Integer(),
            sa.ForeignKey("material_claims.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "context_manifest_id",
            sa.Integer(),
            sa.ForeignKey("context_manifests.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "knowledge_assertion_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "source_region_id",
            sa.Integer(),
            sa.ForeignKey("source_regions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("evidence_state", sa.String(24), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("quote_start", sa.Integer(), nullable=True),
        sa.Column("quote_end", sa.Integer(), nullable=True),
        sa.Column("assessment_method", sa.String(24), nullable=False),
        sa.Column("verifier_profile", sa.String(80), nullable=False),
        sa.Column("verifier_profile_version", sa.String(40), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("review_state", sa.String(16), nullable=False),
        sa.Column("adjudicated_state", sa.String(24), nullable=True),
        sa.Column(
            "reviewed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_state IN ('quote_located', 'supported', 'partial', 'contradicted', "
            "'missing', 'ambiguous', 'conflict', 'non_factual')",
            name="ck_claim_evidence_state",
        ),
        sa.CheckConstraint(
            "assessment_method IN ('mechanical', 'semantic_verifier', 'human')",
            name="ck_claim_evidence_method",
        ),
        sa.CheckConstraint(
            "review_state IN ('needs_review', 'reviewed')", name="ck_claim_evidence_review"
        ),
        sa.CheckConstraint(
            "adjudicated_state IS NULL OR adjudicated_state IN "
            "('quote_located', 'supported', 'partial', 'contradicted', 'missing', "
            "'ambiguous', 'conflict', 'non_factual')",
            name="ck_claim_evidence_adjudicated_state",
        ),
        sa.CheckConstraint(
            "(quote_start IS NULL AND quote_end IS NULL) OR "
            "(quote_start >= 0 AND quote_end >= quote_start)",
            name="ck_claim_evidence_quote_offsets",
        ),
    )
    for table in (
        "owner_id",
        "artifact_version_id",
        "material_claim_id",
        "context_manifest_id",
        "knowledge_assertion_id",
        "source_region_id",
    ):
        op.create_index(
            f"ix_claim_evidence_assessments_{table}", "claim_evidence_assessments", [table]
        )
    op.create_index(
        "ix_claim_evidence_owner_version",
        "claim_evidence_assessments",
        ["owner_id", "artifact_version_id"],
    )

    op.create_table(
        "artifact_block_dependencies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artifact_block_id",
            sa.Integer(),
            sa.ForeignKey("artifact_blocks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_region_id",
            sa.Integer(),
            sa.ForeignKey("source_regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "knowledge_assertion_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("source_content_hash", sa.String(64), nullable=False),
        sa.Column("dependency_hash", sa.String(64), nullable=False),
        sa.Column("dependency_kind", sa.String(16), nullable=False),
        sa.Column("origin", sa.String(24), nullable=False),
        sa.Column("profile_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "artifact_block_id", "source_region_id", "dependency_hash", name="uq_block_dependency"
        ),
        sa.CheckConstraint(
            "dependency_kind IN ('quote', 'assertion', 'lineage')", name="ck_block_dependency_kind"
        ),
        sa.CheckConstraint(
            "origin IN ('proposal', 'evidence', 'carried_forward')",
            name="ck_block_dependency_origin",
        ),
    )
    op.create_index(
        "ix_artifact_block_dependencies_artifact_block_id",
        "artifact_block_dependencies",
        ["artifact_block_id"],
    )
    op.create_index(
        "ix_artifact_block_dependencies_source_region_id",
        "artifact_block_dependencies",
        ["source_region_id"],
    )
    op.create_index(
        "ix_artifact_block_dependencies_knowledge_assertion_id",
        "artifact_block_dependencies",
        ["knowledge_assertion_id"],
    )

    op.create_table(
        "source_region_alignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "parent_pack_version_id",
            sa.Integer(),
            sa.ForeignKey("source_pack_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "child_pack_version_id",
            sa.Integer(),
            sa.ForeignKey("source_pack_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "old_region_id",
            sa.Integer(),
            sa.ForeignKey("source_regions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "new_region_id",
            sa.Integer(),
            sa.ForeignKey("source_regions.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("alignment_state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "alignment_state IN ('unchanged', 'moved', 'changed', 'split', 'merged', "
            "'ambiguous', 'removed', 'added')",
            name="ck_source_region_alignment_state",
        ),
        sa.CheckConstraint(
            "(old_region_id IS NOT NULL OR alignment_state = 'added') AND "
            "(new_region_id IS NOT NULL OR alignment_state = 'removed')",
            name="ck_source_region_alignment_endpoints",
        ),
    )
    op.create_index(
        "ix_source_region_alignments_versions",
        "source_region_alignments",
        ["parent_pack_version_id", "child_pack_version_id"],
    )
    op.create_index(
        "ix_source_region_alignments_old_region_id", "source_region_alignments", ["old_region_id"]
    )
    op.create_index(
        "ix_source_region_alignments_new_region_id", "source_region_alignments", ["new_region_id"]
    )

    op.create_table(
        "artifact_review_decisions",
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
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('accepted', 'rejected')", name="ck_artifact_review_decision"
        ),
    )
    op.create_index(
        "ix_artifact_review_decisions_owner_id", "artifact_review_decisions", ["owner_id"]
    )
    op.create_index(
        "ix_artifact_review_decisions_artifact_version_id",
        "artifact_review_decisions",
        ["artifact_version_id"],
    )
    op.create_index(
        "ix_artifact_review_decisions_version",
        "artifact_review_decisions",
        ["artifact_version_id", "created_at"],
    )

    # Existing artifacts stay lineage-unavailable until re-analysis. Their blocks,
    # evidence, and review history cannot be reconstructed as historical facts.
    op.execute("UPDATE artifact_versions SET origin = 'legacy' WHERE origin IS NULL")
    op.execute("UPDATE material_claims SET block_mapping_state = 'unmapped'")
    _create_immutability_triggers()


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for name in (
            "artifact_versions_immutable_update",
            "artifact_versions_immutable_delete",
            "artifact_blocks_immutable_update",
            "artifact_blocks_immutable_delete",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    elif bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS artifact_versions_immutable ON artifact_versions")
        op.execute("DROP TRIGGER IF EXISTS artifact_blocks_immutable ON artifact_blocks")
        op.execute("DROP FUNCTION IF EXISTS prevent_artifact_snapshot_mutation()")

    op.drop_table("artifact_review_decisions")
    op.drop_table("source_region_alignments")
    op.drop_table("artifact_block_dependencies")
    op.drop_table("claim_evidence_assessments")
    op.drop_table("lineage_proposals")
    op.drop_table("material_claim_blocks")
    op.drop_table("artifact_blocks")
    op.drop_index("ix_discrepancy_findings_material_claim_b_id", table_name="discrepancy_findings")
    op.drop_index("ix_discrepancy_findings_material_claim_a_id", table_name="discrepancy_findings")
    with op.batch_alter_table("discrepancy_findings") as batch:
        batch.drop_constraint("fk_discrepancy_claim_b", type_="foreignkey")
        batch.drop_constraint("fk_discrepancy_claim_a", type_="foreignkey")
        batch.drop_column("material_claim_b_id")
        batch.drop_column("material_claim_a_id")
    op.drop_column("artifact_versions", "origin")
    op.drop_column("jobs", "targeted_block_keys")
    with op.batch_alter_table("material_claims") as batch:
        batch.drop_constraint("ck_material_claims_block_mapping_state", type_="check")
        batch.drop_column("block_mapping_state")
