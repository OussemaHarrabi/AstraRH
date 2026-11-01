"""Deterministic payroll exports. They are exports for human filing, never filings."""

import csv
import io
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kernel.errors import Conflict, NotFound
from kernel.people.models import Employee
from packs.finance.models import PayrollRun, Payslip


def _run(session: Session, run_id: UUID) -> PayrollRun:
    run = session.get(PayrollRun, run_id)
    if run is None:
        raise NotFound("Payroll run not found")
    if run.status not in {"approved", "payment_pending", "paid", "closed"}:
        raise Conflict("Exports require an approved payroll run")
    return run


def _csv(headers: list[str], rows: list[list[str]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def journal(session: Session, run_id: UUID) -> str:
    run = _run(session, run_id)
    rows = session.execute(
        select(Payslip, Employee.external_id)
        .join(Employee, Employee.id == Payslip.employee_id)
        .where(Payslip.run_id == run.id)
        .order_by(Employee.external_id)
    )
    return _csv(
        ["run_id", "employee", "gross", "employee_deductions", "income_tax", "solidarity", "net_pay", "employer_cost"],
        [
            [str(run.id), employee, *[format(value, "f") for value in (slip.gross, slip.employee_deductions, slip.income_tax, slip.solidarity, slip.net_pay, slip.employer_cost)]]
            for slip, employee in rows
        ],
    )


def contributions(session: Session, run_id: UUID) -> str:
    run = _run(session, run_id)
    rows = session.execute(
        select(Payslip, Employee.external_id)
        .join(Employee, Employee.id == Payslip.employee_id)
        .where(Payslip.run_id == run.id)
        .order_by(Employee.external_id)
    )
    return _csv(
        ["run_id", "employee", "gross", "employee_cnss", "income_tax", "solidarity", "employer_cost"],
        [
            [str(run.id), employee, format(slip.gross, "f"), format(slip.employee_deductions, "f"), format(slip.income_tax, "f"), format(slip.solidarity, "f"), format(slip.employer_cost, "f")]
            for slip, employee in rows
        ],
    )
