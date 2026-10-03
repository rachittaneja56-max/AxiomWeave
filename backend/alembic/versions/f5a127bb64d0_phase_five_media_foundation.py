"""add private deterministic media workflow records

Revision ID: f5a127bb64d0
Revises: c4a91b0d7e22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5a127bb64d0"
down_revision: str | None = "c4a91b0d7e22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_renders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("artifact_version_id", sa.Integer(), nullable=False),
        sa.Column("artifact_family", sa.String(32), nullable=False),
        sa.Column("renderer_profile", sa.String(80), nullable=False),
        sa.Column("renderer_version", sa.String(40), nullable=False),
        sa.Column("render_plan", sa.JSON(), nullable=False),
        sa.Column("render_plan_hash", sa.String(64), nullable=False),
        sa.Column("dependency_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("primary_asset_id", sa.Integer()),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "artifact_family IN ('infographic', 'video_package')",
            name="ck_media_renders_artifact_family",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'rendering', 'partial_failure', 'ready_for_review', "
            "'approved', 'rejected', 'failed')",
            name="ck_media_renders_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"], ["artifact_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "artifact_version_id", name="uq_media_renders_id_version"),
    )
    op.create_index("ix_media_renders_owner_id", "media_renders", ["owner_id"])
    op.create_index(
        "ix_media_renders_artifact_version_id", "media_renders", ["artifact_version_id"]
    )
    op.create_index("ix_media_renders_dependency_key", "media_renders", ["dependency_key"])

    op.create_table(
        "media_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("render_id", sa.Integer(), nullable=False),
        sa.Column("task_key", sa.String(80), nullable=False),
        sa.Column("task_kind", sa.String(32), nullable=False),
        sa.Column("dependency_key", sa.String(64), nullable=False),
        sa.Column("ordinal", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failure_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "task_kind IN ('infographic_render', 'video_scene_render', 'video_compose')",
            name="ck_media_tasks_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_media_tasks_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["render_id"], ["media_renders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("render_id", "task_key", name="uq_media_tasks_render_key"),
    )
    op.create_index("ix_media_tasks_owner_id", "media_tasks", ["owner_id"])
    op.create_index("ix_media_tasks_render_id", "media_tasks", ["render_id"])
    op.create_index("ix_media_tasks_dependency_key", "media_tasks", ["dependency_key"])

    op.create_table(
        "media_assets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("render_id", sa.Integer()),
        sa.Column("task_id", sa.Integer()),
        sa.Column("source_asset_id", sa.Integer()),
        sa.Column("parent_media_asset_id", sa.Integer()),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("media_type", sa.String(127), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(80), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("renderer_profile", sa.String(80)),
        sa.Column("renderer_version", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("byte_size >= 0", name="ck_media_assets_nonnegative_bytes"),
        sa.CheckConstraint("width IS NULL OR width > 0", name="ck_media_assets_positive_width"),
        sa.CheckConstraint("height IS NULL OR height > 0", name="ck_media_assets_positive_height"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0", name="ck_media_assets_nonnegative_duration"
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["render_id"], ["media_renders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["media_tasks.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["parent_media_asset_id"], ["media_assets.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_media_assets_storage_key"),
    )
    op.create_index("ix_media_assets_owner_id", "media_assets", ["owner_id"])
    op.create_index("ix_media_assets_render_id", "media_assets", ["render_id"])
    op.create_index("ix_media_assets_task_id", "media_assets", ["task_id"])
    op.create_index("ix_media_assets_source_asset_id", "media_assets", ["source_asset_id"])
    op.create_index(
        "ix_media_assets_parent_media_asset_id", "media_assets", ["parent_media_asset_id"]
    )
    op.create_index("ix_media_assets_content_hash", "media_assets", ["content_hash"])

    op.create_table(
        "media_rights_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("source_asset_id", sa.Integer()),
        sa.Column("media_asset_id", sa.Integer()),
        sa.Column("rights_basis", sa.String(32), nullable=False),
        sa.Column("consent_state", sa.String(24), nullable=False),
        sa.Column("consent_required", sa.Boolean(), nullable=False),
        sa.Column("attribution", sa.String(500)),
        sa.Column("confirmed_by_user_id", sa.Integer()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(source_asset_id IS NOT NULL AND media_asset_id IS NULL) OR "
            "(source_asset_id IS NULL AND media_asset_id IS NOT NULL)",
            name="ck_media_rights_exactly_one_asset",
        ),
        sa.CheckConstraint(
            "rights_basis IN ('user_owned', 'permission_confirmed', 'public_domain', "
            "'system_generated', 'derived', 'not_applicable', 'unknown')",
            name="ck_media_rights_basis",
        ),
        sa.CheckConstraint(
            "consent_state IN ('confirmed', 'not_applicable', 'unknown')",
            name="ck_media_rights_consent",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_asset_id"], ["source_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["confirmed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_asset_id", name="uq_media_rights_source_asset"),
        sa.UniqueConstraint("media_asset_id", name="uq_media_rights_media_asset"),
    )
    op.create_index("ix_media_rights_records_owner_id", "media_rights_records", ["owner_id"])

    op.create_table(
        "media_review_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("media_render_id", sa.Integer(), nullable=False),
        sa.Column("primary_asset_hash", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_media_review_decision"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["media_render_id"], ["media_renders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_review_decisions_owner_id", "media_review_decisions", ["owner_id"])
    op.create_index(
        "ix_media_review_decisions_media_render_id",
        "media_review_decisions",
        ["media_render_id"],
    )

    op.create_table(
        "media_operation_metrics",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("render_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer()),
        sa.Column("operation_type", sa.String(40), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("input_bytes", sa.Integer(), nullable=False),
        sa.Column("output_bytes", sa.Integer(), nullable=False),
        sa.Column("output_duration_ms", sa.Integer()),
        sa.Column("tool_version", sa.String(120), nullable=False),
        sa.Column("external_api_cost", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["render_id"], ["media_renders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["task_id"], ["media_tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_operation_metrics_owner_id", "media_operation_metrics", ["owner_id"])
    op.create_index(
        "ix_media_operation_metrics_render_id", "media_operation_metrics", ["render_id"]
    )
    op.create_index("ix_media_operation_metrics_task_id", "media_operation_metrics", ["task_id"])

    with op.batch_alter_table("source_assets") as batch_op:
        batch_op.drop_constraint("ck_source_assets_source_kind", type_="check")
        batch_op.drop_constraint("ck_source_assets_extraction_coverage", type_="check")
        batch_op.create_check_constraint(
            "ck_source_assets_source_kind",
            "source_kind IN ('text', 'file', 'url', 'image', 'audio', 'video')",
        )
        batch_op.create_check_constraint(
            "ck_source_assets_extraction_coverage",
            "extraction_coverage IN ('complete', 'partial', 'unavailable')",
        )

    with op.batch_alter_table("source_regions") as batch_op:
        batch_op.add_column(sa.Column("locator_kind", sa.String(32), nullable=True))
        batch_op.add_column(sa.Column("locator_metadata", sa.JSON(), nullable=True))
    op.add_column("source_assets", sa.Column("extraction_details", sa.JSON(), nullable=True))

    op.drop_index("uq_jobs_active_artifact_run", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.alter_column("artifact_run_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("media_task_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_jobs_media_task_id_media_tasks",
            "media_tasks",
            ["media_task_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.drop_constraint("ck_jobs_type", type_="check")
        batch_op.drop_constraint("ck_jobs_resource_class", type_="check")
        batch_op.create_check_constraint(
            "ck_jobs_type", "job_type IN ('artifact_generation', 'media_task')"
        )
        batch_op.create_check_constraint(
            "ck_jobs_resource_class", "resource_class IN ('model_io', 'media_cpu')"
        )
        batch_op.create_check_constraint(
            "ck_jobs_target_matches_type",
            "(job_type = 'artifact_generation' AND artifact_run_id IS NOT NULL "
            "AND media_task_id IS NULL AND resource_class = 'model_io') OR "
            "(job_type = 'media_task' AND artifact_run_id IS NULL "
            "AND media_task_id IS NOT NULL AND resource_class = 'media_cpu')",
        )

    op.create_index("ix_jobs_media_task_id", "jobs", ["media_task_id"])
    op.create_index(
        "uq_jobs_active_artifact_run",
        "jobs",
        ["artifact_run_id"],
        unique=True,
        sqlite_where=sa.text(
            "job_type = 'artifact_generation' AND status IN ('queued', 'running')"
        ),
        postgresql_where=sa.text(
            "job_type = 'artifact_generation' AND status IN ('queued', 'running')"
        ),
    )
    op.create_index(
        "uq_jobs_active_media_task",
        "jobs",
        ["media_task_id"],
        unique=True,
        sqlite_where=sa.text("job_type = 'media_task' AND status IN ('queued', 'running')"),
        postgresql_where=sa.text("job_type = 'media_task' AND status IN ('queued', 'running')"),
    )

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER media_render_plan_immutable BEFORE UPDATE ON media_renders "
            "WHEN OLD.owner_id != NEW.owner_id "
            "OR OLD.artifact_version_id != NEW.artifact_version_id "
            "OR OLD.artifact_family != NEW.artifact_family "
            "OR OLD.renderer_profile != NEW.renderer_profile "
            "OR OLD.renderer_version != NEW.renderer_version "
            "OR OLD.render_plan != NEW.render_plan "
            "OR OLD.render_plan_hash != NEW.render_plan_hash "
            "OR OLD.dependency_key != NEW.dependency_key "
            "BEGIN SELECT RAISE(ABORT, 'media render plan is immutable'); END"
        )
    elif bind.dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION guard_media_render_plan() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF OLD.owner_id IS DISTINCT FROM NEW.owner_id OR "
            "OLD.artifact_version_id IS DISTINCT FROM NEW.artifact_version_id OR "
            "OLD.artifact_family IS DISTINCT FROM NEW.artifact_family OR "
            "OLD.renderer_profile IS DISTINCT FROM NEW.renderer_profile OR "
            "OLD.renderer_version IS DISTINCT FROM NEW.renderer_version OR "
            "OLD.render_plan::text IS DISTINCT FROM NEW.render_plan::text OR "
            "OLD.render_plan_hash IS DISTINCT FROM NEW.render_plan_hash OR "
            "OLD.dependency_key IS DISTINCT FROM NEW.dependency_key THEN "
            "RAISE EXCEPTION 'media render plan is immutable'; END IF; RETURN NEW; END $$"
        )
        op.execute(
            "CREATE TRIGGER media_render_plan_immutable BEFORE UPDATE ON media_renders "
            "FOR EACH ROW EXECUTE FUNCTION guard_media_render_plan()"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS media_render_plan_immutable")
    elif bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS media_render_plan_immutable ON media_renders")
        op.execute("DROP FUNCTION IF EXISTS guard_media_render_plan()")

    op.drop_index("uq_jobs_active_media_task", table_name="jobs")
    op.drop_index("uq_jobs_active_artifact_run", table_name="jobs")
    op.drop_index("ix_jobs_media_task_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch_op:
        batch_op.drop_constraint("ck_jobs_target_matches_type", type_="check")
        batch_op.drop_constraint("ck_jobs_type", type_="check")
        batch_op.drop_constraint("ck_jobs_resource_class", type_="check")
        batch_op.drop_constraint("fk_jobs_media_task_id_media_tasks", type_="foreignkey")
        batch_op.drop_column("media_task_id")
        batch_op.alter_column("artifact_run_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_check_constraint("ck_jobs_type", "job_type IN ('artifact_generation')")
        batch_op.create_check_constraint("ck_jobs_resource_class", "resource_class IN ('model_io')")
    op.create_index(
        "uq_jobs_active_artifact_run",
        "jobs",
        ["artifact_run_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    with op.batch_alter_table("source_regions") as batch_op:
        batch_op.drop_column("locator_metadata")
        batch_op.drop_column("locator_kind")
    op.drop_column("source_assets", "extraction_details")
    with op.batch_alter_table("source_assets") as batch_op:
        batch_op.drop_constraint("ck_source_assets_source_kind", type_="check")
        batch_op.drop_constraint("ck_source_assets_extraction_coverage", type_="check")
        batch_op.create_check_constraint(
            "ck_source_assets_source_kind", "source_kind IN ('text', 'file', 'url')"
        )
        batch_op.create_check_constraint(
            "ck_source_assets_extraction_coverage", "extraction_coverage IN ('complete', 'partial')"
        )

    for index, table in (
        ("ix_media_operation_metrics_task_id", "media_operation_metrics"),
        ("ix_media_operation_metrics_render_id", "media_operation_metrics"),
        ("ix_media_operation_metrics_owner_id", "media_operation_metrics"),
        ("ix_media_review_decisions_media_render_id", "media_review_decisions"),
        ("ix_media_review_decisions_owner_id", "media_review_decisions"),
        ("ix_media_rights_records_owner_id", "media_rights_records"),
        ("ix_media_assets_content_hash", "media_assets"),
        ("ix_media_assets_parent_media_asset_id", "media_assets"),
        ("ix_media_assets_source_asset_id", "media_assets"),
        ("ix_media_assets_task_id", "media_assets"),
        ("ix_media_assets_render_id", "media_assets"),
        ("ix_media_assets_owner_id", "media_assets"),
        ("ix_media_tasks_dependency_key", "media_tasks"),
        ("ix_media_tasks_render_id", "media_tasks"),
        ("ix_media_tasks_owner_id", "media_tasks"),
        ("ix_media_renders_dependency_key", "media_renders"),
        ("ix_media_renders_artifact_version_id", "media_renders"),
        ("ix_media_renders_owner_id", "media_renders"),
    ):
        op.drop_index(index, table_name=table)
    op.drop_table("media_operation_metrics")
    op.drop_table("media_review_decisions")
    op.drop_table("media_rights_records")
    op.drop_table("media_assets")
    op.drop_table("media_tasks")
    op.drop_table("media_renders")
