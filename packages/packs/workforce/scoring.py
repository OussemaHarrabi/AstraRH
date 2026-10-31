"""Team overload score — a transparent factor-sum over team totals.

Deterministic arithmetic (invariant 5): the LLM never computes this; it only
narrates it. The grain is team x week, so there is NO per-person score
anywhere — by design (ARCHITECTURE "what we will not build": no individual
productivity or conflict score). Alerts name the team and the reasons, never
a person.

    score = sum(weight x value) over the factors, weights summing to 1
    value = each signal normalised to 0..1 against a fixed cap

Mirrors kernel.explain's Factor / ScoreResult shape. At platform-v0 this is
registered with @register_scorer so the <WhyPanel> renders the factors and a
DecisionRecord can replay the exact sum.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

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


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    weight: Decimal
    value: Decimal
    contribution: Decimal


@dataclass(frozen=True)
class ScoreResult:
    score: Decimal
    factors: list[Factor]


@dataclass(frozen=True)
class TeamWeek:
    """One team's totals for one week. The only input the scorer ever sees."""

    org_unit_id: str
    week: str
    headcount: int
    actual_hours: Decimal
    on_leave_count: int = 0
    open_reqs: int = 0


def score_overload(tw: TeamWeek) -> ScoreResult:
    hc = Decimal(tw.headcount)
    if hc > 0:
        avg = Decimal(tw.actual_hours) / hc
        overtime_per_head = max(Decimal(0), avg - BASELINE_HOURS)
        overtime_value = _clamp01(overtime_per_head / OVERTIME_CAP)
        coverage_value = _clamp01((Decimal(tw.on_leave_count) / hc) / COVERAGE_CAP)
        open_value = _clamp01((Decimal(tw.open_reqs) / hc) / OPEN_ROLES_CAP)
    else:
        overtime_value = coverage_value = open_value = Decimal(0)

    factors = [
        Factor("overtime", "Overtime over baseline", W_OVERTIME, _round(overtime_value), _round(W_OVERTIME * overtime_value)),
        Factor("coverage", "Coverage gap (on leave)", W_COVERAGE, _round(coverage_value), _round(W_COVERAGE * coverage_value)),
        Factor("open_roles", "Open roles", W_OPEN, _round(open_value), _round(W_OPEN * open_value)),
    ]
    score = sum((f.contribution for f in factors), Decimal(0))
    return ScoreResult(score=_round(score), factors=factors)


def is_overloaded(result: ScoreResult, threshold: Decimal = THRESHOLD) -> bool:
    return result.score >= threshold
