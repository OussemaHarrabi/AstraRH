"""Public API of the shared people records."""

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.errors import NotFound
from kernel.people.models import (
    Employee,
    KpiDefinition,
    KpiObservation,
    OrgUnit,
    Person,
    PersonSkillEvidence,
    Position,
    Skill,
    SkillRelation,
)

__all__ = [
    "Employee",
    "KpiDefinition",
    "KpiObservation",
    "OrgUnit",
    "Person",
    "PersonSkillEvidence",
    "Position",
    "Skill",
    "SkillRelation",
    "add_skill_evidence",
    "record_kpi",
    "skill_by_external_id",
    "skill_relations",
]


def skill_by_external_id(session: Session, external_id: str) -> Skill:
    skill = session.scalar(select(Skill).where(Skill.external_id == external_id))
    if skill is None:
        raise NotFound(f"Unknown skill {external_id}")
    return skill


def skill_relations(session: Session) -> dict[UUID, dict[UUID, Decimal]]:
    """Adjacency used for deterministic scoring, in both directions."""
    relations: dict[UUID, dict[UUID, Decimal]] = {}
    for row in session.scalars(select(SkillRelation)):
        relations.setdefault(row.skill_id, {})[row.related_skill_id] = row.strength
        relations.setdefault(row.related_skill_id, {})[row.skill_id] = row.strength
    return relations


def add_skill_evidence(
    session: Session,
    tenant_id: UUID,
    person_id: UUID,
    skill_id: UUID,
    level: int,
    source: str,
    evidence: str,
) -> PersonSkillEvidence:
    row = PersonSkillEvidence(
        tenant_id=tenant_id,
        person_id=person_id,
        skill_id=skill_id,
        level=level,
        source=source,
        evidence=evidence,
    )
    session.add(row)
    return row


def record_kpi(
    session: Session,
    tenant_id: UUID,
    kpi_external_id: str,
    value: Decimal,
    source: str,
    scope_type: str = "tenant",
    scope_id: str | None = None,
) -> KpiObservation:
    kpi = session.scalar(select(KpiDefinition).where(KpiDefinition.external_id == kpi_external_id))
    if kpi is None:
        raise NotFound(f"Unknown KPI {kpi_external_id}")
    row = KpiObservation(
        tenant_id=tenant_id,
        kpi_id=kpi.id,
        value=value,
        source=source,
        scope_type=scope_type,
        scope_id=scope_id,
    )
    session.add(row)
    return row
