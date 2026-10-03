from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import UserDefinedType


class Vector(UserDefinedType[list[float]]):
    """PostgreSQL pgvector value with a SQLite TEXT representation for local tests."""

    cache_ok = True

    def get_col_spec(self, **_kw: object) -> str:
        return "vector"

    def bind_processor(self, dialect: Dialect):
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(format(float(item), ".9g") for item in value) + "]"

        return process

    def result_processor(self, dialect: Dialect, coltype: object):
        def process(value: str | None) -> list[float] | None:
            if value is None:
                return None
            return [float(item) for item in value.strip("[]").split(",") if item]

        return process


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type: Vector, _compiler: object, **_kw: object) -> str:
    return "TEXT"


def utc_now() -> datetime:
    return datetime.now(UTC)


def source_content_hash(source_text: str) -> str:
    return sha256(source_text.encode("utf-8")).hexdigest()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ActionPlan(Base):
    __tablename__ = "action_plans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'awaiting_confirmation', 'executing', 'completed', "
            "'partially_completed', 'rejected', 'expired', 'failed')",
            name="ck_action_plans_status",
        ),
        CheckConstraint("plan_version > 0", name="ck_action_plans_positive_version"),
        Index("ix_action_plans_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    transformation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("transformation_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    user_request: Mapped[str] = mapped_column(String(2_000), nullable=False)
    explanation: Mapped[str] = mapped_column(String(1_000), nullable=False)
    planner_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    planner_profile_version: Mapped[str] = mapped_column(String(40), nullable=False)
    planner_model: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    execution_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ActionPlanStep(Base):
    __tablename__ = "action_plan_steps"
    __table_args__ = (
        UniqueConstraint("action_plan_id", "ordinal", name="uq_action_plan_steps_ordinal"),
        CheckConstraint("ordinal > 0", name="ck_action_plan_steps_positive_ordinal"),
        CheckConstraint(
            "status IN ('waiting', 'running', 'completed', 'failed', 'skipped')",
            name="ck_action_plan_steps_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    action_plan_id: Mapped[int] = mapped_column(
        ForeignKey("action_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    command_type: Mapped[str] = mapped_column(String(48), nullable=False)
    arguments: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    target_ids: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False, default=dict)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    consequential: Mapped[bool] = mapped_column(Boolean, nullable=False)
    precondition_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="waiting")
    result_reference: Mapped[str | None] = mapped_column(String(160))
    error_code: Mapped[str | None] = mapped_column(String(64))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_messages_role"),
        Index("ix_chat_messages_workspace_created", "owner_id", "transformation_run_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    transformation_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("transformation_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    action_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_plans.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(String(4_000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_events_owner_created", "owner_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(48), nullable=False)
    target_id: Mapped[str] = mapped_column(String(80), nullable=False)
    action_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_plans.id", ondelete="RESTRICT"), index=True
    )
    request_id: Mapped[str | None] = mapped_column(String(80), index=True)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    safe_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelUsageRecord(Base):
    __tablename__ = "model_usage_records"
    __table_args__ = (
        CheckConstraint(
            "result_state IN ('succeeded', 'failed', 'incomplete')",
            name="ck_model_usage_records_result_state",
        ),
        Index("ix_model_usage_task_started", "task_profile", "started_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="RESTRICT"))
    artifact_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT")
    )
    action_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("action_plans.id", ondelete="RESTRICT")
    )
    task_profile: Mapped[str] = mapped_column(String(48), nullable=False)
    provider: Mapped[str] = mapped_column(String(48), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    result_state: Mapped[str] = mapped_column(String(16), nullable=False)
    cache_state: Mapped[str] = mapped_column(String(24), nullable=False, default="disabled")
    error_class: Mapped[str | None] = mapped_column(String(80))


class RateLimitBucket(Base):
    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        CheckConstraint("request_count > 0", name="ck_rate_limit_buckets_positive_count"),
    )

    scope: Mapped[str] = mapped_column(String(48), primary_key=True)
    key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LoginThrottle(Base):
    __tablename__ = "login_throttles"

    login_key_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    session_token_digest: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceVersion(Base):
    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint("source_id", "version_number", name="uq_source_versions_source_number"),
        CheckConstraint("version_number > 0", name="ck_source_versions_positive_number"),
        CheckConstraint(
            "sensitivity_class IN ('public', 'internal', 'restricted')",
            name="ck_source_versions_sensitivity_class",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    parent_source_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sensitivity_class: Mapped[str] = mapped_column(String(16), nullable=False, default="internal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourcePack(Base):
    __tablename__ = "source_packs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourcePackVersion(Base):
    __tablename__ = "source_pack_versions"
    __table_args__ = (
        UniqueConstraint("source_pack_id", "version_number", name="uq_source_pack_versions_number"),
        UniqueConstraint("source_version_id", name="uq_source_pack_versions_source_version"),
        CheckConstraint("version_number > 0", name="ck_source_pack_versions_positive_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_pack_id: Mapped[int] = mapped_column(
        ForeignKey("source_packs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False
    )
    parent_source_pack_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_pack_versions.id", ondelete="RESTRICT"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourcePackMembership(Base):
    """One exact source version and asset assigned a role in a pack snapshot."""

    __tablename__ = "source_pack_memberships"
    __table_args__ = (
        UniqueConstraint(
            "source_pack_version_id", "source_version_id", name="uq_pack_member_source_version"
        ),
        UniqueConstraint(
            "source_pack_version_id", "source_asset_id", name="uq_pack_member_source_asset"
        ),
        UniqueConstraint(
            "source_pack_version_id", "ordinal", name="uq_pack_member_version_ordinal"
        ),
        CheckConstraint(
            "role IN ('PRIMARY', 'SUPPORTING', 'STYLE', 'REFERENCE', 'OPERATOR_CONTEXT')",
            name="ck_source_pack_membership_role",
        ),
        CheckConstraint("ordinal > 0", name="ck_source_pack_membership_positive_ordinal"),
        Index(
            "uq_source_pack_membership_primary",
            "source_pack_version_id",
            unique=True,
            sqlite_where=text("role = 'PRIMARY'"),
            postgresql_where=text("role = 'PRIMARY'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_pack_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_pack_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey("source_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceSegment(Base):
    __tablename__ = "source_segments"
    __table_args__ = (
        UniqueConstraint("source_version_id", "ordinal", name="uq_source_segments_version_ordinal"),
        UniqueConstraint("source_version_id", "locator", name="uq_source_segments_version_locator"),
        CheckConstraint("ordinal > 0", name="ck_source_segments_positive_ordinal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[str] = mapped_column(String(255), nullable=False)
    segment_text: Mapped[str] = mapped_column(Text, nullable=False)


class SourceAsset(Base):
    __tablename__ = "source_assets"
    __table_args__ = (
        CheckConstraint(
            "authority_role IN ('authoritative', 'supporting')",
            name="ck_source_assets_authority_role",
        ),
        CheckConstraint(
            "source_kind IN ('text', 'file', 'url', 'image', 'audio', 'video')",
            name="ck_source_assets_source_kind",
        ),
        CheckConstraint("byte_size >= 0", name="ck_source_assets_nonnegative_byte_size"),
        CheckConstraint(
            "extraction_coverage IN ('complete', 'partial', 'unavailable')",
            name="ck_source_assets_extraction_coverage",
        ),
        CheckConstraint(
            "extraction_profile_version > 0",
            name="ck_source_assets_extraction_profile_version",
        ),
        UniqueConstraint("storage_key", name="uq_source_assets_storage_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_pack_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_pack_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Retained for existing rows and migration compatibility. Snapshot authority is stored on
    # SourcePackMembership; this legacy value must not be used to determine factual authority.
    legacy_authority_role: Mapped[str] = mapped_column("authority_role", String(24), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    media_type: Mapped[str] = mapped_column(String(127), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str | None] = mapped_column(String(80))
    provenance_url: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    # Profile/version identifies the supported extraction contract; method records the
    # specific extractor used (for example, pdf_native_plus_ocr).
    extraction_profile: Mapped[str] = mapped_column(String(40), nullable=False)
    extraction_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Coverage is completeness for this extraction profile, not semantic correctness.
    extraction_coverage: Mapped[str] = mapped_column(String(16), nullable=False)
    extraction_details: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceRegion(Base):
    __tablename__ = "source_regions"
    __table_args__ = (
        UniqueConstraint("source_asset_id", "ordinal", name="uq_source_regions_asset_ordinal"),
        UniqueConstraint("source_asset_id", "locator", name="uq_source_regions_asset_locator"),
        UniqueConstraint("source_segment_id", name="uq_source_regions_source_segment"),
        CheckConstraint("ordinal > 0", name="ck_source_regions_positive_ordinal"),
        CheckConstraint(
            "page_number IS NULL OR page_number > 0", name="ck_source_regions_positive_page"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey("source_assets.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Compatibility projection for current text workflows. Canonical addressing is by asset
    # and locator, so future non-text regions do not need a fabricated legacy segment.
    source_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_segments.id", ondelete="RESTRICT"), nullable=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[str] = mapped_column(String(255), nullable=False)
    region_type: Mapped[str] = mapped_column(String(32), nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    locator_kind: Mapped[str | None] = mapped_column(String(32))
    locator_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)


class TransformationRun(Base):
    __tablename__ = "transformation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supporting_context: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audience: Mapped[str] = mapped_column(String(120), nullable=False)
    tone: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(80), nullable=False)
    detail_level: Mapped[str] = mapped_column(String(20), nullable=False)
    objective: Mapped[str] = mapped_column(String(160), nullable=False)
    style: Mapped[str] = mapped_column(String(120), nullable=False)
    selected_output_types: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ArtifactRun(Base):
    __tablename__ = "artifact_runs"
    __table_args__ = (
        UniqueConstraint(
            "transformation_run_id", "output_type", name="uq_artifact_runs_transformation_output"
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_artifact_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transformation_run_id: Mapped[int] = mapped_column(
        ForeignKey("transformation_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    output_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (
        UniqueConstraint(
            "artifact_run_id", "version_number", name="uq_artifact_versions_run_number"
        ),
        CheckConstraint("version_number > 0", name="ck_artifact_versions_positive_number"),
        CheckConstraint(
            "review_status IN ('draft', 'accepted', 'rejected')",
            name="ck_artifact_versions_review_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_run_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    context_manifest_id: Mapped[int | None] = mapped_column(
        ForeignKey("context_manifests.id", ondelete="RESTRICT"), index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(120))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    artifact_schema_version: Mapped[str | None] = mapped_column(String(40))
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    origin: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ArtifactBlock(Base):
    """A deterministic, server-owned addressable unit of visible artifact text."""

    __tablename__ = "artifact_blocks"
    __table_args__ = (
        UniqueConstraint("artifact_version_id", "block_key", name="uq_artifact_blocks_version_key"),
        UniqueConstraint(
            "artifact_version_id", "ordinal", name="uq_artifact_blocks_version_ordinal"
        ),
        CheckConstraint("ordinal > 0", name="ck_artifact_blocks_positive_ordinal"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_version_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    block_key: Mapped[str] = mapped_column(String(255), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(40), nullable=False)
    visible_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    structural_metadata: Mapped[dict[str, object] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MaterialClaimBlock(Base):
    __tablename__ = "material_claim_blocks"
    __table_args__ = (
        UniqueConstraint("material_claim_id", "artifact_block_id", name="uq_claim_block_link"),
        CheckConstraint("mapping_state IN ('validated', 'ambiguous')", name="ck_claim_block_state"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    material_claim_id: Mapped[int] = mapped_column(
        ForeignKey("material_claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_block_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_blocks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    mapping_state: Mapped[str] = mapped_column(String(16), nullable=False, default="validated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LineageProposal(Base):
    """Raw generation proposal plus a separate server-owned validation result."""

    __tablename__ = "lineage_proposals"
    __table_args__ = (
        CheckConstraint(
            "validation_state IN ('validated', 'invalid_scope', 'invalid_region', "
            "'invalid_assertion', 'invalid_span', 'ambiguous', 'unresolved')",
            name="ck_lineage_proposals_validation_state",
        ),
        CheckConstraint(
            "(proposed_quote_start IS NULL AND proposed_quote_end IS NULL) OR "
            "(proposed_quote_start >= 0 AND proposed_quote_end >= proposed_quote_start)",
            name="ck_lineage_proposals_quote_offsets",
        ),
        CheckConstraint(
            "(validated_quote_start IS NULL AND validated_quote_end IS NULL) OR "
            "(validated_quote_start >= 0 AND validated_quote_end > validated_quote_start)",
            name="ck_lineage_proposals_validated_quote_offsets",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_version_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_block_id: Mapped[int | None] = mapped_column(
        ForeignKey("artifact_blocks.id", ondelete="RESTRICT"), index=True
    )
    material_claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("material_claims.id", ondelete="RESTRICT"), index=True
    )
    proposed_block_key: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_claim: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_source_region_id: Mapped[int | None] = mapped_column(Integer)
    proposed_assertion_id: Mapped[int | None] = mapped_column(Integer)
    proposed_quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_quote_start: Mapped[int | None] = mapped_column(Integer)
    proposed_quote_end: Mapped[int | None] = mapped_column(Integer)
    validated_quote_start: Mapped[int | None] = mapped_column(Integer)
    validated_quote_end: Mapped[int | None] = mapped_column(Integer)
    validation_state: Mapped[str] = mapped_column(String(24), nullable=False, default="unresolved")
    rejection_reason: Mapped[str | None] = mapped_column(String(80))
    proposal_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    proposal_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClaimEvidenceAssessment(Base):
    __tablename__ = "claim_evidence_assessments"
    __table_args__ = (
        CheckConstraint(
            "evidence_state IN ('quote_located', 'supported', 'partial', 'contradicted', "
            "'missing', 'ambiguous', 'conflict', 'non_factual')",
            name="ck_claim_evidence_state",
        ),
        CheckConstraint(
            "assessment_method IN ('mechanical', 'semantic_verifier', 'human')",
            name="ck_claim_evidence_method",
        ),
        CheckConstraint(
            "review_state IN ('needs_review', 'reviewed')", name="ck_claim_evidence_review"
        ),
        CheckConstraint(
            "adjudicated_state IS NULL OR adjudicated_state IN ('quote_located', 'supported', "
            "'partial', 'contradicted', 'missing', 'ambiguous', 'conflict', 'non_factual')",
            name="ck_claim_evidence_adjudicated_state",
        ),
        CheckConstraint(
            "(quote_start IS NULL AND quote_end IS NULL) OR "
            "(quote_start >= 0 AND quote_end >= quote_start)",
            name="ck_claim_evidence_quote_offsets",
        ),
        Index("ix_claim_evidence_owner_version", "owner_id", "artifact_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_version_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    material_claim_id: Mapped[int] = mapped_column(
        ForeignKey("material_claims.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    context_manifest_id: Mapped[int | None] = mapped_column(
        ForeignKey("context_manifests.id", ondelete="RESTRICT"), index=True
    )
    knowledge_assertion_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"), index=True
    )
    source_region_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_regions.id", ondelete="RESTRICT"), index=True
    )
    evidence_state: Mapped[str] = mapped_column(String(24), nullable=False)
    source_quote: Mapped[str | None] = mapped_column(Text)
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    assessment_method: Mapped[str] = mapped_column(String(24), nullable=False)
    verifier_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    verifier_profile_version: Mapped[str] = mapped_column(String(40), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80))
    review_state: Mapped[str] = mapped_column(String(16), nullable=False, default="needs_review")
    adjudicated_state: Mapped[str | None] = mapped_column(String(24))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ArtifactBlockDependency(Base):
    __tablename__ = "artifact_block_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "artifact_block_id", "source_region_id", "dependency_hash", name="uq_block_dependency"
        ),
        CheckConstraint(
            "dependency_kind IN ('quote', 'assertion', 'lineage')", name="ck_block_dependency_kind"
        ),
        CheckConstraint(
            "origin IN ('proposal', 'evidence', 'carried_forward')",
            name="ck_block_dependency_origin",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_block_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_blocks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_region_id: Mapped[int] = mapped_column(
        ForeignKey("source_regions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    knowledge_assertion_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"), index=True
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dependency_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dependency_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    origin: Mapped[str] = mapped_column(String(24), nullable=False)
    profile_version: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceRegionAlignment(Base):
    __tablename__ = "source_region_alignments"
    __table_args__ = (
        CheckConstraint(
            "alignment_state IN ('unchanged', 'moved', 'changed', 'split', 'merged', "
            "'ambiguous', 'removed', 'added')",
            name="ck_source_region_alignment_state",
        ),
        CheckConstraint(
            "(old_region_id IS NOT NULL OR alignment_state = 'added') AND "
            "(new_region_id IS NOT NULL OR alignment_state = 'removed')",
            name="ck_source_region_alignment_endpoints",
        ),
        Index(
            "ix_source_region_alignments_versions",
            "parent_pack_version_id",
            "child_pack_version_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_pack_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_pack_versions.id", ondelete="RESTRICT"), nullable=False
    )
    child_pack_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_pack_versions.id", ondelete="RESTRICT"), nullable=False
    )
    old_region_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_regions.id", ondelete="RESTRICT"), index=True
    )
    new_region_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_regions.id", ondelete="RESTRICT"), index=True
    )
    alignment_state: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ArtifactReviewDecision(Base):
    __tablename__ = "artifact_review_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('accepted', 'rejected')", name="ck_artifact_review_decision"),
        Index("ix_artifact_review_decisions_version", "artifact_version_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_version_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MediaRender(Base):
    __tablename__ = "media_renders"
    __table_args__ = (
        CheckConstraint(
            "artifact_family IN ('infographic', 'video_package')",
            name="ck_media_renders_artifact_family",
        ),
        CheckConstraint(
            "status IN ('pending', 'rendering', 'partial_failure', 'ready_for_review', "
            "'approved', 'rejected', 'failed')",
            name="ck_media_renders_status",
        ),
        UniqueConstraint("id", "artifact_version_id", name="uq_media_renders_id_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_version_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_family: Mapped[str] = mapped_column(String(32), nullable=False)
    renderer_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(40), nullable=False)
    render_plan: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    render_plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dependency_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    # The exact final asset is checked against MediaAsset.owner_id in the service boundary.
    primary_asset_id: Mapped[int | None] = mapped_column(Integer)
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaTask(Base):
    __tablename__ = "media_tasks"
    __table_args__ = (
        CheckConstraint(
            "task_kind IN ('infographic_render', 'video_scene_render', 'video_compose')",
            name="ck_media_tasks_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_media_tasks_status",
        ),
        UniqueConstraint("render_id", "task_key", name="uq_media_tasks_render_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    render_id: Mapped[int] = mapped_column(
        ForeignKey("media_renders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task_key: Mapped[str] = mapped_column(String(80), nullable=False)
    task_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    dependency_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ordinal: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    failure_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        CheckConstraint("byte_size >= 0", name="ck_media_assets_nonnegative_bytes"),
        CheckConstraint("width IS NULL OR width > 0", name="ck_media_assets_positive_width"),
        CheckConstraint("height IS NULL OR height > 0", name="ck_media_assets_positive_height"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_media_assets_nonnegative_duration",
        ),
        UniqueConstraint("storage_key", name="uq_media_assets_storage_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    render_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_renders.id", ondelete="RESTRICT"), index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_tasks.id", ondelete="RESTRICT"), index=True
    )
    source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id", ondelete="RESTRICT"), index=True
    )
    parent_media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT"), index=True
    )
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)
    media_type: Mapped[str] = mapped_column(String(127), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[str] = mapped_column(String(80), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    renderer_profile: Mapped[str | None] = mapped_column(String(80))
    renderer_version: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MediaRightsRecord(Base):
    __tablename__ = "media_rights_records"
    __table_args__ = (
        CheckConstraint(
            "(source_asset_id IS NOT NULL AND media_asset_id IS NULL) OR "
            "(source_asset_id IS NULL AND media_asset_id IS NOT NULL)",
            name="ck_media_rights_exactly_one_asset",
        ),
        CheckConstraint(
            "rights_basis IN ('user_owned', 'permission_confirmed', 'public_domain', "
            "'system_generated', 'derived', 'not_applicable', 'unknown')",
            name="ck_media_rights_basis",
        ),
        CheckConstraint(
            "consent_state IN ('confirmed', 'not_applicable', 'unknown')",
            name="ck_media_rights_consent",
        ),
        UniqueConstraint("source_asset_id", name="uq_media_rights_source_asset"),
        UniqueConstraint("media_asset_id", name="uq_media_rights_media_asset"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_assets.id", ondelete="RESTRICT")
    )
    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="RESTRICT")
    )
    rights_basis: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    consent_state: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    consent_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attribution: Mapped[str | None] = mapped_column(String(500))
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaReviewDecision(Base):
    __tablename__ = "media_review_decisions"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_media_review_decision"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    media_render_id: Mapped[int] = mapped_column(
        ForeignKey("media_renders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    primary_asset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MediaOperationMetric(Base):
    __tablename__ = "media_operation_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    render_id: Mapped[int] = mapped_column(
        ForeignKey("media_renders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_tasks.id", ondelete="RESTRICT"), index=True
    )
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    input_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_duration_ms: Mapped[int | None] = mapped_column(Integer)
    tool_version: Mapped[str] = mapped_column(String(120), nullable=False)
    external_api_cost: Mapped[float | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("job_type IN ('artifact_generation', 'media_task')", name="ck_jobs_type"),
        CheckConstraint(
            "resource_class IN ('model_io', 'media_cpu')", name="ck_jobs_resource_class"
        ),
        CheckConstraint(
            "(job_type = 'artifact_generation' AND artifact_run_id IS NOT NULL "
            "AND media_task_id IS NULL AND resource_class = 'model_io') OR "
            "(job_type = 'media_task' AND artifact_run_id IS NULL "
            "AND media_task_id IS NOT NULL AND resource_class = 'media_cpu')",
            name="ck_jobs_target_matches_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_jobs_status"
        ),
        CheckConstraint(
            "failure_code IS NULL OR status = 'failed'", name="ck_jobs_failure_code_status"
        ),
        CheckConstraint(
            "(status = 'running' AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status != 'running' AND worker_id IS NULL AND lease_expires_at IS NULL)",
            name="ck_jobs_lease_state",
        ),
        CheckConstraint(
            "(status IN ('succeeded', 'failed') AND terminal_at IS NOT NULL) "
            "OR (status IN ('queued', 'running') AND terminal_at IS NULL)",
            name="ck_jobs_terminal_state",
        ),
        Index("ix_jobs_claim", "resource_class", "status", "created_at", "id"),
        Index(
            "uq_jobs_active_artifact_run",
            "artifact_run_id",
            unique=True,
            sqlite_where=text(
                "job_type = 'artifact_generation' AND status IN ('queued', 'running')"
            ),
            postgresql_where=text(
                "job_type = 'artifact_generation' AND status IN ('queued', 'running')"
            ),
        ),
        Index(
            "uq_jobs_active_media_task",
            "media_task_id",
            unique=True,
            sqlite_where=text("job_type = 'media_task' AND status IN ('queued', 'running')"),
            postgresql_where=text("job_type = 'media_task' AND status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("artifact_runs.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    media_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_tasks.id", ondelete="RESTRICT"), index=True
    )
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    base_artifact_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT")
    )
    targeted_block_keys: Mapped[list[str] | None] = mapped_column(JSON)
    context_manifest_id: Mapped[int | None] = mapped_column(
        ForeignKey("context_manifests.id", ondelete="RESTRICT"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, default="artifact_generation")
    resource_class: Mapped[str] = mapped_column(String(40), nullable=False, default="model_io")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))


class JobDependency(Base):
    __tablename__ = "job_dependencies"
    __table_args__ = (
        UniqueConstraint("job_id", "depends_on_job_id", name="uq_job_dependencies_edge"),
        CheckConstraint("job_id != depends_on_job_id", name="ck_job_dependencies_not_self"),
        Index("ix_job_dependencies_dependency", "depends_on_job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    depends_on_job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )


class JobAttempt(Base):
    __tablename__ = "job_attempts"
    __table_args__ = (
        UniqueConstraint("job_id", "attempt_number", name="uq_job_attempts_job_number"),
        CheckConstraint("attempt_number > 0", name="ck_job_attempts_positive_number"),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')", name="ck_job_attempts_status"
        ),
        CheckConstraint(
            "failure_code IS NULL OR status = 'failed'",
            name="ck_job_attempts_failure_code_status",
        ),
        CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) "
            "OR (status IN ('succeeded', 'failed') AND finished_at IS NOT NULL)",
            name="ck_job_attempts_finished_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(64))


class EvidenceLink(Base):
    __tablename__ = "evidence_links"
    __table_args__ = (
        CheckConstraint(
            "status IN ('linked', 'support_not_located')",
            name="ck_evidence_links_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("claim_batches.id", ondelete="RESTRICT")
    )
    material_claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("material_claims.id", ondelete="RESTRICT"), unique=True
    )
    knowledge_assertion_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_assertions.id", ondelete="RESTRICT")
    )
    artifact_version_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_segments.id", ondelete="RESTRICT"), index=True
    )
    source_quote: Mapped[str | None] = mapped_column(Text)
    source_locator: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DiscrepancyFinding(Base):
    __tablename__ = "discrepancy_findings"
    __table_args__ = (
        UniqueConstraint(
            "artifact_version_a_id",
            "artifact_version_b_id",
            name="uq_discrepancy_findings_version_pair",
        ),
        CheckConstraint(
            "artifact_version_a_id != artifact_version_b_id",
            name="ck_discrepancy_findings_distinct_versions",
        ),
        CheckConstraint(
            "review_status IN ('open', 'dismissed')",
            name="ck_discrepancy_findings_review_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_version_a_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_version_b_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    material_claim_a_id: Mapped[int | None] = mapped_column(
        ForeignKey("material_claims.id", ondelete="RESTRICT"), index=True
    )
    material_claim_b_id: Mapped[int | None] = mapped_column(
        ForeignKey("material_claims.id", ondelete="RESTRICT"), index=True
    )
    statement_a: Mapped[str] = mapped_column(Text, nullable=False)
    statement_b: Mapped[str] = mapped_column(Text, nullable=False)
    discrepancy_type: Mapped[str] = mapped_column(String(80), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeAssertion(Base):
    """A candidate proposition whose exact source provenance is recorded mechanically."""

    __tablename__ = "knowledge_assertions"
    __table_args__ = (
        CheckConstraint(
            "provenance_state IN ('validated', 'unresolved')",
            name="ck_knowledge_assertions_provenance_state",
        ),
        CheckConstraint(
            "review_state IN ('needs_review', 'reviewed')",
            name="ck_knowledge_assertions_review_state",
        ),
        CheckConstraint(
            "(quote_start IS NULL AND quote_end IS NULL) OR "
            "(quote_start >= 0 AND quote_end >= quote_start)",
            name="ck_knowledge_assertions_quote_offsets",
        ),
        UniqueConstraint(
            "source_region_id",
            "normalized_hash",
            "extraction_profile",
            "extraction_profile_version",
            name="uq_knowledge_assertions_exact_input",
        ),
        Index("ix_knowledge_assertions_owner_pack", "owner_id", "source_pack_version_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_pack_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_pack_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_region_id: Mapped[int] = mapped_column(
        ForeignKey("source_regions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_quote: Mapped[str | None] = mapped_column(Text)
    quote_start: Mapped[int | None] = mapped_column(Integer)
    quote_end: Mapped[int | None] = mapped_column(Integer)
    proposition: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    predicate: Mapped[str | None] = mapped_column(Text)
    object_value: Mapped[str | None] = mapped_column(Text)
    date_value: Mapped[str | None] = mapped_column(String(80))
    unit: Mapped[str | None] = mapped_column(String(80))
    qualifier: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    polarity: Mapped[str | None] = mapped_column(String(24))
    extraction_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    extraction_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance_state: Mapped[str] = mapped_column(String(16), nullable=False)
    review_state: Mapped[str] = mapped_column(String(20), nullable=False, default="needs_review")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"
    __table_args__ = (
        CheckConstraint(
            "source_assertion_id != target_assertion_id", name="ck_knowledge_relations_distinct"
        ),
        CheckConstraint(
            "review_state IN ('needs_review', 'reviewed')",
            name="ck_knowledge_relations_review_state",
        ),
        Index("ix_knowledge_relations_owner", "owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_assertion_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    target_assertion_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    relation_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    extraction_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    extraction_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    review_state: Mapped[str] = mapped_column(String(20), nullable=False, default="needs_review")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClaimScan(Base):
    __tablename__ = "claim_scans"
    __table_args__ = (
        UniqueConstraint("artifact_version_id", name="uq_claim_scans_artifact_version"),
        CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed', 'needs_review')",
            name="ck_claim_scans_status",
        ),
        Index("ix_claim_scans_owner", "owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    artifact_version_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT"), nullable=False
    )
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    text_projection: Mapped[str | None] = mapped_column(Text)
    extraction_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    extraction_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClaimBatch(Base):
    __tablename__ = "claim_batches"
    __table_args__ = (
        UniqueConstraint("claim_scan_id", "ordinal", name="uq_claim_batches_scan_ordinal"),
        CheckConstraint("ordinal > 0", name="ck_claim_batches_positive_ordinal"),
        CheckConstraint(
            "text_start >= 0 AND text_end >= text_start", name="ck_claim_batches_text_range"
        ),
        CheckConstraint("attempt_count >= 0", name="ck_claim_batches_attempt_count"),
        CheckConstraint(
            "status IN ('pending', 'running', 'complete', 'failed', 'needs_review')",
            name="ck_claim_batches_status",
        ),
        Index("ix_claim_batches_scan_status", "claim_scan_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_scan_id: Mapped[int] = mapped_column(
        ForeignKey("claim_scans.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text_start: Mapped[int] = mapped_column(Integer, nullable=False)
    text_end: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    extraction_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    extraction_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MaterialClaim(Base):
    __tablename__ = "material_claims"
    __table_args__ = (
        CheckConstraint(
            "artifact_start >= 0 AND artifact_end >= artifact_start",
            name="ck_material_claims_offsets",
        ),
        UniqueConstraint(
            "claim_batch_id",
            "artifact_start",
            "artifact_end",
            "normalized_hash",
            name="uq_material_claims_exact_span",
        ),
        Index("ix_material_claims_scan", "claim_scan_id"),
        CheckConstraint(
            "block_mapping_state IS NULL OR block_mapping_state IN "
            "('validated', 'ambiguous', 'unmapped')",
            name="ck_material_claims_block_mapping_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    claim_scan_id: Mapped[int] = mapped_column(
        ForeignKey("claim_scans.id", ondelete="RESTRICT"), nullable=False
    )
    claim_batch_id: Mapped[int] = mapped_column(
        ForeignKey("claim_batches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    knowledge_assertion_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_assertions.id", ondelete="RESTRICT"), unique=True
    )
    artifact_quote: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_start: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_end: Mapped[int] = mapped_column(Integer, nullable=False)
    proposition: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    claim_type: Mapped[str | None] = mapped_column(String(80))
    block_mapping_state: Mapped[str | None] = mapped_column(String(16), default="unmapped")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ContextManifest(Base):
    __tablename__ = "context_manifests"
    __table_args__ = (
        CheckConstraint("context_budget_units >= 0", name="ck_context_manifests_budget"),
        CheckConstraint("estimated_context_units >= 0", name="ck_context_manifests_estimated"),
        CheckConstraint("available_input_budget >= 0", name="ck_context_manifests_available"),
        CheckConstraint("reserved_margin >= 0", name="ck_context_manifests_reserved"),
        Index("ix_context_manifests_owner", "owner_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_pack_id: Mapped[int] = mapped_column(
        ForeignKey("source_packs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_pack_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_pack_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    task_class: Mapped[str] = mapped_column(String(40), nullable=False)
    artifact_family: Mapped[str] = mapped_column(String(40), nullable=False)
    route: Mapped[str] = mapped_column(String(40), nullable=False)
    context_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    context_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    query_construction_version: Mapped[int] = mapped_column(Integer, nullable=False)
    query_text: Mapped[str | None] = mapped_column(Text)
    budget_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    estimation_method: Mapped[str] = mapped_column(String(80), nullable=False)
    context_budget_units: Mapped[int] = mapped_column(Integer, nullable=False)
    available_input_budget: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_context_units: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_margin: Mapped[int] = mapped_column(Integer, nullable=False)
    extraction_coverage: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ContextManifestEntry(Base):
    __tablename__ = "context_manifest_entries"
    __table_args__ = (
        UniqueConstraint(
            "context_manifest_id", "source_region_id", name="uq_context_manifest_region"
        ),
        CheckConstraint(
            "estimated_context_units >= 0", name="ck_context_manifest_entries_estimated"
        ),
        CheckConstraint(
            "candidate_rank IS NULL OR candidate_rank > 0", name="ck_context_manifest_entries_rank"
        ),
        CheckConstraint(
            "lexical_rank IS NULL OR lexical_rank > 0",
            name="ck_context_manifest_entries_lexical_rank",
        ),
        CheckConstraint(
            "vector_rank IS NULL OR vector_rank > 0", name="ck_context_manifest_entries_vector_rank"
        ),
        CheckConstraint(
            "fused_rank IS NULL OR fused_rank > 0", name="ck_context_manifest_entries_fused_rank"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    context_manifest_id: Mapped[int] = mapped_column(
        ForeignKey("context_manifests.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_region_id: Mapped[int] = mapped_column(
        ForeignKey("source_regions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_asset_id: Mapped[int] = mapped_column(
        ForeignKey("source_assets.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[int] = mapped_column(
        ForeignKey("source_pack_memberships.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    selected: Mapped[bool] = mapped_column(nullable=False, default=True)
    candidate_rank: Mapped[int | None] = mapped_column(Integer)
    lexical_rank: Mapped[int | None] = mapped_column(Integer)
    lexical_score: Mapped[float | None] = mapped_column()
    vector_rank: Mapped[int | None] = mapped_column(Integer)
    vector_score: Mapped[float | None] = mapped_column()
    fused_rank: Mapped[int | None] = mapped_column(Integer)
    fused_score: Mapped[float | None] = mapped_column()
    locator: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    estimated_context_units: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    profile_metadata: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class TextEmbeddingProfile(Base):
    __tablename__ = "text_embedding_profiles"
    __table_args__ = (
        UniqueConstraint(
            "profile_name", "profile_version", name="uq_text_embedding_profiles_version"
        ),
        CheckConstraint("dimension > 0", name="ck_text_embedding_profiles_dimension"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_name: Mapped[str] = mapped_column(String(100), nullable=False)
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    input_construction_version: Mapped[str] = mapped_column(String(80), nullable=False)
    privacy_classification: Mapped[str] = mapped_column(String(80), nullable=False)
    quality_disposition: Mapped[str] = mapped_column(
        String(24), nullable=False, default="MECHANICS_ONLY"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RegionEmbedding(Base):
    __tablename__ = "region_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "source_region_id", "embedding_profile_id", name="uq_region_embeddings_dependency"
        ),
        Index("ix_region_embeddings_profile", "embedding_profile_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_region_id: Mapped[int] = mapped_column(
        ForeignKey("source_regions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    embedding_profile_id: Mapped[int] = mapped_column(
        ForeignKey("text_embedding_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    source_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


@event.listens_for(ContextManifest, "before_update")
@event.listens_for(ContextManifest, "before_delete")
@event.listens_for(ContextManifestEntry, "before_update")
@event.listens_for(ContextManifestEntry, "before_delete")
def _immutable_manifest_record(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("Context manifests and entries are immutable snapshots")


@event.listens_for(ArtifactVersion, "before_update")
def _immutable_artifact_version(
    _mapper: object, _connection: object, target: ArtifactVersion
) -> None:
    state = inspect(target)
    immutable_fields = (
        "artifact_run_id",
        "version_number",
        "source_version_id",
        "context_manifest_id",
        "content",
        "provider",
        "model",
        "prompt_version",
        "prompt_hash",
        "artifact_schema_version",
        "origin",
        "created_at",
    )
    if any(state.attrs[name].history.has_changes() for name in immutable_fields):
        raise ValueError("Artifact versions are immutable snapshots")


@event.listens_for(ArtifactVersion, "before_delete")
@event.listens_for(ArtifactBlock, "before_update")
@event.listens_for(ArtifactBlock, "before_delete")
def _immutable_artifact_record(_mapper: object, _connection: object, _target: object) -> None:
    raise ValueError("Artifact versions and blocks are immutable snapshots")
