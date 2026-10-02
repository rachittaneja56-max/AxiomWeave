"""add durable artifact generation jobs

Revision ID: d9a32ce14f60
Revises: a17c0f5e2d91
Create Date: 2026-10-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9a32ce14f60"
down_revision: str | None = "a17c0f5e2d91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("artifact_run_id", sa.Integer(), nullable=False),
        sa.Column("source_version_id", sa.Integer(), nullable=False),
        sa.Column("base_artifact_version_id", sa.Integer(), nullable=True),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("resource_class", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint("job_type IN ('artifact_generation')", name="ck_jobs_type"),
        sa.CheckConstraint("resource_class IN ('model_io')", name="ck_jobs_resource_class"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_jobs_status"
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR status = 'failed'", name="ck_jobs_failure_code_status"
        ),
        sa.CheckConstraint(
            "(status = 'running' AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status != 'running' AND worker_id IS NULL AND lease_expires_at IS NULL)",
            name="ck_jobs_lease_state",
        ),
        sa.CheckConstraint(
            "(status IN ('succeeded', 'failed') AND terminal_at IS NOT NULL) "
            "OR (status IN ('queued', 'running') AND terminal_at IS NULL)",
            name="ck_jobs_terminal_state",
        ),
        sa.ForeignKeyConstraint(["artifact_run_id"], ["artifact_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_version_id"], ["source_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["base_artifact_version_id"], ["artifact_versions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_artifact_run_id"), "jobs", ["artifact_run_id"], unique=False)
    op.create_index(op.f("ix_jobs_source_version_id"), "jobs", ["source_version_id"], unique=False)
    op.create_index("ix_jobs_claim", "jobs", ["resource_class", "status", "created_at", "id"])
    op.create_index(
        "uq_jobs_active_artifact_run",
        "jobs",
        ["artifact_run_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )

    op.create_table(
        "job_dependencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("depends_on_job_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("job_id != depends_on_job_id", name="ck_job_dependencies_not_self"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["depends_on_job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "depends_on_job_id", name="uq_job_dependencies_edge"),
    )
    op.create_index(
        op.f("ix_job_dependencies_job_id"), "job_dependencies", ["job_id"], unique=False
    )
    op.create_index("ix_job_dependencies_dependency", "job_dependencies", ["depends_on_job_id"])

    op.create_table(
        "job_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.CheckConstraint("attempt_number > 0", name="ck_job_attempts_positive_number"),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_job_attempts_status"
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR status = 'failed'",
            name="ck_job_attempts_failure_code_status",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) "
            "OR (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL)",
            name="ck_job_attempts_finished_state",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_job_number"),
    )
    op.create_index(op.f("ix_job_attempts_job_id"), "job_attempts", ["job_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_job_attempts_job_id"), table_name="job_attempts")
    op.drop_table("job_attempts")
    op.drop_index("ix_job_dependencies_dependency", table_name="job_dependencies")
    op.drop_index(op.f("ix_job_dependencies_job_id"), table_name="job_dependencies")
    op.drop_table("job_dependencies")
    op.drop_index("uq_jobs_active_artifact_run", table_name="jobs")
    op.drop_index("ix_jobs_claim", table_name="jobs")
    op.drop_index(op.f("ix_jobs_source_version_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_artifact_run_id"), table_name="jobs")
    op.drop_table("jobs")
