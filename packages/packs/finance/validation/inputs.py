"""Payroll input checks. Pure: no database, no clock, no model.

A row is either malformed, and rejected with a reason so the sender can fix and resend it, or it is
stored. Stored inputs are then compared with each other and with the employees' engagements, and
anything that needs a person is raised as an issue. Limits marked [verify] are configuration, not
labour law.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from packs.finance.validation.common import BLOCKING, REVIEW, WARNING, IssueSpec

HOURS, ABSENCE = "hours", "absence"
BONUS, ALLOWANCE, REIMBURSEMENT = "bonus", "allowance", "reimbursement"
QUANTITY_KINDS = {HOURS, ABSENCE}
AMOUNT_KINDS = {BONUS, ALLOWANCE, REIMBURSEMENT}
KINDS = QUANTITY_KINDS | AMOUNT_KINDS

MAX_HOURS_PER_ROW = Decimal(24)
LONG_DAY_HOURS = Decimal(12)
MAX_ABSENCE_DAYS = Decimal(31)
MONTHLY_HOURS_REVIEW = Decimal(300)  # [verify]
UNUSUAL_AMOUNT = Decimal(20000)
MAX_AMOUNT = Decimal(10_000_000)

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMBER = re.compile(r"^\d{1,12}(\.\d{1,3})?$")
REFERENCE = re.compile(r"^[A-Za-z0-9._:/-]{1,64}$")
EMPLOYEE = re.compile(r"^[A-Za-z0-9._:/-]{1,64}$")


@dataclass(frozen=True)
class ParsedRow:
    line: int
    employee: str
    kind: str
    effective_date: date
    quantity: Decimal | None
    amount: Decimal | None
    reference: str | None


@dataclass(frozen=True)
class Rejection:
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class InputView:
    id: UUID
    employee_id: UUID
    kind: str
    effective_date: date
    quantity: Decimal | None
    amount: Decimal | None
    reference: str | None


def _number(text: str) -> Decimal | None:
    """Plain digits with up to 3 decimals. No signs, exponents, separators or words."""
    return Decimal(text) if NUMBER.match(text) else None


def parse_row(
    line: int, data: dict[str, str], period_start: date, period_end: date
) -> ParsedRow | Rejection:
    def reject(code: str, message: str) -> Rejection:
        return Rejection(line, code, message)

    employee = (data.get("employee") or "").strip()
    kind = (data.get("kind") or "").strip().lower()
    day_text = (data.get("effective_date") or "").strip()
    quantity_text = (data.get("quantity") or "").strip()
    amount_text = (data.get("amount") or "").strip()
    reference = (data.get("reference") or "").strip() or None

    if not employee or not EMPLOYEE.match(employee):
        return reject("EMPLOYEE_INVALID", "The employee id is missing or contains odd characters.")
    if kind not in KINDS:
        return reject(
            "KIND_UNKNOWN", f"{kind or 'No kind'} is not one of {', '.join(sorted(KINDS))}."
        )
    if not DATE.match(day_text):
        return reject("DATE_INVALID", "The date must look like 2026-11-30.")
    try:
        day = date.fromisoformat(day_text)
    except ValueError:
        return reject("DATE_INVALID", f"{day_text} is not a real date.")
    if not period_start <= day <= period_end:
        return reject(
            "DATE_OUTSIDE_PERIOD",
            f"{day.isoformat()} is outside {period_start.isoformat()} to {period_end.isoformat()}.",
        )
    if reference is not None and not REFERENCE.match(reference):
        return reject(
            "REFERENCE_INVALID",
            "The reference may only use letters, digits and . _ : / - (up to 64 characters).",
        )

    quantity = amount = None
    if kind in QUANTITY_KINDS:
        if amount_text:
            return reject("VALUE_NOT_ALLOWED", f"A {kind} row takes a quantity, not an amount.")
        quantity = _number(quantity_text)
        limit = MAX_HOURS_PER_ROW if kind == HOURS else MAX_ABSENCE_DAYS
        if quantity is None or quantity <= 0 or quantity > limit:
            unit = "hours" if kind == HOURS else "days"
            return reject("QUANTITY_INVALID", f"The {unit} must be above 0 and at most {limit}.")
    else:
        if quantity_text:
            return reject("VALUE_NOT_ALLOWED", f"A {kind} row takes an amount, not a quantity.")
        amount = _number(amount_text)
        if amount is None or amount <= 0 or amount > MAX_AMOUNT:
            return reject("AMOUNT_INVALID", f"The amount must be above 0 and at most {MAX_AMOUNT}.")
    return ParsedRow(line, employee, kind, day, quantity, amount, reference)


def conflicts(
    inputs: list[InputView],
    coverage: dict[UUID, list[tuple[date, date | None]]],
    scope: set[UUID],
) -> dict[UUID, list[IssueSpec]]:
    """Issues for the inputs in scope, judged against all the inputs of the period."""
    result: dict[UUID, list[IssueSpec]] = {i.id: [] for i in inputs if i.id in scope}
    hours_by_employee: dict[UUID, Decimal] = {}
    for item in inputs:
        if item.kind == HOURS and item.quantity is not None:
            hours_by_employee[item.employee_id] = (
                hours_by_employee.get(item.employee_id, Decimal(0)) + item.quantity
            )

    for item in inputs:
        if item.id not in scope:
            continue
        found = result[item.id]

        def add(code, severity, field, message, next_action, owner, found=found) -> None:
            found.append(IssueSpec(code, severity, field, message, next_action, owner))

        covered = any(
            start <= item.effective_date and (end is None or item.effective_date <= end)
            for start, end in coverage.get(item.employee_id, [])
        )
        if not covered:
            add(
                "NO_ACTIVE_ENGAGEMENT",
                BLOCKING,
                "employee",
                f"The employee has no active engagement on {item.effective_date.isoformat()}.",
                "Activate the engagement or withdraw the input",
                "HR",
            )
        same_day = [
            o
            for o in inputs
            if o.id != item.id
            and o.employee_id == item.employee_id
            and o.effective_date == item.effective_date
        ]
        if any(
            o.kind == item.kind and o.quantity == item.quantity and o.amount == item.amount
            for o in same_day
        ):
            add(
                "POSSIBLE_DUPLICATE",
                REVIEW,
                "duplicate",
                "Another input has the same employee, kind, date and value but a different "
                "reference.",
                "Confirm both are real, or withdraw one",
                "FINANCE",
            )
        if item.kind in {HOURS, ABSENCE} and any(
            o.kind in ({HOURS, ABSENCE} - {item.kind}) for o in same_day
        ):
            add(
                "ABSENCE_AND_HOURS_SAME_DAY",
                REVIEW,
                "overlap",
                "Hours and an absence are both recorded for this employee on this day.",
                "Confirm which one is right",
                "FINANCE",
            )
        if item.kind == HOURS and item.quantity is not None and item.quantity > LONG_DAY_HOURS:
            add(
                "LONG_DAY",
                WARNING,
                "quantity",
                f"{item.quantity} hours in one day is unusually long.",
                "Check the figure before payroll",
                "FINANCE",
            )
        if item.kind == HOURS and hours_by_employee.get(item.employee_id, 0) > MONTHLY_HOURS_REVIEW:
            add(
                "MONTHLY_HOURS_HIGH",
                REVIEW,
                "monthly_hours",
                f"This employee has more than {MONTHLY_HOURS_REVIEW} hours in the period (limit "
                "to verify).",
                "Confirm the hours are permitted and real",
                "FINANCE",
            )
        if item.amount is not None and item.amount > UNUSUAL_AMOUNT:
            add(
                "AMOUNT_UNUSUAL",
                WARNING,
                "amount",
                f"An amount above {UNUSUAL_AMOUNT} is unusual (limit to verify).",
                "Check the figure before payroll",
                "FINANCE",
            )
    return result
