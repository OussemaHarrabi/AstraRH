"""Finance events. IDs, status and counts only: never salary lines, bank details or identity."""

from datetime import date
from uuid import UUID

from pydantic import BaseModel

from kernel.events import event_type


@event_type("finance.engagement.validated.v1")
class EngagementValidated(BaseModel):
    engagement_id: UUID
    status: str
    blocking: int
    review: int


@event_type("finance.engagement.activated.v1")
class EngagementActivated(BaseModel):
    engagement_id: UUID
    employee_id: UUID
    type: str
    starts_on: date


@event_type("finance.engagement.amended.v1")
class EngagementAmended(BaseModel):
    engagement_id: UUID
    effective_from: date


@event_type("finance.engagement.ending_soon.v1")
class EngagementEndingSoon(BaseModel):
    engagement_id: UUID
    ends_on: date


@event_type("finance.civp.activated.v1")
class CivpActivated(BaseModel):
    placement_id: UUID
    engagement_id: UUID
    starts_on: date


@event_type("finance.civp.payment_due.v1")
class CivpPaymentDue(BaseModel):
    placement_id: UUID
    month: date
    payer: str


@event_type("finance.civp.payment_reconciled.v1")
class CivpPaymentReconciled(BaseModel):
    placement_id: UUID
    month: date
    payer: str
    status: str


@event_type("finance.civp.completed.v1")
class CivpCompleted(BaseModel):
    placement_id: UUID
    engagement_id: UUID


@event_type("finance.payroll.calculated.v1")
class PayrollCalculated(BaseModel):
    run_id: UUID
    payslips: int
    exceptions: int


@event_type("finance.payroll.approved.v1")
class PayrollApproved(BaseModel):
    run_id: UUID
    payslips: int


@event_type("finance.payroll.rejected.v1")
class PayrollRejected(BaseModel):
    run_id: UUID


@event_type("finance.payroll.closed.v1")
class PayrollClosed(BaseModel):
    run_id: UUID


@event_type("finance.payment.submitted.v1")
class PaymentSubmitted(BaseModel):
    run_id: UUID
    release_number: int
    lines: int


@event_type("finance.payment.reconciled.v1")
class PaymentReconciled(BaseModel):
    run_id: UUID
    paid: int
    failed: int
