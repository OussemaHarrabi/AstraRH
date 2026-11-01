"""Journey events. They are the only way other packs learn what happened."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from kernel.events import event_type


@event_type("journey.plan.activated.v1")
class PlanActivated(BaseModel):
    plan_id: UUID
    employee_id: UUID


@event_type("journey.checkin.due.v1")
class CheckinDue(BaseModel):
    checkin_id: UUID
    plan_id: UUID
    employee_id: UUID
    kind: str


@event_type("journey.pulse.submitted.v1")
class PulseSubmitted(BaseModel):
    checkin_id: UUID
    plan_id: UUID
    employee_id: UUID
    answers: dict[str, Any]


@event_type("journey.evidence.recorded.v1")
class EvidenceRecorded(BaseModel):
    task_id: UUID
    plan_id: UUID
    employee_id: UUID
    summary: str


@event_type("journey.skill_gap.confirmed.v1")
class SkillGapConfirmed(BaseModel):
    gap_id: UUID
    employee_id: UUID
    skill_id: UUID
    current_level: int
    required_level: int
    gap: int
    severity: str


@event_type("journey.training.completed.v1")
class TrainingCompleted(BaseModel):
    enrollment_id: UUID
    employee_id: UUID
    course_id: UUID
    cost_tnd: str
    hours: int
    kpi_id: UUID
    completed_at: datetime
    verification: str
    measured_effect: str | None = None


@event_type("journey.onboarding.completed.v1")
class OnboardingCompleted(BaseModel):
    plan_id: UUID
    employee_id: UUID
    completed_at: datetime
    milestones_total: int
    milestones_with_evidence: int
    verified_skills: list[dict[str, Any]]
