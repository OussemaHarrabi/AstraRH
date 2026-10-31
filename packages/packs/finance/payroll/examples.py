"""Runs a rule set's own hand-checked examples. Pure: it only uses the formula and the rules."""

from dataclasses import dataclass
from decimal import Decimal

from packs.finance.payroll import calc
from packs.finance.payroll.rules import RuleSet


@dataclass(frozen=True)
class ExampleResult:
    name: str
    passed: bool
    mismatches: dict[str, tuple[Decimal, Decimal | None]]
    error: str | None = None


def run(rule_set: RuleSet) -> list[ExampleResult]:
    results = []
    for example in rule_set.examples:
        data = calc.PayslipInput(example.gross, example.head_of_family, example.children)
        try:
            slip = calc.payslip(data, rule_set)
        except calc.PayslipInvalid as exc:
            results.append(ExampleResult(example.name, False, {}, str(exc)))
            continue
        mismatches = {}
        for field, expected in example.expect.items():
            actual = getattr(slip, field)
            if actual != expected:
                mismatches[field] = (expected, actual)
        results.append(ExampleResult(example.name, not mismatches, mismatches))
    return results
