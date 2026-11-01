"""Finance API."""

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select

from kernel import explain
from kernel.authz import has_role, require_role
from kernel.errors import NotFound
from kernel.people.models import Employee
from kernel.web import request_context
from packs.finance import engagements, inputs, issues, runs, service
from packs.finance.models import (
    DocumentRef,
    Engagement,
    HireNotice,
    PayrollInput,
    PayrollInputBatch,
    PayrollInputRejection,
    PayrollRun,
    Payslip,
    PayslipLine,
    RuleSetRecord,
    ValidationIssue,
)
from packs.finance.payroll import calc

READ_ROLES = {"admin", "finance", "hr", "auditor"}
WRITE_ROLES = {"admin", "finance"}
MAX_SCENARIOS = 6
ENGAGEMENT_READ = {"admin", "finance", "hr", "auditor"}
ENGAGEMENT_WRITE = {"admin", "finance", "hr"}
PAY_READ = {"admin", "finance", "auditor"}
PAY_WRITE = {"admin", "finance"}
INPUT_READ = {"admin", "finance", "auditor"}
INPUT_WRITE = {"admin", "finance"}
RUN_SUMMARY_READ = {"admin", "finance", "hr", "auditor"}
RUN_DETAIL_READ = {"admin", "finance", "auditor"}
RUN_WRITE = {"admin", "finance"}

router = APIRouter()


class NetBody(BaseModel):
    gross: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    head_of_family: bool = False
    children: list[Literal["child", "student", "disabled"]] = Field(
        default_factory=list, max_length=20
    )
    on: date | None = None


class CompareBody(BaseModel):
    on: date | None = None
    scenarios: list[NetBody] = Field(min_length=1, max_length=MAX_SCENARIOS)


class RuleSetBody(BaseModel):
    definition: dict[str, Any]


def _input(body: NetBody) -> calc.PayslipInput:
    return calc.PayslipInput(body.gross, body.head_of_family, tuple(body.children))


def _summary(record: RuleSetRecord) -> dict[str, Any]:
    return {
        "id": str(record.id),
        "rule_id": record.rule_id,
        "version": record.version,
        "jurisdiction": record.jurisdiction,
        "status": record.status,
        "valid_from": record.valid_from.isoformat(),
        "valid_to": record.valid_to.isoformat() if record.valid_to else None,
        "is_demo": record.is_demo,
        "source_ref": record.source_ref,
        "definition_hash": record.definition_hash,
    }


