from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin, utcnow


class EventOutbox(TenantMixin, Base):
    """Written in the same transaction as the change it announces. Also the replay log."""

    __tablename__ = "event_outbox"
    __table_args__ = (
        Index("ix_event_outbox_unrouted", "tenant_id", "routed_at", "id"),
        {"schema": "core"},
    )

    type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    traceparent: Mapped[str | None] = mapped_column(String(64))
    routed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EventDelivery(TenantMixin, Base):
    """One row per event and consumer, so a failing consumer never blocks the others."""

    __tablename__ = "event_delivery"
    __table_args__ = (
        UniqueConstraint("event_id", "consumer"),
        Index("ix_event_delivery_due", "tenant_id", "status", "next_attempt_at"),
        {"schema": "core"},
    )

    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.event_outbox.id"), nullable=False
    )
    consumer: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    last_error: Mapped[str | None] = mapped_column(Text)
