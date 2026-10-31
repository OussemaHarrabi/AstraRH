"""Database access. Every tenant query runs in a transaction that has set app.tenant_id,
so row-level security applies. With no tenant set, RLS returns nothing (fail closed)."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import DateTime, Engine, ForeignKey, MetaData, create_engine, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, declared_attr, mapped_column

from kernel.ids import uuid7

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

_url_override: ContextVar[str | None] = ContextVar("astra_db_url", default=None)
_engines: dict[str, Engine] = {}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TenantMixin:
    """Required on every table: UUIDv7 id, tenant_id under RLS, created_at."""

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)

    @declared_attr
    def tenant_id(cls) -> Mapped[UUID]:  # noqa: N805 - SQLAlchemy declared_attr convention
        return mapped_column(
            PG_UUID(as_uuid=True), ForeignKey("core.tenant.id"), nullable=False, index=True
        )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


def database_url() -> str:
    url = _url_override.get() or os.environ["DATABASE_URL"]
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def get_engine() -> Engine:
    url = database_url()
    if url not in _engines:
        _engines[url] = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
    return _engines[url]


@contextmanager
def use_database(url: str) -> Iterator[None]:
    """Run as another database role. Used by tests and migrations."""
    token = _url_override.set(url)
    try:
        yield
    finally:
        _url_override.reset(token)


@contextmanager
def tenant_session(tenant_id: UUID | str) -> Iterator[Session]:
    """One transaction scoped to a tenant: commits on success, rolls back on error."""
    with Session(get_engine(), expire_on_commit=False) as session, session.begin():
        session.execute(
            text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": str(tenant_id)}
        )
        yield session


@contextmanager
def global_session() -> Iterator[Session]:
    """A transaction with no tenant: only global catalogues (tenant, action types) are visible."""
    with Session(get_engine(), expire_on_commit=False) as session, session.begin():
        yield session


def active_tenant_ids() -> list[UUID]:
    with global_session() as session:
        rows = session.execute(text("SELECT id FROM core.tenant WHERE active")).all()
    return [row[0] for row in rows]