@router.post("/calculator/net", summary="Gross to net, line by line. Nothing is stored.")
def calculate_net(body: NetBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        return service.calculate_net(ctx.session, _input(body), body.on or service.today_in_tunis())


@router.post("/calculator/compare", summary="Several gross-to-net scenarios side by side")
def compare(body: CompareBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        return {
            "scenarios": [
                service.calculate_net(
                    ctx.session, _input(item), item.on or body.on or service.today_in_tunis()
                )
                for item in body.scenarios
            ]
        }


@router.get("/rule-sets", summary="Rule sets, without their full definitions")
def list_rule_sets(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        rows = ctx.session.scalars(
            select(RuleSetRecord).order_by(RuleSetRecord.valid_from, RuleSetRecord.rule_id)
        ).all()
        return [_summary(row) for row in rows]


@router.get("/rule-sets/{record_id}", summary="One rule set with its full definition")
def get_rule_set(record_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        record = service.get_rule_set(ctx.session, record_id)
        return {**_summary(record), "definition": record.definition}


@router.post("/rule-sets", status_code=201, summary="Save a new rule set as a draft")
def create_rule_set(body: RuleSetBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        record = service.create_rule_set(ctx.session, ctx.actor.tenant_id, body.definition)
        return _summary(record)


@router.post("/rule-sets/{record_id}/test", summary="Run the rule set's hand-checked examples")
def test_rule_set(record_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, READ_ROLES)
        record = service.get_rule_set(ctx.session, record_id)
        return service.example_report(service.parse_definition(record.definition))


@router.post(
    "/rule-sets/{record_id}/activate",
    status_code=202,
    summary="Propose activating a rule set. A different person must approve it.",
)
def activate_rule_set(record_id: UUID, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, WRITE_ROLES)
        proposal = service.request_activation(
            ctx.session, ctx.actor.tenant_id, ctx.actor, record_id
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}


class PayItemBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    amount: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    valid_from: date
    valid_to: date | None = None
    frequency: Literal["monthly"] = "monthly"


class EngagementBody(BaseModel):
    type: Literal["CDI", "CDD", "CIVP"]
    starts_on: date
    ends_on: date | None = None
    job_title: str = Field(min_length=1, max_length=200)
    work_location: str | None = Field(default=None, max_length=128)
    weekly_hours: Decimal | None = Field(default=None, gt=0, le=168, max_digits=5, decimal_places=2)
    cdd_reason_code: str | None = Field(default=None, max_length=64)
    head_of_family: bool = False
    children: list[Literal["child", "student", "disabled"]] = Field(
        default_factory=list, max_length=20
    )
    external_request_id: str | None = Field(default=None, max_length=128)
    pay_items: list[PayItemBody] = Field(default_factory=list, max_length=20)


class ConvertBody(EngagementBody):
    employee_id: UUID | None = None


class DocumentBody(BaseModel):
    doc_type: str = Field(min_length=1, max_length=48)
    note: str | None = Field(default=None, max_length=500)
    file_key: str | None = Field(default=None, max_length=500)


class DocumentReviewBody(BaseModel):
    decision: Literal["verified", "rejected"]
    note: str | None = Field(default=None, max_length=500)


class ReasonBody(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class AmendBody(BaseModel):
    field: Literal["base_salary", "weekly_hours", "job_title", "work_location", "ends_on"]
    new_value: str = Field(min_length=1, max_length=200)
    effective_from: date
    reason: str = Field(min_length=3, max_length=1000)


def _new_engagement(body: EngagementBody) -> engagements.NewEngagement:
    return engagements.NewEngagement(
        type=body.type,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        job_title=body.job_title.strip(),
        work_location=body.work_location,
        weekly_hours=body.weekly_hours,
        cdd_reason_code=body.cdd_reason_code,
        head_of_family=body.head_of_family,
        children=list(body.children),
        external_request_id=body.external_request_id,
        pay_items=[
            engagements.PayItemInput(i.code, i.amount, i.valid_from, i.valid_to, i.frequency)
            for i in body.pay_items
        ],
    )


def _engagement_json(session, row: Engagement, show_pay: bool) -> dict[str, Any]:
    items = None
    if show_pay:
        items = [
            {
                "code": i.code,
                "amount": format(i.amount, "f"),
                "frequency": i.frequency,
                "valid_from": i.valid_from.isoformat(),
                "valid_to": i.valid_to.isoformat() if i.valid_to else None,
            }
            for i in engagements.pay_items_of(session, row.id)
        ]
    issues = engagements.open_issues(session, row.id)
    return {
        "id": str(row.id),
        "employee_id": str(row.employee_id),
        "type": row.type,
        "status": row.status,
        "starts_on": row.starts_on.isoformat(),
        "ends_on": row.ends_on.isoformat() if row.ends_on else None,
        "job_title": row.job_title,
        "work_location": row.work_location,
        "weekly_hours": None if row.weekly_hours is None else format(row.weekly_hours, "f"),
        "cdd_reason_code": row.cdd_reason_code,
        "head_of_family": row.head_of_family,
        "children": row.children,
        "open_issues": {
            "blocking": sum(1 for i in issues if i.severity == "blocking"),
            "review": sum(1 for i in issues if i.severity == "review"),
        },
        "pay_items": items,
    }


def _issue_json(row: ValidationIssue) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "severity": row.severity,
        "field": row.field,
        "message": row.message,
        "next_action": row.next_action,
        "owner_role": row.owner_role,
        "status": row.status,
        "resolution_reason": row.resolution_reason,
    }


def _document_json(row: DocumentRef) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "doc_type": row.doc_type,
        "verification_status": row.verification_status,
        "verified_at": row.verified_at.isoformat() if row.verified_at else None,
        "note": row.note,
    }


@router.post(
    "/employees/{employee_id}/engagements",
    status_code=201,
    summary="Create an engagement as a draft. The same request id returns the same engagement.",
)
def create_engagement(
    employee_id: UUID, body: EngagementBody, request: Request, response: Response
) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_WRITE)
        if body.pay_items:
            require_role(ctx.actor, PAY_WRITE)
        row, created = engagements.create_engagement(
            ctx.session, ctx.actor.tenant_id, employee_id, _new_engagement(body)
        )
        if not created:
            response.status_code = 200
        return _engagement_json(ctx.session, row, has_role(ctx.actor, PAY_READ))


@router.get("/engagements", summary="Engagements. Pay amounts are shown only to finance roles.")
def list_engagements(request: Request, employee_id: UUID | None = None) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_READ)
        query = select(Engagement).order_by(Engagement.created_at)
        if employee_id:
            query = query.where(Engagement.employee_id == employee_id)
        show_pay = has_role(ctx.actor, PAY_READ)
        return [_engagement_json(ctx.session, row, show_pay) for row in ctx.session.scalars(query)]


@router.get("/engagements/{engagement_id}", summary="One engagement with its documents checklist")
def get_engagement(engagement_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_READ)
        row = engagements.get_engagement(ctx.session, engagement_id)
        body = _engagement_json(ctx.session, row, has_role(ctx.actor, PAY_READ))
        body["checklist"] = engagements.checklist(ctx.session, row)
        return body


@router.post("/engagements/{engagement_id}/pay-items", status_code=201, summary="Add a pay item")
def add_pay_item(engagement_id: UUID, body: PayItemBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, PAY_WRITE)
        row = engagements.get_engagement(ctx.session, engagement_id)
        engagements.add_pay_item(
            ctx.session,
            ctx.actor.tenant_id,
            row,
            engagements.PayItemInput(
                body.code, body.amount, body.valid_from, body.valid_to, body.frequency
            ),
        )
        return _engagement_json(ctx.session, row, True)


@router.post("/engagements/{engagement_id}/validate", summary="Run the checks again")
def validate_engagement(engagement_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_WRITE)
        row = engagements.get_engagement(ctx.session, engagement_id)
        engagements.validate_engagement(ctx.session, ctx.actor.tenant_id, row)
        return {
            "status": row.status,
            "issues": [_issue_json(i) for i in engagements.open_issues(ctx.session, row.id)],
        }


@router.get("/engagements/{engagement_id}/issues", summary="Every issue raised for an engagement")
def list_issues(engagement_id: UUID, request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_READ)
        engagements.get_engagement(ctx.session, engagement_id)
        rows = ctx.session.scalars(
            select(ValidationIssue)
            .where(
                ValidationIssue.entity_type == "engagement",
                ValidationIssue.entity_id == engagement_id,
            )
            .order_by(ValidationIssue.created_at)
        )
        return [_issue_json(row) for row in rows]


@router.post("/issues/{issue_id}/resolve", summary="Decide a review item, with a reason")
def resolve_issue(issue_id: UUID, body: ReasonBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        found = ctx.session.get(ValidationIssue, issue_id)
        about_pay = found is not None and found.entity_type in {"payroll_input", "payroll_run"}
        require_role(ctx.actor, INPUT_WRITE if about_pay else ENGAGEMENT_WRITE)
        return _issue_json(issues.resolve_issue(ctx.session, ctx.actor, issue_id, body.reason))


@router.get("/engagements/{engagement_id}/documents", summary="Documents and the checklist")
def list_documents(engagement_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_READ)
        row = engagements.get_engagement(ctx.session, engagement_id)
        documents = ctx.session.scalars(
            select(DocumentRef)
            .where(DocumentRef.engagement_id == engagement_id)
            .order_by(DocumentRef.created_at)
        )
        return {
            "checklist": engagements.checklist(ctx.session, row),
            "documents": [_document_json(d) for d in documents],
        }


@router.post("/engagements/{engagement_id}/documents", status_code=201, summary="Record a document")
def add_document(engagement_id: UUID, body: DocumentBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_WRITE)
        row = engagements.get_engagement(ctx.session, engagement_id)
        document = engagements.add_document(
            ctx.session, ctx.actor.tenant_id, row, body.doc_type, body.note, body.file_key
        )
        return _document_json(document)


@router.post("/documents/{document_id}/review", summary="Verify or reject a document")
def review_document(
    document_id: UUID, body: DocumentReviewBody, request: Request
) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_WRITE)
        document = engagements.review_document(
            ctx.session, ctx.actor, document_id, body.decision, body.note
        )
        return _document_json(document)


@router.post(
    "/engagements/{engagement_id}/activate",
    status_code=202,
    summary="Propose activating a validated engagement. A person must approve it.",
)
def activate_engagement(engagement_id: UUID, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_WRITE)
        proposal = engagements.request_activation(
            ctx.session, ctx.actor.tenant_id, ctx.actor, engagement_id
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}


@router.post(
    "/engagements/{engagement_id}/amendments",
    status_code=202,
    summary="Propose a change from a date. A person must approve it.",
)
def amend_engagement(engagement_id: UUID, body: AmendBody, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_WRITE)
        if body.field == "base_salary":
            require_role(ctx.actor, PAY_WRITE)
        proposal = engagements.request_amendment(
            ctx.session,
            ctx.actor.tenant_id,
            ctx.actor,
            engagement_id,
            body.field,
            body.new_value,
            body.effective_from,
            body.reason,
        )
        return {"proposal_id": str(proposal.id), "status": proposal.status}


@router.get("/hire-notices", summary="Candidates who reached hired and still need their terms")
def list_hire_notices(request: Request, status: str | None = None) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_READ)
        query = select(HireNotice).order_by(HireNotice.created_at)
        if status:
            query = query.where(HireNotice.status == status)
        return [
            {
                "id": str(n.id),
                "application_id": str(n.application_id),
                "job_id": str(n.job_id),
                "person_id": str(n.person_id) if n.person_id else None,
                "status": n.status,
                "engagement_id": str(n.engagement_id) if n.engagement_id else None,
            }
            for n in ctx.session.scalars(query)
        ]


@router.post(
    "/hire-notices/{notice_id}/engagement",
    status_code=201,
    summary="Complete a hire notice with the employee and the terms",
)
def convert_hire_notice(notice_id: UUID, body: ConvertBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, ENGAGEMENT_WRITE)
        if body.pay_items:
            require_role(ctx.actor, PAY_WRITE)
        row = engagements.convert_hire_notice(
            ctx.session, ctx.actor.tenant_id, notice_id, body.employee_id, _new_engagement(body)
        )
        return _engagement_json(ctx.session, row, has_role(ctx.actor, PAY_READ))


class InputRowBody(BaseModel):
    model_config = {"extra": "forbid"}

    employee: str = Field(max_length=64)
    kind: str = Field(max_length=24)
    effective_date: str = Field(max_length=10)
    quantity: str | None = Field(default=None, max_length=20)
    amount: str | None = Field(default=None, max_length=20)
    reference: str | None = Field(default=None, max_length=64)


class InputRowsBody(BaseModel):
    source: Literal["manual", "time", "leave", "compensation"] = "manual"
    period_start: date
    period_end: date
    rows: list[InputRowBody] = Field(min_length=1, max_length=inputs.MAX_ROWS)


def _input_json(row: PayrollInput, employee_ref: str) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "line": row.line_number,
        "employee": employee_ref,
        "kind": row.kind,
        "effective_date": row.effective_date.isoformat(),
        "quantity": None if row.quantity is None else format(row.quantity, "f"),
        "amount": None if row.amount is None else format(row.amount, "f"),
        "reference": row.reference,
        "status": row.status,
        "note": row.reject_reason,
    }


