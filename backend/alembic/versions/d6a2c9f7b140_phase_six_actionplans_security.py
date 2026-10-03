"""add Phase 6 ActionPlans, audit, telemetry, and rate limiting

Revision ID: d6a2c9f7b140
Revises: f5a127bb64d0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d6a2c9f7b140"
down_revision: str | None = "f5a127bb64d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("source_versions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sensitivity_class",
                sa.String(length=16),
                nullable=False,
                server_default="internal",
            )
        )
        batch_op.create_check_constraint(
            "ck_source_versions_sensitivity_class",
            "sensitivity_class IN ('public', 'internal', 'restricted')",
        )

    op.create_table(
        "action_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("transformation_run_id", sa.Integer(), nullable=False),
        sa.Column("user_request", sa.String(length=2000), nullable=False),
        sa.Column("explanation", sa.String(length=1000), nullable=False),
        sa.Column("planner_profile", sa.String(length=80), nullable=False),
        sa.Column("planner_profile_version", sa.String(length=40), nullable=False),
        sa.Column("planner_model", sa.String(length=120), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed', 'awaiting_confirmation', 'executing', 'completed', "
            "'partially_completed', 'rejected', 'expired', 'failed')",
            name="ck_action_plans_status",
        ),
        sa.CheckConstraint("plan_version > 0", name="ck_action_plans_positive_version"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["transformation_run_id"], ["transformation_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_plans_owner_id", "action_plans", ["owner_id"])
    op.create_index(
        "ix_action_plans_transformation_run_id", "action_plans", ["transformation_run_id"]
    )
    op.create_index("ix_action_plans_owner_created", "action_plans", ["owner_id", "created_at"])

    op.create_table(
        "action_plan_steps",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("action_plan_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("command_type", sa.String(length=48), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("target_ids", sa.JSON(), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("consequential", sa.Boolean(), nullable=False),
        sa.Column("precondition_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result_reference", sa.String(length=160), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint("ordinal > 0", name="ck_action_plan_steps_positive_ordinal"),
        sa.CheckConstraint(
            "status IN ('waiting', 'running', 'completed', 'failed', 'skipped')",
            name="ck_action_plan_steps_status",
        ),
        sa.ForeignKeyConstraint(["action_plan_id"], ["action_plans.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_plan_id", "ordinal", name="uq_action_plan_steps_ordinal"),
    )
    op.create_index("ix_action_plan_steps_action_plan_id", "action_plan_steps", ["action_plan_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("transformation_run_id", sa.Integer(), nullable=False),
        sa.Column("action_plan_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.String(length=4000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
        sa.ForeignKeyConstraint(["action_plan_id"], ["action_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["transformation_run_id"], ["transformation_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_owner_id", "chat_messages", ["owner_id"])
    op.create_index(
        "ix_chat_messages_transformation_run_id", "chat_messages", ["transformation_run_id"]
    )
    op.create_index("ix_chat_messages_action_plan_id", "chat_messages", ["action_plan_id"])
    op.create_index(
        "ix_chat_messages_workspace_created",
        "chat_messages",
        ["owner_id", "transformation_run_id", "id"],
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("target_type", sa.String(length=48), nullable=False),
        sa.Column("target_id", sa.String(length=80), nullable=False),
        sa.Column("action_plan_id", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(length=80), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("safe_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["action_plan_id"], ["action_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_owner_id", "audit_events", ["owner_id"])
    op.create_index("ix_audit_events_action_plan_id", "audit_events", ["action_plan_id"])
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])
    op.create_index("ix_audit_events_owner_created", "audit_events", ["owner_id", "created_at"])

    op.create_table(
        "model_usage_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("artifact_version_id", sa.Integer(), nullable=True),
        sa.Column("action_plan_id", sa.Integer(), nullable=True),
        sa.Column("task_profile", sa.String(length=48), nullable=False),
        sa.Column("provider", sa.String(length=48), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("profile_version", sa.String(length=40), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("result_state", sa.String(length=16), nullable=False),
        sa.Column("cache_state", sa.String(length=24), nullable=False),
        sa.Column("error_class", sa.String(length=80), nullable=True),
        sa.CheckConstraint(
            "result_state IN ('succeeded', 'failed', 'incomplete')",
            name="ck_model_usage_records_result_state",
        ),
        sa.ForeignKeyConstraint(["action_plan_id"], ["action_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["artifact_version_id"], ["artifact_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_model_usage_records_owner_id", "model_usage_records", ["owner_id"])
    op.create_index("ix_model_usage_records_job_id", "model_usage_records", ["job_id"])
    op.create_index(
        "ix_model_usage_records_artifact_version_id", "model_usage_records", ["artifact_version_id"]
    )
    op.create_index(
        "ix_model_usage_records_action_plan_id", "model_usage_records", ["action_plan_id"]
    )
    op.create_index(
        "ix_model_usage_task_started", "model_usage_records", ["task_profile", "started_at"]
    )

    op.create_table(
        "rate_limit_buckets",
        sa.Column("scope", sa.String(length=48), nullable=False),
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("request_count > 0", name="ck_rate_limit_buckets_positive_count"),
        sa.PrimaryKeyConstraint("scope", "key_digest", "window_start"),
    )


def downgrade() -> None:
    op.drop_table("rate_limit_buckets")
    op.drop_index("ix_model_usage_task_started", table_name="model_usage_records")
    op.drop_index("ix_model_usage_records_action_plan_id", table_name="model_usage_records")
    op.drop_index("ix_model_usage_records_artifact_version_id", table_name="model_usage_records")
    op.drop_index("ix_model_usage_records_job_id", table_name="model_usage_records")
    op.drop_index("ix_model_usage_records_owner_id", table_name="model_usage_records")
    op.drop_table("model_usage_records")
    op.drop_index("ix_audit_events_owner_created", table_name="audit_events")
    op.drop_index("ix_audit_events_request_id", table_name="audit_events")
    op.drop_index("ix_audit_events_action_plan_id", table_name="audit_events")
    op.drop_index("ix_audit_events_owner_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_chat_messages_workspace_created", table_name="chat_messages")
    op.drop_index("ix_chat_messages_action_plan_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_transformation_run_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_owner_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_action_plan_steps_action_plan_id", table_name="action_plan_steps")
    op.drop_table("action_plan_steps")
    op.drop_index("ix_action_plans_owner_created", table_name="action_plans")
    op.drop_index("ix_action_plans_transformation_run_id", table_name="action_plans")
    op.drop_index("ix_action_plans_owner_id", table_name="action_plans")
    op.drop_table("action_plans")
    with op.batch_alter_table("source_versions") as batch_op:
        batch_op.drop_constraint("ck_source_versions_sensitivity_class", type_="check")
        batch_op.drop_column("sensitivity_class")
