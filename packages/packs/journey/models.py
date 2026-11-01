"""Journey pack tables: onboarding, check-ins, skill gaps and training."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

# The worker imports pack models directly; load the core metadata they reference
# so SQLAlchemy can resolve tenant/employee/position/skill/KPI foreign keys.
import kernel.identity.models  # noqa: F401
import kernel.people.models  # noqa: F401
from kernel.db import Base, TenantMixin

SCHEMA = "journey"
UUID_TYPE = PG_UUID(as_uuid=True)


class OnboardingTemplate(TenantMixin, Base):
    __tablename__ = "onboarding_template"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id"),
        {"schema": SCHEMA},
    )

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    position_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.position.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="role-profile-v1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class TemplateTask(TenantMixin, Base):
    __tablename__ = "template_task"
    __table_args__ = (
        UniqueConstraint("template_id", "position"),
        Index("ix_template_task_tenant_template", "tenant_id", "template_id"),
        {"schema": SCHEMA},
    )

    template_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.onboarding_template.id"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    task_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(16), nullable=False)
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_required: Mapped[str] = mapped_column(Text, nullable=False)


class OnboardingPlan(TenantMixin, Base):
    __tablename__ = "onboarding_plan"
    __table_args__ = (
        UniqueConstraint("tenant_id", "employee_id", "start_date"),
        Index("ix_onboarding_plan_tenant_status", "tenant_id", "status"),
        {"schema": SCHEMA},
    )

    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False, index=True
    )
    template_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("journey.onboarding_template.id")
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_ramp_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    phase: Mapped[str] = mapped_column(String(16), nullable=False, default="preboarding")
    plan_approved_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    approval_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class OnboardingTask(TenantMixin, Base):
    __tablename__ = "onboarding_task"
    __table_args__ = (
        Index("ix_onboarding_task_tenant_plan", "tenant_id", "plan_id"),
        Index("ix_onboarding_task_tenant_due", "tenant_id", "due_at", "status"),
        {"schema": SCHEMA},
    )

    plan_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.onboarding_plan.id"), nullable=False
    )
    template_task_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("journey.template_task.id")
    )
    phase: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    task_kind: Mapped[str] = mapped_column(String(24), nullable=False, default="standard")
    owner_role: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_employee_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id")
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_required: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class BuddyAssignment(TenantMixin, Base):
    __tablename__ = "buddy_assignment"
    __table_args__ = (
        UniqueConstraint("plan_id"),
        Index("ix_buddy_assignment_tenant_buddy", "tenant_id", "buddy_employee_id"),
        {"schema": SCHEMA},
    )

    plan_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.onboarding_plan.id"), nullable=False
    )
    buddy_employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False
    )
    cadence: Mapped[str] = mapped_column(String(32), nullable=False, default="weekly")
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    approval_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class Checkin(TenantMixin, Base):
    __tablename__ = "checkin"
    __table_args__ = (
        Index("ix_checkin_tenant_plan_kind", "tenant_id", "plan_id", "kind"),
        {"schema": SCHEMA},
    )

    plan_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.onboarding_plan.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    escalation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PulseSurvey(TenantMixin, Base):
    __tablename__ = "pulse_survey"
    __table_args__ = (
        UniqueConstraint("checkin_id", "version"),
        {"schema": SCHEMA},
    )

    checkin_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.checkin.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    questions: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)


class PulseResponse(TenantMixin, Base):
    __tablename__ = "pulse_response"
    __table_args__ = (
        UniqueConstraint("checkin_id"),
        Index("ix_pulse_response_tenant_checkin", "tenant_id", "checkin_id"),
        {"schema": SCHEMA},
    )

    survey_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.pulse_survey.id"), nullable=False
    )
    checkin_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.checkin.id"), nullable=False
    )
    answers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SupportFlag(TenantMixin, Base):
    __tablename__ = "support_flag"
    __table_args__ = (
        Index("ix_support_flag_tenant_plan_status", "tenant_id", "plan_id", "status"),
        {"schema": SCHEMA},
    )

    plan_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.onboarding_plan.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    facts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class SkillRequirement(TenantMixin, Base):
    __tablename__ = "skill_requirement"
    __table_args__ = (
        UniqueConstraint("tenant_id", "position_id", "skill_id", "version"),
        Index("ix_skill_requirement_tenant_position", "tenant_id", "position_id"),
        CheckConstraint("level_required BETWEEN 1 AND 4", name="level"),
        {"schema": SCHEMA},
    )

    position_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.position.id"), nullable=False
    )
    skill_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("core.skill.id"), nullable=False)
    level_required: Mapped[int] = mapped_column(Integer, nullable=False)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="role-profile-v1")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SkillGap(TenantMixin, Base):
    __tablename__ = "skill_gap"
    __table_args__ = (
        Index("ix_skill_gap_tenant_employee_skill", "tenant_id", "employee_id", "skill_id"),
        Index("ix_skill_gap_tenant_status", "tenant_id", "status"),
        CheckConstraint("current_level BETWEEN 1 AND 4", name="current_level"),
        CheckConstraint("required_level BETWEEN 1 AND 4", name="required_level"),
        {"schema": SCHEMA},
    )

    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False
    )
    skill_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("core.skill.id"), nullable=False)
    requirement_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.skill_requirement.id"), nullable=False
    )
    current_level: Mapped[int] = mapped_column(Integer, nullable=False)
    required_level: Mapped[int] = mapped_column(Integer, nullable=False)
    gap: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    severity_score: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 4), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    factors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    decided_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    decision_record_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class Course(TenantMixin, Base):
    __tablename__ = "course"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id"),
        Index("ix_course_tenant_skill", "tenant_id", "skill_id"),
        CheckConstraint("level_gained BETWEEN 1 AND 4", name="level_gained"),
        {"schema": SCHEMA},
    )

    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    cost_tnd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_id: Mapped[UUID] = mapped_column(UUID_TYPE, ForeignKey("core.skill.id"), nullable=False)
    level_gained: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    format: Mapped[str] = mapped_column(String(24), nullable=False, default="course")
    url: Mapped[str | None] = mapped_column(Text)
    kpi_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.kpi_definition.id"), nullable=False
    )
    expected_effect: Mapped[str] = mapped_column(Text, nullable=False)


class TrainingRecommendation(TenantMixin, Base):
    __tablename__ = "training_recommendation"
    __table_args__ = (
        Index("ix_training_recommendation_tenant_employee", "tenant_id", "employee_id", "status"),
        {"schema": SCHEMA},
    )

    gap_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.skill_gap.id"), nullable=False
    )
    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="course")
    course_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("journey.course.id")
    )
    mentor_employee_id: Mapped[UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id")
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    cost_tnd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    kpi_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.kpi_definition.id"), nullable=False
    )
    expected_effect: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="proposed")
    approval_id: Mapped[UUID | None] = mapped_column(UUID_TYPE)


class Enrollment(TenantMixin, Base):
    __tablename__ = "enrollment"
    __table_args__ = (
        UniqueConstraint("recommendation_id"),
        Index("ix_enrollment_tenant_employee", "tenant_id", "employee_id", "status"),
        {"schema": SCHEMA},
    )

    recommendation_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.training_recommendation.id"), nullable=False
    )
    employee_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.employee.id"), nullable=False
    )
    course_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.course.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="assigned")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    verified_by: Mapped[UUID | None] = mapped_column(UUID_TYPE)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ImpactMeasure(TenantMixin, Base):
    __tablename__ = "impact_measure"
    __table_args__ = (
        UniqueConstraint("recommendation_id", "kpi_id"),
        Index("ix_impact_measure_tenant_kpi", "tenant_id", "kpi_id"),
        {"schema": SCHEMA},
    )

    recommendation_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("journey.training_recommendation.id"), nullable=False
    )
    kpi_id: Mapped[UUID] = mapped_column(
        UUID_TYPE, ForeignKey("core.kpi_definition.id"), nullable=False
    )
    baseline_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    post_value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    delta: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    comparison_employee_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    caveat: Mapped[str] = mapped_column(Text, nullable=False)