@router.post(
    "/input-batches",
    status_code=201,
    summary="Import a CSV of approved hours, absences, bonuses, allowances and reimbursements",
)
async def import_input_csv(
    request: Request,
    response: Response,
    period_start: date = Form(),
    period_end: date = Form(),
    file: UploadFile = File(),
) -> dict[str, Any]:
    content = await file.read(inputs.MAX_BYTES + 1)
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_WRITE)
        batch, created = inputs.import_rows(
            ctx.session,
            ctx.actor.tenant_id,
            ctx.actor.user_id,
            "csv",
            period_start,
            period_end,
            inputs.parse_csv(content),
            inputs.content_hash_of_file(content, period_start, period_end),
        )
        if not created:
            response.status_code = 200
        return inputs.batch_summary(ctx.session, batch)


@router.post(
    "/input-batches/rows",
    status_code=201,
    summary="Send input rows as JSON. The same content returns the same batch.",
)
def import_input_rows(body: InputRowsBody, request: Request, response: Response) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_WRITE)
        rows = [
            inputs.RawRow(
                number,
                {k: (v or "") for k, v in item.model_dump().items()},
            )
            for number, item in enumerate(body.rows, start=1)
        ]
        batch, created = inputs.import_rows(
            ctx.session,
            ctx.actor.tenant_id,
            ctx.actor.user_id,
            body.source,
            body.period_start,
            body.period_end,
            rows,
            inputs.content_hash_of_rows(rows, body.period_start, body.period_end),
        )
        if not created:
            response.status_code = 200
        return inputs.batch_summary(ctx.session, batch)


