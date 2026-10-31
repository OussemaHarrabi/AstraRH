from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin

EMBEDDING_DIMENSIONS = 384
UUID_TYPE = PG_UUID(as_uuid=True)


class Job(TenantMixin, Base):
    __tablename__ = "job"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "talent"})

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    org_unit: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    active_rubric_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class Rubric(TenantMixin, Base):
    """Versioned and immutable once active, so a score can always name exactly what produced it."""

    __tablename__ = "rubric"
    __table_args__ = (UniqueConstraint("job_id", "version"), {"schema": "talent"})

    job_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("talent.job.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="human")
    criteria: Mapped[list] = mapped_column(JSONB, nullable=False)
    approved_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class Candidate(TenantMixin, Base):
    __tablename__ = "candidate"
    __table_args__ = {"schema": "talent"}

    person_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("core.person.id"), nullable=False)


class CandidateIdentity(TenantMixin, Base):
    """Kept apart on purpose: scoring code never reads this table."""

    __tablename__ = "candidate_identity"
    __table_args__ = (UniqueConstraint("candidate_id"), {"schema": "talent"})

    candidate_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.candidate.id"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(64))


class Application(TenantMixin, Base):
    __tablename__ = "application"
    __table_args__ = {"schema": "talent"}

    job_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.job.id"), nullable=False, index=True
    )
    candidate_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.candidate.id"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(24), nullable=False, default="applied")


class StageEvent(TenantMixin, Base):
    __tablename__ = "stage_event"
    __table_args__ = {"schema": "talent"}

    application_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.application.id"), nullable=False, index=True
    )
    from_stage: Mapped[str | None] = mapped_column(String(24))
    to_stage: Mapped[str] = mapped_column(String(24), nullable=False)
    proposal_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    reason: Mapped[str | None] = mapped_column(Text)


class CvDocument(TenantMixin, Base):
    __tablename__ = "cv_document"
    __table_args__ = (UniqueConstraint("application_id"), {"schema": "talent"})

    application_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.application.id"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("talent.job.id"), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_key: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="uploaded")
    status_reason: Mapped[str | None] = mapped_column(Text)
    blind_text: Mapped[str | None] = mapped_column(Text)
    parse_method: Mapped[str | None] = mapped_column(String(16))
    pages: Mapped[int | None] = mapped_column(Integer)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    hidden_text_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CvChunk(TenantMixin, Base):
    __tablename__ = "cv_chunk"
    __table_args__ = (
        Index("ix_cv_chunk_job_cv", "job_id", "cv_id"),
        {"schema": "talent"},
    )

    cv_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.cv_document.id"), nullable=False
    )
    job_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("talent.job.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)


class ExtractedProfile(TenantMixin, Base):
    """Frozen once read. Ranking uses this copy, so changing nothing can't change the result."""

    __tablename__ = "extracted_profile"
    __table_args__ = (UniqueConstraint("cv_id"), {"schema": "talent"})

    cv_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.cv_document.id"), nullable=False
    )
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    removed_spans: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)


class RankingRun(TenantMixin, Base):
    __tablename__ = "ranking_run"
    __table_args__ = {"schema": "talent"}

    job_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.job.id"), nullable=False, index=True
    )
    rubric_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.rubric.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")
    requested_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    inputs_hash: Mapped[str | None] = mapped_column(String(64))
    order_hash: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Score(TenantMixin, Base):
    __tablename__ = "score"
    __table_args__ = (
        UniqueConstraint("ranking_id", "application_id"),
        {"schema": "talent"},
    )

    ranking_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.ranking_run.id"), nullable=False, index=True
    )
    application_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.application.id"), nullable=False, index=True
    )
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    tiebreak: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    rank: Mapped[int | None] = mapped_column(Integer)
    meets_must_haves: Mapped[bool | None] = mapped_column(Boolean)
    decision_record_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class CriterionOverride(TenantMixin, Base):
    """A recruiter's correction. It feeds later rankings, with the reason kept for audit."""

    __tablename__ = "criterion_override"
    __table_args__ = {"schema": "talent"}

    application_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("talent.application.id"), nullable=False, index=True
    )
    criterion_id: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False)
