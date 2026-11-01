from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin

UUID_TYPE = PG_UUID(as_uuid=True)


class BusyBlock(TenantMixin, Base):
    """Time someone isn't free. A real deployment syncs these from Google or Microsoft calendars."""

    __tablename__ = "busy_block"
    __table_args__ = {"schema": "calendar"}

    participant: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="Busy")
    # manual: typed in by a person. ics: imported from a calendar file, replaced on re-import.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )


class Booking(TenantMixin, Base):
    __tablename__ = "booking"
    __table_args__ = {"schema": "calendar"}

    title: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ref: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="confirmed", server_default="confirmed"
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Hold(TenantMixin, Base):
    """A slot offered to someone, kept off other offers until it is booked, released or expires."""

    __tablename__ = "hold"
    __table_args__ = {"schema": "calendar"}

    owner: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    participant: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class BookingSeat(TenantMixin, Base):
    """One row per participant. A database constraint makes double booking impossible."""

    __tablename__ = "booking_seat"
    __table_args__ = {"schema": "calendar"}

    booking_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("calendar.booking.id"), nullable=False, index=True
    )
    participant: Mapped[str] = mapped_column(String(320), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