@router.get("/input-batches", summary="Input batches, newest first")
def list_input_batches(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_READ)
        rows = ctx.session.scalars(
            select(PayrollInputBatch).order_by(PayrollInputBatch.created_at.desc())
        )
        return [inputs.batch_summary(ctx.session, row) for row in rows]


@router.get("/input-batches/{batch_id}", summary="One input batch with its counts")
def get_input_batch(batch_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_READ)
        return inputs.batch_summary(ctx.session, inputs.get_batch(ctx.session, batch_id))


@router.get("/input-batches/{batch_id}/rows", summary="The inputs stored from a batch")
def list_batch_rows(
    batch_id: UUID, request: Request, status: str | None = None
) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_READ)
        inputs.get_batch(ctx.session, batch_id)
        query = (
            select(PayrollInput, Employee.external_id)
            .join(Employee, Employee.id == PayrollInput.employee_id)
            .where(PayrollInput.batch_id == batch_id)
            .order_by(PayrollInput.line_number, PayrollInput.created_at)
        )
        if status:
            query = query.where(PayrollInput.status == status)
        return [_input_json(row, ref) for row, ref in ctx.session.execute(query)]


@router.get("/input-batches/{batch_id}/rejections", summary="Rows that were not stored, and why")
def list_batch_rejections(batch_id: UUID, request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_READ)
        inputs.get_batch(ctx.session, batch_id)
        rows = ctx.session.scalars(
            select(PayrollInputRejection)
            .where(PayrollInputRejection.batch_id == batch_id)
            .order_by(PayrollInputRejection.line_number)
        )
        return [
            {"line": r.line_number, "code": r.code, "message": r.message, "raw": r.raw}
            for r in rows
        ]


