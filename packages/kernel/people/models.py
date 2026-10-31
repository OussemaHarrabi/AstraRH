"""The shared records that make the packs one ecosystem: person, org, skills, KPIs."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from kernel.db import Base, TenantMixin, utcnow


class Person(TenantMixin, Base):
    """One human, from candidate to employee to alumni. Contact details live in the packs."""

    __tablename__ = "person"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "core"})

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False, default="candidate")


class OrgUnit(TenantMixin, Base):
    __tablename__ = "org_unit"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "core"})

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.org_unit.id")
    )


class Position(TenantMixin, Base):
    __tablename__ = "position"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "core"})

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)


class Employee(TenantMixin, Base):
    __tablename__ = "employee"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "core"})

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    person_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.person.id"), nullable=False, index=True
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    org_unit_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.org_unit.id"), nullable=False, index=True
    )
    position_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.position.id"), nullable=False
    )
    manager_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.employee.id")
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class Skill(TenantMixin, Base):
    __tablename__ = "skill"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "core"})

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class SkillRelation(TenantMixin, Base):
    """Authoritative skill adjacency. Scoring reads this, never Neo4j, so ranks are reproducible."""

    __tablename__ = "skill_relation"
    __table_args__ = (
        UniqueConstraint("tenant_id", "skill_id", "related_skill_id"),
        {"schema": "core"},
    )

    skill_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.skill.id"), nullable=False
    )
    related_skill_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.skill.id"), nullable=False
    )
    strength: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False, default=Decimal("0.5"))


class PersonSkillEvidence(TenantMixin, Base):
    """A skill claim about a person always names its source and evidence."""

    __tablename__ = "person_skill_evidence"
    __table_args__ = {"schema": "core"}

    person_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.person.id"), nullable=False, index=True
    )
    skill_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.skill.id"), nullable=False, index=True
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False)
    confirmed_by: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True))


class KpiDefinition(TenantMixin, Base):
    __tablename__ = "kpi_definition"
    __table_args__ = (UniqueConstraint("tenant_id", "external_id"), {"schema": "core"})

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_pack: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="higher_is_better")


class KpiObservation(TenantMixin, Base):
    __tablename__ = "kpi_observation"
    __table_args__ = {"schema": "core"}

    kpi_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("core.kpi_definition.id"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, default="tenant")
    scope_id: Mapped[str | None] = mapped_column(String(64))
    value: Mapped[Decimal] = mapped_column(Numeric(16, 4), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    source: Mapped[str] = mapped_column(String(64), nullable=False)
