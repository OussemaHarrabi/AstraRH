from datetime import date, datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin

EMBEDDING_DIMENSIONS = 384
UUID_TYPE = PG_UUID(as_uuid=True)


class Document(TenantMixin, Base):
    """audience_roles empty means everyone in the company may read it.

    Status: processing (uploaded, not yet indexed), active, superseded (a newer version of the
    same external_id is active), or failed. Only active documents can be cited."""

    __tablename__ = "document"
    __table_args__ = {"schema": "knowledge"}

    title: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    effective_date: Mapped[date | None] = mapped_column(Date)
    audience_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    source: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Chunk(TenantMixin, Base):
    __tablename__ = "chunk"
    __table_args__ = {"schema": "knowledge"}

    document_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("knowledge.document.id"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    section: Mapped[str] = mapped_column(Text, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    audience_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class Question(TenantMixin, Base):
    __tablename__ = "question"
    __table_args__ = {"schema": "knowledge"}

    asker_id: Mapped[UUID] = mapped_column(UUID_TYPE, nullable=False, index=True)
    asker_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    answer: Mapped[str | None] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    refusal_reason: Mapped[str | None] = mapped_column(Text)
    top_similarity: Mapped[float | None] = mapped_column(Float)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when a person in HR wrote the answer rather than the assistant.
    answered_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    feedback_helpful: Mapped[bool | None] = mapped_column(Boolean)
    feedback_comment: Mapped[str | None] = mapped_column(Text)


class Ticket(TenantMixin, Base):
    """A question the documents couldn't answer, now waiting for a person in HR.

    Status: open, claimed (someone is on it), answered, or closed (no answer needed)."""

    __tablename__ = "ticket"
    __table_args__ = {"schema": "knowledge"}

    question_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("knowledge.question.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    answer: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
