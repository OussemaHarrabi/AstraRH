"""Payroll runs: create, calculate, submit, recall and replay.

Calculation runs in the worker, started by an event, because only the worker may write payslips.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from kernel import explain, trust
from kernel.canonical import payload_hash
from kernel.db import utcnow
from kernel.errors import Conflict, KernelError, NotFound, ValidationFailed
from kernel.events import publish
from kernel.identity import Actor
from kernel.people.models import Employee
from packs.finance import inputs as inputs_module
from packs.finance import issues, payments, proposals, service
from packs.finance.events import PayrollCalculated, PayrollCalculationRequested, PayrollRejected
from packs.finance.models import (
    Engagement,
    PayItem,
    PayrollInput,
    PayrollInputBatch,
    PayrollRun,
    PayrollRunInput,
    Payslip,
    PayslipLine,
    RuleSetRecord,
    ValidationIssue,
)
from packs.finance.payroll import calc, rules, scorer
from packs.finance.validation.common import BLOCKING, REVIEW, IssueSpec

ENTITY = "payroll_run"
APPROVE_ACTION = "finance.payroll.approve"
DEFAULT_REGIME = "TN_PRIVATE_NON_AGRI"
MAX_PERIOD_DAYS = 31
NET_CHANGE_REVIEW = Decimal("0.20")  # [verify]
DECISION_VIEW_ROLES = ["admin", "finance", "auditor"]
FROZEN = {"approval_pending", "approved", "payment_pending", "paid", "closed"}
SETTLED = ["approved", "payment_pending", "paid", "closed"]
NOT_CONSIDERED = ["Name", "Gender", "Age", "Nationality", "Address"]
BASE_SALARY = "BASE_SALARY"


def _text(value: Decimal) -> str:
    return format(value, "f")


def _label(code: str) -> str:
    return code.replace("_", " ").capitalize()


def get_run(session: Session, run_id: UUID) -> PayrollRun:
    run = session.get(PayrollRun, run_id)
    if run is None:
        raise NotFound("Payroll run not found")
    return run


def _rule_set_for(session: Session, start: date, end: date) -> tuple[rules.RuleSet, dict[str, Any]]:
    """One rule set must cover the whole period. A change inside it is not supported."""
    try:
        active = service.active_rule_sets(session)
        chosen = rules.select(active, end)
    except rules.RuleSetUnavailable as exc:
        raise Conflict(str(exc)) from exc
    if not chosen.covers(start):
        raise Conflict(f"Rule set {chosen.id} does not cover the whole period: it starts later")
    definition = session.scalar(
        select(RuleSetRecord.definition).where(RuleSetRecord.rule_id == chosen.id)
    )
    return chosen, definition


def create_run(
    session: Session,
    tenant_id: UUID,
    actor: Actor,
    period_start: date,
    period_end: date,
    pay_date: date,
    regime_id: str,
    batch_ids: list[UUID],
    external_request_id: str | None,
) -> tuple[PayrollRun, bool]:
    refs = sorted({str(b) for b in batch_ids})
    if external_request_id:
        existing = session.scalar(
            select(PayrollRun).where(PayrollRun.external_request_id == external_request_id)
        )
        if existing is not None:
            same = (
                existing.period_start == period_start
                and existing.period_end == period_end
                and existing.pay_date == pay_date
                and existing.regime_id == regime_id
                and sorted(existing.input_batch_refs) == refs
            )
            if not same:
                raise Conflict("That request id was used for a different payroll run")
            return existing, False
    if period_end < period_start:
        raise ValidationFailed("The period ends before it starts")
    if (period_end - period_start).days >= MAX_PERIOD_DAYS:
        raise ValidationFailed(f"A pay period is at most {MAX_PERIOD_DAYS} days")
    if pay_date < period_start:
        raise ValidationFailed("The pay date is before the period starts")
    overlapping = session.scalar(
        select(PayrollRun.id).where(
            PayrollRun.period_start <= period_end, PayrollRun.period_end >= period_start
        )
    )
    if overlapping is not None:
        raise Conflict("Another payroll run already covers part of this period")
    _rule_set_for(session, period_start, period_end)
    for batch_id in batch_ids:
        batch = session.get(PayrollInputBatch, batch_id)
        if batch is None:
            raise NotFound(f"Input batch {batch_id} not found")
        if batch.period_start < period_start or batch.period_end > period_end:
            raise ValidationFailed(f"Input batch {batch_id} is not inside the period of the run")
    run = PayrollRun(
        tenant_id=tenant_id,
        external_request_id=external_request_id,
        period_start=period_start,
        period_end=period_end,
        pay_date=pay_date,
        regime_id=regime_id,
        input_batch_refs=refs,
        prepared_by=actor.user_id,
    )
    session.add(run)
    session.flush()
    return run, True


def request_calculation(session: Session, tenant_id: UUID, run_id: UUID) -> PayrollRun:
    """Asks the worker to calculate. Safe to repeat while the run is still a draft or calculated."""
    run = session.get(PayrollRun, run_id, with_for_update=True)
    if run is None:
        raise NotFound("Payroll run not found")
    if run.status not in {"draft", "calculated"}:
        raise Conflict(f"A {run.status.replace('_', ' ')} run cannot be recalculated")
    if run.calculation_state == "requested":
        raise Conflict("A calculation is already waiting for the worker")
    _rule_set_for(session, run.period_start, run.period_end)
    if run.status == "calculated":
        run.status = "draft"
    run.calculation_state = "requested"
    session.flush()
    publish(session, tenant_id, PayrollCalculationRequested(run_id=run.id))
    return run


@dataclass
class _Plan:
    engagement: Engagement
    components: dict[str, Decimal]
    reimbursements: Decimal


def _specs_for_employee(
    spec: list[IssueSpec], code: str, severity: str, employee: str, message: str, action: str
) -> None:
    spec.append(IssueSpec(code, severity, f"employee:{employee}", message, action, "FINANCE"))


def calculate(session: Session, tenant_id: UUID, run_id: UUID) -> PayrollRun | None:
    """Worker only. Rebuilds every payslip of the run from the engagements, pay items and inputs."""
    run = session.get(PayrollRun, run_id, with_for_update=True)
    if run is None or run.calculation_state != "requested" or run.status != "draft":
        return None
    try:
        chosen, definition = _rule_set_for(session, run.period_start, run.period_end)
    except Conflict as exc:
        run.calculation_state = "failed"
        run.calculation_error = exc.message
        session.flush()
        return run

    old = [p.id for p in session.scalars(select(Payslip).where(Payslip.run_id == run.id))]
    if old:
        session.execute(delete(PayslipLine).where(PayslipLine.payslip_id.in_(old)))
        session.execute(delete(Payslip).where(Payslip.run_id == run.id))
    session.execute(delete(PayrollRunInput).where(PayrollRunInput.run_id == run.id))
    session.flush()

    specs: list[IssueSpec] = []
    externals = {e.id: e.external_id for e in session.scalars(select(Employee))}
    batch_ids = [UUID(b) for b in run.input_batch_refs]

    for batch_id in batch_ids:
        counts = inputs_module.issue_counts(session, batch_id)
        if counts["blocking"] or counts["review"]:
            specs.append(
                IssueSpec(
                    "BATCH_NEEDS_ATTENTION",
                    BLOCKING,
                    f"batch:{batch_id}",
                    "An input batch of this run still has open issues.",
                    "Resolve them in the input batch, then calculate again",
                    "FINANCE",
                )
            )

    used = (
        list(
            session.scalars(
                select(PayrollInput).where(
                    PayrollInput.batch_id.in_(batch_ids),
                    PayrollInput.status == "accepted",
                    PayrollInput.effective_date.between(run.period_start, run.period_end),
                )
            )
        )
        if batch_ids
        else []
    )
    by_employee: dict[UUID, list[PayrollInput]] = {}
    for row in used:
        by_employee.setdefault(row.employee_id, []).append(row)
        session.add(PayrollRunInput(tenant_id=tenant_id, run_id=run.id, input_id=row.id))

    engagements = list(
        session.scalars(
            select(Engagement).where(
                Engagement.status == "active",
                Engagement.type != "CIVP",
                Engagement.starts_on <= run.period_end,
                (Engagement.ends_on.is_(None)) | (Engagement.ends_on >= run.period_start),
            )
        )
    )
    per_employee: dict[UUID, list[Engagement]] = {}
    for engagement in engagements:
        per_employee.setdefault(engagement.employee_id, []).append(engagement)

    plans: dict[UUID, _Plan] = {}
    for employee_id, owned in per_employee.items():
        who = externals.get(employee_id, str(employee_id))
        fail = _specs_for_employee
        if len(owned) > 1:
            fail(
                specs,
                "MULTIPLE_ENGAGEMENTS",
                BLOCKING,
                str(employee_id),
                f"{who} has several active engagements in this period.",
                "Close all but one engagement",
            )
            continue
        engagement = owned[0]
        if engagement.starts_on > run.period_start or (
            engagement.ends_on is not None and engagement.ends_on < run.period_end
        ):
            fail(
                specs,
                "PARTIAL_PERIOD",
                BLOCKING,
                str(employee_id),
                f"{who} is employed for only part of this period. Proration is not built yet.",
                "Pay this employee outside this run",
            )
            continue
        items = list(
            session.scalars(
                select(PayItem).where(
                    PayItem.engagement_id == engagement.id,
                    PayItem.valid_from <= run.period_end,
                    (PayItem.valid_to.is_(None)) | (PayItem.valid_to >= run.period_start),
                )
            )
        )
        components: dict[str, Decimal] = {}
        reimbursements = Decimal(0)
        broken = False
        for item in items:
            whole = item.valid_from <= run.period_start and (
                item.valid_to is None or item.valid_to >= run.period_end
            )
            if not whole or item.code in components:
                fail(
                    specs,
                    "PAY_CHANGE_IN_PERIOD",
                    BLOCKING,
                    str(employee_id),
                    f"The {item.code} of {who} changes inside this period. Proration is not "
                    "built yet.",
                    "Pay this employee outside this run",
                )
                broken = True
                break
            if item.code == "REIMBURSEMENT":
                reimbursements += item.amount
            else:
                components[item.code] = item.amount
        if broken:
            continue
        if BASE_SALARY not in components:
            fail(
                specs,
                "NO_BASE_SALARY",
                BLOCKING,
                str(employee_id),
                f"{who} has no base salary for this period.",
                "Enter the base salary",
            )
            continue
        plans[employee_id] = _Plan(engagement, components, reimbursements)

    for employee_id, rows in by_employee.items():
        who = externals.get(employee_id, str(employee_id))
        if employee_id not in plans:
            _specs_for_employee(
                specs,
                "INPUT_WITHOUT_PAYSLIP",
                BLOCKING,
                str(employee_id),
                f"{who} has inputs in this run but no payslip is produced.",
                "Fix the employee's engagement or withdraw the inputs",
            )
            continue
        plan = plans[employee_id]
        absence_days = Decimal(0)
        for row in rows:
            if row.kind in {"bonus", "allowance"}:
                code = row.kind.upper()
                plan.components[code] = plan.components.get(code, Decimal(0)) + row.amount
            elif row.kind == "reimbursement":
                plan.reimbursements += row.amount
            elif row.kind == "absence":
                absence_days += row.quantity
        if absence_days:
            _specs_for_employee(
                specs,
                "ABSENCE_NOT_PRICED",
                REVIEW,
                str(employee_id),
                f"{who} has {_text(absence_days)} days of absence. A deduction for "
                "unpaid absence is not calculated yet.",
                "Confirm that no deduction applies",
            )

    destinations = payments.destinations_of(session, list(plans))
    for employee_id in plans:
        if employee_id not in destinations:
            _specs_for_employee(
                specs,
                "NO_PAYMENT_DESTINATION",
                BLOCKING,
                str(employee_id),
                f"{externals.get(employee_id, employee_id)} has no payment destination.",
                "Record the employee's payment destination",
            )

    results: list[list[str]] = []
    input_hashes: list[list[str]] = []
    for employee_id in sorted(plans, key=str):
        plan = plans[employee_id]
        who = externals.get(employee_id, str(employee_id))
        ordered = sorted(plan.components.items(), key=lambda kv: (kv[0] != BASE_SALARY, kv[0]))
        gross = sum((amount for _, amount in ordered), Decimal(0))
        data = calc.PayslipInput(
            gross,
            plan.engagement.head_of_family,
            tuple(plan.engagement.children),
            tuple((code, _label(code), amount) for code, amount in ordered),
            plan.reimbursements,
        )
        try:
            slip = calc.payslip(data, chosen)
        except calc.PayslipInvalid as exc:
            _specs_for_employee(
                specs,
                "PAYSLIP_REFUSED",
                BLOCKING,
                str(employee_id),
                f"The payslip of {who} cannot be calculated: {exc}",
                "Fix the pay data and calculate again",
            )
            continue
        if slip.net_pay <= 0:
            _specs_for_employee(
                specs,
                "NET_PAY_NOT_POSITIVE",
                BLOCKING,
                str(employee_id),
                f"The net pay of {who} is {_text(slip.net_pay)}.",
                "Check the pay data",
            )
        previous = session.scalar(
            select(Payslip.net_pay)
            .join(PayrollRun, PayrollRun.id == Payslip.run_id)
            .where(
                Payslip.employee_id == employee_id,
                PayrollRun.id != run.id,
                PayrollRun.status.in_(SETTLED),
                PayrollRun.period_end < run.period_start,
            )
            .order_by(PayrollRun.period_end.desc())
            .limit(1)
        )
        if previous and previous > 0:
            change = (slip.net_pay - previous) / previous
            if abs(change) > NET_CHANGE_REVIEW:
                _specs_for_employee(
                    specs,
                    "NET_CHANGE_LARGE",
                    REVIEW,
                    str(employee_id),
                    f"The net pay of {who} went from {_text(previous)} to {_text(slip.net_pay)}, "
                    f"a change of {change * 100:.1f} percent (limit {NET_CHANGE_REVIEW * 100:.0f} "
                    "percent, to verify).",
                    "Confirm the change is expected",
                )

        inputs = scorer.scorer_inputs(definition, data)
        limits = ["Allowances are taxed and reimbursements are not [verify the treatment]."]
        if chosen.is_demo:
            limits.insert(0, service.DEMO_NOTICE)
        decision = explain.record(
            session,
            tenant_id,
            explain.DecisionDraft(
                kind="finance.payslip",
                question=f"How was the net pay of {who} for {run.period_start.isoformat()} "
                f"to {run.period_end.isoformat()} calculated?",
                outcome={"net_pay": _text(slip.net_pay), "rule_set": chosen.id},
                subject={"employee_id": str(employee_id), "run_id": str(run.id)},
                score=slip.net_pay,
                factors=scorer.factors_of(slip),
                scorer=scorer.SCORER,
                scorer_version=scorer.VERSION,
                inputs=inputs,
                not_considered=NOT_CONSIDERED,
                limits=limits,
                versions={"rule_set": chosen.id, "rule_set_hash": chosen.definition_hash},
                view_roles=DECISION_VIEW_ROLES,
            ),
        )
        payslip = Payslip(
            tenant_id=tenant_id,
            run_id=run.id,
            employee_id=employee_id,
            engagement_id=plan.engagement.id,
            gross=slip.gross,
            employee_deductions=slip.employee_deductions,
            income_tax=slip.income_tax,
            solidarity=slip.solidarity,
            net_pay=slip.net_pay,
            employer_cost=slip.employer_cost,
            inputs={k: v for k, v in inputs.items() if k != "rule_set"},
            decision_record_id=decision.id,
        )
        session.add(payslip)
        session.flush()
        for position, line in enumerate(slip.lines):
            session.add(
                PayslipLine(
                    tenant_id=tenant_id,
                    payslip_id=payslip.id,
                    position=position,
                    code=line.code,
                    label=line.label,
                    kind=line.kind,
                    base=line.base,
                    rate=line.rate,
                    amount=line.amount,
                    rule_ref=line.rule_ref,
                )
            )
        results.append(
            [str(employee_id)]
            + [
                _text(v)
                for v in (
                    slip.gross,
                    slip.employee_deductions,
                    slip.income_tax,
                    slip.solidarity,
                    slip.net_pay,
                    slip.employer_cost,
                )
            ]
        )
        input_hashes.append([str(employee_id), payload_hash(inputs)])

    session.flush()
    issues.sync(session, tenant_id, ENTITY, run.id, specs)
    open_now = issues.open_for(session, ENTITY, run.id)
    run.rule_set_refs = {
        "id": chosen.id,
        "version": chosen.version,
        "hash": chosen.definition_hash,
        "is_demo": chosen.is_demo,
    }
    run.inputs_hash = payload_hash(input_hashes)
    run.results_hash = payload_hash(results)
    run.calculated_at = utcnow()
    run.calculation_state = "done"
    run.calculation_error = None
    run.status = "calculated"
    session.flush()
    publish(
        session,
        tenant_id,
        PayrollCalculated(
            run_id=run.id,
            payslips=len(results),
            exceptions=sum(1 for i in open_now if i.severity in {BLOCKING, REVIEW}),
        ),
    )
    return run


def results_hash_of(session: Session, run_id: UUID) -> str:
    rows = session.scalars(select(Payslip).where(Payslip.run_id == run_id)).all()
    return payload_hash(
        sorted(
            [
                [str(p.employee_id)]
                + [
                    _text(v)
                    for v in (
                        p.gross,
                        p.employee_deductions,
                        p.income_tax,
                        p.solidarity,
                        p.net_pay,
                        p.employer_cost,
                    )
                ]
                for p in rows
            ]
        )
    )


def totals(session: Session, run_id: UUID) -> dict[str, str]:
    row = session.execute(
        select(
            func.count(Payslip.id),
            func.coalesce(func.sum(Payslip.gross), 0),
            func.coalesce(func.sum(Payslip.employee_deductions), 0),
            func.coalesce(func.sum(Payslip.income_tax), 0),
            func.coalesce(func.sum(Payslip.solidarity), 0),
            func.coalesce(func.sum(Payslip.net_pay), 0),
            func.coalesce(func.sum(Payslip.employer_cost), 0),
        ).where(Payslip.run_id == run_id)
    ).one()
    keys = ("gross", "employee_deductions", "income_tax", "solidarity", "net_pay", "employer_cost")
    return {
        "payslips": str(row[0]),
        **{k: _text(Decimal(v)) for k, v in zip(keys, row[1:], strict=True)},
    }


def open_counts(session: Session, run_id: UUID) -> dict[str, int]:
    pending = issues.open_for(session, ENTITY, run_id)
    return {
        s: sum(1 for i in pending if i.severity == s) for s in ("blocking", "review", "warning")
    }


def run_json(session: Session, run: PayrollRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "period_start": run.period_start.isoformat(),
        "period_end": run.period_end.isoformat(),
        "pay_date": run.pay_date.isoformat(),
        "regime_id": run.regime_id,
        "status": run.status,
        "calculation_state": run.calculation_state,
        "calculation_error": run.calculation_error if run.calculation_state == "failed" else None,
        "rule_set": run.rule_set_refs or None,
        "input_batches": run.input_batch_refs,
        "calculated_at": run.calculated_at.isoformat() if run.calculated_at else None,
        "prepared_by": str(run.prepared_by) if run.prepared_by else None,
        "approved_by": str(run.approved_by) if run.approved_by else None,
        "totals": totals(session, run.id),
        "open_issues": open_counts(session, run.id),
        "notice": service.DEMO_NOTICE if (run.rule_set_refs or {}).get("is_demo") else None,
    }


def submit_for_approval(
    session: Session, tenant_id: UUID, actor: Actor, run_id: UUID
) -> trust.Proposal:
    """Propose approval (R3). The proposal binds the exact results by their hash."""
    run = session.get(PayrollRun, run_id, with_for_update=True)
    if run is None:
        raise NotFound("Payroll run not found")
    if run.status != "calculated" or run.calculation_state != "done":
        raise Conflict(f"The run is {run.status.replace('_', ' ')}, not calculated")
    pending = issues.open_for(session, ENTITY, run.id)
    blockers = [i for i in pending if i.severity in {BLOCKING, REVIEW}]
    if blockers:
        raise Conflict(
            "Open issues must be fixed or decided first: "
            + ", ".join(sorted({f"{i.code} ({i.severity})" for i in blockers}))
        )
    totals_now = totals(session, run.id)
    if totals_now["payslips"] == "0":
        raise Conflict("The run has no payslips")
    actual = results_hash_of(session, run.id)
    if actual != run.results_hash:
        raise Conflict("The payslips no longer match the calculated results")
    attempt = proposals.next_attempt(
        session, actor, f"{APPROVE_ACTION}:{run.id}:{actual[:16]}:", f"Payroll run {run.id}"
    )
    decided = session.scalars(
        select(ValidationIssue).where(
            ValidationIssue.entity_type == ENTITY,
            ValidationIssue.entity_id == run.id,
            ValidationIssue.status == "resolved",
        )
    ).all()
    notes = "; ".join(f"{i.code}: {i.resolution_reason}" for i in decided) or "none"
    refs = run.rule_set_refs or {}
    limits = [
        "Every figure comes from the rule set and the inputs. Nothing is estimated by a model."
    ]
    if refs.get("is_demo"):
        limits.insert(0, service.DEMO_NOTICE)
    decision = explain.record(
        session,
        tenant_id,
        explain.DecisionDraft(
            kind="finance.payroll.approval",
            question="Should this payroll run be approved?",
            outcome={
                "payslips": totals_now["payslips"],
                "total_net": totals_now["net_pay"],
                "total_employer_cost": totals_now["employer_cost"],
            },
            rationale=(
                f"Period {run.period_start.isoformat()} to {run.period_end.isoformat()}, "
                f"{totals_now['payslips']} payslips under rule set {refs.get('id')}. "
                f"Items a person decided: {notes}."
            ),
            limits=limits,
            versions={"results_hash": actual, "rule_set_hash": refs.get("hash")},
            view_roles=DECISION_VIEW_ROLES,
        ),
    )
    proposal = trust.propose(
        session,
        tenant_id,
        APPROVE_ACTION,
        {"run_id": str(run.id), "results_hash": actual},
        f"Approve the payroll run for {run.period_start.isoformat()} "
        f"to {run.period_end.isoformat()}",
        decision.id,
        f"{APPROVE_ACTION}:{run.id}:{actual[:16]}:{attempt}",
        requested_by=actor.user_id,
    )
    run.status = "approval_pending"
    run.approval_proposal_id = proposal.id
    run.last_edited_by = actor.user_id
    session.flush()
    return proposal


def recall_submission(session: Session, actor: Actor, run_id: UUID) -> PayrollRun:
    """Take a run back before it is approved. The open request is superseded."""
    run = session.get(PayrollRun, run_id, with_for_update=True)
    if run is None:
        raise NotFound("Payroll run not found")
    if run.status != "approval_pending":
        raise Conflict(f"The run is {run.status.replace('_', ' ')}, not waiting for approval")
    proposal = session.get(trust.Proposal, run.approval_proposal_id)
    if proposal is not None:
        if proposal.status in {"executed", "executing"}:
            raise Conflict(f"The approval request is already {proposal.status}")
        if proposal.status in {"pending_approval", "approved", "blocked"}:
            trust.supersede(session, proposal, str(actor.user_id), "Recalled by the preparer")
    run.status = "draft"
    run.calculation_state = "idle"
    run.approval_proposal_id = None
    session.flush()
    return run


def mark_rejected(session: Session, tenant_id: UUID, proposal_id: UUID) -> PayrollRun | None:
    """The approver said no: the run goes back to draft and must be calculated again."""
    run = session.scalar(
        select(PayrollRun).where(PayrollRun.approval_proposal_id == proposal_id).with_for_update()
    )
    if run is None or run.status != "approval_pending":
        return None
    run.status = "draft"
    run.calculation_state = "idle"
    session.flush()
    publish(session, tenant_id, PayrollRejected(run_id=run.id))
    return run


def verify_run(session: Session, run_id: UUID) -> dict[str, Any]:
    """Replay every payslip from its stored inputs and compare, then check the run's hash."""
    run = get_run(session, run_id)
    payslips = session.scalars(select(Payslip).where(Payslip.run_id == run_id)).all()
    mismatched = []
    for payslip in payslips:
        try:
            result = explain.verify(session, payslip.decision_record_id)
        except (ValueError, KeyError, ArithmeticError, KernelError):
            # Inputs that no longer make sense are a failed replay, not a crash.
            mismatched.append(str(payslip.id))
            continue
        recorded_matches_row = (
            result.get("recomputed_score") is not None
            and Decimal(result["recomputed_score"]) == payslip.net_pay
        )
        if not (result.get("match") and recorded_matches_row):
            mismatched.append(str(payslip.id))
    hash_ok = bool(run.results_hash) and results_hash_of(session, run_id) == run.results_hash
    return {
        "payslips": len(payslips),
        "matching": len(payslips) - len(mismatched),
        "mismatched": mismatched,
        "run_hash_matches": hash_ok,
        "verified": bool(payslips) and not mismatched and hash_ok,
    }
