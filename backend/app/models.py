from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
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
    google_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
