from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
            "source_kind IN ('text', 'file', 'url')", name="ck_source_assets_source_kind"
        ),
        CheckConstraint("byte_size >= 0", name="ck_source_assets_nonnegative_byte_size"),
        CheckConstraint(
            "extraction_coverage IN ('complete', 'partial')",
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
    content: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(120))
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_version: Mapped[str | None] = mapped_column(String(120))
    prompt_hash: Mapped[str | None] = mapped_column(String(64))
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("job_type IN ('artifact_generation')", name="ck_jobs_type"),
        CheckConstraint("resource_class IN ('model_io')", name="ck_jobs_resource_class"),
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
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    artifact_run_id: Mapped[int] = mapped_column(
        ForeignKey("artifact_runs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("source_versions.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    base_artifact_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("artifact_versions.id", ondelete="RESTRICT")
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
    statement_a: Mapped[str] = mapped_column(Text, nullable=False)
    statement_b: Mapped[str] = mapped_column(Text, nullable=False)
    discrepancy_type: Mapped[str] = mapped_column(String(80), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