@router.get("/input-batches/{batch_id}/issues", summary="Issues raised on a batch's inputs")
def list_batch_issues(
    batch_id: UUID, request: Request, status: str | None = None
) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_READ)
        inputs.get_batch(ctx.session, batch_id)
        query = (
            select(ValidationIssue, PayrollInput)
            .join(PayrollInput, PayrollInput.id == ValidationIssue.entity_id)
            .where(ValidationIssue.entity_type == inputs.ENTITY, PayrollInput.batch_id == batch_id)
            .order_by(PayrollInput.line_number, ValidationIssue.created_at)
        )
        if status:
            query = query.where(ValidationIssue.status == status)
        return [
            {**_issue_json(issue), "input_id": str(row.id), "line": row.line_number}
            for issue, row in ctx.session.execute(query)
        ]


@router.post("/input-batches/{batch_id}/validate", summary="Check the batch again")
def validate_input_batch(batch_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_WRITE)
        batch = inputs.get_batch(ctx.session, batch_id)
        inputs.validate_batch(ctx.session, ctx.actor.tenant_id, batch)
        return inputs.batch_summary(ctx.session, batch)


@router.post("/payroll-inputs/{input_id}/withdraw", summary="Withdraw an input, with a reason")
def withdraw_input(input_id: UUID, body: ReasonBody, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, INPUT_WRITE)
        row = inputs.withdraw_input(ctx.session, ctx.actor, input_id, body.reason)
        employee = ctx.session.get(Employee, row.employee_id)
        return _input_json(row, employee.external_id)


class RunBody(BaseModel):
    period_start: date
    period_end: date
    pay_date: date
    regime_id: str = Field(default=runs.DEFAULT_REGIME, min_length=1, max_length=64)
    input_batch_ids: list[UUID] = Field(default_factory=list, max_length=20)
    external_request_id: str | None = Field(default=None, max_length=128)


def _payslip_json(row: Payslip, employee_ref: str) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "run_id": str(row.run_id),
        "employee": employee_ref,
        "gross": format(row.gross, "f"),
        "employee_deductions": format(row.employee_deductions, "f"),
        "income_tax": format(row.income_tax, "f"),
        "solidarity": format(row.solidarity, "f"),
        "net_pay": format(row.net_pay, "f"),
        "employer_cost": format(row.employer_cost, "f"),
        "status": row.status,
        "decision_record_id": str(row.decision_record_id) if row.decision_record_id else None,
    }


@router.post(
    "/payroll-runs",
    status_code=201,
    summary="Create a payroll run for a period. The same request id returns the same run.",
)
def create_payroll_run(body: RunBody, request: Request, response: Response) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_WRITE)
        run, created = runs.create_run(
            ctx.session,
            ctx.actor.tenant_id,
            ctx.actor,
            body.period_start,
            body.period_end,
            body.pay_date,
            body.regime_id,
            body.input_batch_ids,
            body.external_request_id,
        )
        if not created:
            response.status_code = 200
        return runs.run_json(ctx.session, run)


