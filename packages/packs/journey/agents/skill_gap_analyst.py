"""Skill Gap Analyst: evidence -> a proposed gap -> a human confirmation.

The arithmetic is deterministic. The agent never changes a level and never
confirms a gap; it creates a proposal with a DecisionRecord.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from kernel.ai import AgentContext
from kernel.events.models import EventOutbox
from kernel.explain import DecisionDraft, Factor
from kernel.explain import Evidence as DecisionEvidence
from kernel.people.models import Employee, PersonSkillEvidence, Skill
from packs.journey import events as _events  # noqa: F401 - registers the pack's events
from packs.journey.models import SkillGap, SkillRequirement
from packs.journey.services import gap as gap_math

SOURCE_MAP = {
    "assessment": "assessment",
    "applied_evidence": "applied_evidence",
    "manager": "manager",
    "course": "course",
    "inferred": "inferred",
    "self": "self",
}


def run(ctx: AgentContext, event: EventOutbox | None) -> None:
    payload: dict[str, Any] = dict(event.payload) if event else {}
    employee_id = payload.get("employee_id")
    if not employee_id:
        return
    employee = ctx.session.get(Employee, UUID(str(employee_id)))
    if employee is None:
        return
    requirements = ctx.session.scalars(
        select(SkillRequirement).where(
            SkillRequirement.position_id == employee.position_id,
            SkillRequirement.version == 1,
        )
    ).all()
    if not requirements:
        return
    max_weight = max((Decimal(str(item.weight)) for item in requirements), default=Decimal("1"))
    proposed = 0
    for requirement in requirements:
        skill = ctx.session.get(Skill, requirement.skill_id)
        if skill is None:
            continue
        signals = ctx.session.scalars(
            select(PersonSkillEvidence).where(
                PersonSkillEvidence.person_id == employee.person_id,
                PersonSkillEvidence.skill_id == requirement.skill_id,
            )
        ).all()
        if not signals:
            continue
        evidence = [
            gap_math.Evidence(
                kind=SOURCE_MAP.get(item.source, "inferred"),
                weight=Decimal("1"),
                summary=item.evidence,
                ref=str(item.id),
            )
            for item in signals
        ]
        current = max(item.level for item in signals)
        assessment = gap_math.assess(
            skill.name,
            requirement.level_required,
            current,
            mandatory=requirement.is_mandatory,
            weight=Decimal(str(requirement.weight)),
            max_weight=max_weight,
            evidence=evidence,
        )
        if assessment.gap == 0:
            continue
        existing = ctx.session.scalar(
            select(SkillGap).where(
                SkillGap.employee_id == employee.id,
                SkillGap.skill_id == requirement.skill_id,
                SkillGap.status.in_(("proposed", "confirmed")),
            )
        )
        if existing is not None:
            continue
        factors = [
            {
                "key": factor.key,
                "label": factor.label,
                "weight": str(factor.weight),
                "value": str(factor.value),
                "contribution": str(factor.contribution),
            }
            for factor in assessment.severity.factors
        ]
        gap = SkillGap(
            tenant_id=ctx.tenant_id,
            employee_id=employee.id,
            skill_id=requirement.skill_id,
            requirement_id=requirement.id,
            current_level=assessment.current_level,
            required_level=assessment.required_level,
            gap=assessment.gap,
            severity=assessment.severity.label,
            severity_score=assessment.severity.score,
            confidence=assessment.confidence,
            message=assessment.message,
            factors=factors,
            evidence=[
                {
                    "kind": item.kind,
                    "weight": str(item.weight),
                    "summary": item.summary,
                    "ref": item.ref,
                }
                for item in evidence
            ],
            status="proposed",
        )
        ctx.session.add(gap)
        ctx.session.flush()
        decision = ctx.record_decision(
            DecisionDraft(
                kind="skill_gap",
                question=f"Should we confirm the {skill.name} gap for this employee?",
                outcome={
                    "severity": assessment.severity.label,
                    "current_level": assessment.current_level,
                    "required_level": assessment.required_level,
                    "gap": assessment.gap,
                },
                subject={"employee_id": str(employee.id), "skill_id": str(skill.id)},
                score=assessment.severity.score,
                factors=[
                    Factor(
                        key=item["key"],
                        label=item["label"],
                        weight=Decimal(item["weight"]),
                        value=Decimal(item["value"]),
                        contribution=Decimal(item["contribution"]),
                    )
                    for item in factors
                ],
                evidence=[
                    DecisionEvidence(
                        ref=item.ref or f"{gap.id}-{index}",
                        factor_key=None,
                        source_type=item.kind,
                        source_id=item.ref or str(gap.id),
                        quote=item.summary,
                    )
                    for index, item in enumerate(evidence, start=1)
                ],
                not_considered=["name", "gender", "age", "nationality", "photo"],
                limits=[assessment.message],
                versions={"model": "deterministic", "prompt_hash": "none"},
                view_roles=["admin", "hr", "manager", "auditor"],
            )
        )
        gap.decision_record_id = decision.id
        ctx.propose(
            "journey.gap.confirm",
            {"gap_id": str(gap.id), "decision_record_id": str(decision.id)},
            f"Confirm the {skill.name} gap for {employee.display_name}",
            decision.id,
            f"journey-gap:{employee.id}:{skill.id}",
            target={"type": "employee", "id": str(employee.id)},
        )
        proposed += 1
        if proposed >= 3:
            break
