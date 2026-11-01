"""A payslip as an explainable, replayable decision.

The kernel recomputes the score when a decision is recorded and again on every replay, so what a
person sees is provably what the formula produced. The inputs hold everything the formula needs,
including the rule set itself, because a replay has nothing else to read.

Each factor is a signed line: earnings and reimbursements count +1, contributions and taxes -1.
The factors then add up exactly to net pay.
"""

from decimal import Decimal
from typing import Any

from kernel.explain import Factor, ScoreResult, register_scorer
from packs.finance.payroll import calc, rules

SCORER = "finance.payroll"
VERSION = "1"

PLUS, MINUS = Decimal(1), Decimal(-1)
FACTOR_LINES = (
    ("GROSS", PLUS),
    ("CNSS_EMPLOYEE", MINUS),
    ("IRPP", MINUS),
    ("CSS", MINUS),
    ("REIMBURSEMENT", PLUS),
)


def scorer_inputs(rule_definition: dict[str, Any], data: calc.PayslipInput) -> dict[str, Any]:
    """Plain JSON, with every number as a string, so it hashes the same after a round trip."""
    return {
        "rule_set": rule_definition,
        "gross": format(data.gross, "f"),
        "head_of_family": data.head_of_family,
        "children": list(data.children),
        "components": [
            [code, label, format(amount, "f")] for code, label, amount in data.components
        ],
        "reimbursements": format(data.reimbursements, "f"),
    }


def payslip_input(inputs: dict[str, Any]) -> calc.PayslipInput:
    return calc.PayslipInput(
        gross=Decimal(inputs["gross"]),
        head_of_family=bool(inputs["head_of_family"]),
        children=tuple(inputs["children"]),
        components=tuple(
            (code, label, Decimal(amount)) for code, label, amount in inputs["components"]
        ),
        reimbursements=Decimal(inputs["reimbursements"]),
    )


def compute(inputs: dict[str, Any]) -> calc.Payslip:
    return calc.payslip(payslip_input(inputs), rules.parse(inputs["rule_set"]))


def factors_of(slip: calc.Payslip) -> list[Factor]:
    by_code = {line.code: line for line in slip.lines}
    factors = []
    for code, weight in FACTOR_LINES:
        line = by_code.get(code)
        if line is None:
            continue
        factors.append(
            Factor(
                key=code,
                label=line.label,
                weight=weight,
                value=line.amount,
                contribution=weight * line.amount,
            )
        )
    return factors


@register_scorer(SCORER, VERSION)
def score(inputs: dict[str, Any]) -> ScoreResult:
    slip = compute(inputs)
    factors = factors_of(slip)
    return ScoreResult(score=sum((f.contribution for f in factors), Decimal(0)), factors=factors)
