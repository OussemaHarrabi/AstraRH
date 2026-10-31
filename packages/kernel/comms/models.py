from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin

UUID_TYPE = PG_UUID(as_uuid=True)


class Thread(TenantMixin, Base):
    __tablename__ = "thread"
    __table_args__ = {"schema": "comms"}

    subject: Mapped[str] = mapped_column(Text, nullable=False)
    party_email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # open: someone still has to deal with it. handled: a person closed it or a reply went out.
    # A new inbound message reopens it.
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="open", server_default="open", index=True
    )
    handled_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_note: Mapped[str | None] = mapped_column(Text)


class Message(TenantMixin, Base):
    """Inbound bodies are untrusted, so only the quarantined reader ever gives them to a model."""

    __tablename__ = "message"
    __table_args__ = (UniqueConstraint("tenant_id", "provider_id"), {"schema": "comms"})

    thread_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("comms.thread.id"), nullable=False, index=True
    )
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    sender: Mapped[str] = mapped_column(String(320), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class Classification(TenantMixin, Base):
    __tablename__ = "classification"
    __table_args__ = (UniqueConstraint("message_id"), {"schema": "comms"})

    message_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("comms.message.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    urgency: Mapped[str] = mapped_column(String(16), nullable=False)
    needs_human: Mapped[bool] = mapped_column(Boolean, nullable=False)
    human_reason: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    quote: Mapped[str | None] = mapped_column(Text)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    # Set when a person corrects the sorting. The model's values are kept for evals.
    corrected_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model_values: Mapped[dict | None] = mapped_column(JSONB)


class Digest(TenantMixin, Base):
    __tablename__ = "digest"
    __table_args__ = (UniqueConstraint("tenant_id", "day"), {"schema": "comms"})

    day: Mapped[date] = mapped_column(Date, nullable=False)
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False)


class DigestItem(TenantMixin, Base):
    __tablename__ = "digest_item"
    __table_args__ = (UniqueConstraint("digest_id", "message_id"), {"schema": "comms"})

    digest_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("comms.digest.id"), nullable=False, index=True
    )
    message_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("comms.message.id"), nullable=False
    )