@router.get("/payroll-runs", summary="Payroll runs with their totals. HR sees totals only.")
def list_payroll_runs(request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_SUMMARY_READ)
        rows = ctx.session.scalars(select(PayrollRun).order_by(PayrollRun.period_start.desc()))
        return [runs.run_json(ctx.session, row) for row in rows]


@router.get("/payroll-runs/{run_id}", summary="One payroll run with its totals and open issues")
def get_payroll_run(run_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_SUMMARY_READ)
        return runs.run_json(ctx.session, runs.get_run(ctx.session, run_id))


@router.post(
    "/payroll-runs/{run_id}/calculate",
    status_code=202,
    summary="Ask the worker to calculate every payslip. Poll the run for the result.",
)
def calculate_payroll_run(run_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_WRITE)
        run = runs.request_calculation(ctx.session, ctx.actor.tenant_id, run_id)
        return {"status": run.status, "calculation_state": run.calculation_state}


@router.get("/payroll-runs/{run_id}/payslips", summary="The payslips of a run")
def list_run_payslips(run_id: UUID, request: Request) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_DETAIL_READ)
        runs.get_run(ctx.session, run_id)
        rows = ctx.session.execute(
            select(Payslip, Employee.external_id)
            .join(Employee, Employee.id == Payslip.employee_id)
            .where(Payslip.run_id == run_id)
            .order_by(Employee.external_id)
        )
        return [_payslip_json(row, ref) for row, ref in rows]


@router.get("/payslips/{payslip_id}", summary="One payslip with every line and the rule it used")
def get_payslip(payslip_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_DETAIL_READ)
        row = ctx.session.get(Payslip, payslip_id)
        if row is None:
            raise NotFound("Payslip not found")
        employee = ctx.session.get(Employee, row.employee_id)
        lines = ctx.session.scalars(
            select(PayslipLine)
            .where(PayslipLine.payslip_id == row.id)
            .order_by(PayslipLine.position)
        )
        return {
            **_payslip_json(row, employee.external_id),
            "lines": [
                {
                    "code": line.code,
                    "label": line.label,
                    "kind": line.kind,
                    "base": format(line.base, "f"),
                    "rate": None if line.rate is None else format(line.rate, "f"),
                    "amount": format(line.amount, "f"),
                    "rule_ref": line.rule_ref,
                }
                for line in lines
            ],
        }


@router.post("/payslips/{payslip_id}/verify", summary="Replay a payslip from its stored inputs")
def verify_payslip(payslip_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_DETAIL_READ)
        row = ctx.session.get(Payslip, payslip_id)
        if row is None:
            raise NotFound("Payslip not found")
        return explain.verify(ctx.session, row.decision_record_id)


@router.get("/payroll-runs/{run_id}/issues", summary="Exceptions and anomalies on a run")
def list_run_issues(
    run_id: UUID, request: Request, status: str | None = None
) -> list[dict[str, Any]]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_DETAIL_READ)
        runs.get_run(ctx.session, run_id)
        query = (
            select(ValidationIssue)
            .where(ValidationIssue.entity_type == runs.ENTITY, ValidationIssue.entity_id == run_id)
            .order_by(ValidationIssue.created_at)
        )
        if status:
            query = query.where(ValidationIssue.status == status)
        return [_issue_json(row) for row in ctx.session.scalars(query)]


@router.post(
    "/payroll-runs/{run_id}/verify", summary="Replay every payslip and check the run's hash"
)
def verify_payroll_run(run_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_DETAIL_READ)
        return runs.verify_run(ctx.session, run_id)


@router.post(
    "/payroll-runs/{run_id}/submit",
    status_code=202,
    summary="Submit a calculated run for approval. A different person must approve it.",
)
def submit_payroll_run(run_id: UUID, request: Request) -> dict[str, str]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_WRITE)
        proposal = runs.submit_for_approval(ctx.session, ctx.actor.tenant_id, ctx.actor, run_id)
        return {"proposal_id": str(proposal.id), "status": proposal.status}


@router.post("/payroll-runs/{run_id}/recall", summary="Take a submitted run back before approval")
def recall_payroll_run(run_id: UUID, request: Request) -> dict[str, Any]:
    with request_context(request) as ctx:
        require_role(ctx.actor, RUN_WRITE)
        return runs.run_json(ctx.session, runs.recall_submission(ctx.session, ctx.actor, run_id))
