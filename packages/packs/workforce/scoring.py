"""Team overload score — a transparent factor-sum over team totals.

Registered with kernel.explain, so the overload alert produces a real
DecisionRecord: factors sum exactly to the score and it can be replayed by
`rescore`. Deterministic arithmetic (invariant 5): the LLM never computes this.

The grain is team x week — there is NO per-person score anywhere, by design
(ARCHITECTURE "what we will not build": no individual productivity score).

    score = sum(weight x value) over the factors, weights summing to 1
    value = each signal clamped to 0..1 against a fixed cap
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from kernel.explain import Factor, ScoreResult, register_scorer

SCORER = "workforce.overload"
SCORER_VERSION = "1"

BASELINE_HOURS = Decimal("40")  # person-week baseline
OVERTIME_CAP = Decimal("15")  # +15h/head over baseline == full signal
COVERAGE_CAP = Decimal("0.30")  # 30% of the team on leave == full signal
OPEN_ROLES_CAP = Decimal("0.20")  # open reqs == 20% of headcount == full signal
THRESHOLD = Decimal("0.50")  # score >= this raises an R0 alert

W_OVERTIME = Decimal("0.60")
W_COVERAGE = Decimal("0.25")
W_OPEN = Decimal("0.15")

FOUR = Decimal("0.0001")


def _round(value: Decimal) -> Decimal:
    return value.quantize(FOUR, rounding=ROUND_HALF_UP)


def _clamp01(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(0), value))


def team_inputs(
    headcount: int, actual_hours: Any, on_leave_count: int = 0, open_reqs: int = 0
) -> dict[str, Any]:
    """The only input the scorer ever sees: one team's totals for one week."""
    return {
        "headcount": int(headcount),
        "actual_hours": str(actual_hours),
        "on_leave_count": int(on_leave_count),
        "open_reqs": int(open_reqs),
    }


@register_scorer(SCORER, SCORER_VERSION)
def score(inputs: dict[str, Any]) -> ScoreResult:
    headcount = Decimal(str(inputs["headcount"]))
    if headcount > 0:
        avg = Decimal(str(inputs["actual_hours"])) / headcount
        overtime = _clamp01(max(Decimal(0), avg - BASELINE_HOURS) / OVERTIME_CAP)
        coverage = _clamp01((Decimal(str(inputs.get("on_leave_count", 0))) / headcount) / COVERAGE_CAP)
        open_roles = _clamp01((Decimal(str(inputs.get("open_reqs", 0))) / headcount) / OPEN_ROLES_CAP)
    else:
        overtime = coverage = open_roles = Decimal(0)

    # contribution = weight x value (value rounded), so weight*value == contribution
    # exactly and the factors sum exactly to the score — both checked by kernel.explain.
    factors = [
        _factor("overtime", "Overtime over baseline", W_OVERTIME, overtime),
        _factor("coverage", "Coverage gap (on leave)", W_COVERAGE, coverage),
        _factor("open_roles", "Open roles", W_OPEN, open_roles),
    ]
    return ScoreResult(score=sum((f.contribution for f in factors), Decimal(0)), factors=factors)


def _factor(key: str, label: str, weight: Decimal, raw_value: Decimal) -> Factor:
    value = _round(raw_value)
    return Factor(key=key, label=label, weight=weight, value=value, contribution=weight * value)


def is_overloaded(result: ScoreResult, threshold: Decimal = THRESHOLD) -> bool:
    return result.score >= threshold
