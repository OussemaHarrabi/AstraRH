from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin, utcnow
from kernel.ids import uuid7


class Tenant(Base):
    """Global catalogue. A tenant with active=false is ignored by background processes."""

    __tablename__ = "tenant"
    __table_args__ = {"schema": "core"}

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class UserAccount(TenantMixin, Base):
    __tablename__ = "user_account"
    __table_args__ = (UniqueConstraint("tenant_id", "email"), {"schema": "core"})

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    person_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RoleAssignment(TenantMixin, Base):
    """A role, optionally limited to one scope such as a single org unit."""

    __tablename__ = "role_assignment"
    __table_args__ = {"schema": "core"}

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.user_account.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_type: Mapped[str | None] = mapped_column(String(32))
    scope_id: Mapped[str | None] = mapped_column(String(64))


class LoginAttempt(TenantMixin, Base):
    __tablename__ = "login_attempt"
    __table_args__ = (
        Index("ix_login_attempt_key_created", "key_hash", "created_at"),
        {"schema": "core"},
    )

    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
