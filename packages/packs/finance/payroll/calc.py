"""The payslip formula. Pure arithmetic: no database, no model, no clock, no randomness.

Order, with every value taken from the rule set:
    employee CNSS      = rate x gross                          (up to the ceiling, if any)
    monthly taxable    = gross - employee CNSS
    annual taxable     = monthly taxable x 12
    expenses           = rate x annual taxable, capped
    family deductions  = head of family + children (first N only)
    net taxable        = annual taxable - expenses - family deductions, never below 0
    income tax         = progressive brackets on net taxable, divided by 12
    solidarity levy    = rate x net taxable, divided by 12, none within the exempt amount
    net pay            = gross - employee CNSS - income tax - solidarity levy
    employer cost      = gross + employer CNSS + other employer charges

Each displayed line is rounded once, half up, to the rule set's decimal places, and net pay is the
sum of those rounded lines, so the lines always add up exactly.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from packs.finance.payroll.rules import RuleSet

MONTHS = Decimal(12)
ZERO = Decimal(0)

EARNING = "earning"
DEDUCTION = "deduction"
TAX = "tax"
EMPLOYER_COST = "employer_cost"

CHILD = "child"
STUDENT = "student"
DISABLED = "disabled"
CHILD_KINDS = {CHILD, STUDENT, DISABLED}


class PayslipInvalid(ValueError):
    pass


@dataclass(frozen=True)
class PayslipInput:
    gross: Decimal
    head_of_family: bool = False
    children: tuple[str, ...] = ()


@dataclass(frozen=True)
class Line:
    code: str
    label: str
    kind: str
    base: Decimal
    rate: Decimal | None
    amount: Decimal
    rule_ref: str


@dataclass(frozen=True)
class Payslip:
    gross: Decimal
    lines: tuple[Line, ...]
    employee_deductions: Decimal
    income_tax: Decimal
    solidarity: Decimal
    net_pay: Decimal
    employer_cost: Decimal
    rule_set_id: str
    rule_set_hash: str
    working: dict[str, Decimal] = field(default_factory=dict)


def _round(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _family_deduction(rules: RuleSet, data: PayslipInput) -> Decimal:
    family = rules.family
    total = family.head_of_family if data.head_of_family else ZERO
    for kind in data.children[: family.max_children]:
        if kind not in CHILD_KINDS:
            raise PayslipInvalid(f"Unknown child kind {kind!r}")
        if kind == DISABLED:
            if family.disabled_child is None:
                raise PayslipInvalid("This rule set has no value for a disabled child")
            total += family.disabled_child
        elif kind == STUDENT:
            total += family.student_child
        else:
            total += family.child
    return total


def _income_tax_annual(rules: RuleSet, taxable: Decimal) -> Decimal:
    tax = ZERO
    lower = ZERO
    for bracket in rules.brackets:
        if taxable <= lower:
            break
        upper = taxable if bracket.up_to is None else min(taxable, bracket.up_to)
        tax += (upper - lower) * bracket.rate
        if bracket.up_to is None:
            break
        lower = bracket.up_to
    return tax


def payslip(data: PayslipInput, rules: RuleSet) -> Payslip:
    if data.gross <= 0:
        raise PayslipInvalid("Gross pay must be above zero")
    places = rules.places
    ref = rules.id

    cnss_base = data.gross
    if rules.cnss_monthly_ceiling is not None:
        cnss_base = min(cnss_base, rules.cnss_monthly_ceiling)
    cnss_employee = _round(cnss_base * rules.cnss_employee_rate, places)

    monthly_taxable = data.gross - cnss_employee
    annual_taxable = monthly_taxable * MONTHS
    expenses = min(
        annual_taxable * rules.professional_expenses_rate, rules.professional_expenses_cap_annual
    )
    family_deduction = _family_deduction(rules, data)
    net_taxable = max(ZERO, annual_taxable - expenses - family_deduction)

    income_tax = _round(_income_tax_annual(rules, net_taxable) / MONTHS, places)
    css = _round(ZERO, places)
    if net_taxable > rules.css_exempt_up_to:
        css = _round(net_taxable * rules.css_rate / MONTHS, places)

    net_pay = data.gross - cnss_employee - income_tax - css

    lines = [
        Line("GROSS", "Gross salary", EARNING, data.gross, None, data.gross, f"{ref}#gross"),
        Line(
            "CNSS_EMPLOYEE",
            "Employee social security (CNSS)",
            DEDUCTION,
            cnss_base,
            rules.cnss_employee_rate,
            cnss_employee,
            f"{ref}#cnss_employee",
        ),
        Line(
            "IRPP",
            "Income tax (IRPP)",
            TAX,
            net_taxable,
            None,
            income_tax,
            f"{ref}#irpp_brackets",
        ),
        Line(
            "CSS",
            "Social solidarity contribution (CSS)",
            TAX,
            net_taxable,
            rules.css_rate,
            css,
            f"{ref}#css",
        ),
    ]

    employer_cnss = _round(cnss_base * rules.cnss_employer_rate, places)
    employer_lines = [
        Line(
            "CNSS_EMPLOYER",
            "Employer social security (CNSS)",
            EMPLOYER_COST,
            cnss_base,
            rules.cnss_employer_rate,
            employer_cnss,
            f"{ref}#cnss_employer",
        )
    ]
    for charge in rules.employer_charges:
        employer_lines.append(
            Line(
                charge.code,
                charge.label,
                EMPLOYER_COST,
                data.gross,
                charge.rate,
                _round(data.gross * charge.rate, places),
                f"{ref}#employer_charges.{charge.code}",
            )
        )
    employer_cost = data.gross + sum((line.amount for line in employer_lines), ZERO)

    return Payslip(
        gross=data.gross,
        lines=tuple(lines + employer_lines),
        employee_deductions=cnss_employee,
        income_tax=income_tax,
        solidarity=css,
        net_pay=net_pay,
        employer_cost=employer_cost,
        rule_set_id=rules.id,
        rule_set_hash=rules.definition_hash,
        working={
            "monthly_taxable": monthly_taxable,
            "annual_taxable": annual_taxable,
            "professional_expenses": expenses,
            "family_deductions": family_deduction,
            "annual_net_taxable": net_taxable,
        },
    )
