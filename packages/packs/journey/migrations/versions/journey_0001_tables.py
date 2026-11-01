"""journey tables

Revision ID: journey_0001
Revises: None
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "journey_0001"
down_revision = None
branch_labels = ("journey",)
depends_on = "kernel_0002"


def upgrade() -> None:
    op.create_table('course',
    sa.Column('external_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=False),
    sa.Column('cost_tnd', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('hours', sa.Integer(), nullable=False),
    sa.Column('skill_id', sa.UUID(), nullable=False),
    sa.Column('level_gained', sa.Integer(), nullable=False),
    sa.Column('format', sa.String(length=24), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('kpi_id', sa.UUID(), nullable=False),
    sa.Column('expected_effect', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('level_gained BETWEEN 1 AND 4', name=op.f('ck_course_level_gained')),
    sa.ForeignKeyConstraint(['kpi_id'], ['core.kpi_definition.id'], name=op.f('fk_course_kpi_id_kpi_definition')),
    sa.ForeignKeyConstraint(['skill_id'], ['core.skill.id'], name=op.f('fk_course_skill_id_skill')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_course_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_course')),
    sa.UniqueConstraint('tenant_id', 'external_id', name=op.f('uq_course_tenant_id_external_id')),
    schema='journey'
    )
    op.create_index(op.f('ix_course_tenant_id'), 'course', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_course_tenant_skill', 'course', ['tenant_id', 'skill_id'], unique=False, schema='journey')
    op.create_table('onboarding_template',
    sa.Column('external_id', sa.String(length=64), nullable=False),
    sa.Column('position_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('duration_days', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['position_id'], ['core.position.id'], name=op.f('fk_onboarding_template_position_id_position')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_onboarding_template_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_onboarding_template')),
    sa.UniqueConstraint('tenant_id', 'external_id', name=op.f('uq_onboarding_template_tenant_id_external_id')),
    schema='journey'
    )
    op.create_index(op.f('ix_onboarding_template_position_id'), 'onboarding_template', ['position_id'], unique=False, schema='journey')
    op.create_index(op.f('ix_onboarding_template_tenant_id'), 'onboarding_template', ['tenant_id'], unique=False, schema='journey')
    op.create_table('skill_requirement',
    sa.Column('position_id', sa.UUID(), nullable=False),
    sa.Column('skill_id', sa.UUID(), nullable=False),
    sa.Column('level_required', sa.Integer(), nullable=False),
    sa.Column('is_mandatory', sa.Boolean(), nullable=False),
    sa.Column('weight', sa.Numeric(precision=4, scale=2), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('level_required BETWEEN 1 AND 4', name=op.f('ck_skill_requirement_level')),
    sa.ForeignKeyConstraint(['position_id'], ['core.position.id'], name=op.f('fk_skill_requirement_position_id_position')),
    sa.ForeignKeyConstraint(['skill_id'], ['core.skill.id'], name=op.f('fk_skill_requirement_skill_id_skill')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_skill_requirement_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_skill_requirement')),
    sa.UniqueConstraint('tenant_id', 'position_id', 'skill_id', 'version', name=op.f('uq_skill_requirement_tenant_id_position_id_skill_id_version')),
    schema='journey'
    )
    op.create_index(op.f('ix_skill_requirement_tenant_id'), 'skill_requirement', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_skill_requirement_tenant_position', 'skill_requirement', ['tenant_id', 'position_id'], unique=False, schema='journey')
    op.create_table('onboarding_plan',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('template_id', sa.UUID(), nullable=True),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('target_ramp_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('phase', sa.String(length=16), nullable=False),
    sa.Column('plan_approved_by', sa.UUID(), nullable=True),
    sa.Column('approval_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['core.employee.id'], name=op.f('fk_onboarding_plan_employee_id_employee')),
    sa.ForeignKeyConstraint(['template_id'], ['journey.onboarding_template.id'], name=op.f('fk_onboarding_plan_template_id_onboarding_template')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_onboarding_plan_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_onboarding_plan')),
    sa.UniqueConstraint('tenant_id', 'employee_id', 'start_date', name=op.f('uq_onboarding_plan_tenant_id_employee_id_start_date')),
    schema='journey'
    )
    op.create_index(op.f('ix_onboarding_plan_employee_id'), 'onboarding_plan', ['employee_id'], unique=False, schema='journey')
    op.create_index(op.f('ix_onboarding_plan_tenant_id'), 'onboarding_plan', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_onboarding_plan_tenant_status', 'onboarding_plan', ['tenant_id', 'status'], unique=False, schema='journey')
    op.create_table('skill_gap',
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('skill_id', sa.UUID(), nullable=False),
    sa.Column('requirement_id', sa.UUID(), nullable=False),
    sa.Column('current_level', sa.Integer(), nullable=False),
    sa.Column('required_level', sa.Integer(), nullable=False),
    sa.Column('gap', sa.Integer(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('severity_score', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('factors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('decided_by', sa.UUID(), nullable=True),
    sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('decision_record_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.CheckConstraint('current_level BETWEEN 1 AND 4', name=op.f('ck_skill_gap_current_level')),
    sa.CheckConstraint('required_level BETWEEN 1 AND 4', name=op.f('ck_skill_gap_required_level')),
    sa.ForeignKeyConstraint(['employee_id'], ['core.employee.id'], name=op.f('fk_skill_gap_employee_id_employee')),
    sa.ForeignKeyConstraint(['requirement_id'], ['journey.skill_requirement.id'], name=op.f('fk_skill_gap_requirement_id_skill_requirement')),
    sa.ForeignKeyConstraint(['skill_id'], ['core.skill.id'], name=op.f('fk_skill_gap_skill_id_skill')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_skill_gap_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_skill_gap')),
    schema='journey'
    )
    op.create_index('ix_skill_gap_tenant_employee_skill', 'skill_gap', ['tenant_id', 'employee_id', 'skill_id'], unique=False, schema='journey')
    op.create_index(op.f('ix_skill_gap_tenant_id'), 'skill_gap', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_skill_gap_tenant_status', 'skill_gap', ['tenant_id', 'status'], unique=False, schema='journey')
    op.create_table('template_task',
    sa.Column('template_id', sa.UUID(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('phase', sa.String(length=16), nullable=False),
    sa.Column('task_kind', sa.String(length=24), nullable=False),
    sa.Column('owner_role', sa.String(length=16), nullable=False),
    sa.Column('due_day', sa.Integer(), nullable=False),
    sa.Column('mandatory', sa.Boolean(), nullable=False),
    sa.Column('evidence_required', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['template_id'], ['journey.onboarding_template.id'], name=op.f('fk_template_task_template_id_onboarding_template')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_template_task_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_template_task')),
    sa.UniqueConstraint('template_id', 'position', name=op.f('uq_template_task_template_id_position')),
    schema='journey'
    )
    op.create_index(op.f('ix_template_task_tenant_id'), 'template_task', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_template_task_tenant_template', 'template_task', ['tenant_id', 'template_id'], unique=False, schema='journey')
    op.create_table('buddy_assignment',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('buddy_employee_id', sa.UUID(), nullable=False),
    sa.Column('cadence', sa.String(length=32), nullable=False),
    sa.Column('last_contact_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    sa.Column('approval_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['buddy_employee_id'], ['core.employee.id'], name=op.f('fk_buddy_assignment_buddy_employee_id_employee')),
    sa.ForeignKeyConstraint(['plan_id'], ['journey.onboarding_plan.id'], name=op.f('fk_buddy_assignment_plan_id_onboarding_plan')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_buddy_assignment_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_buddy_assignment')),
    sa.UniqueConstraint('plan_id', name=op.f('uq_buddy_assignment_plan_id')),
    schema='journey'
    )
    op.create_index('ix_buddy_assignment_tenant_buddy', 'buddy_assignment', ['tenant_id', 'buddy_employee_id'], unique=False, schema='journey')
    op.create_index(op.f('ix_buddy_assignment_tenant_id'), 'buddy_assignment', ['tenant_id'], unique=False, schema='journey')
    op.create_table('checkin',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('escalation', sa.Boolean(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['journey.onboarding_plan.id'], name=op.f('fk_checkin_plan_id_onboarding_plan')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_checkin_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_checkin')),
    schema='journey'
    )
    op.create_index(op.f('ix_checkin_tenant_id'), 'checkin', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_checkin_tenant_plan_kind', 'checkin', ['tenant_id', 'plan_id', 'kind'], unique=False, schema='journey')
    op.create_table('onboarding_task',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('template_task_id', sa.UUID(), nullable=True),
    sa.Column('phase', sa.String(length=16), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('task_kind', sa.String(length=24), nullable=False),
    sa.Column('owner_role', sa.String(length=16), nullable=False),
    sa.Column('owner_employee_id', sa.UUID(), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('mandatory', sa.Boolean(), nullable=False),
    sa.Column('evidence_required', sa.Text(), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('approved_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['owner_employee_id'], ['core.employee.id'], name=op.f('fk_onboarding_task_owner_employee_id_employee')),
    sa.ForeignKeyConstraint(['plan_id'], ['journey.onboarding_plan.id'], name=op.f('fk_onboarding_task_plan_id_onboarding_plan')),
    sa.ForeignKeyConstraint(['template_task_id'], ['journey.template_task.id'], name=op.f('fk_onboarding_task_template_task_id_template_task')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_onboarding_task_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_onboarding_task')),
    schema='journey'
    )
    op.create_index('ix_onboarding_task_tenant_due', 'onboarding_task', ['tenant_id', 'due_at', 'status'], unique=False, schema='journey')
    op.create_index(op.f('ix_onboarding_task_tenant_id'), 'onboarding_task', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_onboarding_task_tenant_plan', 'onboarding_task', ['tenant_id', 'plan_id'], unique=False, schema='journey')
    op.create_table('support_flag',
    sa.Column('plan_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=False),
    sa.Column('facts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('raised_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['plan_id'], ['journey.onboarding_plan.id'], name=op.f('fk_support_flag_plan_id_onboarding_plan')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_support_flag_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_support_flag')),
    schema='journey'
    )
    op.create_index(op.f('ix_support_flag_tenant_id'), 'support_flag', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_support_flag_tenant_plan_status', 'support_flag', ['tenant_id', 'plan_id', 'status'], unique=False, schema='journey')
    op.create_table('training_recommendation',
    sa.Column('gap_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=True),
    sa.Column('mentor_employee_id', sa.UUID(), nullable=True),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('cost_tnd', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('hours', sa.Integer(), nullable=False),
    sa.Column('kpi_id', sa.UUID(), nullable=False),
    sa.Column('expected_effect', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('approval_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['journey.course.id'], name=op.f('fk_training_recommendation_course_id_course')),
    sa.ForeignKeyConstraint(['employee_id'], ['core.employee.id'], name=op.f('fk_training_recommendation_employee_id_employee')),
    sa.ForeignKeyConstraint(['gap_id'], ['journey.skill_gap.id'], name=op.f('fk_training_recommendation_gap_id_skill_gap')),
    sa.ForeignKeyConstraint(['kpi_id'], ['core.kpi_definition.id'], name=op.f('fk_training_recommendation_kpi_id_kpi_definition')),
    sa.ForeignKeyConstraint(['mentor_employee_id'], ['core.employee.id'], name=op.f('fk_training_recommendation_mentor_employee_id_employee')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_training_recommendation_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_training_recommendation')),
    schema='journey'
    )
    op.create_index('ix_training_recommendation_tenant_employee', 'training_recommendation', ['tenant_id', 'employee_id', 'status'], unique=False, schema='journey')
    op.create_index(op.f('ix_training_recommendation_tenant_id'), 'training_recommendation', ['tenant_id'], unique=False, schema='journey')
    op.create_table('enrollment',
    sa.Column('recommendation_id', sa.UUID(), nullable=False),
    sa.Column('employee_id', sa.UUID(), nullable=False),
    sa.Column('course_id', sa.UUID(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('score', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('verified_by', sa.UUID(), nullable=True),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['course_id'], ['journey.course.id'], name=op.f('fk_enrollment_course_id_course')),
    sa.ForeignKeyConstraint(['employee_id'], ['core.employee.id'], name=op.f('fk_enrollment_employee_id_employee')),
    sa.ForeignKeyConstraint(['recommendation_id'], ['journey.training_recommendation.id'], name=op.f('fk_enrollment_recommendation_id_training_recommendation')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_enrollment_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_enrollment')),
    sa.UniqueConstraint('recommendation_id', name=op.f('uq_enrollment_recommendation_id')),
    schema='journey'
    )
    op.create_index('ix_enrollment_tenant_employee', 'enrollment', ['tenant_id', 'employee_id', 'status'], unique=False, schema='journey')
    op.create_index(op.f('ix_enrollment_tenant_id'), 'enrollment', ['tenant_id'], unique=False, schema='journey')
    op.create_table('impact_measure',
    sa.Column('recommendation_id', sa.UUID(), nullable=False),
    sa.Column('kpi_id', sa.UUID(), nullable=False),
    sa.Column('baseline_value', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('post_value', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('delta', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('comparison_employee_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('method', sa.Text(), nullable=False),
    sa.Column('measured_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('caveat', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['kpi_id'], ['core.kpi_definition.id'], name=op.f('fk_impact_measure_kpi_id_kpi_definition')),
    sa.ForeignKeyConstraint(['recommendation_id'], ['journey.training_recommendation.id'], name=op.f('fk_impact_measure_recommendation_id_training_recommendation')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_impact_measure_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_impact_measure')),
    sa.UniqueConstraint('recommendation_id', 'kpi_id', name=op.f('uq_impact_measure_recommendation_id_kpi_id')),
    schema='journey'
    )
    op.create_index(op.f('ix_impact_measure_tenant_id'), 'impact_measure', ['tenant_id'], unique=False, schema='journey')
    op.create_index('ix_impact_measure_tenant_kpi', 'impact_measure', ['tenant_id', 'kpi_id'], unique=False, schema='journey')
    op.create_table('pulse_survey',
    sa.Column('checkin_id', sa.UUID(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('questions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['checkin_id'], ['journey.checkin.id'], name=op.f('fk_pulse_survey_checkin_id_checkin')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_pulse_survey_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulse_survey')),
    sa.UniqueConstraint('checkin_id', 'version', name=op.f('uq_pulse_survey_checkin_id_version')),
    schema='journey'
    )
    op.create_index(op.f('ix_pulse_survey_tenant_id'), 'pulse_survey', ['tenant_id'], unique=False, schema='journey')
    op.create_table('pulse_response',
    sa.Column('survey_id', sa.UUID(), nullable=False),
    sa.Column('checkin_id', sa.UUID(), nullable=False),
    sa.Column('answers', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['checkin_id'], ['journey.checkin.id'], name=op.f('fk_pulse_response_checkin_id_checkin')),
    sa.ForeignKeyConstraint(['survey_id'], ['journey.pulse_survey.id'], name=op.f('fk_pulse_response_survey_id_pulse_survey')),
    sa.ForeignKeyConstraint(['tenant_id'], ['core.tenant.id'], name=op.f('fk_pulse_response_tenant_id_tenant')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pulse_response')),
    sa.UniqueConstraint('checkin_id', name=op.f('uq_pulse_response_checkin_id')),
    schema='journey'
    )
    op.create_index('ix_pulse_response_tenant_checkin', 'pulse_response', ['tenant_id', 'checkin_id'], unique=False, schema='journey')
    op.create_index(op.f('ix_pulse_response_tenant_id'), 'pulse_response', ['tenant_id'], unique=False, schema='journey')


def downgrade() -> None:
    op.drop_table("pulse_response", schema="journey")
    op.drop_table("pulse_survey", schema="journey")
    op.drop_table("impact_measure", schema="journey")
    op.drop_table("enrollment", schema="journey")
    op.drop_table("training_recommendation", schema="journey")
    op.drop_table("support_flag", schema="journey")
    op.drop_table("onboarding_task", schema="journey")
    op.drop_table("checkin", schema="journey")
    op.drop_table("buddy_assignment", schema="journey")
    op.drop_table("template_task", schema="journey")
    op.drop_table("skill_gap", schema="journey")
    op.drop_table("onboarding_plan", schema="journey")
    op.drop_table("skill_requirement", schema="journey")
    op.drop_table("onboarding_template", schema="journey")
    op.drop_table("course", schema="journey")
